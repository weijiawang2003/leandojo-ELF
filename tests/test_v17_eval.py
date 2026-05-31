"""Pin v17 evaluation headline numbers.

Composes the v17 result as:
  * v16 token model for forall_inst / rewrite_succ /
    exists_reconstruct / neg_imp_exfalso (read from v16_policy_eval),
  * v17 token model for neg_exfalso (read from v17_policy_eval),
  * v17 policy throughout.

Pins:
  * v12-v16 pinned pass@5 metrics on disk are unchanged.
  * v17 policy on v17 candidates lifts neg_exfalso pass@5 to 1.000.
  * neg_exfalso_arrow_pq is solved in the v17 raw beam.
  * The v17 composed configuration achieves mean pass@5 = 1.000
    on the templated v11 family-LOFO benchmark.
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
V16_POL = ROOT / "data" / "baselines" / "v16_policy_eval"
V17_TOK = ROOT / "data" / "baselines" / "v17_token_seq2seq"
V17_POL = ROOT / "data" / "baselines" / "v17_policy_eval"


def _load(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------- v12-v16 on-disk pass@5 untouched ----------------------


def test_v17_does_not_overwrite_v12() -> None:
    md = _load(V12 / "forall_inst" / "literal_adapt_rerank" / "metrics.json")
    if md is None:
        pytest.skip("v12 absent")
    assert md["pass@5"] == pytest.approx(3.0 / 7, abs=1e-3)


def test_v17_does_not_overwrite_v13() -> None:
    md = _load(V13 / "metrics_rerun.json")
    if md is None:
        pytest.skip("v13 absent")
    assert md["forall_inst"]["literal_adapt_rerank"]["pass@5_warm_rerun"] \
        == pytest.approx(6.0 / 7, abs=1e-3)


def test_v17_does_not_overwrite_v14() -> None:
    md = _load(V14 / "metrics_rerun.json")
    if md is None:
        pytest.skip("v14 absent")
    assert md["forall_inst"]["literal_adapt_rerank"]["pass@5_warm_rerun"] \
        == pytest.approx(7.0 / 7, abs=1e-3)


def test_v17_does_not_overwrite_v15_pass_at_5() -> None:
    """v15's pass@5 pinned values must remain — the v17 policy edit
    changes pass@1 routing only; pass@5 was tied across configs on
    v14 candidates."""
    md = _load(V15 / "neg_exfalso" / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v15 metrics absent")
    assert md["pass@5"] == pytest.approx(5.0 / 8, abs=1e-3)


def test_v17_does_not_overwrite_v16_pass_at_5() -> None:
    md = _load(V16_POL / "neg_exfalso" / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v16 policy absent")
    assert md["pass@5"] == pytest.approx(7.0 / 8, abs=1e-3)


# ----------------- v17 token + v17 policy on neg_exfalso ------------------


def test_v17_neg_exfalso_raw_pass5_is_one() -> None:
    md = _load(V17_TOK / "neg_exfalso" / "raw" / "metrics.json")
    if md is None:
        pytest.skip("v17 token neg_exfalso absent")
    assert md["pass@5"] == pytest.approx(1.000, abs=1e-3)


def test_v17_policy_neg_exfalso_pass1_lifted() -> None:
    md = _load(V17_POL / "neg_exfalso" / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v17 policy neg_exfalso absent")
    assert md["pass@1"] == pytest.approx(0.750, abs=1e-3)
    assert md["pass@5"] == pytest.approx(1.000, abs=1e-3)
    assert md["pass@10"] == pytest.approx(1.000, abs=1e-3)


def test_v17_policy_neg_exfalso_learned_pass1_equals_policy() -> None:
    """v17 policy routes contradiction to learned, so neg_exfalso
    pass@1 under policy must equal pass@1 under learned."""
    pol = _load(V17_POL / "neg_exfalso" / "policy" / "metrics.json")
    lrn = _load(V17_POL / "neg_exfalso" / "learned" / "metrics.json")
    if pol is None or lrn is None:
        pytest.skip("v17 policy or learned absent")
    assert pol["pass@1"] == pytest.approx(lrn["pass@1"], abs=1e-6)


# ----------------- neg_exfalso_arrow_pq rank movement --------------------


def test_neg_exfalso_arrow_pq_solved_in_top5() -> None:
    """The v17 brief's primary target: the residual v16 row's
    verifying candidate must land at rank < 5 in the v17 raw beam."""
    p = V17_TOK / "neg_exfalso" / "raw" / "predictions.jsonl"
    if not p.exists():
        pytest.skip("v17 raw predictions absent")
    found = False
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("theorem_name") != "neg_exfalso_arrow_pq":
            continue
        found = True
        ranks_v = [i for i, v in enumerate(r.get("verifications", []))
                   if v.get("success")]
        assert ranks_v, (
            "v17 raw beam has NO verified candidate for "
            "neg_exfalso_arrow_pq — corpus didn't transfer")
        assert min(ranks_v) < 5, (
            f"v17 first verified rank for neg_exfalso_arrow_pq = "
            f"{min(ranks_v)}; must be < 5")
        return
    assert found, "neg_exfalso_arrow_pq not in v17 predictions"


def test_neg_exfalso_arrow_pq_at_least_one_verified() -> None:
    p = V17_TOK / "neg_exfalso" / "raw" / "predictions.jsonl"
    if not p.exists():
        pytest.skip("v17 raw predictions absent")
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("theorem_name") == "neg_exfalso_arrow_pq":
            n = sum(1 for v in r.get("verifications", [])
                    if v.get("success"))
            assert n >= 1, (
                f"v17 neg_exfalso_arrow_pq has {n} verified candidates")
            return
    pytest.skip("neg_exfalso_arrow_pq not in v17 predictions")


# ----------------- composed-config mean pass@k ----------------------------


# Composed v17: v16 for 4 families + v17 for neg_exfalso, v17 policy.
def _composed_pass_at(k: int) -> float:
    """Average pass@k across the 5 families using the documented
    composed-config sources."""
    sources = {
        "forall_inst": V16_POL,
        "rewrite_succ": V16_POL,
        "neg_exfalso": V17_POL,
        "exists_reconstruct": V16_POL,
        "neg_imp_exfalso": V16_POL,
    }
    vals = []
    for fam, root in sources.items():
        md = _load(root / fam / "policy" / "metrics.json")
        if md is None:
            return float("nan")
        vals.append(md[f"pass@{k}"])
    return sum(vals) / len(vals)


def test_composed_v17_mean_pass_at_5_is_one() -> None:
    mean = _composed_pass_at(5)
    if mean != mean:  # NaN guard
        pytest.skip("v17 composed metrics absent")
    assert mean == pytest.approx(1.000, abs=1e-3), (
        f"v17 composed mean pass@5 = {mean}; expected 1.000")


def test_composed_v17_mean_pass_at_10_is_one() -> None:
    mean = _composed_pass_at(10)
    if mean != mean:
        pytest.skip("v17 composed metrics absent")
    assert mean == pytest.approx(1.000, abs=1e-3)


def test_composed_v17_mean_pass_at_1_at_least_0_95() -> None:
    mean = _composed_pass_at(1)
    if mean != mean:
        pytest.skip("v17 composed metrics absent")
    # Documented as 0.950; allow ±0.005.
    assert mean >= 0.945, f"composed pass@1 = {mean} < 0.945"
    assert mean == pytest.approx(0.950, abs=1e-3)


# ----------------- v17 token invariant (no fused tokens) ------------------


def test_v17_token_no_fused_keywords() -> None:
    md = _load(V17_TOK / "neg_exfalso" / "raw" / "metrics.json")
    if md is None:
        pytest.skip("v17 token absent")
    assert md["n_with_fused_token"] == 0, (
        "v17 retrain introduced fused-keyword candidates — the "
        "tokenizer invariant must persist through corpus additions")
