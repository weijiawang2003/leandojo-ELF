"""Mini-ELF v30 — Part 6: train the v30 Mathlib specialists.

Same architecture as v24/v29 (bi-GRU + attention, token tokeniser, seed 0, 40 epochs).
Trains the v30 density-repair configs on Mathlib-tier rows only (v29 pool + v30
targeted). Never overwrites v24/v29 (writes `token_seq2seq_v30_*`). No capacity probe
by default (v29 showed data, not capacity, is the bottleneck). The theorem and
targeted-family holdouts read off `v30_general_targeted` directly (it already excludes
their test statements) — no separate probe models.

Configs (from data/processed/v30_mathlib_specialist/configs):
  v30_general_targeted   v29_general + v30 targeted (unweighted)   [recommended]
  v30_targeted_upsample  general_targeted + v30 rows again (2× repair)
  v30_v29best_plus       v29 set_finset_order_heavy + v30 targeted
  v30_targeted_only      v30 rows only                             [ablation]
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
logger = logging.getLogger("train_v30_mathlib_specialist")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _examples(rows):
    return [Example(theorem_name=r.get("theorem_name", ""), theorem_statement=r.get("theorem_statement", ""),
                    state_before=r.get("state_before", ""), tactic=r.get("tactic", ""), split="train") for r in rows]


def train_one(label, train_rows, val_rows, out_dir, *, epochs, embed, hidden, lr, batch_size, beam_width, seed):
    src = [build_input_text(r.get("theorem_statement", ""), r.get("state_before", "")) for r in train_rows]
    vocab = TokenVocab.build(src, [r.get("tactic", "") for r in train_rows])
    cfg = TokenTrainConfig(epochs=epochs, batch_size=batch_size, lr=lr, embedding_dim=embed,
                           hidden_dim=hidden, beam_width=beam_width, seed=seed)
    t0 = time.perf_counter()
    art = train_token(_examples(train_rows), _examples(val_rows), vocab, cfg,
                      log_fn=lambda r: logger.info("    [%s] epoch=%d train_loss=%.4f val_exact=%.4f",
                                                   label, r["epoch"], r["train_loss"], r["val_greedy_exact_top1"])
                      if (r["epoch"] % 10 == 0 or r["epoch"] == cfg.epochs - 1) else None)
    runtime = time.perf_counter() - t0
    save_token_artifacts(out_dir, art, cfg, extra={"corpus": label})
    rec = {"config": label, "out_dir": str(out_dir), "n_train_rows": len(train_rows), "vocab_size": len(vocab),
           "n_parameters": art.summary["n_parameters"], "best_epoch": art.summary["best_epoch"],
           "val_greedy_exact_top1": art.val_metrics.get("greedy_exact_top1", art.val_metrics.get("val_greedy_exact_top1", -1)),
           "runtime_seconds": round(runtime, 1)}
    logger.info("  DONE %-24s rows=%d vocab=%d params=%d best_epoch=%d val_exact=%.3f (%.1fs)",
                label, len(train_rows), len(vocab), rec["n_parameters"], rec["best_epoch"],
                rec["val_greedy_exact_top1"], runtime)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    base = ROOT / "data" / "processed" / "v30_mathlib_specialist"
    ap.add_argument("--base-dir", default=str(base))
    ap.add_argument("--models-root", default=str(ROOT / "data" / "models"))
    ap.add_argument("--manifest", default=str(base / "train_manifest.json"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--configs", default="general_targeted,targeted_upsample,v29best_plus,targeted_only")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    base = Path(args.base_dir)
    cfgd = base / "configs"
    val_rows = _read(cfgd / "val_rows.jsonl")
    models_root = Path(args.models_root)
    want = [c.strip() for c in args.configs.split(",") if c.strip()]
    spec = {
        "general_targeted": (cfgd / "v30_general_targeted_train_rows.jsonl", 96, 128),
        "targeted_upsample": (cfgd / "v30_targeted_upsample_train_rows.jsonl", 96, 128),
        "v29best_plus": (cfgd / "v30_v29best_plus_train_rows.jsonl", 96, 128),
        "targeted_only": (cfgd / "v30_targeted_only_train_rows.jsonl", 96, 128),
        "large": (cfgd / "v30_general_targeted_train_rows.jsonl", 128, 192),
    }
    manifest = {"config": "v30_train", "configs": {}, "epochs": args.epochs, "n_val_rows": len(val_rows),
                "uses_state_after": False, "uses_manual_oracle": False,
                "note": "v24 broad-core and v29 specialists never overwritten; no capacity probe by default."}
    for c in want:
        if c not in spec:
            logger.warning("unknown config %s", c); continue
        tf, embed, hidden = spec[c]
        rows = _read(Path(tf))
        if not rows:
            logger.warning("no rows for %s", c); continue
        out_dir = models_root / f"token_seq2seq_v30_{c}"
        logger.info("training v30_%s (%d rows) ...", c, len(rows))
        manifest["configs"][c] = train_one(f"v30_{c}", rows, val_rows, out_dir, epochs=args.epochs,
                                            embed=embed, hidden=hidden, lr=3e-3, batch_size=32,
                                            beam_width=10, seed=args.seed)
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V30 TRAIN DONE: %d configs", len(manifest["configs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
