"""Mini-ELF v31 — Part 5: train the v31 normalized specialists.

Same token seq2seq architecture as v24/v30 (bi-GRU + attention, seed 0, 40 epochs).
Trains the v31 configs. Never overwrites v24/v30 (writes `token_seq2seq_v31_*`). No
capacity probe by default.

Configs (from data/processed/v31_canonical_mathlib/configs):
  canonical_general       every v30-base row canonicalized (Approach A)        [own canonical val]
  raw_canonical_mixture   raw + canonical rows                                 [mixed val]
  raw_plus_projection_aug v30 base + 140 verified projection rename-aug rows    [raw val] (Approach B)

`pattern_rerank_only` (Approach C) and the `v30_general_targeted` fallback use the
existing v30 model — no new training. The canonical config carries a canonical val set
so checkpoint selection is in the same (canonical) space the model decodes in.
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
logger = logging.getLogger("train_v31_normalized_specialist")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _examples(rows):
    return [Example(theorem_name=r.get("theorem_name", ""), theorem_statement=r.get("theorem_statement", ""),
                    state_before=r.get("state_before", ""), tactic=r.get("tactic", ""), split="train") for r in rows]


def train_one(label, train_rows, val_rows, out_dir, *, epochs, embed, hidden, seed):
    src = [build_input_text(r.get("theorem_statement", ""), r.get("state_before", "")) for r in train_rows]
    vocab = TokenVocab.build(src, [r.get("tactic", "") for r in train_rows])
    cfg = TokenTrainConfig(epochs=epochs, batch_size=32, lr=3e-3, embedding_dim=embed,
                           hidden_dim=hidden, beam_width=10, seed=seed)
    t0 = time.perf_counter()
    art = train_token(_examples(train_rows), _examples(val_rows), vocab, cfg,
                      log_fn=lambda r: logger.info("    [%s] epoch=%d val_exact=%.4f", label, r["epoch"],
                                                   r["val_greedy_exact_top1"])
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
    base = ROOT / "data" / "processed" / "v31_canonical_mathlib"
    ap.add_argument("--base-dir", default=str(base))
    ap.add_argument("--models-root", default=str(ROOT / "data" / "models"))
    ap.add_argument("--manifest", default=str(base / "train_manifest.json"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--configs", default="canonical_general,raw_canonical_mixture,raw_plus_projection_aug")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    cfgd = Path(args.base_dir) / "configs"
    v30_val = ROOT / "data" / "processed" / "v30_mathlib_specialist" / "configs" / "val_rows.jsonl"
    # (train_file, val_file, embed, hidden)
    spec = {
        "canonical_general": (cfgd / "canonical_general_train_rows.jsonl", cfgd / "canonical_general_val_rows.jsonl", 96, 128),
        "raw_canonical_mixture": (cfgd / "raw_canonical_mixture_train_rows.jsonl", cfgd / "raw_canonical_mixture_val_rows.jsonl", 96, 128),
        "raw_plus_projection_aug": (cfgd / "raw_plus_projection_aug_train_rows.jsonl", v30_val, 96, 128),
        "raw_plus_canonical_aug": (cfgd / "raw_plus_canonical_aug_train_rows.jsonl", cfgd / "raw_plus_canonical_aug_val_rows.jsonl", 96, 128),
    }
    manifest = {"config": "v31_train", "configs": {}, "epochs": args.epochs,
                "uses_state_after": False, "uses_manual_oracle": False, "not_v19_placeholders": True,
                "note": "v24 broad-core and v30 specialists never overwritten; no capacity probe."}
    for c in [x.strip() for x in args.configs.split(",") if x.strip()]:
        if c not in spec:
            logger.warning("unknown config %s", c); continue
        tf, vf, embed, hidden = spec[c]
        rows = _read(Path(tf))
        if not rows:
            logger.warning("no rows for %s", c); continue
        vrows = _read(Path(vf))
        out_dir = Path(args.models_root) / f"token_seq2seq_v31_{c}"
        logger.info("training v31_%s (%d rows, val %d) ...", c, len(rows), len(vrows))
        manifest["configs"][c] = train_one(f"v31_{c}", rows, vrows, out_dir, epochs=args.epochs,
                                            embed=embed, hidden=hidden, seed=args.seed)
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V31 TRAIN DONE: %d configs", len(manifest["configs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
