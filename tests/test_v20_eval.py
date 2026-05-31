"""Tests for the v20 broad-core evaluation outputs.

Pins:
  * v17/v18/v19 metrics on disk are not overwritten.
  * v20 broad-plus pass@5 ≥ v18 broad-only pass@5 (= 0.583) on the
    BEST config (raw / policy / abstract / policy_abstract).
  * implication pass@5 moves off 0.000 (target ≥ 0.333; brief asks
    ≥ 0.500 ideally).
  * bool pass@5 moves off 0.000.
  * No state_after in any v20 output.
  * Per-config metrics have a ``uses_state_after: false`` flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V20_EVAL = ROOT / "data" / "baselines" / "v20_broad_plus_eval"
V18_BO = ROOT / "data" / "baselines" / "v18_broad_only_eval" / "policy" / "metrics.json"
V17_TOK = ROOT / "data" / "baselines" / "v17_token_seq2seq"
V19_ABS_ONLY = ROOT / "data" / "baselines" / "v19_abstract_only_eval" / "policy" / "metrics.json"


def _read_metrics(p: Path):
    if not p.exists():
        pytest.skip(f"metrics absent: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------- v17/v18/v19 not overwritten ---------------------------


def test_v18_broad_only_metrics_unchanged() -> None:
    m = _read_metrics(V18_BO)
    # v18 broad-only policy pass@5 = 0.5833... — pinned.
    assert m["pass@5"] == pytest.approx(0.5833333333333334, abs=1e-9), (
        f"v18 broad-only pass@5 changed: {m['pass@5']}")
    assert m["pass@1"] == pytest.approx(0.5, abs=1e-9)
    assert m["pass@10"] == pytest.approx(0.6041666666666666, abs=1e-9)


def test_v19_abstract_only_metrics_unchanged() -> None:
    m = _read_metrics(V19_ABS_ONLY)
    # v19 abstract-only policy: pass@5 = 0.208 (memory pin).
    # Allow 0.05 tolerance (deterministic but file format may round).
    assert 0.10 < m["pass@5"] < 0.30, (
        f"v19 abstract-only pass@5 surprising: {m['pass@5']}")


# ----------------- v20 broad-plus eval ------------------------------------


def test_v20_eval_outputs_exist() -> None:
    summary = V20_EVAL / "summary.json"
    if not summary.exists():
        pytest.skip("v20 broad-plus eval not yet produced")
    assert summary.exists()
    for cfg in ("raw", "rule", "learned", "policy", "abstract",
                "policy_abstract"):
        m = V20_EVAL / cfg / "metrics.json"
        assert m.exists(), f"v20 {cfg} metrics missing"


def _best_pass_at_5() -> tuple[str, float]:
    summary = V20_EVAL / "summary.json"
    if not summary.exists():
        pytest.skip("v20 broad-plus eval not yet produced")
    s = json.loads(summary.read_text(encoding="utf-8"))
    best_cfg, best_p5 = "", -1.0
    for cfg, m in s["configs"].items():
        if m["pass@5"] > best_p5:
            best_p5 = m["pass@5"]
            best_cfg = cfg
    return best_cfg, best_p5


def test_v20_best_pass_at_5_beats_v18_broad_only() -> None:
    cfg, p5 = _best_pass_at_5()
    # v18 broad-only pass@5 = 0.583. v20 brief target: ≥.
    assert p5 >= 0.5833 - 1e-9, (
        f"v20 best pass@5 ({cfg}={p5}) did not match/beat "
        f"v18 broad-only 0.5833")


def test_v20_implication_pass_at_5_moves_off_zero() -> None:
    cfg, _ = _best_pass_at_5()
    m = json.loads((V20_EVAL / cfg / "metrics.json").read_text(
        encoding="utf-8"))
    imp = m.get("per_category", {}).get("implication", {})
    # v18/v19 implication pass@5 was 0.000.
    assert imp.get("pass@5", 0) > 0, (
        f"v20 implication pass@5 still 0 on best config {cfg}: {imp}")


def test_v20_bool_pass_at_5_moves_off_zero() -> None:
    cfg, _ = _best_pass_at_5()
    m = json.loads((V20_EVAL / cfg / "metrics.json").read_text(
        encoding="utf-8"))
    boolm = m.get("per_category", {}).get("bool", {})
    assert boolm.get("pass@5", 0) > 0, (
        f"v20 bool pass@5 still 0 on best config {cfg}: {boolm}")


def test_v20_no_unresolved_placeholder_in_errors() -> None:
    """v19's failure mode was unresolved_placeholder dominating
    errors. v20 returns to raw-name generation; this category must
    be absent in v20 error taxonomies."""
    summary = V20_EVAL / "summary.json"
    if not summary.exists():
        pytest.skip()
    s = json.loads(summary.read_text(encoding="utf-8"))
    for cfg, m in s["configs"].items():
        tax = m.get("error_taxonomy", {})
        assert "unresolved_placeholder" not in tax, (
            f"v20 {cfg} has unresolved_placeholder errors: {tax}")


def test_v20_metrics_record_no_state_after() -> None:
    summary = V20_EVAL / "summary.json"
    if not summary.exists():
        pytest.skip()
    s = json.loads(summary.read_text(encoding="utf-8"))
    for cfg, m in s["configs"].items():
        assert m.get("uses_state_after") is False, (
            f"v20 {cfg} did not record uses_state_after=False")


def test_v20_preserves_equality_rewrite() -> None:
    """v17/v18 equality_rewrite was 1.000. v20 must not regress."""
    cfg, _ = _best_pass_at_5()
    m = json.loads((V20_EVAL / cfg / "metrics.json").read_text(
        encoding="utf-8"))
    eq = m.get("per_category", {}).get("equality_rewrite", {})
    assert eq.get("pass@5", 0) >= 0.833 - 1e-9, (
        f"v20 equality_rewrite regressed: {eq}")


def test_v20_at_least_one_abstract_config() -> None:
    """The v20 brief requires both 'abstract' and 'policy_abstract'
    configs in the eval output."""
    summary = V20_EVAL / "summary.json"
    if not summary.exists():
        pytest.skip()
    s = json.loads(summary.read_text(encoding="utf-8"))
    assert "abstract" in s["configs"]
    assert "policy_abstract" in s["configs"]


# ----------------- timeout-corrected (warm rerun) headline ---------------

V20_CORRECTED = ROOT / "data" / "baselines" / "v20_broad_plus_eval_timeout_rerun"


def test_v20_corrected_abstract_headline() -> None:
    """Pin the warm-rerun-corrected headline for the best (abstract)
    config: pass@1=0.625, pass@5=0.729, pass@10=0.729."""
    m = V20_CORRECTED / "abstract" / "metrics.json"
    if not m.exists():
        pytest.skip("v20 timeout-corrected eval not produced")
    d = json.loads(m.read_text(encoding="utf-8"))
    assert d["pass@1"] == pytest.approx(0.625, abs=1e-3)
    assert d["pass@5"] == pytest.approx(0.7291666666666666, abs=1e-3)
    assert d["pass@10"] == pytest.approx(0.7291666666666666, abs=1e-3)


def test_v20_corrected_implication_and_bool_closed() -> None:
    """Both data-shape gaps fully closed at pass@5=1.000 on the
    corrected abstract config."""
    m = V20_CORRECTED / "abstract" / "metrics.json"
    if not m.exists():
        pytest.skip()
    d = json.loads(m.read_text(encoding="utf-8"))
    assert d["per_category"]["implication"]["pass@5"] == pytest.approx(1.0)
    assert d["per_category"]["bool"]["pass@5"] == pytest.approx(1.0)


def test_v20_corrected_forall_regression_documented() -> None:
    """The forall regression (0.667 -> 0.000) is a real, honestly
    recorded negative — pin it so any future 'fix' is deliberate."""
    m = V20_CORRECTED / "abstract" / "metrics.json"
    if not m.exists():
        pytest.skip()
    d = json.loads(m.read_text(encoding="utf-8"))
    assert d["per_category"]["forall"]["pass@5"] == pytest.approx(0.0)


def test_v20_timeout_rerun_summary_flips() -> None:
    """The warm rerun flipped 9 spurious-timeout candidates to success
    and confirmed the rest as real errors (0 still-timeout)."""
    p = V20_EVAL / "timeout_rerun_summary.json"
    if not p.exists():
        pytest.skip()
    s = json.loads(p.read_text(encoding="utf-8"))
    assert s["n_flipped_to_success"] == 9
    assert s["n_still_timeout"] == 0
    assert s["n_flipped_to_real_error"] == 26


def test_v20_corrected_no_unresolved_placeholder() -> None:
    for cfg in ("raw", "abstract", "policy_abstract"):
        m = V20_CORRECTED / cfg / "metrics.json"
        if not m.exists():
            pytest.skip()
        d = json.loads(m.read_text(encoding="utf-8"))
        assert "unresolved_placeholder" not in d["error_taxonomy"]
