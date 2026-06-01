"""Mini-ELF v32 — train the repaired canonical specialist (v31 canonical base + the
37 verified `∅∩` final-residual repair rows, canonicalized). Same architecture/seed as
v31; writes `token_seq2seq_v32_canonical_repaired`; never overwrites v24/v30/v31.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from train_v31_normalized_specialist import _read, train_one  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_v32_repaired")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    cfgd = ROOT / "data" / "processed" / "v32_mathlib" / "configs"
    ap.add_argument("--train", default=str(cfgd / "v32_canonical_repaired_train_rows.jsonl"))
    ap.add_argument("--val", default=str(cfgd / "v32_canonical_repaired_val_rows.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "models" / "token_seq2seq_v32_canonical_repaired"))
    ap.add_argument("--manifest", default=str(ROOT / "data" / "processed" / "v32_mathlib" / "train_manifest.json"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    rows = _read(Path(args.train))
    vrows = _read(Path(args.val))
    logger.info("training v32_canonical_repaired (%d rows, val %d) ...", len(rows), len(vrows))
    rec = train_one("v32_canonical_repaired", rows, vrows, Path(args.out),
                    epochs=args.epochs, embed=96, hidden=128, seed=args.seed)
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps({"config": "v32_train", "configs": {"v32_canonical_repaired": rec},
                                               "uses_state_after": False, "uses_manual_oracle": False,
                                               "note": "v24/v30/v31 never overwritten"}, indent=2), encoding="utf-8")
    logger.info("V32 TRAIN DONE: val_exact=%.3f", rec["val_greedy_exact_top1"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
