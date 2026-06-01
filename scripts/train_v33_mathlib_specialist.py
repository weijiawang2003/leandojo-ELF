"""Mini-ELF v33 — Part 5: train the v33 canonical specialists.

Same architecture/seed as v31/v32. Configs: v33_general_residual (recommended),
v33_general_residual_stress, v33_residual_only (ablation). Writes
`token_seq2seq_v33_*`; never overwrites v24/v32. No capacity probe.
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
logger = logging.getLogger("train_v33")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    cfgd = ROOT / "data" / "processed" / "v33_mathlib_specialist" / "configs"
    ap.add_argument("--base-dir", default=str(cfgd))
    ap.add_argument("--models-root", default=str(ROOT / "data" / "models"))
    ap.add_argument("--manifest", default=str(ROOT / "data" / "processed" / "v33_mathlib_specialist" / "train_manifest.json"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--configs", default="general_residual,general_residual_stress,residual_only")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    cfgd = Path(args.base_dir)
    val = _read(cfgd / "val_rows.jsonl")
    spec = {
        "general_residual": cfgd / "v33_general_residual_train_rows.jsonl",
        "general_residual_stress": cfgd / "v33_general_residual_stress_train_rows.jsonl",
        "residual_only": cfgd / "v33_residual_only_train_rows.jsonl",
    }
    manifest = {"config": "v33_train", "configs": {}, "uses_state_after": False, "uses_manual_oracle": False,
                "note": "v24 broad-core and v32 specialists never overwritten; canonical mode."}
    for c in [x.strip() for x in args.configs.split(",") if x.strip()]:
        rows = _read(spec[c])
        if not rows:
            logger.warning("no rows for %s", c); continue
        out_dir = Path(args.models_root) / f"token_seq2seq_v33_{c}"
        logger.info("training v33_%s (%d rows, val %d) ...", c, len(rows), len(val))
        manifest["configs"][c] = train_one(f"v33_{c}", rows, val, out_dir, epochs=args.epochs, embed=96, hidden=128, seed=args.seed)
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("V33 TRAIN DONE: %d configs", len(manifest["configs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
