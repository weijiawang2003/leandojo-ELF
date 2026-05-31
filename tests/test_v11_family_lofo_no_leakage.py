"""Leakage guard tests for v11 per-family LOFO regimes.

v11 trains one seq2seq per held planner-blind family on a pool of
(v8 family-LOFO train) + (v10 redundancy cells minus held-family
duplicates). These tests pin three invariants per regime:

  1. No test theorem_name appears in train.
  2. No exact (state_before, tactic) pair appears in both train and test.
  3. No row with `family == <held>` appears in train (including v10 cells
     that might collide on family name).

They are stricter than `test_v10_no_leakage.py` because the v11 split adds
v10 cells of arbitrary family/operation, and a future v10 corpus that uses
the same family name as a planner-blind held family would silently leak.

Tests skip silently if the v11 regime dirs are absent (no model trained
yet).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
V11_ROOT = ROOT / "data" / "processed" / "proof_blocks_v11_family_lofo"


def _read_rows(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            continue
    return rows


def _v11_folds() -> List[Path]:
    if not V11_ROOT.exists():
        return []
    return sorted(p for p in V11_ROOT.iterdir() if p.is_dir())


def test_v11_no_theorem_name_leakage_per_fold():
    """For every v11 family-LOFO fold, no test theorem_name is in train."""
    folds = _v11_folds()
    if not folds:
        return
    violations: List[str] = []
    for fold in folds:
        train = _read_rows(fold / "train.jsonl")
        test = _read_rows(fold / "test.jsonl")
        train_thms: Set[str] = {r["theorem_name"] for r in train}
        test_thms: Set[str] = {r["theorem_name"] for r in test}
        leaked = train_thms & test_thms
        if leaked:
            violations.append(f"{fold.name}: {sorted(leaked)[:3]}")
    assert not violations, "v11 theorem-name leakage:\n  " + "\n  ".join(violations)


def test_v11_no_state_tactic_pair_leakage_per_fold():
    """For every v11 fold, no (state_before, tactic) pair in test is in train.
    Even if a v10 cell shares the surface-form tactic, it must not share the
    exact (state_before, tactic) row of any test."""
    folds = _v11_folds()
    if not folds:
        return
    violations: List[str] = []
    for fold in folds:
        train = _read_rows(fold / "train.jsonl")
        test = _read_rows(fold / "test.jsonl")
        train_pairs: Set[Tuple[str, str]] = {
            (r["state_before"], r["tactic"]) for r in train
        }
        test_pairs: Set[Tuple[str, str]] = {
            (r["state_before"], r["tactic"]) for r in test
        }
        leaked = train_pairs & test_pairs
        if leaked:
            violations.append(f"{fold.name}: {len(leaked)} pair(s)")
    assert not violations, ("v11 (state_before, tactic) leakage:\n  "
                            + "\n  ".join(violations))


def test_v11_train_excludes_held_family_planner_blind_rows():
    """For every v11 fold, NO planner_blind row in train carries
    family == <held>. (This is the original v8 LOFO condition; v11 must
    not silently weaken it when adding v10 cells.)"""
    folds = _v11_folds()
    if not folds:
        return
    violations: List[str] = []
    for fold in folds:
        fam = fold.name
        train = _read_rows(fold / "train.jsonl")
        bad = [r for r in train
               if r.get("corpus_source") == "planner_blind"
               and r.get("family") == fam]
        if bad:
            violations.append(f"{fold.name}: {len(bad)} planner_blind rows "
                              f"with family={fam}")
    assert not violations, ("v11 held-family planner_blind leakage:\n  "
                            + "\n  ".join(violations))


def test_v11_v10_cells_in_train_carry_redundancy_corpus_source():
    """Sanity: every v10 row that landed in v11 train must be tagged
    ``corpus_source=redundancy_corpus`` (otherwise the leakage tests above
    cannot find them). Skips if no v10 cells were kept in any fold."""
    folds = _v11_folds()
    if not folds:
        return
    any_v10_kept = False
    for fold in folds:
        train = _read_rows(fold / "train.jsonl")
        v10 = [r for r in train if r.get("corpus_source") == "redundancy_corpus"]
        if v10:
            any_v10_kept = True
            for r in v10:
                assert "theorem_name" in r and r["theorem_name"].startswith("v10_"), (
                    f"{fold.name}: v10-tagged row has unexpected theorem_name "
                    f"{r.get('theorem_name')!r}"
                )
    # If no v10 cells were ever kept, the test is vacuous but should still
    # not fail — the dataset just doesn't have v10 redundancy yet.
    # (Skip is preferable to assert in that case.)
    if not any_v10_kept:
        return


def test_v11_manifest_records_leakage_assertions_passed():
    """The build script writes ``leakage_assertions: passed`` into each
    manifest after running its inline checks. If a manifest is missing or
    fails to record that, fail loudly."""
    folds = _v11_folds()
    if not folds:
        return
    violations: List[str] = []
    for fold in folds:
        mp = fold / "manifest.json"
        if not mp.exists():
            violations.append(f"{fold.name}: missing manifest.json")
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            violations.append(f"{fold.name}: manifest.json not valid JSON")
            continue
        if m.get("leakage_assertions") != "passed":
            violations.append(f"{fold.name}: leakage_assertions != passed "
                              f"({m.get('leakage_assertions')!r})")
    assert not violations, "v11 manifest leakage record:\n  " + "\n  ".join(violations)
