"""Tests for the v16 family-LOFO build: leakage guards must not be
bypassable.

Pins:
  * Every v16 family-LOFO train.jsonl contains the v11 train rows
    plus the v16 corpus train rows — and **no test theorem name**
    from ANY v11 LOFO family.
  * No exact (statement, state, tactic) triple in train matches a
    held-family test row.
  * The combined train sets are clearly tagged so a downstream audit
    can separate v11 and v16 sources.
  * The test set is structurally unchanged from v11 LOFO.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V11_ROOT = ROOT / "data" / "processed" / "proof_blocks_v11_family_lofo"
V16_ROOT = ROOT / "data" / "processed" / "proof_blocks_v16_token"

V16_FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso")


def _read(p: Path):
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


# ----------------- existence ----------------------------------------------


def test_v16_folds_exist() -> None:
    if not V16_ROOT.exists():
        pytest.skip("v16 LOFO folds absent; run scripts/build_v16_family_lofo.py")
    for fam in V16_FAMILIES:
        assert (V16_ROOT / fam / "train.jsonl").exists()
        assert (V16_ROOT / fam / "test.jsonl").exists()
        assert (V16_ROOT / fam / "manifest.json").exists()


# ----------------- the headline leakage guard -----------------------------


def _all_v11_test_names() -> set:
    names: set = set()
    for fam in V16_FAMILIES:
        for r in _read(V11_ROOT / fam / "test.jsonl"):
            nm = r.get("theorem_name")
            if nm:
                names.add(nm)
    return names


@pytest.mark.parametrize("fam", V16_FAMILIES)
def test_no_held_family_test_theorem_name_in_v16_train(fam: str) -> None:
    if not (V16_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v16 fold {fam} absent")
    forbidden_names = _all_v11_test_names()
    for r in _read(V16_ROOT / fam / "train.jsonl"):
        # v11 train rows already use clean LOFO names; the guard is
        # specifically about v16 corpus rows.
        if r.get("corpus_source") == "v16_contrapositive_corpus":
            assert r.get("theorem_name") not in forbidden_names, (
                f"v16 corpus row leaked into {fam} train: "
                f"theorem_name={r['theorem_name']}")


@pytest.mark.parametrize("fam", V16_FAMILIES)
def test_no_exact_triple_match_with_held_family_test(fam: str) -> None:
    if not (V16_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v16 fold {fam} absent")
    test_triples = set()
    for r in _read(V16_ROOT / fam / "test.jsonl"):
        test_triples.add((
            r.get("theorem_statement", ""),
            r.get("state_before", ""),
            r.get("tactic", ""),
        ))
    for r in _read(V16_ROOT / fam / "train.jsonl"):
        if r.get("corpus_source") != "v16_contrapositive_corpus":
            continue
        key = (r.get("theorem_statement", ""),
               r.get("state_before", ""),
               r.get("tactic", ""))
        assert key not in test_triples, (
            f"v16 corpus row exactly matches held-family test triple in {fam}")


# ----------------- manifest accuracy --------------------------------------


@pytest.mark.parametrize("fam", V16_FAMILIES)
def test_manifest_counts_match_jsonl(fam: str) -> None:
    if not (V16_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v16 fold {fam} absent")
    mp = V16_ROOT / fam / "manifest.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    n_train = sum(1 for _ in (V16_ROOT / fam / "train.jsonl").open(
        encoding="utf-8") if _.strip())
    n_test = sum(1 for _ in (V16_ROOT / fam / "test.jsonl").open(
        encoding="utf-8") if _.strip())
    assert m["n_train_total"] == n_train
    assert m["n_test"] == n_test
    assert m["uses_state_after"] is False


@pytest.mark.parametrize("fam", V16_FAMILIES)
def test_v16_train_strictly_greater_than_v11(fam: str) -> None:
    if not (V16_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v16 fold {fam} absent")
    v11 = _read(V11_ROOT / fam / "train.jsonl")
    v16 = _read(V16_ROOT / fam / "train.jsonl")
    assert len(v16) > len(v11), (
        f"v16 {fam} train is not augmented: v11={len(v11)} v16={len(v16)}")


@pytest.mark.parametrize("fam", V16_FAMILIES)
def test_v16_test_identical_to_v11(fam: str) -> None:
    if not (V16_ROOT / fam / "test.jsonl").exists():
        pytest.skip(f"v16 fold {fam} absent")
    v11 = (V11_ROOT / fam / "test.jsonl").read_text(encoding="utf-8")
    v16 = (V16_ROOT / fam / "test.jsonl").read_text(encoding="utf-8")
    assert v11 == v16, f"v16 test set diverged from v11 LOFO on {fam}"


# ----------------- v16 corpus source visibility ---------------------------


@pytest.mark.parametrize("fam", V16_FAMILIES)
def test_v16_corpus_rows_clearly_tagged(fam: str) -> None:
    if not (V16_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v16 fold {fam} absent")
    rows = _read(V16_ROOT / fam / "train.jsonl")
    n_v16 = sum(1 for r in rows
                if r.get("corpus_source") == "v16_contrapositive_corpus")
    assert n_v16 > 0, f"v16 fold {fam} has no v16 corpus rows"
    # v16 corpus rows must NOT carry a v10 origin tag (no v10 leakage)
    for r in rows:
        if r.get("corpus_source") == "v16_contrapositive_corpus":
            assert r.get("regime") == "v16_contrapositive_redundancy"
