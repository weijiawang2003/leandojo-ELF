"""Mini-ELF v27 — Part 6: train the v27 Mathlib specialists.

Same architecture as v14/v18/v24/v26 (bi-GRU + additive attention, token-level
tokeniser, deterministic seed 0). Trains the v27 configs from the Part-5 dataset,
each on Mathlib-tier rows only (v26 specialist pool + v27 expanded) — never the
full v24 broad-core corpus, which stays untouched.

Configs (from data/processed/v27_mathlib_specialist/configs/):
  v27_base               v26 base train + v27 expanded
  v27_widened            v26 widened train + v27 expanded   (recommended baseline)
  v27_category_balanced  category-balanced cap
  v27_set_heavy          widened with Set rows upsampled 2x  (optional)
  v27_large              v27_widened rows with bigger embed/hidden (optional)

Vocabulary is built from each config's train rows only; the shared val set is used
purely for checkpoint selection (val-OOV → <unk>). No state_after; no manual oracle.
Writes data/models/token_seq2seq_v27_<config>/ and a manifest with rows / params /
vocab size / epochs / runtime / val-exact / selected checkpoint per config.
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
logger = logging.getLogger("train_v27_mathlib_specialist")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _examples(rows: List[Dict[str, Any]]) -> List[Example]:
    return [Example(theorem_name=r.get("theorem_name", ""),
                    theorem_statement=r.get("theorem_statement", ""),
                    state_before=r.get("state_before", ""),
                    tactic=r.get("tactic", ""), split="train") for r in rows]


def train_one(label: str, train_rows: List[Dict[str, Any]], val_rows: List[Dict[str, Any]],
              out_dir: Path, *, epochs: int, embed: int, hidden: int, lr: float,
              batch_size: int, beam_width: int, seed: int) -> Dict[str, Any]:
    src_texts = [build_input_text(r.get("theorem_statement", ""), r.get("state_before", "")) for r in train_rows]
    tactics = [r.get("tactic", "") for r in train_rows]
    vocab = TokenVocab.build(src_texts, tactics)
    train_ex = _examples(train_rows)
    val_ex = _examples(val_rows)
    cfg = TokenTrainConfig(epochs=epochs, batch_size=batch_size, lr=lr,
                           embedding_dim=embed, hidden_dim=hidden, beam_width=beam_width, seed=seed)
    t0 = time.perf_counter()
    art = train_token(train_ex, val_ex, vocab, cfg,
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
    logger.info("  DONE %-22s rows=%d vocab=%d params=%d best_epoch=%d val_exact=%.3f (%.1fs)",
                label, len(train_rows), len(vocab), rec["n_parameters"], rec["best_epoch"],
                rec["val_greedy_exact_top1"], runtime)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    cfgd = ROOT / "data" / "processed" / "v27_mathlib_specialist" / "configs"
    ap.add_argument("--configs-dir", default=str(cfgd))
    ap.add_argument("--models-root", default=str(ROOT / "data" / "models"))
    ap.add_argument("--manifest", default=str(ROOT / "data" / "processed" / "v27_mathlib_specialist" / "train_manifest.json"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--configs", default="base,widened,category_balanced,set_heavy",
                    help="comma list of: base,widened,category_balanced,set_heavy,large")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    cfgd = Path(args.configs_dir)
    val_rows = _read(cfgd / "val_rows.jsonl")
    models_root = Path(args.models_root)
    want = [c.strip() for c in args.configs.split(",") if c.strip()]

    spec = {
        "base": ("v27_base_train_rows.jsonl", 96, 128),
        "widened": ("v27_widened_train_rows.jsonl", 96, 128),
        "category_balanced": ("v27_category_balanced_train_rows.jsonl", 96, 128),
        "set_heavy": ("v27_set_heavy_train_rows.jsonl", 96, 128),
        "large": ("v27_widened_train_rows.jsonl", 128, 192),
    }
    manifest = {"config": "v27_train", "configs": {}, "epochs": args.epochs,
                "n_val_rows": len(val_rows), "uses_state_after": False, "uses_manual_oracle": False}
    for c in want:
        if c not in spec:
            logger.warning("unknown config %s — skipping", c)
            continue
        fname, embed, hidden = spec[c]
        rows = _read(cfgd / fname)
        if not rows:
            logger.warning("no rows for %s at %s — skipping", c, cfgd / fname)
            continue
        out_dir = models_root / f"token_seq2seq_v27_{c}"
        logger.info("training v27_%s (%d rows, embed=%d hidden=%d) ...", c, len(rows), embed, hidden)
        manifest["configs"][c] = train_one(f"v27_{c}", rows, val_rows, out_dir,
                                            epochs=args.epochs, embed=embed, hidden=hidden,
                                            lr=3e-3, batch_size=32, beam_width=10, seed=args.seed)

    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V27 TRAIN DONE: %d configs -> manifest %s", len(manifest["configs"]), args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
