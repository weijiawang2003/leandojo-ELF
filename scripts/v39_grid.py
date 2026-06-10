"""Mini-ELF v39 — matched-budget crossover orchestrator (Track A + Track B driver).

Runs a queue of training cells sequentially on the single GPU, resumable: a cell
whose config.json already exists is skipped. Each cell -> v39_train.train_cell.
Metrics appended to outputs/v39/<run>/matrix_metrics.jsonl (one row per
checkpoint); snapshots + per-cell config under the same dir.

Track A (default): existing v35 corpus (frozen vocab + 24-theorem tier untouched).
  * crossover grid : 3 families x U-ladder (nested subsets of train) @ matched budget
  * headline       : 3 families @ U=full @ larger budget (the verified-eval snapshots)
Track B: a prebuilt LeanDojo corpus dir (own vocab + own dev set) for the scale arm.

Guardrails: train-only vocab (the corpus's own), no state_after, the 24-theorem
tier never enters train/dev, fixed seed 3407.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_data import load_dataset, mathlib_test_tier, gold_lookup
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from v39_train import train_cell, NanError

OUT = ROOT / "outputs" / "v39"


def nested_order(n: int, seed: int = 3407) -> List[int]:
    g = torch.Generator(device="cpu"); g.manual_seed(seed)
    return torch.randperm(n, generator=g).tolist()


def load_corpus(corpus_dir: Optional[str]):
    """Return (vocab, manifest, train_rows, dev_rows, golds, tier_or_None, tag)."""
    if corpus_dir is None:
        ds = load_dataset()
        vocab, man = ds["vocab"], ds["manifest"]
        train, val = ds["train"], ds["val"]
        tier = mathlib_test_tier(ds["test"], cap=24)
        golds = gold_lookup(train + val + ds["test"])
        return vocab, man, train, val, golds, tier, "trackA_v35"
    d = Path(corpus_dir)
    vocab = TokenVocab.load(d / "vocab.json")
    man = json.loads((d / "manifest.json").read_text())
    train = [json.loads(l) for l in (d / "train.jsonl").read_text().splitlines() if l.strip()]
    dev = [json.loads(l) for l in (d / "dev.jsonl").read_text().splitlines() if l.strip()]
    golds = gold_lookup(train + dev)
    return vocab, man, train, dev, golds, None, d.name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--run", default="trackA", help="subdir under outputs/v39 for this run")
    ap.add_argument("--corpus-dir", default=None, help="prebuilt corpus dir (Track B); default=v35")
    ap.add_argument("--scale", default="30M")
    ap.add_argument("--families", default="ar,mdlm,flow")
    ap.add_argument("--u-ladder", default="", help="comma list of U sizes; default=eighths of train")
    ap.add_argument("--grid-budget", type=float, default=3e7)
    ap.add_argument("--headline-budget", type=float, default=1.5e8)
    ap.add_argument("--phases", default="grid,headline", help="grid,headline (Track A) or scale (Track B)")
    ap.add_argument("--ckpt-fracs", default="0.1,0.25,0.5,1.0")
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--dev-n", type=int, default=160)
    ap.add_argument("--k-dev", type=int, default=4)
    ap.add_argument("--gen-steps", type=int, default=16)
    ap.add_argument("--time-cap-min", type=float, default=40.0)
    ap.add_argument("--budget-hours", type=float, default=99.0)
    args = ap.parse_args(argv)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    out = OUT / args.run; out.mkdir(parents=True, exist_ok=True)
    metrics_path = out / "matrix_metrics.jsonl"
    log = print
    deadline = time.perf_counter() + args.budget_hours * 3600

    vocab, man, train_rows, dev_rows, golds, tier, ctag = load_corpus(args.corpus_dir)
    families = args.families.split(",")
    ckpt_fracs = [float(x) for x in args.ckpt_fracs.split(",")]
    full = len(train_rows)
    if args.u_ladder:
        ladder = [int(x) for x in args.u_ladder.split(",")]
    else:
        ladder = [round(full * f) for f in (0.125, 0.25, 0.5, 1.0)]
    ladder = sorted(set(min(u, full) for u in ladder))
    order = nested_order(full, args.seed)
    def subset(U): return [train_rows[i] for i in order[:U]]

    log(f"[v39 {args.run}] corpus={ctag} dev={dev} train={full} dev_rows={len(dev_rows)} "
        f"vocab={len(vocab)} ladder={ladder} families={families} phases={args.phases}")

    # ---- assemble cell queue ----
    cells: List[Dict[str, Any]] = []
    phases = args.phases.split(",")
    if "grid" in phases:
        for U in ladder:
            for fam in families:
                cells.append(dict(family=fam, scale=args.scale, U=U, rows=subset(U),
                                  budget=args.grid_budget, tag="grid",
                                  cell_id=f"grid_{fam}_{args.scale}_U{U}"))
    if "headline" in phases:
        for fam in families:
            cells.append(dict(family=fam, scale=args.scale, U=full, rows=train_rows,
                              budget=args.headline_budget, tag="headline",
                              cell_id=f"headline_{fam}_{args.scale}_U{full}"))
    if "scale" in phases:  # Track B
        for U in ladder:
            for fam in families:
                cells.append(dict(family=fam, scale=args.scale, U=U, rows=subset(U),
                                  budget=args.grid_budget, tag="scale",
                                  cell_id=f"scale_{fam}_{args.scale}_U{U}"))

    done = {c.stem for c in (out / "configs").glob("*.json")} if (out / "configs").exists() else set()
    log(f"[v39 {args.run}] {len(cells)} cells queued, {len(done)} already done")

    for i, c in enumerate(cells):
        cid = c["cell_id"]
        if cid in done:
            log(f"  [{i+1}/{len(cells)}] SKIP {cid} (done)"); continue
        if time.perf_counter() > deadline:
            log(f"  [{i+1}/{len(cells)}] STOP {cid}: budget exhausted"); break
        lr = args.lr
        for attempt in (1, 2):
            try:
                t0 = time.perf_counter()
                res = train_cell(
                    family=c["family"], scale=c["scale"], train_rows=c["rows"], val_rows=dev_rows,
                    dev_rows=dev_rows, vocab=vocab, manifest=man, golds=golds,
                    token_budget=c["budget"], ckpt_fracs=ckpt_fracs, batch_size=args.batch_size,
                    base_lr=lr, seed=args.seed, device=dev, cell_id=cid, out_dir=out,
                    dev_n=args.dev_n, K_dev=args.k_dev, gen_steps=args.gen_steps,
                    time_cap_s=args.time_cap_min * 60,
                    extra_meta={"tag": c["tag"], "corpus": ctag, "attempt": attempt, "lr_used": lr})
                with metrics_path.open("a", encoding="utf-8") as f:
                    for m in res["metrics"]:
                        f.write(json.dumps({**m, "tag": c["tag"], "corpus": ctag}) + "\n")
                fm = res["final"]
                log(f"  [{i+1}/{len(cells)}] DONE {cid} ({res['elapsed_s']:.0f}s, {res['npar']/1e6:.1f}M) "
                    f"val={fm.get('val_loss')} exact={fm.get('dev_exact_seq')} "
                    f"pertok={fm.get('dev_per_token')} distinct={fm.get('dev_distinct_mean')}")
                break
            except NanError as e:
                log(f"  [{i+1}/{len(cells)}] NaN {cid} attempt {attempt}: {e}")
                if attempt == 1:
                    lr = lr / 2; log(f"     retry at lr={lr}")
                else:
                    log(f"     FAILED {cid} (NaN x2)")
                    with metrics_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"cell": cid, "family": c["family"], "U": c["U"],
                                            "tag": c["tag"], "status": "FAILED_NAN"}) + "\n")
            except Exception as e:  # noqa: BLE001
                import traceback; traceback.print_exc()
                log(f"  [{i+1}/{len(cells)}] ERROR {cid}: {e}")
                with metrics_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"cell": cid, "tag": c["tag"], "status": "ERROR", "err": str(e)}) + "\n")
                break
        if dev == "cuda":
            torch.cuda.empty_cache()

    log(f"[v39 {args.run}] queue complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
