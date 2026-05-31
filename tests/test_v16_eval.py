"""Pin the v16 eval headline numbers.

The v16 brief's primary target is `neg_imp_exfalso` pass@5 = 1.000
with `neg_imp_exfalso_ab`'s first verified rank ≤ 5. Plus
no-regression on every family v15 already solved.

Pins:
  * v12 / v13 / v14 / v15 metrics on disk are NOT overwritten.
  * v16 raw + +LA token-eval metrics match the documented headline.
  * v16 + v15 policy metrics match the documented headline.
  * `neg_imp_exfalso_ab` policy first-verified rank is ≤ 5.
  * Mean pass@5 under v16 + policy ≥ 0.97 (the headline).
  * pass@10 under v16 + policy ≥ 0.97 (proves real generator lift).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "data" / "baselines" / "v12_eval"
V13 = ROOT / "data" / "baselines" / "v13_timeout_rerun"
V14 = ROOT / "data" / "baselines" / "v14_timeout_rerun"
V15 = ROOT / "data" / "baselines" / "v15_learned_reranker"
V16_TOK = ROOT / "data" / "baselines" / "v16_token_seq2seq"
V16_POL = ROOT / "data" / "baselines" / "v16_policy_eval"

FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
            "exists_reconstruct", "neg_imp_exfalso")


def _load(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------- v12 / v13 / v14 / v15 on-disk untouched -----------------


def test_v16_does_not_overwrite_v12() -> None:
    md = _load(V12 / "forall_inst" / "literal_adapt_rerank" / "metrics.json")
    if md is None:
        pytest.skip("v12 absent")
    assert md["pass@5"] == pytest.approx(3.0 / 7, abs=1e-3)


def test_v16_does_not_overwrite_v13() -> None:
    md = _load(V13 / "metrics_rerun.json")
    if md is None:
        pytest.skip("v13 absent")
    v = md["forall_inst"]["literal_adapt_rerank"]["pass@5_warm_rerun"]
    assert v == pytest.approx(6.0 / 7, abs=1e-3)


def test_v16_does_not_overwrite_v14() -> None:
    md = _load(V14 / "metrics_rerun.json")
    if md is None:
        pytest.skip("v14 absent")
    v = md["forall_inst"]["literal_adapt_rerank"]["pass@5_warm_rerun"]
    assert v == pytest.approx(7.0 / 7, abs=1e-3)


def test_v16_does_not_overwrite_v15() -> None:
    md = _load(V15 / "neg_imp_exfalso" / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v15 policy metrics absent")
    # v15 policy pinned 0.800 on neg_imp_exfalso pass@5
    assert md["pass@5"] == pytest.approx(0.800, abs=1e-3)


# ----------------- v16 token raw + +LA pins -------------------------------


# (family, config, key, expected)
V16_TOK_PINNED = [
    # forall_inst: pass@5 preserved at 1.000 with +LA
    ("forall_inst", "literal_adapt_rerank", "pass@5", 1.000),
    # rewrite_succ: pass@5 preserved at 1.000
    ("rewrite_succ", "literal_adapt_rerank", "pass@5", 1.000),
    # neg_exfalso: lifted to 0.875
    ("neg_exfalso", "raw", "pass@5", 0.875),
    ("neg_exfalso", "literal_adapt_rerank", "pass@5", 0.875),
    # exists_reconstruct: preserved
    ("exists_reconstruct", "raw", "pass@5", 1.000),
    ("exists_reconstruct", "literal_adapt_rerank", "pass@5", 1.000),
    # neg_imp_exfalso: brief's primary target
    ("neg_imp_exfalso", "raw", "pass@5", 1.000),
    ("neg_imp_exfalso", "raw", "pass@1", 1.000),
    ("neg_imp_exfalso", "literal_adapt_rerank", "pass@5", 1.000),
    ("neg_imp_exfalso", "literal_adapt_rerank", "pass@1", 1.000),
    ("neg_imp_exfalso", "literal_adapt_rerank", "pass@10", 1.000),
]


@pytest.mark.parametrize("fam,cfg,key,expected", V16_TOK_PINNED,
                         ids=lambda x: str(x))
def test_v16_token_pinned(fam: str, cfg: str, key: str,
                          expected: float) -> None:
    md = _load(V16_TOK / fam / cfg / "metrics.json")
    if md is None:
        pytest.skip(f"v16 token {fam}/{cfg} absent")
    assert md[key] == pytest.approx(expected, abs=1e-3), (
        f"v16 token {fam}/{cfg} {key}: expected {expected} got {md[key]}")


def test_v16_token_zero_fused_tokens() -> None:
    """The v14 token-level invariant (no fused-keyword candidates)
    must persist through v16 retraining."""
    for fam in FAMILIES:
        md = _load(V16_TOK / fam / "raw" / "metrics.json")
        if md is None:
            pytest.skip(f"v16 token raw {fam} absent")
        assert md["n_with_fused_token"] == 0, (
            f"v16 {fam} produced {md['n_with_fused_token']} "
            f"fused-keyword candidates")


# ----------------- v16 + v15 policy pins ----------------------------------


V16_POL_PINNED = [
    ("forall_inst", "policy", "pass@1", 1.000),
    ("forall_inst", "policy", "pass@5", 1.000),
    ("rewrite_succ", "policy", "pass@1", 1.000),
    ("rewrite_succ", "policy", "pass@5", 1.000),
    ("exists_reconstruct", "policy", "pass@1", 1.000),
    ("exists_reconstruct", "policy", "pass@5", 1.000),
    ("neg_imp_exfalso", "policy", "pass@1", 1.000),
    ("neg_imp_exfalso", "policy", "pass@5", 1.000),
    ("neg_imp_exfalso", "policy", "pass@10", 1.000),
    # neg_exfalso: policy inherits rule's 0.375 pass@1 (sub-optimal,
    # see v15-mis-routing finding) but 0.875 pass@5.
    ("neg_exfalso", "policy", "pass@5", 0.875),
    # neg_exfalso learned beats rule on pass@1 under v16:
    ("neg_exfalso", "learned", "pass@1", 0.625),
]


@pytest.mark.parametrize("fam,cfg,key,expected", V16_POL_PINNED,
                         ids=lambda x: str(x))
def test_v16_policy_pinned(fam: str, cfg: str, key: str,
                           expected: float) -> None:
    md = _load(V16_POL / fam / cfg / "metrics.json")
    if md is None:
        pytest.skip(f"v16 policy {fam}/{cfg} absent")
    assert md[key] == pytest.approx(expected, abs=1e-3), (
        f"v16 policy {fam}/{cfg} {key}: expected {expected} got {md[key]}")


# ----------------- aggregate headline -------------------------------------


def test_v16_policy_mean_pass_at_5_beats_v15() -> None:
    means = []
    for fam in FAMILIES:
        md = _load(V16_POL / fam / "policy" / "metrics.json")
        if md is None:
            pytest.skip(f"v16 policy {fam} absent")
        means.append(md["pass@5"])
    mean = sum(means) / len(means)
    assert mean == pytest.approx(0.975, abs=1e-3), (
        f"v16 + policy mean pass@5 = {mean} ; expected 0.975")


def test_v16_policy_mean_pass_at_10_lifts_above_v15_ceiling() -> None:
    """v15's pass@10 ceiling was 0.925. v16 must lift it — that's the
    strongest proof of a real generator change."""
    means = []
    for fam in FAMILIES:
        md = _load(V16_POL / fam / "policy" / "metrics.json")
        if md is None:
            pytest.skip(f"v16 policy {fam} absent")
        means.append(md["pass@10"])
    mean = sum(means) / len(means)
    assert mean == pytest.approx(0.975, abs=1e-3)


# ----------------- the neg_imp_exfalso_ab rank movement -------------------


def test_neg_imp_exfalso_ab_rank_lifted_to_top5() -> None:
    """The brief's headline: rank 6 → ≤ 4."""
    p = V16_TOK / "neg_imp_exfalso" / "raw" / "predictions.jsonl"
    if not p.exists():
        pytest.skip("v16 raw predictions absent")
    found = False
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("theorem_name") != "neg_imp_exfalso_ab":
            continue
        found = True
        ranks_of_verified = [i for i, v in enumerate(r.get("verifications", []))
                             if v.get("success")]
        assert ranks_of_verified, (
            "no verified candidate in v16 raw beam for neg_imp_exfalso_ab")
        assert min(ranks_of_verified) < 5, (
            f"v16 brief target missed: neg_imp_exfalso_ab first verified "
            f"rank = {min(ranks_of_verified)} (must be < 5)"
        )
    assert found, "neg_imp_exfalso_ab not in v16 predictions"


