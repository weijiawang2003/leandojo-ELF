"""Mini-ELF v15 — train per-family-LOFO learned rerankers.

Reads ``data/processed/v15_rerank_dataset/all_candidates.jsonl`` (built
by ``scripts/build_rerank_dataset.py``), splits it leave-family-out
for each of the 5 v11 LOFO families, trains one reranker per held
family, and writes the fitted model to
``data/models/v15_reranker/<held_family>/``.

Each per-fold model is trained on **every candidate row whose
theorem is NOT in the held family**. The eval rows are the v14
candidates on the held family — they're consumed by
``evaluate_v15_reranker.py``; here we only train.

A second mode (``--global``) trains a single reranker on the full
dataset, ignoring leakage — useful as a smoke baseline but **never
the headline metric**.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.learned_reranker import (  # noqa: E402
    TrainConfig, train_reranker,
)
from mini_elf_lean.rerank_dataset import (  # noqa: E402
    compute_stats, leave_family_out_split, read_rows,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_learned_reranker")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset",
                    default=str(ROOT / "data" / "processed"
                                / "v15_rerank_dataset" / "all_candidates.jsonl"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "models" / "v15_reranker"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ", "neg_exfalso",
                             "exists_reconstruct", "neg_imp_exfalso"])
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--lr", type=float, default=0.5)
    ap.add_argument("--l2", type=float, default=1e-3)
    ap.add_argument("--class-weight-positive", type=float, default=6.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--hashed-dim", type=int, default=256)
    ap.add_argument("--global-only", action="store_true",
                    help="Skip LOFO and train one model on the full dataset.")
    args = ap.parse_args(argv)

    rows = read_rows(Path(args.dataset))
    if not rows:
        logger.error("no candidate rows at %s", args.dataset)
        return 1
    stats = compute_stats(rows)
    logger.info("dataset: %d rows  verified=%d  pos_fraction=%.3f",
                stats.n_total, stats.n_verified, stats.positive_fraction)

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    cfg = TrainConfig(
        epochs=args.epochs, lr=args.lr, l2=args.l2,
        class_weight_positive=args.class_weight_positive,
        seed=args.seed, hashed_dim=args.hashed_dim,
    )

    if args.global_only:
        logger.info("training GLOBAL reranker (no leakage guard)")
        m = train_reranker(rows, cfg=cfg)
        m.save(out_root / "global")
        logger.info("global model saved -- |w|=%d epochs=%d",
                    len(m.weights), cfg.epochs)
        return 0

    for fam in args.families:
        train, evalr = leave_family_out_split(rows, held_family=fam)
        # Use 10 % of training rows as val for inspection (stratified by
        # verified label so we don't get a val with zero positives).
        n_val = max(20, len(train) // 10)
        pos = [r for r in train if r.verified]
        neg = [r for r in train if not r.verified]
        import random as _r
        rng = _r.Random(args.seed)
        rng.shuffle(pos)
        rng.shuffle(neg)
        n_val_pos = min(len(pos) // 5, max(2, n_val // 10))
        n_val_neg = max(1, n_val - n_val_pos)
        val_rows = pos[:n_val_pos] + neg[:n_val_neg]
        train_rows = pos[n_val_pos:] + neg[n_val_neg:]
        rng.shuffle(train_rows)
        rng.shuffle(val_rows)

        logger.info("FAM=%s held_theorems=%d train=%d val=%d eval=%d",
                    fam, len({r.theorem_name for r in evalr}),
                    len(train_rows), len(val_rows), len(evalr))
        m = train_reranker(train_rows, cfg=cfg, val_rows=val_rows)
        out_dir = out_root / fam
        m.save(out_dir)
        # Persist held theorems for downstream audit
        (out_dir / "held_theorems.json").write_text(
            json.dumps(sorted({r.theorem_name for r in evalr}),
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        final = m.train_history[-1] if m.train_history else {}
        logger.info("  saved %s  n_features=%d final_train_loss=%.4f "
                    "final_train_acc=%.3f final_val_acc=%s",
                    out_dir, len(m.weights), final.get("train_loss", 0.0),
                    final.get("train_acc", 0.0),
                    final.get("val_acc", "-"))

    logger.info("V15 RERANKER TRAINING DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
