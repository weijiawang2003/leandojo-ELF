"""Unit tests for the v10 scaling-analysis script.

Exercises ``analyze_v10_scaling._build_scaling_table``,
``_aggregate``/``_aggregate_sum``, and the end-to-end ``main`` against a tiny
fake set of metrics.json files. No model, no Lean.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_v10_scaling as ana  # noqa: E402


def _make_metrics(d: Path, **overrides) -> None:
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "n_test_theorems": 4,
        "pass@1": 0.0,
        "pass@5": 0.25,
        "pass@10": 0.25,
        "total_verified_candidates": 1,
        "novel_verified": 1,
        "cross_family_verified": 1,
        "cross_operation_verified": 0,
    }
    payload.update(overrides)
    (d / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")


def _make_processed_corpus(p_root: Path) -> None:
    """Write a tiny redundancy_lean_cli/next_tactic.jsonl mirroring corpus
    layout: 2 ops × 2 surface families × 1 row."""
    d = p_root / "redundancy_lean_cli"
    d.mkdir(parents=True, exist_ok=True)
    rows = [
        {"theorem_name": "v10_opA_fam1", "tactic": "exact h",
         "metadata": {"operation": "opA", "surface_family": "fam1"},
         "split": "train"},
        {"theorem_name": "v10_opA_fam2", "tactic": "exact g",
         "metadata": {"operation": "opA", "surface_family": "fam2"},
         "split": "train"},
        {"theorem_name": "v10_opB_fam1", "tactic": "rfl",
         "metadata": {"operation": "opB", "surface_family": "fam1"},
         "split": "train"},
        {"theorem_name": "v10_opB_fam2", "tactic": "trivial",
         "metadata": {"operation": "opB", "surface_family": "fam2"},
         "split": "train"},
    ]
    with (d / "next_tactic.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


# ---------------- low-level helpers ----------------


def test_per_op_train_features_counts_families_and_rows(tmp_path):
    _make_processed_corpus(tmp_path)
    feats = ana._per_op_train_features(tmp_path)
    assert feats["opA"]["n_train_families"] == 2
    assert feats["opA"]["n_train_rows"] == 2
    assert feats["opB"]["n_train_families"] == 2
    assert feats["opB"]["n_train_rows"] == 2


def test_aggregate_skips_missing_folds(tmp_path):
    per_fold = {
        "f1": {"baseline_v8": {"pass@5": 0.4},
               "redundancy_only": None,
               "combined_v10": {"pass@5": 0.8}},
        "f2": {"baseline_v8": {"pass@5": 0.0},
               "redundancy_only": {"pass@5": 1.0},
               "combined_v10": None},
    }
    means = ana._aggregate(per_fold, "pass@5")
    assert means["baseline_v8"] == 0.2
    assert means["redundancy_only"] == 1.0
    assert means["combined_v10"] == 0.8


def test_aggregate_returns_none_when_no_fold_has_metric():
    per_fold = {"f1": {m: None for m in ana.MODELS}}
    means = ana._aggregate(per_fold, "pass@5")
    for m in ana.MODELS:
        assert means[m] is None


def test_aggregate_sum_sums_verified_counts():
    per_fold = {
        "f1": {"baseline_v8": {"total_verified_candidates": 3},
               "redundancy_only": {"total_verified_candidates": 5},
               "combined_v10": None},
        "f2": {"baseline_v8": {"total_verified_candidates": 1},
               "redundancy_only": None,
               "combined_v10": {"total_verified_candidates": 2}},
    }
    sums = ana._aggregate_sum(per_fold, "total_verified_candidates")
    assert sums["baseline_v8"] == 4
    assert sums["redundancy_only"] == 5
    assert sums["combined_v10"] == 2


# ---------------- end-to-end ----------------


def test_main_handles_missing_eval_dir_with_dashes(tmp_path, monkeypatch):
    """If the eval root is empty, the doc must still write — cells become `—`."""
    p_root = tmp_path / "processed"
    e_root = tmp_path / "eval"
    out_md = tmp_path / "V10_SCALING_ANALYSIS.md"
    out_json = tmp_path / "scaling_summary.json"
    _make_processed_corpus(p_root)
    e_root.mkdir()  # empty
    argv = ["analyze_v10_scaling.py",
            "--processed-root", str(p_root),
            "--eval-root", str(e_root),
            "--out-md", str(out_md),
            "--out-summary", str(out_json)]
    monkeypatch.setattr(sys, "argv", argv)
    rc = ana.main()
    assert rc == 0
    text = out_md.read_text(encoding="utf-8")
    # missing metrics render as `—`, never as `0.000`
    assert "—" in text
    # the table should still list the corpus operations
    assert "`opA`" in text and "`opB`" in text
    # no fake zeros
    assert " | 0.000 |" not in text


def test_main_writes_op_holdout_pass5_when_metrics_present(tmp_path, monkeypatch):
    p_root = tmp_path / "processed"
    e_root = tmp_path / "eval"
    _make_processed_corpus(p_root)
    # add a baseline_v8 metrics for op holdout fold "opA"
    _make_metrics(e_root / "redundancy_operation_holdout" / "opA" / "baseline_v8",
                  **{"pass@5": 0.5, "pass@10": 0.75})
    out_md = tmp_path / "V10.md"
    argv = ["analyze_v10_scaling.py",
            "--processed-root", str(p_root),
            "--eval-root", str(e_root),
            "--out-md", str(out_md),
            "--out-summary", str(tmp_path / "s.json")]
    monkeypatch.setattr(sys, "argv", argv)
    rc = ana.main()
    assert rc == 0
    text = out_md.read_text(encoding="utf-8")
    # pass@5 for baseline_v8 on opA must render as 0.500
    assert "0.500" in text


def test_main_emits_summary_json(tmp_path, monkeypatch):
    p_root = tmp_path / "processed"
    e_root = tmp_path / "eval"
    out_md = tmp_path / "V10.md"
    out_json = tmp_path / "s.json"
    _make_processed_corpus(p_root)
    e_root.mkdir()
    argv = ["analyze_v10_scaling.py",
            "--processed-root", str(p_root),
            "--eval-root", str(e_root),
            "--out-md", str(out_md),
            "--out-summary", str(out_json)]
    monkeypatch.setattr(sys, "argv", argv)
    assert ana.main() == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    for key in ("per_operation_train_features", "operation_holdout",
                "cell_holdout", "donorless_eval", "v8_negative_controls"):
        assert key in data
