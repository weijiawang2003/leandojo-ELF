"""v14 eval-artefact invariants.

Unlike ``test_v12_eval`` / ``test_v13_timeout_rerun``, the v14 brief
explicitly does NOT promise a pass@k lift — token-level decoding may
fix malformed strings *without* moving any leaderboard number. So
this module pins **invariants** rather than concrete metric values:

  * v12 metrics on disk are untouched by v14.
  * v13 metrics on disk are untouched by v14.
  * The v14 metrics file structure has every field the comparison
    script reads.
  * The token model emits zero fused-keyword tokens.
  * ``uses_state_after`` is False in every config.
  * ``forall_inst_var_m_pass@5`` is reported (whatever the value).
  * ``literal_adapt_verified`` is non-decreasing v14_raw → v14
    literal_adapt_rerank for forall_inst (the +literal-adapt layer
    can only add, never remove, verified candidates).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "data" / "baselines" / "v12_eval"
V13 = ROOT / "data" / "baselines" / "v13_timeout_rerun"
V14 = ROOT / "data" / "baselines" / "v14_token_seq2seq"

V14_FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso")


def _load(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _load_v14(fam: str, config: str) -> Optional[Dict[str, Any]]:
    return _load(V14 / fam / config / "metrics.json")


# ----------------- invariants over v12/v13 (must NOT be touched) ----------


def test_v14_does_not_overwrite_v12_metrics() -> None:
    fp = V12 / "forall_inst" / "literal_adapt_rerank" / "metrics.json"
    if not fp.exists():
        pytest.skip("v12 metrics absent")
    md = json.loads(fp.read_text(encoding="utf-8"))
    # v12 forall_inst literal_adapt_rerank pass@5 lower bound = 3/7 = 0.429
    assert md.get("pass@5") == pytest.approx(3.0 / 7, abs=1e-3), (
        "v14 silently overwrote v12 forall_inst metrics — honesty violation"
    )


def test_v14_does_not_overwrite_v13_metrics() -> None:
    fp = V13 / "metrics_rerun.json"
    if not fp.exists():
        pytest.skip("v13 metrics absent")
    md = json.loads(fp.read_text(encoding="utf-8"))
    # v13 corrected forall_inst literal_adapt_rerank pass@5 = 6/7
    actual = md.get("forall_inst", {}).get("literal_adapt_rerank",
                                           {}).get("pass@5_warm_rerun")
    assert actual == pytest.approx(6.0 / 7, abs=1e-3), (
        "v14 silently overwrote v13 corrected forall_inst metrics"
    )


# ----------------- v14 metrics file structure -----------------------------


@pytest.mark.parametrize("fam", V14_FAMILIES)
def test_v14_raw_metrics_have_required_fields(fam: str) -> None:
    md = _load_v14(fam, "raw")
    if md is None:
        pytest.skip(f"v14 metrics absent for {fam}/raw")
    required = (
        "n_test_theorems", "pass@1", "pass@5", "pass@10",
        "verified_total", "novel_verified", "n_with_fused_token",
        "fused_token_rate", "n_malformed", "malformed_rate",
        "n_truncated_shape", "n_schema_exact_h_num", "n_schema_rw_h",
        "error_taxonomy", "literal_adapt_verified",
        "forall_inst_var_m_pass@5", "uses_state_after",
        "k_max", "beam_width", "config",
    )
    for k in required:
        assert k in md, f"{fam}/raw missing field {k!r}"
    assert md["uses_state_after"] is False
    assert md["config"] == "raw"


@pytest.mark.parametrize("fam", V14_FAMILIES)
def test_v14_raw_emits_zero_fused_tokens(fam: str) -> None:
    """Headline tokenizer invariant: a token-level model trained on
    clean v11 tactics cannot emit `rwexact` / `refintro` / similar
    fused-keyword artefacts. The eval script counts them; the
    expected number is exactly 0."""
    md = _load_v14(fam, "raw")
    if md is None:
        pytest.skip(f"v14 metrics absent for {fam}/raw")
    assert md["n_with_fused_token"] == 0, (
        f"{fam}/raw produced {md['n_with_fused_token']} fused-keyword "
        f"candidates — the token-level invariant is violated"
    )


# ----------------- literal_adapt_rerank invariant -------------------------


def test_forall_inst_literal_adapt_does_not_remove_verified_candidates() -> None:
    """`literal_adapt_rerank` is a *superset* candidate config; its
    verified-count can only equal or exceed the raw config. (pass@k
    however can drop if rerank changes the top-k cut, so we pin
    verified-total not pass@k.)"""
    raw = _load_v14("forall_inst", "raw")
    lar = _load_v14("forall_inst", "literal_adapt_rerank")
    if raw is None or lar is None:
        pytest.skip("v14 forall_inst metrics absent")
    assert lar["verified_total"] >= raw["verified_total"]


@pytest.mark.parametrize("fam", V14_FAMILIES)
def test_v14_literal_adapt_rerank_carries_state_after_false(fam: str) -> None:
    md = _load_v14(fam, "literal_adapt_rerank")
    if md is None:
        pytest.skip(f"v14 {fam}/literal_adapt_rerank absent")
    assert md["uses_state_after"] is False


# ----------------- forall_inst_var_m indicator ----------------------------


def test_forall_inst_var_m_indicator_is_present() -> None:
    md = _load_v14("forall_inst", "raw")
    if md is None:
        pytest.skip("v14 forall_inst raw absent")
    assert "forall_inst_var_m_pass@5" in md, (
        "forall_inst_var_m is the v14 brief's headline target; its "
        "pass@5 indicator must be in the metrics for downstream readers"
    )


# ----------------- v14 model summary ---------------------------------------


@pytest.mark.parametrize("fam", ("forall_inst", "rewrite_succ"))
def test_v14_model_summary_has_seed_and_no_state_after(fam: str) -> None:
    p = ROOT / "data" / "models" / "token_seq2seq_v14" / fam / "summary.json"
    if not p.exists():
        pytest.skip(f"v14 model summary absent for {fam}")
    s = json.loads(p.read_text(encoding="utf-8"))
    assert s.get("summary", {}).get("uses_state_after") is False
    # Token source label must be present
    assert s.get("summary", {}).get("source") == "token_seq2seq"
