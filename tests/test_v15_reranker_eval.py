"""Invariants for the v15 evaluation artefacts.

Pins:
  * v15 does not overwrite v12 / v13 / v14 metrics on disk,
  * v15 metrics file structure is well-formed,
  * pass@10 is identical across configs in every fold (reranker
    reorders only — the candidate set is the same),
  * the policy config dominates the others on mean pass@5 (the
    headline result),
  * the neg_imp_exfalso headline number stays pinned at 0.800 pass@5
    for raw / learned / policy and 0.000 for rule.
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


def _load(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _metrics(fam: str, cfg: str) -> Optional[Dict[str, Any]]:
    return _load(V15 / fam / cfg / "metrics.json")


# ----------------- honesty invariants ------------------------------------


def test_v15_does_not_overwrite_v12() -> None:
    fp = V12 / "forall_inst" / "literal_adapt_rerank" / "metrics.json"
    if not fp.exists():
        pytest.skip("v12 metrics absent")
    md = json.loads(fp.read_text(encoding="utf-8"))
    assert md.get("pass@5") == pytest.approx(3.0 / 7, abs=1e-3)


def test_v15_does_not_overwrite_v13() -> None:
    fp = V13 / "metrics_rerun.json"
    if not fp.exists():
        pytest.skip("v13 metrics absent")
    md = json.loads(fp.read_text(encoding="utf-8"))
    v = md.get("forall_inst", {}).get("literal_adapt_rerank", {}).get(
        "pass@5_warm_rerun")
    assert v == pytest.approx(6.0 / 7, abs=1e-3)


def test_v15_does_not_overwrite_v14() -> None:
    fp = V14 / "metrics_rerun.json"
    if not fp.exists():
        pytest.skip("v14 metrics absent")
    md = json.loads(fp.read_text(encoding="utf-8"))
    v = md.get("forall_inst", {}).get("literal_adapt_rerank", {}).get(
        "pass@5_warm_rerun")
    assert v == pytest.approx(7.0 / 7, abs=1e-3)


# ----------------- metric structure --------------------------------------


V15_FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso")
V15_CONFIGS = ("raw", "rule", "learned", "policy")


@pytest.mark.parametrize("fam,cfg", [(f, c) for f in V15_FAMILIES
                                     for c in V15_CONFIGS])
def test_v15_metrics_structure(fam: str, cfg: str) -> None:
    md = _metrics(fam, cfg)
    if md is None:
        pytest.skip(f"v15 {fam}/{cfg} absent")
    for k in ("pass@1", "pass@3", "pass@5", "pass@10", "MRR",
              "n_test_theorems", "verified_ceiling_match_rows",
              "config", "uses_state_after"):
        assert k in md, f"{fam}/{cfg} missing {k}"
    assert md["uses_state_after"] is False
    assert md["config"] == cfg


# ----------------- pass@10 ceiling preservation --------------------------


@pytest.mark.parametrize("fam", V15_FAMILIES)
def test_pass_at_10_identical_across_configs(fam: str) -> None:
    """The reranker reorders only — every config sees the same set of
    candidates, so pass@10 is the same as the underlying v14 + LA
    pool's verified-set indicator."""
    values = []
    for cfg in V15_CONFIGS:
        md = _metrics(fam, cfg)
        if md is None:
            pytest.skip(f"v15 {fam}/{cfg} absent")
        values.append(md["pass@10"])
    assert len(set(round(v, 6) for v in values)) == 1, (
        f"{fam}: pass@10 differs across configs ({values}) — reranker "
        f"must be reorder-only")


@pytest.mark.parametrize("fam", V15_FAMILIES)
def test_verified_ceiling_match_is_per_row_complete(fam: str) -> None:
    """Stronger ceiling check: the SET of verified candidates in each
    reordered list must equal the SET of verified candidates in raw,
    for every test row."""
    for cfg in V15_CONFIGS:
        md = _metrics(fam, cfg)
        if md is None:
            pytest.skip(f"v15 {fam}/{cfg} absent")
        assert md["verified_ceiling_match_rows"] == md["n_test_theorems"]


# ----------------- headline policy numbers -------------------------------


# (fam, cfg, key, expected)
PINNED = [
    # neg_imp_exfalso: the headline win
    ("neg_imp_exfalso", "rule", "pass@5", 0.000),
    ("neg_imp_exfalso", "raw", "pass@5", 0.800),
    ("neg_imp_exfalso", "learned", "pass@5", 0.800),
    ("neg_imp_exfalso", "policy", "pass@5", 0.800),
    ("neg_imp_exfalso", "policy", "pass@10", 1.000),
    # forall_inst: rule and policy must hit 1.000 pass@1
    ("forall_inst", "rule", "pass@1", 1.000),
    ("forall_inst", "policy", "pass@1", 1.000),
    ("forall_inst", "policy", "pass@5", 1.000),
    # rewrite_succ: rule and policy must hit 1.000 pass@1
    ("rewrite_succ", "rule", "pass@1", 1.000),
    ("rewrite_succ", "policy", "pass@1", 1.000),
    # exists_reconstruct: learned and policy must hit 1.000 pass@1
    ("exists_reconstruct", "learned", "pass@1", 1.000),
    ("exists_reconstruct", "policy", "pass@1", 1.000),
    # neg_exfalso: pass@5 preserved at 0.625 across all configs
    ("neg_exfalso", "policy", "pass@5", 5.0 / 8),
]


@pytest.mark.parametrize("fam,cfg,key,expected", PINNED,
                         ids=lambda x: str(x))
def test_v15_pinned(fam: str, cfg: str, key: str, expected: float) -> None:
    md = _metrics(fam, cfg)
    if md is None:
        pytest.skip(f"v15 {fam}/{cfg} absent")
    assert md[key] == pytest.approx(expected, abs=1e-3), (
        f"{fam}/{cfg} {key}: expected {expected:.3f} got {md[key]!r}")


def test_policy_mean_pass_at_5_beats_rule_and_learned() -> None:
    means = {}
    for cfg in V15_CONFIGS:
        vs = []
        for fam in V15_FAMILIES:
            md = _metrics(fam, cfg)
            if md is None:
                pytest.skip(f"v15 {fam}/{cfg} absent")
            vs.append(md["pass@5"])
        means[cfg] = sum(vs) / len(vs)
    assert means["policy"] >= means["rule"] - 1e-6
    assert means["policy"] >= means["learned"] - 1e-6
    assert means["policy"] >= means["raw"] - 1e-6
    # Sanity bounds matching the documented headline 0.885.
    assert means["policy"] == pytest.approx(0.885, abs=1e-3), means


def test_pass_at_10_mean_is_pinned() -> None:
    vs = []
    for fam in V15_FAMILIES:
        md = _metrics(fam, "policy")
        if md is None:
            pytest.skip(f"v15 {fam}/policy absent")
        vs.append(md["pass@10"])
    mean = sum(vs) / len(vs)
    # v14 generator's ceiling — must not change under any policy.
    assert mean == pytest.approx(0.925, abs=1e-3)


# ----------------- summary file ------------------------------------------


def test_summary_file_exists_and_has_no_state_after() -> None:
    p = V15 / "summary.json"
    if not p.exists():
        pytest.skip("v15 summary absent")
    s = json.loads(p.read_text(encoding="utf-8"))
    assert s["uses_state_after"] is False
    assert isinstance(s["folds"], list) and len(s["folds"]) > 0
