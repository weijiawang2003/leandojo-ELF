"""Tests for the baseline evaluation harness.

Uses a fake verifier (lookup table) so no Lean is needed. The contracts:

  - pass@k and top-k-any-verified are computed off the same rank order.
  - VerificationCache survives a round-trip through disk and reuses entries.
  - The verifier is only called for distinct candidate tactics (dedup).
  - Empty eval split still produces a metrics + predictions output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from mini_elf_lean.baseline_eval import (
    EvaluationResult,
    VerificationCache,
    _cache_key,
    _pass_at_k,
    _topk_any_verified,
    evaluate,
)
from mini_elf_lean.baselines import Example, MajorityBaseline


def _ex(name="t1", state="⊢ p", tactic="exact h", split="val") -> Example:
    return Example(
        theorem_name=name,
        theorem_statement=f"({name})",
        state_before=state,
        tactic=tactic,
        split=split,
    )


# ---- helpers ----


def test_pass_at_k_takes_first_k_only() -> None:
    results = [
        {"success": False}, {"success": False}, {"success": True}, {"success": True},
    ]
    assert _pass_at_k(results, 1) is False
    assert _pass_at_k(results, 2) is False
    assert _pass_at_k(results, 3) is True
    assert _pass_at_k([], 5) is False


def test_topk_any_verified_returns_true_on_first_match() -> None:
    preds = ["wrong", "still_wrong", "exact h"]
    verified = frozenset({"exact h", "assumption"})
    assert _topk_any_verified(preds, verified, 1) is False
    assert _topk_any_verified(preds, verified, 3) is True
    assert _topk_any_verified([], verified, 3) is False
    assert _topk_any_verified(preds, frozenset(), 3) is False


# ---- verification cache ----


def test_cache_key_is_stable_and_distinct_for_different_inputs() -> None:
    k1 = _cache_key("t1", "exact h")
    assert k1 == _cache_key("t1", "exact h")  # stable
    assert k1 != _cache_key("t2", "exact h")  # theorem matters
    assert k1 != _cache_key("t1", "exact g")  # tactic matters


def test_verification_cache_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "vc.json"
    c = VerificationCache.load(p, enabled=True)
    assert c.get("t", "rfl") is None
    c.put("t", "rfl", {"success": True, "error": None, "elapsed_ms": 1.0})
    c.save()

    c2 = VerificationCache.load(p, enabled=True)
    assert c2.get("t", "rfl") == {"success": True, "error": None, "elapsed_ms": 1.0}
    # Missing keys still miss after reload.
    assert c2.get("t", "exact h") is None


def test_verification_cache_disabled_is_noop(tmp_path: Path) -> None:
    c = VerificationCache(path=tmp_path / "vc.json", enabled=False)
    c.put("t", "rfl", {"success": True})
    c.save()
    assert not (tmp_path / "vc.json").exists()
    assert c.get("t", "rfl") is None


def test_verification_cache_corrupt_file_starts_fresh(tmp_path: Path) -> None:
    p = tmp_path / "vc.json"
    p.write_text("{not valid json", encoding="utf-8")
    c = VerificationCache.load(p, enabled=True)
    assert len(c) == 0  # corrupt file ignored, not crashed


# ---- evaluate(): end-to-end with a fake verifier ----


class _FakeVerifier:
    """Lookup-table verifier. Counts calls so we can assert dedup happened."""

    def __init__(self, accept: Dict[str, bool]) -> None:
        self.accept = accept
        self.calls: List[tuple] = []

    def __call__(self, theorem_name: str, theorem_statement: str, tactic: str) -> Dict[str, Any]:
        self.calls.append((theorem_name, tactic))
        ok = self.accept.get(tactic, False)
        return {"success": ok, "error": None if ok else f"reject:{tactic}", "elapsed_ms": 0.1}


def _full_corpus() -> List[Example]:
    return [
        _ex(name="ax_p", state="⊢ p", tactic="exact h", split="train"),
        _ex(name="ax_p", state="⊢ p", tactic="assumption", split="train"),  # alternate verified
        _ex(name="ax_q", state="⊢ q", tactic="exact h", split="train"),
        _ex(name="ax_r", state="⊢ r", tactic="exact h", split="val"),
    ]


def test_evaluate_exact_match_and_oracle_alternates() -> None:
    full = _full_corpus()
    train = [e for e in full if e.split == "train"]
    eval_ = [e for e in full if e.split == "val"]
    baseline = MajorityBaseline().fit(train)  # majority: 'exact h' (3) > 'assumption' (1)

    r = evaluate(
        baseline, train=train, eval_examples=eval_, full_dataset=full,
        k_values=(1, 3, 5), top_k=5,
    )
    assert r.metrics["n_examples"] == 1
    # The single eval row's gold is 'exact h'; majority's top1 is 'exact h'.
    assert r.metrics["exact_match"]["top1_exact"] == 1.0
    # Oracle for (ax_r, ⊢ r) only knows {exact h}; predictions include it.
    assert r.metrics["exact_match"]["topk_any_verified"]["1"]["rate"] == 1.0


def test_evaluate_with_fake_verifier_dedups_and_reports_pass_at_k() -> None:
    full = _full_corpus()
    train = [e for e in full if e.split == "train"]
    eval_ = [e for e in full if e.split == "val"]
    baseline = MajorityBaseline().fit(train)

    fake = _FakeVerifier({"exact h": True})  # accept only one
    cache = VerificationCache(enabled=False)
    r = evaluate(
        baseline, train=train, eval_examples=eval_, full_dataset=full,
        k_values=(1, 3, 5), top_k=5, verifier=fake, cache=cache,
    )
    assert r.metrics["lean_verification"]["pass_at_k"]["1"]["rate"] == 1.0
    # Majority predicts ['exact h', 'assumption']; both distinct, so 2 verifier calls.
    assert len(fake.calls) == 2


def test_evaluate_verifier_only_called_for_unique_candidates(tmp_path: Path) -> None:
    """If a baseline emits duplicates in its top-k (it shouldn't, but defense
    in depth) the verifier still sees each distinct tactic at most once."""

    class _RepeatBaseline:
        name = "repeat"

        def predict(self, ex: Example, *, k: int) -> List[str]:
            return ["a", "a", "b", "a"][:k]

    eval_ = [_ex(name="t", state="⊢ p", tactic="a", split="val")]
    train = [_ex(name="train_only", state="⊢ p", tactic="a", split="train")]
    fake = _FakeVerifier({"a": True, "b": False})
    cache = VerificationCache(enabled=False)
    r = evaluate(
        _RepeatBaseline(), train=train, eval_examples=eval_, full_dataset=train + eval_,
        k_values=(1, 3, 5), top_k=4, verifier=fake, cache=cache,
    )
    assert sorted({t for _, t in fake.calls}) == ["a", "b"]
    assert len(fake.calls) == 2
    # pass@1 should still be True because 'a' (the first prediction) succeeds.
    assert r.metrics["lean_verification"]["pass_at_k"]["1"]["rate"] == 1.0


def test_evaluate_uses_cache_to_avoid_redundant_calls(tmp_path: Path) -> None:
    full = _full_corpus()
    train = [e for e in full if e.split == "train"]
    eval_ = [e for e in full if e.split == "val"]
    baseline = MajorityBaseline().fit(train)

    cache = VerificationCache.load(tmp_path / "vc.json", enabled=True)
    fake1 = _FakeVerifier({"exact h": True})
    evaluate(baseline, train=train, eval_examples=eval_, full_dataset=full,
             verifier=fake1, cache=cache)
    n1 = len(fake1.calls)
    assert n1 == 2  # exact h + assumption

    cache.save()
    cache2 = VerificationCache.load(tmp_path / "vc.json", enabled=True)
    fake2 = _FakeVerifier({"exact h": True})
    evaluate(baseline, train=train, eval_examples=eval_, full_dataset=full,
             verifier=fake2, cache=cache2)
    # Cache hit on both -> verifier called zero times this run.
    assert len(fake2.calls) == 0


def test_evaluate_no_verifier_omits_lean_section() -> None:
    full = _full_corpus()
    train = [e for e in full if e.split == "train"]
    eval_ = [e for e in full if e.split == "val"]
    baseline = MajorityBaseline().fit(train)
    r = evaluate(baseline, train=train, eval_examples=eval_, full_dataset=full)
    assert "lean_verification" not in r.metrics
    # per-row Lean fields are also absent.
    assert "lean_results" not in r.predictions[0]


def test_evaluate_empty_eval_returns_zero_metrics() -> None:
    train = [_ex(name="t1", tactic="rfl", split="train")]
    full = train  # empty eval
    baseline = MajorityBaseline().fit(train)
    r = evaluate(baseline, train=train, eval_examples=[], full_dataset=full)
    assert r.metrics["n_examples"] == 0
    assert r.metrics["small_sample_warning"] is True
    # All rates explicit-zero, never NaN/None.
    assert r.metrics["exact_match"]["top1_exact"] == 0.0


def test_evaluate_records_provenance_when_baseline_supports_it() -> None:
    """RetrievalBaseline.predict_with_neighbors is called when present."""
    from mini_elf_lean.baselines import RetrievalBaseline

    train = [_ex(name="a", state="⊢ p", tactic="exact h", split="train"),
             _ex(name="b", state="⊢ q", tactic="assumption", split="train")]
    eval_ = [_ex(name="c", state="⊢ r", tactic="exact h", split="val")]
    baseline = RetrievalBaseline(neighbors=4).fit(train)
    r = evaluate(baseline, train=train, eval_examples=eval_,
                 full_dataset=train + eval_)
    prov = r.predictions[0]["prediction_provenance"]
    assert prov and "source_theorem" in prov[0]
