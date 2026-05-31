"""Mini-ELF v2 pipeline: build_dataset split-override + per-row metadata,
combined-corpus provenance, failure taxonomy, and no-state_after guards.
Pure-Python (torch is imported transitively but no model is built); no Lean."""

from __future__ import annotations

import json
from pathlib import Path

from mini_elf_lean.dataset_builder import BuildFilters, SplitConfig, build_dataset

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _trace(name, tactic, stmt="(p : Prop) : p", state="p : Prop\n⊢ p"):
    return {
        "theorem_name": name, "theorem_statement": stmt, "state_before": state,
        "tactic": tactic, "state_after": "<verified by lean-cli>", "success": True,
        "proof_finished": True, "backend": "lean-cli",
    }


def _write(path, rows):
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_build_dataset_split_override_and_metadata(tmp_path):
    traces = tmp_path / "v.jsonl"
    _write(traces, [_trace("t1", "exact h"), _trace("t2", "rfl"), _trace("t3", "intro h")])
    override = {"t1": "train", "t2": "val", "t3": "test"}
    meta = {
        "t1": {"pattern_family": "fam_a", "difficulty": "easy"},
        "t2": {"pattern_family": "fam_b", "difficulty": "hard"},
        "t3": {"pattern_family": "fam_c", "difficulty": "medium"},
    }
    summary = build_dataset(
        [traces], tmp_path / "out",
        filters=BuildFilters(backends=("lean-cli",)),
        splits=SplitConfig(seed=1), split_override=override, split_strategy="custom",
        theorem_meta=meta, corpus_source="hard",
    )
    rows = [json.loads(l) for l in (tmp_path / "out" / "next_tactic.jsonl").read_text().splitlines()]
    by_name = {r["theorem_name"]: r for r in rows}
    assert by_name["t1"]["split"] == "train"
    assert by_name["t2"]["split"] == "val"
    assert by_name["t3"]["split"] == "test"
    # metadata attached, incl. corpus_source
    assert by_name["t1"]["metadata"]["pattern_family"] == "fam_a"
    assert by_name["t1"]["metadata"]["corpus_source"] == "hard"
    # strategy recorded
    splits = json.loads((tmp_path / "out" / "theorem_splits.json").read_text())
    assert splits["strategy"] == "custom"


def test_build_dataset_falls_back_to_hash_when_no_override(tmp_path):
    traces = tmp_path / "v.jsonl"
    _write(traces, [_trace(f"thm{i}", "rfl") for i in range(10)])
    summary = build_dataset([traces], tmp_path / "out",
                            filters=BuildFilters(backends=("lean-cli",)))
    rows = [json.loads(l) for l in (tmp_path / "out" / "next_tactic.jsonl").read_text().splitlines()]
    assert all(r["split"] in ("train", "val", "test") for r in rows)
    assert all("metadata" not in r for r in rows)  # no meta -> no metadata key


def test_combined_corpus_provenance_is_leakage_free():
    """The on-disk combined dataset (if built) must tag corpus_source and keep
    train/val/test theorem-disjoint."""
    import pytest
    nt = Path("data/processed/combined_lean_cli/next_tactic.jsonl")
    if not nt.exists():
        pytest.skip("combined dataset not built")
    rows = [json.loads(l) for l in nt.read_text(encoding="utf-8").splitlines()]
    sources = {r.get("metadata", {}).get("corpus_source") for r in rows}
    assert sources == {"basic", "hard"}
    by_split = {}
    for r in rows:
        by_split.setdefault(r["split"], set()).add(r["theorem_name"])
    tr, va, te = by_split.get("train", set()), by_split.get("val", set()), by_split.get("test", set())
    assert not (tr & va) and not (tr & te) and not (va & te)


def test_failure_taxonomy_classify():
    from scripts.analyze_v2_failures import _classify
    # malformed head
    assert _classify("(p:Prop):p", "p : Prop\n⊢ p", "garblexyz hp", None, False) == "malformed"
    # wrong conjunct: goal p matches LEFT of h:p∧q, candidate uses .2
    assert _classify("(p q:Prop)(h:p∧q):p", "p q : Prop\nh : p ∧ q\n⊢ p", "exact h.2", "and_elim_left", False) == "wrong_conjunct"
    # exists goal failure -> wrong_witness
    assert _classify(": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5", "exact ⟨0, rfl⟩", "exists_witness", False) == "wrong_witness"
    # requires_multistep single-shot -> missing_multistep
    assert _classify("(a b c d:Prop)...", "a b c d : Prop\n⊢ a → d", "exact h1", "imp_chain3", True) == "missing_multistep"


def test_analyze_handles_predictions():
    from scripts.analyze_v2_failures import analyze
    preds = [{
        "theorem_name": "t1", "theorem_statement": "(p q:Prop)(h:p∧q):p",
        "state_before": "p q : Prop\nh : p ∧ q\n⊢ p",
        "predictions": ["exact h.2", "exact h.1"],
        "prediction_provenance": [{"source": "flow_decoder", "reranker_score": 0.9, "sample_count": 5},
                                  {"source": "flow_decoder", "reranker_score": 0.8, "sample_count": 3}],
        "lean_results": {"exact h.2": {"success": False}, "exact h.1": {"success": True}},
    }]
    out = analyze(preds, {"t1": "and_elim_left"}, {"t1": "easy"}, {"t1": False})
    assert out["failure_taxonomy"].get("wrong_conjunct") == 1  # failed top-1 was wrong conjunct
    # a verified candidate (h.1) ranked below the failed top-1 -> false negative
    assert out["reranker_calibration"]["top1_false_negatives"]
    assert out["source_effectiveness"]["verified_by_source"]["flow_decoder"] == 1


def test_v2_modules_never_access_state_after():
    files = [
        SRC / "splits.py",
        SCRIPTS / "analyze_v2_failures.py",
        SCRIPTS / "build_combined.py",
        SCRIPTS / "train_mini_elf_v2.py",
        SCRIPTS / "generate_hard_corpus.py",
    ]
    for f in files:
        text = f.read_text(encoding="utf-8")
        for pat in (".state_after", '["state_after"]', "['state_after']",
                    'get("state_after"', "get('state_after'"):
            assert pat not in text, f"{f.name} accesses state_after via {pat!r}"
