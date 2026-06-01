"""Mini-ELF v29 — Part 6: train the v29 Mathlib specialists.

Same architecture as v14/v18/v24/v26/v27/v28 (bi-GRU + additive attention, token-level
tokeniser, deterministic seed 0). Trains the v29 configs from the Part-5 dataset on
Mathlib-tier rows only (v28 pool + v29 sibling-density corpus) — never the full v24
broad-core corpus, which stays untouched. The v24/v28 model directories are never
overwritten (v29 writes ``token_seq2seq_v29_*``).

Configs (from data/processed/v29_mathlib_specialist/configs):
  v29_general                 v28_general pool + v29 density (unweighted)   [recommended]
  v29_v28best_plus            v28_finset_specialist pool + v29 density
  v29_set_finset_order_heavy  general with set+finset+order upsampled 2x
  v29_category_balanced       category-capped                              [NEGATIVE CONTROL]
  v29_function_order          general with function+order upsampled 2x     [optional specialist]
  v29_large                   v29_general rows, embed 128 / hidden 192      [capacity probe, optional]

Category-holdout transfer-probe models (train on the rest, the category removed):
  set_holdout / finset_holdout / order_holdout

The family-density and low-density holdouts need NO separate model: ``v29_general``
already excludes every split's test statements, and the contrast is *which training
siblings it saw* (dense vs sparse family), so the density law is read by evaluating
the SAME ``v29_general`` on those two test sets (Part 7/9).

Vocabulary is built from each config's train rows only; the shared val set is used
purely for checkpoint selection. No state_after; no manual oracle.
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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.token_seq2seq import TokenTrainConfig, save_token_artifacts, train_token  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_v29_mathlib_specialist")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _examples(rows: List[Dict[str, Any]]) -> List[Example]:
    return [Example(theorem_name=r.get("theorem_name", ""),
                    theorem_statement=r.get("theorem_statement", ""),
                    state_before=r.get("state_before", ""),
                    tactic=r.get("tactic", ""), split="train") for r in rows]


def train_one(label, train_rows, val_rows, out_dir, *, epochs, embed, hidden, lr,
              batch_size, beam_width, seed) -> Dict[str, Any]:
    src_texts = [build_input_text(r.get("theorem_statement", ""), r.get("state_before", "")) for r in train_rows]
    tactics = [r.get("tactic", "") for r in train_rows]
    vocab = TokenVocab.build(src_texts, tactics)
    cfg = TokenTrainConfig(epochs=epochs, batch_size=batch_size, lr=lr,
                           embedding_dim=embed, hidden_dim=hidden, beam_width=beam_width, seed=seed)
    t0 = time.perf_counter()
    art = train_token(_examples(train_rows), _examples(val_rows), vocab, cfg,
                      log_fn=lambda r: logger.info("    [%s] epoch=%d train_loss=%.4f val_loss=%.4f val_exact=%.4f",
                                                   label, r["epoch"], r["train_loss"], r["val_loss"],
                                                   r["val_greedy_exact_top1"])
                      if (r["epoch"] % 10 == 0 or r["epoch"] == cfg.epochs - 1) else None)
    runtime = time.perf_counter() - t0
    save_token_artifacts(out_dir, art, cfg, extra={"corpus": label})
    rec = {"config": label, "out_dir": str(out_dir), "n_train_rows": len(train_rows),
           "n_val_rows": len(val_rows), "vocab_size": len(vocab),
           "n_parameters": art.summary["n_parameters"], "epochs": epochs,
           "best_epoch": art.summary["best_epoch"], "embedding_dim": embed, "hidden_dim": hidden,
           "val_greedy_exact_top1": art.val_metrics.get("greedy_exact_top1",
                                    art.val_metrics.get("val_greedy_exact_top1", -1)),
           "val_beam_top10_contains_gold": art.val_metrics.get("beam_top10_contains_gold", -1),
           "runtime_seconds": round(runtime, 1)}
    logger.info("  DONE %-28s rows=%d vocab=%d params=%d best_epoch=%d val_exact=%.3f (%.1fs)",
                label, len(train_rows), len(vocab), rec["n_parameters"], rec["best_epoch"],
                rec["val_greedy_exact_top1"], runtime)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    base = ROOT / "data" / "processed" / "v29_mathlib_specialist"
    ap.add_argument("--base-dir", default=str(base))
    ap.add_argument("--models-root", default=str(ROOT / "data" / "models"))
    ap.add_argument("--manifest", default=str(base / "train_manifest.json"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--configs", default="general,v28best_plus,set_finset_order_heavy,category_balanced,"
                                         "function_order,set_holdout,finset_holdout,order_holdout",
                    help="comma list (add 'large' for the capacity probe)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    base = Path(args.base_dir)
    cfgd = base / "configs"
    val_rows = _read(cfgd / "val_rows.jsonl")
    models_root = Path(args.models_root)
    want = [c.strip() for c in args.configs.split(",") if c.strip()]

    # (train_file, val_file, embed, hidden)
    spec = {
        "general": (cfgd / "v29_general_train_rows.jsonl", None, 96, 128),
        "v28best_plus": (cfgd / "v29_v28best_plus_train_rows.jsonl", None, 96, 128),
        "set_finset_order_heavy": (cfgd / "v29_set_finset_order_heavy_train_rows.jsonl", None, 96, 128),
        "category_balanced": (cfgd / "v29_category_balanced_train_rows.jsonl", None, 96, 128),
        "function_order": (cfgd / "v29_function_order_train_rows.jsonl", None, 96, 128),
        "large": (cfgd / "v29_general_train_rows.jsonl", None, 128, 192),
        "set_holdout": (base / "category_holdout_set" / "train_rows.jsonl", None, 96, 128),
        "finset_holdout": (base / "category_holdout_finset" / "train_rows.jsonl", None, 96, 128),
        "order_holdout": (base / "category_holdout_order" / "train_rows.jsonl", None, 96, 128),
    }
    manifest = {"config": "v29_train", "configs": {}, "epochs": args.epochs,
                "n_val_rows": len(val_rows), "uses_state_after": False, "uses_manual_oracle": False,
                "note": "v24 broad-core and v28 specialists never overwritten; family/low-density "
                        "holdouts read off v29_general (no separate model)."}
    for c in want:
        if c not in spec:
            logger.warning("unknown config %s — skipping", c)
            continue
        tf, vf, embed, hidden = spec[c]
        rows = _read(Path(tf))
        if not rows:
            logger.warning("no rows for %s at %s — skipping", c, tf)
            continue
        vrows = _read(Path(vf)) if vf else val_rows
        out_dir = models_root / f"token_seq2seq_v29_{c}"
        logger.info("training v29_%s (%d rows, embed=%d hidden=%d) ...", c, len(rows), embed, hidden)
        manifest["configs"][c] = train_one(f"v29_{c}", rows, vrows, out_dir,
                                            epochs=args.epochs, embed=embed, hidden=hidden,
                                            lr=3e-3, batch_size=32, beam_width=10, seed=args.seed)

    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V29 TRAIN DONE: %d configs -> manifest %s", len(manifest["configs"]), args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
