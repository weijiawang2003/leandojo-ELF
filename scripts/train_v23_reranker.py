"""Mini-ELF v23 — Part 3: train the refreshed rerankers (full-data
artifacts for inspection; the leakage-clean numbers come from the
leave-one-theorem-out eval in ``evaluate_v23_rerankers.py``).

Configs:
  * **B** ``v23_plain``         — grounding + abstract-pattern features
    only (no category one-hot / category cues).
  * **C** ``v23_category_aware``— B + category one-hot + category-specific
    structural cues + category×cue interactions.

(A = the existing v15 learned reranker, reused, not retrained.
 D = the hybrid policy, evaluated in Part 4/7, not a separate weight set.)

Deterministic CPU logistic regression, class-weighted for the ~16 %
positive rate. No state_after, no manual oracle, no generation change.
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

from mini_elf_lean.learned_reranker import TrainConfig  # noqa: E402
from mini_elf_lean.v23_learned_reranker import train_v23_reranker  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_v23_reranker")


def _read(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rows", default=str(ROOT / "data" / "processed"
                                          / "v23_reranker_data" / "rows.jsonl"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "models"))
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    rows = _read(Path(args.rows))
    logger.info("training rows: %d (%d positive)", len(rows),
                sum(1 for r in rows if r.get("verified")))
    cfg = TrainConfig(epochs=args.epochs, seed=args.seed)

    for label, catf in (("v23_reranker_plain", False),
                        ("v23_reranker_category_aware", True)):
        m = train_v23_reranker(rows, cfg=cfg, category_features=catf)
        out = Path(args.out_root) / label
        m.save(out)
        top = m.top_features(8)
        logger.info("%s: %d features -> %s", label, len(m.index), out)
        logger.info("  top+: %s", [n for n, _ in top[:8]])
    logger.info("v23 reranker training DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
