"""Mini-ELF v37 — overfit control (the final ELF-flow experiment, offline).

v35 showed the non-AR flow recovers ~0.34 of gold tokens per position on
held-out Mathlib rows and verifies 0%; v36 showed scale·objective and a
coherence sampler leave that flat. The open question: is the incoherence an
**architecture limit** (the flow cannot represent a coherent multi-token tactic
even for its OWN training examples) or a **generalization limit** (it can fit
train, but fails to generalize at this data scale)?

This is the discriminating control. We train the v35 flow on a **tiny fixed
TRAIN subset** of M Mathlib-tier theorems with **no held-out and no early
stopping** (val == train, by design — said so explicitly), then run the §2
coherence metric (`v36_coherence_probe`, integrate-from-noise, NOT teacher
forcing) on **those same training rows**. If train exact-seq stays ≈0 / train
per-token ≈0.34 even at M=4 / 800 epochs ⇒ architecture limit (airtight
"fundamental"). If train exact-seq → high while v36 held-out stays ~0.34 ⇒
generalization limit.

Grid: M ∈ {4,16,64} theorems × epochs ∈ {200,800}; optional capacity arm
(M=16, width 256). Per-train hard cap 25 min (skip+log). CPU, deterministic,
offline (no Lean). Writes `data/baselines/v37_overfit/overfit.json`
incrementally. ``state_after`` never read; v37_* artifacts only; v35 model and
trainer reused unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
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
from v36_coherence_probe import coherence_metrics, make_v35_sampler, gold_lookup, read_rows  # noqa: E402

DATA = ROOT / "data" / "processed" / "v35_elf_flow"
OUT = ROOT / "data" / "baselines" / "v37_overfit"

logger = logging.getLogger("v37_overfit_control")


def select_theorems(rows: List[Dict[str, Any]], m: int) -> List[str]:
    """Deterministic, NESTED subset: order Mathlib-tier theorem names by md5 and
    take the first ``m`` (so the M=4 set ⊂ M=16 ⊂ M=64)."""
    names = sorted({r["theorem_name"] for r in rows},
                   key=lambda n: hashlib.md5(n.encode()).hexdigest())
    return names[:m]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--out-dir", default=str(OUT))
    ap.add_argument("--m-values", default="4,16,64")
    ap.add_argument("--epochs-values", default="200,800")
    ap.add_argument("--cell-seconds", type=float, default=1500.0)   # 25 min hard cap
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-samples", type=int, default=16, help="probe samples per row")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--capacity-arm", action="store_true", help="add M=16, width 256, epochs 800")
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(out / "run.log")])

    manifest = json.loads((Path(args.data_dir) / "manifest.json").read_text())
    vocab = TokenVocab.load(Path(args.data_dir) / "vocab.json")
    all_train = read_rows(Path(args.data_dir) / "train.jsonl")
    ml_train = [r for r in all_train if r.get("tier") == "mathlib"]
    logger.info("mathlib train rows=%d, theorems=%d", len(ml_train), len({r["theorem_name"] for r in ml_train}))

    m_values = [int(x) for x in args.m_values.split(",") if x.strip()]
    epochs_values = [int(x) for x in args.epochs_values.split(",") if x.strip()]
    cells: List[Dict[str, Any]] = [{"M": m, "epochs": e, "width": 128} for m in m_values for e in epochs_values]
    if args.capacity_arm:
        cells.append({"M": 16, "epochs": max(epochs_values), "width": 256})

    probe_kw = dict(T=manifest["max_tgt_len"], pad_id=vocab.pad_id, max_cond_len=manifest["max_cond_len"])
    records: List[Dict[str, Any]] = []
    result = {
        "design": "OVERFIT CONTROL — train==probe (no held-out, no early stopping); val==train by design.",
        "data": "Mathlib-tier v35 train rows; subsets nested by md5(theorem_name).",
        "n_mathlib_train_rows": len(ml_train), "records": records,
    }
    t_start = time.perf_counter()

    for spec in cells:
        M, E, W = spec["M"], spec["epochs"], spec["width"]
        cid = f"M{M}_ep{E}_D{W}"
        names = select_theorems(ml_train, M)
        subset = [r for r in ml_train if r["theorem_name"] in set(names)]
        logger.info("=== %s: %d theorems, %d rows ===", cid, len(names), len(subset))
        cfg = ElfV35Config(
            vocab_size=len(vocab), d_model=W, cond_hidden=W, n_layers=3, n_heads=4, ff_dim=2 * W,
            max_tgt_len=manifest["max_tgt_len"], max_cond_len=manifest["max_cond_len"],
            pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
        )
        # no early stopping (patience=None); hard wall-clock cap only; val == train subset.
        tcfg = ElfV35TrainConfig(epochs=E, batch_size=min(args.batch_size, max(len(subset), 1)),
                                 seed=args.seed, patience=None, max_seconds=args.cell_seconds)
        try:
            art = train_flow(cfg, subset, subset, tcfg)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s failed: %s", cid, exc)
            records.append({"id": cid, **spec, "skipped": f"error: {exc}"})
            (out / "overfit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            continue

        mean, std = art.stats.tensors("cpu")
        golds = gold_lookup(subset)
        # cfg_weight=1.0 (pure conditional — fairest "can it reproduce") AND 2.0 (matched to v35/v36)
        m_cfg1 = coherence_metrics(make_v35_sampler(art.model, mean, std, cfg_weight=1.0),
                                   subset, golds, vocab, n_samples=args.n_samples, steps=args.steps, **probe_kw)
        m_cfg2 = coherence_metrics(make_v35_sampler(art.model, mean, std, cfg_weight=2.0),
                                   subset, golds, vocab, n_samples=args.n_samples, steps=args.steps, **probe_kw)
        rec = {
            "id": cid, "M": M, "epochs": E, "width": W,
            "n_theorems": len(names), "n_rows": len(subset),
            "params": art.summary["n_parameters"],
            "train_flow_mse": art.summary["best_val_fm"],  # val==train
            "epochs_run": art.summary["epochs_run"], "timed_out": art.summary["timed_out"],
            "runtime_seconds": art.summary["runtime_seconds"],
            # primary = best of the two cfg weights on each coherence axis
            "train_per_token_gold_recovery": max(m_cfg1["per_token_gold_recovery"], m_cfg2["per_token_gold_recovery"]),
            "train_exact_seq_recovery": max(m_cfg1["exact_seq_recovery_rate"], m_cfg2["exact_seq_recovery_rate"]),
            "metrics_cfg1": m_cfg1, "metrics_cfg2": m_cfg2,
        }
        records.append(rec)
        (out / "overfit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        logger.info("%s: rows=%d params=%d train_mse=%.3f epochs_run=%d | TRAIN per_tok=%.3f exact=%.3f (head_body cfg1=%.3f)",
                    cid, len(subset), rec["params"], rec["train_flow_mse"], rec["epochs_run"],
                    rec["train_per_token_gold_recovery"], rec["train_exact_seq_recovery"],
                    m_cfg1["head_correct_body_wrong_rate"])

    # verdict signal
    best_exact = max((r.get("train_exact_seq_recovery", 0.0) for r in records if "skipped" not in r), default=0.0)
    best_per_tok = max((r.get("train_per_token_gold_recovery", 0.0) for r in records if "skipped" not in r), default=0.0)
    result["verdict"] = {
        "best_train_exact_seq_recovery": best_exact,
        "best_train_per_token_gold_recovery": best_per_tok,
        "architecture_limit": best_exact < 0.10 and best_per_tok < 0.60,
        "generalization_limit": best_exact >= 0.80,
        "note": ("architecture_limit: the flow cannot memorize coherent tactics even on its own "
                 "training rows (gap is fundamental, not just held-out). generalization_limit: it "
                 "fits train but fails the v36 held-out (~0.34). Neither flag set = intermediate; "
                 "read the table."),
        "v35_v36_heldout_per_token_ref": 0.356,
    }
    (out / "overfit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("OVERFIT DONE: best train exact=%.3f per_tok=%.3f | arch_limit=%s gen_limit=%s (%.0fs)",
                best_exact, best_per_tok, result["verdict"]["architecture_limit"],
                result["verdict"]["generalization_limit"], time.perf_counter() - t_start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
