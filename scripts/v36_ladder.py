"""Mini-ELF v36 — scale·objective ladder (offline, gated, budget-aware).

Trains a small grid of flow models on the *same* v35 train split + shared vocab
(reuses the existing ``data/processed/v35_elf_flow`` — does NOT rebuild) and
measures the §2 coherence metrics for each, to answer: **is the v35 inter-token
incoherence closable by scale·objective at CPU scale, or is the curve flat
(fundamental gap)?**

Axes (brief §4): depth ∈ {3,6}, width D ∈ {128,256}, ce_weight ∈ {0.2,1,4},
epochs ∈ {50,150}. ≤18 trains. Each cell is probed with BOTH samplers (v35
continuous + v36 iterative/discrete). A subset of cells additionally trains with
**discrete self-conditioning** (the canonical fix the iterative sampler needs) so
we test training-for-coherence, not only decoding-for-coherence.

Budget: per-cell early-stop on val flow-MSE (patience 8) + a hard wall-clock cap
(``--cell-seconds``, default 900s); a cell that hits the cap is kept (best
checkpoint so far) and flagged ``timed_out``. A global ``--budget-seconds`` stops
launching new cells. ``ladder.json`` is rewritten after every cell so partial
progress survives a kill. CPU, deterministic, no Lean, ``state_after`` never read.
Best config = max ``exact_seq_recovery_rate`` then ``per_token_gold_recovery``
across (cell × sampler).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch  # noqa: E402

from mini_elf_lean.elf_v35_embed import ElfV35Config  # noqa: E402
from mini_elf_lean.elf_v35_train import ElfV35TrainConfig, train as train_flow  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab  # noqa: E402
from v36_coherence_probe import (  # noqa: E402
    coherence_metrics, make_v35_sampler, make_v36_sampler, load_probe, read_rows,
)

DATA = ROOT / "data" / "processed" / "v35_elf_flow"
OUT = ROOT / "data" / "baselines" / "v36_coherence"

logger = logging.getLogger("v36_ladder")


def grid() -> List[Dict[str, Any]]:
    """≤18 cells. Continuous-self-cond cells cover all axis values; discrete cells
    test the canonical coherence fix. `primary` = the sampler whose metrics head
    the cell (continuous→v35, discrete→v36)."""
    C = lambda d, w, ce, ep: {"depth": d, "width": w, "ce": ce, "epochs": ep, "discrete": False, "primary": "v35"}
    Dd = lambda d, w, ce, ep: {"depth": d, "width": w, "ce": ce, "epochs": ep, "discrete": True, "primary": "v36"}
    return [
        # continuous self-cond — scale·objective sweep (covers every axis value)
        C(3, 128, 0.2, 50), C(3, 128, 1.0, 50), C(3, 128, 4.0, 50),
        C(6, 128, 1.0, 50), C(3, 256, 1.0, 50), C(6, 256, 1.0, 50),
        C(3, 128, 1.0, 150), C(6, 128, 4.0, 150), C(3, 256, 4.0, 150),
        # discrete self-cond — canonical fix, probed with the iterative sampler
        Dd(3, 128, 1.0, 50), Dd(3, 128, 4.0, 50), Dd(6, 128, 1.0, 50),
        Dd(3, 256, 1.0, 150),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--out-dir", default=str(OUT))
    ap.add_argument("--cell-seconds", type=float, default=900.0, help="per-cell wall-clock cap")
    ap.add_argument("--budget-seconds", type=float, default=5.0 * 3600, help="stop launching new cells after this")
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-samples", type=int, default=8, help="probe samples per row")
    ap.add_argument("--steps", type=int, default=8, help="probe sampler steps")
    ap.add_argument("--max-probe", type=int, default=80)
    ap.add_argument("--max-cells", type=int, default=18)
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(out / "run.log")])

    manifest = json.loads((Path(args.data_dir) / "manifest.json").read_text())
    vocab = TokenVocab.load(Path(args.data_dir) / "vocab.json")
    train_rows = read_rows(Path(args.data_dir) / "train.jsonl")
    val_rows = read_rows(Path(args.data_dir) / "val.jsonl")
    probe, golds = load_probe(Path(args.data_dir), tier="mathlib", max_probe=args.max_probe)
    probe_kw = dict(T=manifest["max_tgt_len"], pad_id=vocab.pad_id, max_cond_len=manifest["max_cond_len"])
    baseline = json.loads((out / "baseline_v35.json").read_text()) if (out / "baseline_v35.json").exists() else None

    cells: List[Dict[str, Any]] = []
    ladder = {"baseline_v35": baseline, "n_train_rows": len(train_rows), "probe_rows": len(probe),
              "probe_samples": args.n_samples, "probe_steps": args.steps, "cells": cells}
    t_start = time.perf_counter()

    for spec in grid()[: args.max_cells]:
        if time.perf_counter() - t_start > args.budget_seconds:
            logger.warning("global budget reached; stopping after %d cells", len(cells))
            break
        cid = f"d{spec['depth']}_D{spec['width']}_ce{spec['ce']}_ep{spec['epochs']}" + ("_disc" if spec["discrete"] else "")
        logger.info("=== cell %s (%d/%d) ===", cid, len(cells) + 1, min(len(grid()), args.max_cells))
        cfg = ElfV35Config(
            vocab_size=len(vocab), d_model=spec["width"], cond_hidden=spec["width"],
            n_layers=spec["depth"], n_heads=4, ff_dim=2 * spec["width"],
            max_tgt_len=manifest["max_tgt_len"], max_cond_len=manifest["max_cond_len"],
            pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
        )
        tcfg = ElfV35TrainConfig(epochs=spec["epochs"], batch_size=args.batch_size, seed=args.seed,
                                 ce_weight=spec["ce"], patience=args.patience, max_seconds=args.cell_seconds,
                                 discrete_selfcond=spec["discrete"])
        try:
            art = train_flow(cfg, train_rows, val_rows, tcfg)
        except Exception as exc:  # noqa: BLE001 - keep the ladder going
            logger.exception("cell %s failed: %s", cid, exc)
            cells.append({"id": cid, **spec, "skipped": f"error: {exc}"})
            (out / "ladder.json").write_text(json.dumps(ladder, indent=2), encoding="utf-8")
            continue

        mean, std = art.stats.tensors("cpu")
        s35 = make_v35_sampler(art.model, mean, std)
        s36 = make_v36_sampler(art.model, mean, std, remask=True)
        m35 = coherence_metrics(s35, probe, golds, vocab, n_samples=args.n_samples, steps=args.steps, **probe_kw)
        m36 = coherence_metrics(s36, probe, golds, vocab, n_samples=args.n_samples, steps=args.steps, **probe_kw)
        cell = {
            "id": cid, **spec,
            "params": art.summary["n_parameters"], "best_val_fm": art.summary["best_val_fm"],
            "epochs_run": art.summary["epochs_run"], "early_stopped": art.summary["early_stopped"],
            "timed_out": art.summary["timed_out"], "runtime_seconds": art.summary["runtime_seconds"],
            "metrics_v35_sampler": m35, "metrics_v36_sampler": m36,
        }
        cells.append(cell)
        (out / "ladder.json").write_text(json.dumps(ladder, indent=2), encoding="utf-8")
        prim = m36 if spec["primary"] == "v36" else m35
        logger.info("cell %s: params=%d val_fm=%.3f run=%.0fs timed_out=%s | primary(%s) per_tok=%.3f exact=%.3f",
                    cid, cell["params"], cell["best_val_fm"], cell["runtime_seconds"], cell["timed_out"],
                    spec["primary"], prim["per_token_gold_recovery"], prim["exact_seq_recovery_rate"])

    # best (cell × sampler) by exact-seq then per-token
    best = None
    for c in cells:
        for skey in ("metrics_v35_sampler", "metrics_v36_sampler"):
            m = c.get(skey)
            if not m:
                continue
            key = (m["exact_seq_recovery_rate"], m["per_token_gold_recovery"])
            if best is None or key > best["key"]:
                best = {"key": key, "cell": c["id"], "sampler": "v36" if skey.endswith("v36_sampler") else "v35", "metrics": m,
                        "depth": c["depth"], "width": c["width"], "ce": c["ce"], "epochs": c["epochs"],
                        "discrete": c["discrete"], "params": c.get("params")}
    if best:
        best.pop("key", None)
        bm = best["metrics"]
        gate = (bm["per_token_gold_recovery"] >= 0.60) or (bm["exact_seq_recovery_rate"] >= 0.10)
        b_per = baseline["per_token_gold_recovery"] if baseline else None
        b_exact = baseline["exact_seq_recovery_rate"] if baseline else None
        ladder["best"] = best
        ladder["gate"] = {
            "fired": gate,
            "thresholds": {"per_token_gold_recovery>=": 0.60, "exact_seq_recovery_rate>=": 0.10},
            "best_per_token": bm["per_token_gold_recovery"], "best_exact_seq": bm["exact_seq_recovery_rate"],
            "v35_baseline_per_token": b_per, "v35_baseline_exact_seq": b_exact,
        }
        logger.info("BEST cell=%s sampler=%s per_tok=%.3f exact=%.3f | GATE FIRED=%s",
                    best["cell"], best["sampler"], bm["per_token_gold_recovery"], bm["exact_seq_recovery_rate"], gate)
    (out / "ladder.json").write_text(json.dumps(ladder, indent=2), encoding="utf-8")
    logger.info("ladder DONE: %d cells, %.0fs total", len(cells), time.perf_counter() - t_start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