def test_neg_imp_exfalso_ab_has_at_least_two_verified_in_top10() -> None:
    """v16 adds proof variants — we expect multiple verifying
    candidates in the top-10 beam."""
    p = V16_TOK / "neg_imp_exfalso" / "raw" / "predictions.jsonl"
    if not p.exists():
        pytest.skip("v16 raw predictions absent")
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("theorem_name") == "neg_imp_exfalso_ab":
            n = sum(1 for v in r.get("verifications", [])
                    if v.get("success"))
            assert n >= 2, (
                f"v16 neg_imp_exfalso_ab has only {n} verified candidate(s); "
                f"expected ≥ 2 (the v16 corpus teaches 3 proof variants)")
            return
    pytest.skip("neg_imp_exfalso_ab not in v16 predictions")


# ----------------- no regression on solved families ------------------------


@pytest.mark.parametrize("fam,target", [
    ("forall_inst", 1.000),
    ("rewrite_succ", 1.000),
    ("exists_reconstruct", 1.000),
])
def test_v16_policy_preserves_solved_families(fam: str, target: float) -> None:
    md = _load(V16_POL / fam / "policy" / "metrics.json")
    if md is None:
        pytest.skip(f"v16 policy {fam} absent")
    assert md["pass@5"] >= target - 1e-3, (
        f"v16 + policy regressed {fam} pass@5: {md['pass@5']} < {target}")
