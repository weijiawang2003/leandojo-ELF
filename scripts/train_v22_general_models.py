"""Mini-ELF v22 — Part 4: train the single *general* model configs.

The v22 question is whether ONE model can serve all broad-core
categories without the v21 capacity tradeoff (forall recovered only by
routing; exists/negation harmed by a single retrain). We hold the
architecture and training recipe fixed at the v18–v21 settings
(token-level bi-GRU + additive attention, beam 10, deterministic seed
0, 20 epochs) and vary only two axes:

  * **pool**   — ``A_mixed`` (v21 pool + v22 exists, no rebalance) vs
                 ``B_oversample`` (minority operations up-sampled).
  * **capacity** — base ``embed 96 / hidden 128`` vs large
                 ``embed 128 / hidden 192`` (the v21 "capacity" arch,
                 so the large configs are directly comparable to the
                 already-trained ``token_seq2seq_v21_capacity``).

Four NEW models are trained here:

    v22_general_plus_exists      A_mixed       embed 96  / hidden 128
    v22_general_balanced         B_oversample  embed 96  / hidden 128
    v22_general_large            A_mixed       embed 128 / hidden 192
    v22_general_balanced_large   B_oversample  embed 128 / hidden 192

Two reference single models already exist on disk and are NOT retrained
(reused in the Part-5 comparison as the no-exists single-model anchors):

    v22_general_base   == token_seq2seq_v21_broad_plus_forall   (v21 pool, base)
    v22_general_base_L == token_seq2seq_v21_capacity            (v21 pool, large)

Honesty: same trainer as v20/v21 (``token_seq2seq.train_token``); the
tokeniser sees only ``theorem_statement`` + ``state_before`` (never
``state_after``); no manual oracle; v18 leakage guards were applied
when the pools were built. Per-model wall-clock runtime is recorded.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    TokenTrainConfig, save_token_artifacts, train_token,
)
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_v22_general_models")

PROC = ROOT / "data" / "processed" / "v22_balanced_broad"
MODELS = ROOT / "data" / "models"

CONFIGS = [
    {"name": "v22_general_plus_exists",
     "rows": PROC / "A_mixed" / "train_rows.jsonl",
     "embed": 96, "hidden": 128,
     "pool_label": "A_mixed (v21+exists, no rebalance)"},
    {"name": "v22_general_balanced",
     "rows": PROC / "B_oversample" / "train_rows.jsonl",
     "embed": 96, "hidden": 128,
     "pool_label": "B_oversample (minority ops up to cap)"},
    {"name": "v22_general_large",
     "rows": PROC / "A_mixed" / "train_rows.jsonl",
     "embed": 128, "hidden": 192,
     "pool_label": "A_mixed (v21+exists, no rebalance)"},
    {"name": "v22_general_balanced_large",
     "rows": PROC / "B_oversample" / "train_rows.jsonl",
     "embed": 128, "hidden": 192,
     "pool_label": "B_oversample (minority ops up to cap)"},
]


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _opkey(r: Dict[str, Any]) -> str:
    return r.get("required_operation") or r.get("category") or "unknown"


def train_one(cfg: Dict[str, Any], *, epochs: int, batch_size: int, lr: float,
              beam_width: int, seed: int, val_fraction: float) -> Dict[str, Any]:
    rows = _read_jsonl(Path(cfg["rows"]))
    if not rows:
        raise SystemExit(f"no training rows at {cfg['rows']}")
    logger.info("=== %s: %d rows (embed %d / hidden %d) ===",
                cfg["name"], len(rows), cfg["embed"], cfg["hidden"])

    src_texts = [build_input_text(r.get("theorem_statement", ""),
                                  r.get("state_before", "")) for r in rows]
    tactics = [r.get("tactic", "") for r in rows]
    vocab = TokenVocab.build(src_texts, tactics)

    examples = [Example(
        theorem_name=r.get("theorem_name", ""),
        theorem_statement=r.get("theorem_statement", ""),
        state_before=r.get("state_before", ""),
        tactic=r.get("tactic", ""), split="train") for r in rows]

    rng = random.Random(seed)
    indices = list(range(len(examples)))
    rng.shuffle(indices)
    n_val = max(20, int(len(examples) * val_fraction))
    val_idx = set(indices[:n_val])
    train_examples = [e for i, e in enumerate(examples) if i not in val_idx]
    val_examples = [e for i, e in enumerate(examples) if i in val_idx]

    tcfg = TokenTrainConfig(
        epochs=epochs, batch_size=batch_size, lr=lr,
        embedding_dim=cfg["embed"], hidden_dim=cfg["hidden"],
        beam_width=beam_width, seed=seed)

    t0 = time.perf_counter()
    art = train_token(
        train_examples, val_examples, vocab, tcfg,
        log_fn=lambda r: logger.info(
            "  epoch=%d train_loss=%.4f val_loss=%.4f val_exact=%.4f",
            r["epoch"], r["train_loss"], r["val_loss"],
            r["val_greedy_exact_top1"])
        if (r["epoch"] % 5 == 0 or r["epoch"] == tcfg.epochs - 1) else None)
    runtime_s = time.perf_counter() - t0

    out_dir = MODELS / cfg["name"]
    save_token_artifacts(out_dir, art, tcfg,
                         extra={"corpus": cfg["pool_label"], "v22_config": cfg["name"]})
    by_op = Counter(_opkey(r) for r in rows)
    rec = {"name": cfg["name"], "pool": str(cfg["rows"]),
           "pool_label": cfg["pool_label"], "n_rows": len(rows),
           "n_train": len(train_examples), "n_val": len(val_examples),
           "embedding_dim": cfg["embed"], "hidden_dim": cfg["hidden"],
           "vocab_size": len(vocab), "epochs": epochs,
           "runtime_s": round(runtime_s, 1),
           "val_greedy_exact_top1": art.val_metrics.get("greedy_exact_top1",
                                                        art.train_log[-1]["val_greedy_exact_top1"]),
           "final_train_loss": art.train_log[-1]["train_loss"],
           "by_operation": dict(by_op), "out_dir": str(out_dir),
           "uses_state_after": False, "uses_manual_oracle": False}
    logger.info("  DONE %s in %.1fs -> %s", cfg["name"], runtime_s, out_dir)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-fraction", type=float, default=0.08)
    ap.add_argument("--only", default=None,
                    help="comma-separated config names to train (default: all)")
    ap.add_argument("--manifest",
                    default=str(MODELS / "v22_general_manifest.json"))
    args = ap.parse_args(argv)

    only = set(args.only.split(",")) if args.only else None
    records = []
    t_all = time.perf_counter()
    for cfg in CONFIGS:
        if only and cfg["name"] not in only:
            continue
        records.append(train_one(
            cfg, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
            beam_width=args.beam_width, seed=args.seed,
            val_fraction=args.val_fraction))
    total = time.perf_counter() - t_all

    manifest = {
        "trained": records,
        "reference_models_not_retrained": {
            "v22_general_base": "data/models/token_seq2seq_v21_broad_plus_forall "
                                "(v21 pool, embed96/hidden128, NO exists)",
            "v22_general_base_large": "data/models/token_seq2seq_v21_capacity "
                                      "(v21 pool, embed128/hidden192, NO exists)",
        },
        "recipe": {"epochs": args.epochs, "batch_size": args.batch_size,
                   "lr": args.lr, "beam_width": args.beam_width,
                   "seed": args.seed, "trainer": "token_seq2seq.train_token",
                   "architecture": "bi-GRU + additive attention (v18-v21)"},
        "total_runtime_s": round(total, 1),
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    logger.info("ALL v22 GENERAL TRAINING DONE in %.1fs; manifest -> %s",
                total, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
