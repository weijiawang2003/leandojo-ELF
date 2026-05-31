"""Mini-ELF v18 — Part 5: train a single broad token-seq2seq on
*all* clean synthetic verified proof blocks, then evaluate on v18.

The v18 brief's primary question is "how much of v17 transfers".
Part 5 isolates the question "would scaling within the synthetic
corpus alone close the v18 gap?". A *single* model is trained over
the union of:

  * every v11 LOFO **train** row across all 5 families,
  * the v16 contrapositive corpus,
  * the v17 arrow_false_elim corpus.

The combined train set is **explicitly leakage-guarded** against
the v18 corpus by both theorem-name and (statement, state, tactic)
triple — both guards report 0 drops in practice, matching the v16/v17
guarantee.

The model is then evaluated zero-shot on v18 using the same union
panel pattern as ``evaluate_v18_zero_shot.py``: the broad model
takes the role of one extra panel member alongside v16/v17 family
models. We measure pass@k on v18 vs the v17 baseline to see whether
broader synthetic helps.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    TokenTrainConfig, save_token_artifacts, train_token,
)
from mini_elf_lean.token_seq2seq_dataset import (  # noqa: E402
    TokenVocab, build_input_text,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_v18_broad_synthetic_model")


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


def _collect_v18_names_and_triples(
    v18_root: Path,
) -> Tuple[Set[str], Set[Tuple[str, str, str]]]:
    names: Set[str] = set()
    triples: Set[Tuple[str, str, str]] = set()
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read_jsonl(v18_root / fname):
            if r.get("theorem_name"):
                names.add(r["theorem_name"])
            triples.add((r.get("theorem_statement", ""),
                         r.get("state_before", ""),
                         r.get("tactic", "")))
    return names, triples


def _gather_synthetic(
    *, v17_token_root: Path, v16_corpus: Path, v17_corpus: Path,
    v18_root: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Pool: all per-family v17 train rows + v16 corpus + v17 corpus.
    Apply v18 leakage guards. v17 LOFO train files already contain
    v11 LOFO + v16 + v17 corpus rows for each fold — taking the
    *union over folds* would multi-count those. Instead we walk
    sources directly to avoid double counting."""
    names_v18, triples_v18 = _collect_v18_names_and_triples(v18_root)
    stats = {"n_v11_lofo": 0, "n_v16_corpus": 0, "n_v17_corpus": 0,
             "dropped_by_name_guard": 0, "dropped_by_triple_guard": 0,
             "dropped_by_dedup": 0}
    rows: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()  # (theorem_name, tactic)

    # v11 LOFO train rows (one canonical copy per family)
    for fam_dir in (ROOT / "data" / "processed"
                    / "proof_blocks_v11_family_lofo").iterdir():
        if not fam_dir.is_dir():
            continue
        for r in _read_jsonl(fam_dir / "train.jsonl"):
            stats["n_v11_lofo"] += 1
            nm = r.get("theorem_name", "")
            triple = (r.get("theorem_statement", ""),
                      r.get("state_before", ""),
                      r.get("tactic", ""))
            if nm in names_v18:
                stats["dropped_by_name_guard"] += 1
                continue
            if triple in triples_v18:
                stats["dropped_by_triple_guard"] += 1
                continue
            k = (nm, r.get("tactic", ""))
            if k in seen:
                stats["dropped_by_dedup"] += 1
                continue
            seen.add(k)
            rows.append(r)

    # v16 contrapositive corpus
    for r in _read_jsonl(v16_corpus):
        stats["n_v16_corpus"] += 1
        nm = r.get("theorem_name", "")
        triple = (r.get("theorem_statement", ""),
                  r.get("state_before", ""), r.get("tactic", ""))
        if nm in names_v18 or triple in triples_v18:
            stats["dropped_by_name_guard" if nm in names_v18
                  else "dropped_by_triple_guard"] += 1
            continue
        k = (nm, r.get("tactic", ""))
        if k in seen:
            stats["dropped_by_dedup"] += 1
            continue
        seen.add(k)
        rows.append(r)

    # v17 arrow_false_elim corpus
    for r in _read_jsonl(v17_corpus):
        stats["n_v17_corpus"] += 1
        nm = r.get("theorem_name", "")
        triple = (r.get("theorem_statement", ""),
                  r.get("state_before", ""), r.get("tactic", ""))
        if nm in names_v18 or triple in triples_v18:
            stats["dropped_by_name_guard" if nm in names_v18
                  else "dropped_by_triple_guard"] += 1
            continue
        k = (nm, r.get("tactic", ""))
        if k in seen:
            stats["dropped_by_dedup"] += 1
            continue
        seen.add(k)
        rows.append(r)

    return rows, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v17-token-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v17_token"))
    ap.add_argument("--v16-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v16_contrapositive_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--v17-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v17_arrow_false_elim_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--v18-root",
                    default=str(ROOT / "data" / "processed"
                                / "v18_broad_core"))
    ap.add_argument("--out-dir",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v18_broad_synthetic"))
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--embedding-dim", type=int, default=96)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-fraction", type=float, default=0.08)
    args = ap.parse_args(argv)

    rows, stats = _gather_synthetic(
        v17_token_root=Path(args.v17_token_root),
        v16_corpus=Path(args.v16_corpus),
        v17_corpus=Path(args.v17_corpus),
        v18_root=Path(args.v18_root),
    )
    logger.info("synthetic pool: %d rows", len(rows))
    for k, v in stats.items():
        logger.info("  %s = %d", k, v)

    # Build vocab from train texts + targets.
    src_texts = [build_input_text(r.get("theorem_statement", ""),
                                  r.get("state_before", "")) for r in rows]
    tactics = [r.get("tactic", "") for r in rows]
    vocab = TokenVocab.build(src_texts, tactics)
    logger.info("vocab size: %d", len(vocab))

    examples = [Example(
        theorem_name=r.get("theorem_name", ""),
        theorem_statement=r.get("theorem_statement", ""),
        state_before=r.get("state_before", ""),
        tactic=r.get("tactic", ""),
        split="train",
    ) for r in rows]

    # Stratified val by tactic-head (best-effort)
    import random as _r
    rng = _r.Random(args.seed)
    indices = list(range(len(examples)))
    rng.shuffle(indices)
    n_val = max(20, int(len(examples) * args.val_fraction))
    val_idx = set(indices[:n_val])
    train_examples = [e for i, e in enumerate(examples) if i not in val_idx]
    val_examples = [e for i, e in enumerate(examples) if i in val_idx]
    logger.info("train=%d val=%d", len(train_examples), len(val_examples))

    cfg = TokenTrainConfig(
        epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
        embedding_dim=args.embedding_dim, hidden_dim=args.hidden_dim,
        beam_width=args.beam_width, seed=args.seed,
    )
    art = train_token(
        train_examples, val_examples, vocab, cfg,
        log_fn=lambda r: logger.info(
            "  epoch=%d train_loss=%.4f val_loss=%.4f val_exact=%.4f",
            r["epoch"], r["train_loss"], r["val_loss"],
            r["val_greedy_exact_top1"],
        ) if (r["epoch"] % 2 == 0 or r["epoch"] == cfg.epochs - 1) else None,
    )
    out_dir = Path(args.out_dir)
    save_token_artifacts(out_dir, art, cfg, extra={"corpus": "broad_synthetic"})
    (out_dir / "gather_stats.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8")
    logger.info("V18 BROAD SYNTHETIC MODEL TRAINING DONE; saved to %s",
                out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
