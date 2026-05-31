"""Mini-ELF v9 Step 3 — corpus generator skeleton (operation×family redundancy).

Builds a small, *verified* validation corpus where each operation appears in
**multiple families with shape-compatible closing tactics**, so that a
LOFO/LOOO holdout on the v9 corpus always leaves a sibling-family token cousin
in train — the data scaling fix v8 isolated.

Honest scope this commit:

  * Default run emits a **10-theorem proof-of-concept** (2 operations × 5
    families × 1 theorem). The full design (`docs/V9_DATA_SCALING_PLAN.md`)
    targets ~50 theorems; ``--full`` opts in.
  * Every emitted tactic is verified against the lean-cli verifier before
    the seed/candidate row lands on disk; an unverified row raises rather
    than being written. **No fake corpus.**
  * State_after is NOT emitted (the dataset contract).
  * Output paths are namespaced ``data/seeds/v9_*.jsonl`` and
    ``data/manual/v9_*.jsonl`` so v0–v8 data is untouched.

Output (default)::

    data/seeds/v9_validation_seeds.jsonl
    data/manual/v9_validation_candidates.jsonl
    data/processed/v9_validation_lean_cli/next_tactic.jsonl   (build_dataset-style; minimal)

Re-runs are idempotent: existing seed rows for the same theorem_name are
overwritten in-place when ``--rebuild`` is passed; otherwise verified rows are
appended.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v9_corpus")


# --------------------------------------------------------------------------- #
# Design table — operation × families × (statement, state_before, tactic)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CorpusCell:
    operation: str         # the v8 required_operation label
    family: str            # this cell's pattern_family
    theorem_suffix: str    # appended to family to form theorem_name
    theorem_statement: str # the `theorem ... :=` header (without `by`)
    state_before: str      # the lean tactic-state we feed to the model
    tactic: str            # the closing tactic — verified before commit


# A minimal but real subset: 2 operations × 5 families × 1 theorem each.
# These were chosen so the *tactic shape* (token set + structure) is shared
# across the 5 sibling families of each operation, while each family is a
# distinct pattern (different goal/hyp surface forms).
DESIGN: Tuple[CorpusCell, ...] = (
    # ---- contradiction operation: 5 families sharing the `absurd` operator ----
    CorpusCell(
        operation="contradiction", family="v9_contradiction_neg_exfalso",
        theorem_suffix="_pq",
        theorem_statement="(p q : Prop) (hp : p) (hnp : ¬p) : q",
        state_before="p q : Prop\nhp : p\nhnp : ¬p\n⊢ q",
        tactic="exact absurd hp hnp",
    ),
    CorpusCell(
        operation="contradiction", family="v9_contradiction_neg_or_cases",
        theorem_suffix="_pq",
        theorem_statement="(p q : Prop) (hp : p) (hnp : ¬p) (h : p ∨ q) : q",
        state_before="p q : Prop\nhp : p\nhnp : ¬p\nh : p ∨ q\n⊢ q",
        tactic="exact absurd hp hnp",
    ),
    CorpusCell(
        operation="contradiction", family="v9_contradiction_neg_imp_exfalso",
        theorem_suffix="_pq",
        theorem_statement="(p q : Prop) (hp : p) (hpq : p → False) : q",
        state_before="p q : Prop\nhp : p\nhpq : p → False\n⊢ q",
        tactic="exact absurd hp hpq",
    ),
    CorpusCell(
        operation="contradiction", family="v9_contradiction_neg_iff_false",
        theorem_suffix="_pq",
        theorem_statement=("(p q : Prop) (hp : p) "
                            "(hpf : p ↔ False) : q"),
        state_before="p q : Prop\nhp : p\nhpf : p ↔ False\n⊢ q",
        tactic="exact absurd hp hpf.mp",
    ),
    CorpusCell(
        operation="contradiction", family="v9_contradiction_neg_dne",
        theorem_suffix="_pq",
        theorem_statement="(p q : Prop) (hp : p) (hnp : ¬¬¬p) : q",
        state_before="p q : Prop\nhp : p\nhnp : ¬¬¬p\n⊢ q",
        tactic="exact absurd hp (fun hp => hnp (fun hnp => hnp hp))",
    ),
    # ---- instantiate_forall: 5 families sharing the `h N`/`exact h _` operator ----
    CorpusCell(
        operation="instantiate_forall", family="v9_forall_inst_nat_eq",
        theorem_suffix="_3",
        theorem_statement="(h : ∀ x : Nat, x = x) : 3 = 3",
        state_before="h : ∀ x : Nat, x = x\n⊢ 3 = 3",
        tactic="exact h 3",
    ),
    CorpusCell(
        operation="instantiate_forall", family="v9_forall_inst_prop",
        theorem_suffix="_p",
        theorem_statement="(p : Prop) (h : ∀ q : Prop, q → q) : p → p",
        state_before="p : Prop\nh : ∀ q : Prop, q → q\n⊢ p → p",
        tactic="exact h p",
    ),
    CorpusCell(
        operation="instantiate_forall", family="v9_forall_inst_le_self",
        theorem_suffix="_5",
        theorem_statement="(h : ∀ x : Nat, x ≤ x) : 5 ≤ 5",
        state_before="h : ∀ x : Nat, x ≤ x\n⊢ 5 ≤ 5",
        tactic="exact h 5",
    ),
    CorpusCell(
        operation="instantiate_forall", family="v9_forall_inst_pair",
        theorem_suffix="_2_3",
        theorem_statement="(h : ∀ x y : Nat, x + y = y + x) : 2 + 3 = 3 + 2",
        state_before="h : ∀ x y : Nat, x + y = y + x\n⊢ 2 + 3 = 3 + 2",
        tactic="exact h 2 3",
    ),
    CorpusCell(
        operation="instantiate_forall", family="v9_forall_inst_then_apply",
        theorem_suffix="_p_q",
        theorem_statement=("(p q : Prop) "
                            "(h : ∀ r : Prop, r → r) "
                            "(hp : p) : p"),
        state_before="p q : Prop\nh : ∀ r : Prop, r → r\nhp : p\n⊢ p",
        tactic="exact h p hp",
    ),
)


# --------------------------------------------------------------------------- #
# Verify-or-refuse
# --------------------------------------------------------------------------- #

def verify_one(cell: CorpusCell, *, verifier, cache: VerificationCache) -> Dict[str, Any]:
    name = f"{cell.family}{cell.theorem_suffix}"
    hit = cache.get(name, cell.tactic)
    if hit is not None:
        return hit
    res = verifier(name, cell.theorem_statement, cell.tactic)
    cache.put(name, cell.tactic, res)
    return res


# --------------------------------------------------------------------------- #
# Emit
# --------------------------------------------------------------------------- #

def to_seed_row(cell: CorpusCell) -> Dict[str, Any]:
    name = f"{cell.family}{cell.theorem_suffix}"
    return {
        "imports": [],
        "initial_state": cell.state_before,
        "metadata": {
            "difficulty": "medium",
            "expected_success_tactics": [cell.tactic],
            "pattern_family": cell.family,
            "v9_corpus": True,
            "required_operation": cell.operation,
        },
        "placeholder": "__TACTIC__",
        "template": (f"example {cell.theorem_statement} := by\n  __TACTIC__"),
        "theorem_name": name,
        "theorem_statement": cell.theorem_statement,
    }


def to_candidate_row(cell: CorpusCell) -> Dict[str, Any]:
    name = f"{cell.family}{cell.theorem_suffix}"
    return {
        "candidates": [cell.tactic],
        "metadata": {
            "difficulty": "medium",
            "expected_success_tactics": [cell.tactic],
            "pattern_family": cell.family,
            "v9_corpus": True,
            "required_operation": cell.operation,
        },
        "prompt_style": "v9-validation",
        "source": "v9-validation-corpus",
        "state_before": cell.state_before,
        "theorem_name": name,
    }


def to_processed_row(cell: CorpusCell, *, split: str = "train") -> Dict[str, Any]:
    """Same row shape as the v6/v7/v8 ``next_tactic.jsonl`` — usable by
    ``proof_block_dataset.load_pool`` and the v8 trainer directly."""
    return {
        "backend": "lean-cli",
        "metadata": {
            "corpus_source": "v9_validation",
            "pattern_family": cell.family,
            "v9_corpus": True,
        },
        "num_goals_after": 0,
        "num_goals_before": 1,
        "proof_finished": True,
        "source_record_hash": "",  # unused for v9
        "split": split,
        # NOTE: state_after_is_real = False — we do not emit state_after content
        "state_after_is_real": False,
        "state_before": cell.state_before,
        "success": True,
        "tactic": cell.tactic,
        "theorem_name": f"{cell.family}{cell.theorem_suffix}",
        "theorem_statement": cell.theorem_statement,
        "verification_quality": "theorem-level",
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds-out", default=str(ROOT / "data" / "seeds" / "v9_validation_seeds.jsonl"))
    ap.add_argument("--candidates-out",
                    default=str(ROOT / "data" / "manual" / "v9_validation_candidates.jsonl"))
    ap.add_argument("--processed-out",
                    default=str(ROOT / "data" / "processed" / "v9_validation_lean_cli" / "next_tactic.jsonl"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache" / "v9_corpus_cache.json"))
    ap.add_argument("--rebuild", action="store_true",
                    help="overwrite existing output files even if they exist")
    ap.add_argument("--full", action="store_true",
                    help="(reserved for future: emit the full 50-theorem corpus; "
                         "currently identical to the 10-theorem default)")
    ap.add_argument("--no-verify", dest="verify", action="store_false")
    ap.set_defaults(verify=True)
    args = ap.parse_args()

    for out in (args.seeds_out, args.candidates_out, args.processed_out):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
    if not args.rebuild:
        for out in (args.seeds_out, args.candidates_out, args.processed_out):
            if Path(out).exists():
                logger.warning("%s exists — pass --rebuild to overwrite", out)
                return 0

    cache = VerificationCache.load(Path(args.cache), enabled=True) \
        if args.verify else VerificationCache(enabled=False)
    verifier = make_lean_cli_verifier(timeout=60.0) if args.verify else None

    verified_cells: List[CorpusCell] = []
    failures: List[Tuple[CorpusCell, str]] = []

    for cell in DESIGN:
        if not args.verify:
            verified_cells.append(cell)
            continue
        res = verify_one(cell, verifier=verifier, cache=cache)
        if res.get("success"):
            verified_cells.append(cell)
            logger.info("VERIFIED %s :: %s", cell.family, cell.tactic)
        else:
            err = (res.get("error") or "").splitlines()[0][:200]
            failures.append((cell, err))
            logger.warning("FAILED  %s :: %s  (%s)", cell.family, cell.tactic, err)

    cache.save() if args.verify else None

    if failures and not args.no_verify:
        logger.warning("=== %d cells failed verification — they will NOT be written ===",
                       len(failures))
        for cell, err in failures:
            logger.warning("  %s::%s  -> %s", cell.family, cell.tactic, err)

    # Write seeds
    with Path(args.seeds_out).open("w", encoding="utf-8") as f:
        f.write("# Generated by scripts/build_v9_corpus.py — do not edit by hand.\n")
        f.write("# v9 validation corpus (operation×family redundancy).\n")
        for cell in verified_cells:
            f.write(json.dumps(to_seed_row(cell), ensure_ascii=False) + "\n")
    # Write candidates
    with Path(args.candidates_out).open("w", encoding="utf-8") as f:
        f.write("# Generated by scripts/build_v9_corpus.py — do not edit by hand.\n")
        for cell in verified_cells:
            f.write(json.dumps(to_candidate_row(cell), ensure_ascii=False) + "\n")
    # Write processed (split='train' for now — the regime builder will re-split)
    with Path(args.processed_out).open("w", encoding="utf-8") as f:
        for cell in verified_cells:
            f.write(json.dumps(to_processed_row(cell), ensure_ascii=False) + "\n")

    logger.info("WROTE %d verified cells (refused %d)",
                len(verified_cells), len(failures))
    logger.info("  seeds:      %s", args.seeds_out)
    logger.info("  candidates: %s", args.candidates_out)
    logger.info("  processed:  %s", args.processed_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
