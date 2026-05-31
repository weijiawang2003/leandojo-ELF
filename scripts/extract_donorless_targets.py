"""Mini-ELF v8 Part 1 — extract the donorless target set.

The v7 conclusion was: every config collapses to ``pass@5 = 0.00`` on
``family_holdout`` and ``operation_holdout`` because retrieval cannot return a
proof the donor pool does not contain. v8 has to attack those rows directly, so
this script materialises the **target set**:

* For each family_holdout / operation_holdout test theorem
  - ``theorem_name``, ``theorem_statement``, ``state_before``
  - ``family`` (= ``metadata.pattern_family``)
  - ``required_operation`` (computed by the same heuristic that
    :mod:`retrieval_splits` uses — see ``retrieval_features.required_operation``)
  - ``available_donor_families`` (= every family present in train, i.e. every
    family OTHER than the held one for family_holdout; every family whose
    operation differs from the held one for operation_holdout)
  - ``has_manual_verified``      — was this theorem ever verified by lean-cli
                                   anywhere in the seed pool?
  - ``shortest_verified_tactic`` — the shortest such verified tactic across the
                                   seed pool, **for analysis only** (used to
                                   characterise the missing-shape, never as a
                                   model output).
  - ``why_retrieval_fails``      — short string ("no same-family donor",
                                   "no same-operation donor", or
                                   "same-operation sibling has wrong body").

Grouping (matches the v8 brief's taxonomy):
    negation/contradiction → neg_exfalso, neg_imp_exfalso, neg_double_intro
    contrapositive          → neg_contrapositive
    exists_elim             → exists_elim_conj, exists_elim_prop, neg_or_cases
    forall_inst             → forall_inst
    rewrite                 → rewrite_succ
    exists_reconstruct      → exists_reconstruct
    other                   → everything else / unmapped

Outputs
-------
data/baselines/v8_donorless/family_holdout_targets.jsonl
data/baselines/v8_donorless/operation_holdout_targets.jsonl
data/baselines/v8_donorless/summary.json

Honest scope
------------
``state_after`` is *not* loaded. The "shortest verified tactic" is the tactic
field of a verified seed row whose ``state_after_is_real`` we do not consult
(theorem-level only). The shortest tactic is reported for analysis — v8 must
not silently copy it as a model prediction; that would be the manual oracle the
brief explicitly forbids.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.retrieval_features import extract_features  # noqa: E402


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #

def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """Skip comment / blank lines, yield decoded rows."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            yield json.loads(s)


def load_seed_pool() -> List[Dict[str, Any]]:
    """All processed verification rows across the three corpora (the place
    where the *tactic* and the success flag actually live). The
    ``data/seeds/*.jsonl`` files are theorem *definitions* — they do not record
    verified tactics, so they are not the right pool for "shortest verified
    tactic". We pull from ``data/processed/<corpus>/next_tactic.jsonl`` instead
    (theorem-level lean-cli verified)."""
    pool: List[Dict[str, Any]] = []
    proc = ROOT / "data" / "processed"
    if not proc.exists():
        return pool
    for sub in proc.iterdir():
        f = sub / "next_tactic.jsonl"
        if not f.exists():
            continue
        for row in iter_jsonl(f):
            pool.append(row)
    return pool


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #

FAMILY_GROUP: Dict[str, str] = {
    "neg_exfalso": "negation_contradiction",
    "neg_imp_exfalso": "negation_contradiction",
    "neg_double_intro": "negation_contradiction",
    "neg_contrapositive": "contrapositive",
    "exists_elim_conj": "exists_elim",
    "exists_elim_prop": "exists_elim",
    "neg_or_cases": "exists_elim",
    "forall_inst": "forall_inst",
    "rewrite_succ": "rewrite",
    "exists_reconstruct": "exists_reconstruct",
}


def group_for(family: str) -> str:
    return FAMILY_GROUP.get(family, "other")


# --------------------------------------------------------------------------- #
# Audit core
# --------------------------------------------------------------------------- #

