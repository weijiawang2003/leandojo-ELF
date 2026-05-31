"""Leakage guards for the v17 family-LOFO folds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V11_ROOT = ROOT / "data" / "processed" / "proof_blocks_v11_family_lofo"
V16_ROOT = ROOT / "data" / "processed" / "proof_blocks_v16_token"
V17_ROOT = ROOT / "data" / "processed" / "proof_blocks_v17_token"

V17_FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
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


def test_v17_folds_exist() -> None:
    if not V17_ROOT.exists():
        pytest.skip("v17 LOFO folds absent")
    for fam in V17_FAMILIES:
        assert (V17_ROOT / fam / "train.jsonl").exists()
        assert (V17_ROOT / fam / "test.jsonl").exists()
        assert (V17_ROOT / fam / "manifest.json").exists()


def _all_v11_test_names() -> set:
    names: set = set()
    for fam in V17_FAMILIES:
        for r in _read(V11_ROOT / fam / "test.jsonl"):
            nm = r.get("theorem_name")
            if nm:
                names.add(nm)
    return names


@pytest.mark.parametrize("fam", V17_FAMILIES)
def test_no_held_test_name_in_v17_train(fam: str) -> None:
    if not (V17_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v17 fold {fam} absent")
    forbidden = _all_v11_test_names()
    for r in _read(V17_ROOT / fam / "train.jsonl"):
        if r.get("corpus_source") == "v17_arrow_false_elim_corpus":
            assert r.get("theorem_name") not in forbidden, (
                f"v17 arrow_false_elim row leaked into {fam} train: "
                f"theorem_name={r['theorem_name']}")


@pytest.mark.parametrize("fam", V17_FAMILIES)
def test_no_exact_triple_match_with_held_family_test(fam: str) -> None:
    if not (V17_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v17 fold {fam} absent")
    test_triples = set()
    for r in _read(V17_ROOT / fam / "test.jsonl"):
        test_triples.add((
            r.get("theorem_statement", ""),
            r.get("state_before", ""),
            r.get("tactic", ""),
        ))
    for r in _read(V17_ROOT / fam / "train.jsonl"):
        if r.get("corpus_source") != "v17_arrow_false_elim_corpus":
            continue
        key = (r.get("theorem_statement", ""),
               r.get("state_before", ""),
               r.get("tactic", ""))
        assert key not in test_triples, (
            f"v17 row exactly matches held-family test triple in {fam}")


@pytest.mark.parametrize("fam", V17_FAMILIES)
def test_v17_train_strictly_greater_than_v16(fam: str) -> None:
    if not (V17_ROOT / fam / "train.jsonl").exists():
        pytest.skip(f"v17 fold {fam} absent")
    v16 = _read(V16_ROOT / fam / "train.jsonl")
    v17 = _read(V17_ROOT / fam / "train.jsonl")
    assert len(v17) > len(v16), (
        f"v17 {fam} train is not augmented: v16={len(v16)} v17={len(v17)}")


@pytest.mark.parametrize("fam", V17_FAMILIES)
def test_v17_test_identical_to_v16(fam: str) -> None:
    if not (V17_ROOT / fam / "test.jsonl").exists():
        pytest.skip(f"v17 fold {fam} absent")
    v16 = (V16_ROOT / fam / "test.jsonl").read_text(encoding="utf-8")
    v17 = (V17_ROOT / fam / "test.jsonl").read_text(encoding="utf-8")
    assert v16 == v17, f"v17 test set diverged from v16 on {fam}"


@pytest.mark.parametrize("fam", V17_FAMILIES)
def test_v17_manifest_counts(fam: str) -> None:
    if not (V17_ROOT / fam / "manifest.json").exists():
        pytest.skip(f"v17 manifest absent for {fam}")
    m = json.loads((V17_ROOT / fam / "manifest.json").read_text(
        encoding="utf-8"))
    assert m["v17_dropped_by_name_leakage_guard"] == 0
    assert m["v17_dropped_by_triple_leakage_guard"] == 0
    assert m["n_train_v17_added"] > 0
    assert m["uses_state_after"] is False
