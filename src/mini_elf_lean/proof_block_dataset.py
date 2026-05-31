"""Mini-ELF v8 — proof-block dataset for the generative proposer.

Pools every theorem-level lean-cli verified tactic the project knows about
across the three corpora (basic / hard / planner_blind) into a single
deduplicated set of training rows, then carves it into four train/test
*regimes* so the v8 seq2seq can be evaluated under each donor condition v7
identified:

  * ``interpolation``     — random 80/10/10 (theorem-level — all tactics of a
                            theorem stay in one fold). Comparable to the v6
                            current/literal split.
  * ``family_holdout``    — for every planner-blind family in turn, train =
                            everything outside that family, test = that
                            family's rows. Same condition v7 collapsed under.
  * ``operation_holdout`` — same as above but keyed by the v6 retrieval-feature
                            ``required_operation`` heuristic, pooled over the
                            6+1 operations seen across all three corpora.
  * ``donorless_eval``    — the union of the family_holdout test sets. The
                            single benchmark the v8 brief calls "donorless".

Schema of an emitted row::

    {
      "theorem_name":      str,
      "theorem_statement": str,
      "state_before":      str,             # NO state_after — never read here
      "tactic":            str,             # nonempty
      "family":            str | None,
      "required_operation":str,
      "corpus_source":     "basic"|"hard"|"planner_blind",
      "tactic_source":     "manual"|"verified",
      "split":             "train"|"val"|"test",
      "regime":            "interpolation"|"family_holdout/<fam>"|"operation_holdout/<op>"|"donorless_eval",
    }

The leakage invariants the builder enforces are unit-tested separately:

  * the *theorem* never crosses train/test in any regime;
  * the *family* never crosses for ``family_holdout/<fam>``;
  * the *operation* never crosses for ``operation_holdout/<op>``;
  * no row carries ``state_after`` or any field derived from it;
  * every ``tactic`` is nonempty.

Honest scope: the rows are theorem-level (the ``state_before`` is real, the
verified ``state_after`` is *not* loaded). The v3 planner blocks and v4
template ablation blocks were considered as additional sources but were left
out by default — they would inflate train coverage with synthesis output, and
the brief says to "label source clearly" if used. The builder accepts an
``--include-planner-blocks`` flag for the curious; the default is off.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Avoid cross-module imports beyond what's already used elsewhere.
from .retrieval_features import extract_features


PB_FAMILIES = (
    "neg_exfalso", "neg_imp_exfalso", "neg_double_intro", "neg_contrapositive",
    "neg_or_cases", "exists_elim_conj", "exists_elim_prop", "exists_reconstruct",
    "forall_inst", "rewrite_succ",
)


# --------------------------------------------------------------------------- #
# Row
# --------------------------------------------------------------------------- #

@dataclass
class ProofBlockRow:
    theorem_name: str
    theorem_statement: str
    state_before: str
    tactic: str
    family: Optional[str]
    required_operation: str
    corpus_source: str
    tactic_source: str
    split: str = "train"
    regime: str = "interpolation"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "theorem_name": self.theorem_name,
            "theorem_statement": self.theorem_statement,
            "state_before": self.state_before,
            "tactic": self.tactic,
            "family": self.family,
            "required_operation": self.required_operation,
            "corpus_source": self.corpus_source,
            "tactic_source": self.tactic_source,
            "split": self.split,
            "regime": self.regime,
        }


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #

CORPUS_TAGS = {
    "basic_lean_cli": "basic",
    "hard_lean_cli": "hard",
    "planner_blind_lean_cli": "planner_blind",
}

# Source files that contain "duplicate views" of the same verified rows under
# different splits — we read each underlying corpus ONCE via its canonical dir
# to avoid the same (theorem, tactic) showing up 4× because there are 4 split
# variants.
CANONICAL_DIRS = tuple(CORPUS_TAGS.keys())


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            yield json.loads(s)


def _drop_state_after(d: Dict[str, Any]) -> Dict[str, Any]:
    """Mutating no-op that asserts state_after is not leaked into a row."""
    for k in list(d.keys()):
        if k.startswith("state_after"):
            d.pop(k, None)
    return d


def load_pool(repo_root: Path) -> List[ProofBlockRow]:
    """Deduplicated proof-block rows across basic / hard / planner_blind."""
    seen: Set[Tuple[str, str, str]] = set()
    out: List[ProofBlockRow] = []
    for sub in CANONICAL_DIRS:
        f = repo_root / "data" / "processed" / sub / "next_tactic.jsonl"
        if not f.exists():
            continue
        tag = CORPUS_TAGS[sub]
        for row in _iter_jsonl(f):
            if not row.get("success"):
                continue
            tac = (row.get("tactic") or "").strip()
            if not tac:
                continue
            thm = row.get("theorem_name") or ""
            sb  = row.get("state_before") or ""
            key = (thm, tac, sb)
            if key in seen:
                continue
            seen.add(key)
            fam = (row.get("metadata") or {}).get("pattern_family")
            feats = extract_features(row.get("theorem_statement"), sb)
            out.append(ProofBlockRow(
                theorem_name=thm,
                theorem_statement=row.get("theorem_statement") or "",
                state_before=sb,
                tactic=tac,
                family=fam,
                required_operation=feats.required_operation,
                corpus_source=tag,
                tactic_source="verified",
            ))
    return out


# --------------------------------------------------------------------------- #
# Regime builders
# --------------------------------------------------------------------------- #

def _stable_bucket(thm: str, salt: str) -> float:
    h = hashlib.sha256(f"{salt}::{thm}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def build_interpolation(
    pool: Sequence[ProofBlockRow],
    *,
    seed: str = "v8-interp",
    train_frac: float = 0.8,
    val_frac: float = 0.1,
) -> List[ProofBlockRow]:
    """Theorem-level random split. All tactics of a theorem stay in one fold."""
    thm_bucket: Dict[str, float] = {}
    for r in pool:
        thm_bucket.setdefault(r.theorem_name, _stable_bucket(r.theorem_name, seed))
    out: List[ProofBlockRow] = []
    for r in pool:
        b = thm_bucket[r.theorem_name]
        if b < train_frac:
            split = "train"
        elif b < train_frac + val_frac:
            split = "val"
        else:
            split = "test"
        rr = ProofBlockRow(**{**r.__dict__, "split": split, "regime": "interpolation"})
        out.append(rr)
    return out


def build_family_holdout(
    pool: Sequence[ProofBlockRow],
    family: str,
) -> List[ProofBlockRow]:
    """Train = every row whose family != held; test = every row in held family.
    Rows with ``family is None`` are kept in train (they can never be the held
    family by construction)."""
    out: List[ProofBlockRow] = []
    for r in pool:
        split = "test" if r.family == family else "train"
        out.append(ProofBlockRow(**{**r.__dict__, "split": split,
                                     "regime": f"family_holdout/{family}"}))
    return out


def build_operation_holdout(
    pool: Sequence[ProofBlockRow],
    operation: str,
) -> List[ProofBlockRow]:
    """Same as ``family_holdout`` but keyed by ``required_operation``. Note
    that ``unknown`` here means the heuristic abstained — it is still a valid
    held bucket (matches v7 LOOO semantics)."""
    out: List[ProofBlockRow] = []
    for r in pool:
        split = "test" if r.required_operation == operation else "train"
        out.append(ProofBlockRow(**{**r.__dict__, "split": split,
                                     "regime": f"operation_holdout/{operation}"}))
    return out


def build_donorless_eval(pool: Sequence[ProofBlockRow]) -> List[ProofBlockRow]:
    """Train = every row whose family is **not** in any planner-blind family
    set; test = every row whose family IS in that set. This is the single
    "donorless" benchmark — what v8 has to clear to claim donor-absent transfer
    works at all."""
    pb = set(PB_FAMILIES)
    out: List[ProofBlockRow] = []
    for r in pool:
        split = "test" if (r.family in pb) else "train"
        out.append(ProofBlockRow(**{**r.__dict__, "split": split,
                                     "regime": "donorless_eval"}))
    return out


# --------------------------------------------------------------------------- #
# Leakage invariants — enforced + asserted at write time
# --------------------------------------------------------------------------- #

def assert_no_theorem_leakage(rows: Sequence[ProofBlockRow]) -> None:
    seen: Dict[str, str] = {}
    for r in rows:
        prev = seen.get(r.theorem_name)
        if prev is None:
            seen[r.theorem_name] = r.split
        elif prev != r.split:
            raise AssertionError(
                f"theorem leakage: '{r.theorem_name}' "
                f"appears in both {prev!r} and {r.split!r}")


def assert_family_holdout(rows: Sequence[ProofBlockRow], family: str) -> None:
    for r in rows:
        if r.split == "train" and r.family == family:
            raise AssertionError(
                f"family leakage: held '{family}' theorem '{r.theorem_name}' in train")
        if r.split == "test" and r.family != family:
            raise AssertionError(
                f"family leakage: test row '{r.theorem_name}' has family "
                f"{r.family!r} != held {family!r}")


def assert_operation_holdout(rows: Sequence[ProofBlockRow], op: str) -> None:
    for r in rows:
        if r.split == "train" and r.required_operation == op:
            raise AssertionError(
                f"operation leakage: held '{op}' theorem '{r.theorem_name}' in train")
        if r.split == "test" and r.required_operation != op:
            raise AssertionError(
                f"operation leakage: test row '{r.theorem_name}' has op "
                f"{r.required_operation!r} != held {op!r}")


def assert_no_state_after(rows: Sequence[ProofBlockRow]) -> None:
    for r in rows:
        d = r.to_dict()
        for k in d:
            if k.startswith("state_after"):
                raise AssertionError(f"state_after leaked: {k!r}")


def assert_nonempty_tactics(rows: Sequence[ProofBlockRow]) -> None:
    for r in rows:
        if not r.tactic or not r.tactic.strip():
            raise AssertionError(f"empty tactic for {r.theorem_name!r}")


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #

def write_regime(rows: Sequence[ProofBlockRow], out_dir: Path) -> Dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_split: Dict[str, List[ProofBlockRow]] = defaultdict(list)
    for r in rows:
        by_split[r.split].append(r)
    counts: Dict[str, int] = {}
    for split, rs in by_split.items():
        p = out_dir / f"{split}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        counts[split] = len(rs)
    # Manifest
    manifest = {
        "regime": rows[0].regime if rows else "?",
        "counts": counts,
        "n_total": len(rows),
        "n_unique_theorems": len({r.theorem_name for r in rows}),
        "n_families": len({r.family for r in rows if r.family}),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return counts


__all__ = [
    "ProofBlockRow", "PB_FAMILIES",
    "load_pool",
    "build_interpolation", "build_family_holdout",
    "build_operation_holdout", "build_donorless_eval",
    "assert_no_theorem_leakage", "assert_family_holdout",
    "assert_operation_holdout", "assert_no_state_after",
    "assert_nonempty_tactics",
    "write_regime",
]