def collect_test_rows_by_split(split_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    """For each fold subdir, return the test rows (split=='test'). Skips
    manifest/meta files."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for sub in sorted(split_dir.iterdir()):
        if not sub.is_dir():
            continue
        f = sub / "next_tactic.jsonl"
        if not f.exists():
            continue
        rows = [r for r in iter_jsonl(f) if r.get("split") == "test"]
        out[sub.name] = rows
    return out


def index_seeds(pool: List[Dict[str, Any]]) -> Tuple[
    Dict[str, str],                       # theorem -> family
    Dict[str, List[str]],                 # theorem -> verified tactics
]:
    thm2fam: Dict[str, str] = {}
    thm2tac: Dict[str, List[str]] = defaultdict(list)
    for row in pool:
        thm = row.get("theorem_name")
        if not thm:
            continue
        fam = (row.get("metadata") or {}).get("pattern_family")
        if fam and thm not in thm2fam:
            thm2fam[thm] = fam
        if row.get("success") is True:
            tac = row.get("tactic")
            if tac:
                thm2tac[thm].append(tac)
    return thm2fam, thm2tac


def required_op_for_row(row: Dict[str, Any]) -> str:
    """Same heuristic the v6/v7 ranker uses (via :func:`extract_features`)."""
    feats = extract_features(row.get("theorem_statement"),
                             row.get("state_before", "") or "")
    return feats.required_operation


def build_target(
    row: Dict[str, Any],
    *,
    split_kind: str,        # "family_holdout" | "operation_holdout"
    held: str,              # the held family or held operation for this fold
    train_families: Set[str],
    train_operations: Set[str],
    sibling_families: Set[str],
    thm2tac: Dict[str, List[str]],
) -> Dict[str, Any]:
    thm = row.get("theorem_name")
    family = (row.get("metadata") or {}).get("pattern_family", "?")
    op = required_op_for_row(row)
    verified = thm2tac.get(thm, [])
    shortest = min(verified, key=len) if verified else None

    if split_kind == "family_holdout":
        why = "no_same_family_donor"
        if sibling_families:
            why = "no_same_family_donor;same_operation_sibling_in_train"
    else:  # operation_holdout
        why = "no_same_operation_donor"
        if op == "unknown":
            why = "operation_unknown;abstract_filter_abstains"

    return {
        "theorem_name": thm,
        "theorem_statement": row.get("theorem_statement"),
        "state_before": row.get("state_before"),
        "family": family,
        "group": group_for(family),
        "required_operation": op,
        "split_kind": split_kind,
        "held": held,
        "available_donor_families": sorted(train_families - {family}),
        "same_operation_siblings_in_train": sorted(sibling_families),
        "has_manual_verified": bool(verified),
        "n_verified_tactics": len(verified),
        "shortest_verified_tactic": shortest,    # ANALYSIS ONLY — not a model output
        "why_retrieval_fails": why,
    }


def audit() -> Dict[str, Any]:
    pool = load_seed_pool()
    thm2fam, thm2tac = index_seeds(pool)

    out: Dict[str, Any] = {
        "family_holdout": [],
        "operation_holdout": [],
        "summary": {
            "family_holdout": {"n_targets": 0, "by_group": defaultdict(int),
                               "with_manual_verified": 0, "without": 0},
            "operation_holdout": {"n_targets": 0, "by_group": defaultdict(int),
                                  "with_manual_verified": 0, "without": 0},
        },
    }

    # --- family_holdout ---
    fh_dir = ROOT / "data" / "processed" / "planner_blind_family_holdout"
    fh_manifest = json.loads((fh_dir / "manifest.json").read_text(encoding="utf-8"))
    siblings_by_fam: Dict[str, Set[str]] = {
        f["held_family"]: set(f.get("sibling_families") or [])
        for f in fh_manifest.get("folds", [])
    }
    for fam, rows in collect_test_rows_by_split(fh_dir).items():
        siblings = siblings_by_fam.get(fam, set())
        # train families = every family in the corpus except the held one
        train_families = set(thm2fam.values()) - {fam}
        # train operations: we don't filter by op here (this is family_holdout)
        for row in rows:
            t = build_target(
                row, split_kind="family_holdout", held=fam,
                train_families=train_families, train_operations=set(),
                sibling_families=siblings, thm2tac=thm2tac,
            )
            out["family_holdout"].append(t)
            s = out["summary"]["family_holdout"]
            s["n_targets"] += 1
            s["by_group"][t["group"]] += 1
            if t["has_manual_verified"]:
                s["with_manual_verified"] += 1
            else:
                s["without"] += 1

    # --- operation_holdout ---
    op_dir = ROOT / "data" / "processed" / "planner_blind_operation_holdout"
    op_manifest = json.loads((op_dir / "manifest.json").read_text(encoding="utf-8"))
    held_op_by_fold: Dict[str, str] = {
        f["dir"].rsplit("/", 1)[-1]: f["held_operation"]
        for f in op_manifest.get("folds", [])
    }
    for fold_name, rows in collect_test_rows_by_split(op_dir).items():
        held_op = held_op_by_fold.get(fold_name, fold_name)
        # train operations = every op except the held one
        for row in rows:
            t = build_target(
                row, split_kind="operation_holdout", held=held_op,
                train_families=set(thm2fam.values()),
                train_operations=set(),
                sibling_families=set(),
                thm2tac=thm2tac,
            )
            out["operation_holdout"].append(t)
            s = out["summary"]["operation_holdout"]
            s["n_targets"] += 1
            s["by_group"][t["group"]] += 1
            if t["has_manual_verified"]:
                s["with_manual_verified"] += 1
            else:
                s["without"] += 1

    # convert defaultdicts so JSON dumps deterministically
    for k in ("family_holdout", "operation_holdout"):
        out["summary"][k]["by_group"] = dict(out["summary"][k]["by_group"])
    return out


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #

def write_outputs(audit_data: Dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("family_holdout", "operation_holdout"):
        p = out_dir / f"{kind}_targets.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for t in audit_data[kind]:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(audit_data["summary"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "baselines" / "v8_donorless"))
    args = ap.parse_args()

    data = audit()
    out_dir = Path(args.out_dir)
    write_outputs(data, out_dir)

    s = data["summary"]
    print(f"family_holdout    targets: {s['family_holdout']['n_targets']}  "
          f"with_verified: {s['family_holdout']['with_manual_verified']}  "
          f"without: {s['family_holdout']['without']}")
    print(f"  by group: {s['family_holdout']['by_group']}")
    print(f"operation_holdout targets: {s['operation_holdout']['n_targets']}  "
          f"with_verified: {s['operation_holdout']['with_manual_verified']}  "
          f"without: {s['operation_holdout']['without']}")
    print(f"  by group: {s['operation_holdout']['by_group']}")
    print(f"-> wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
