"""Unit tests for the v7 evaluator's pure metric/annotation logic (no Lean)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_retrieval_v7 import annotate_rows, make_proposer, v7_metrics  # noqa: E402
from mini_elf_lean.retrieval_proposer import load_v6_weights  # noqa: E402

# annotate_rows resolves a donor's family by looking up its theorem name (the
# real donors are always train theorems in the seeds), so the donor names below
# are mapped too.
THM2FAM = {"t_same": "famA", "t_xfam": "famB", "t_fail": "famA",
           "donor_same": "famA",   # same family as t_same
           "donor_other": "famA",  # different family than t_xfam (famB) -> cross
           "donor_zzz": "famZ"}
THM2OP = {k: "opX" for k in THM2FAM}


def _row(name, preds, success_idx, donor_name, donor_fam_meta, donor_op, adapted=False):
    """Build a prediction row mimicking baseline_eval.evaluate output."""
    lean = {p: {"success": (i == success_idx)} for i, p in enumerate(preds)}
    prov = [{"source": ("retrieval_adapted" if (i == success_idx and adapted) else "retrieval"),
             "metadata": {"neighbor_theorem": donor_name, "donor_family": donor_fam_meta,
                          "donor_operation": donor_op,
                          "adapted": (adapted if i == success_idx else False)}}
            for i in range(len(preds))]
    pk = {"1": success_idx == 0, "3": 0 <= success_idx < 3, "5": 0 <= success_idx < 5}
    return {"theorem_name": name, "predictions": preds, "prediction_provenance": prov,
            "lean_results": lean, "lean_pass_at_k": pk}


def test_annotate_and_metrics_same_family_vs_cross_family():
    rows = [
        # solved at rank0 by a SAME-family donor (interpolation)
        _row("t_same", ["a", "b", "c"], 0, "donor_same", "famA", "opX"),
        # solved at rank2 by a CROSS-family donor (transfer)
        _row("t_xfam", ["x", "y", "z"], 2, "donor_other", "famB_other", "opX"),
        # never solved
        _row("t_fail", ["p", "q"], -1, "donor_zzz", "famZ", "opX"),
    ]
    # famB_other != famB -> cross-family; train has famA only (so famB,famA presence varies)
    annotate_rows(rows, THM2FAM, THM2OP, train_families={"famA"}, train_ops={"opX"}, held_label="x")
    m = v7_metrics(rows)
    assert m["n_rows"] == 3
    assert m["pass@1"] == round(1 / 3, 4)        # only t_same at rank0
    assert m["pass@5"] == round(2 / 3, 4)        # t_same + t_xfam
    # t_xfam's verifying donor family (famB_other) != its own family (famB) -> cross-family
    assert m["cross_family_verified"] == 1
    # t_same is famA which IS in train_families; t_xfam famB is NOT -> donorless subset = {t_xfam,? }
    # t_xfam (famB) and ... t_fail is famA (in train). So donorless rows = [t_xfam].
    assert m["donorless_same_family_rows"] == 1
    assert m["donorless_pass@5"] == 1.0          # t_xfam solved


def test_failure_taxonomy_buckets():
    rows = [_row("t_fail", ["p", "q"], -1, "d", "famZ", "opX")]
    # famA in train, opX in train -> the failing famA row is "same_family_present_but_failed"
    annotate_rows(rows, THM2FAM, THM2OP, train_families={"famA"}, train_ops={"opX"}, held_label="x")
    m = v7_metrics(rows)
    assert m["failure_taxonomy"].get("same_family_present_but_failed") == 1


def test_adapted_verified_counted():
    rows = [_row("t_same", ["a", "b"], 1, "d", "famA", "opX", adapted=True)]
    annotate_rows(rows, THM2FAM, THM2OP, train_families={"famA"}, train_ops={"opX"}, held_label="x")
    m = v7_metrics(rows)
    assert m["adapted_verified"] == 1


def test_per_family_and_operation_breakdown_present():
    rows = [_row("t_same", ["a"], 0, "d", "famA", "opX")]
    annotate_rows(rows, THM2FAM, THM2OP, train_families={"famA"}, train_ops={"opX"}, held_label="x")
    m = v7_metrics(rows)
    assert "famA" in m["per_family_pass_at_k"]
    assert "opX" in m["per_operation_pass_at_k"]


def test_make_proposer_types():
    w = load_v6_weights(None)
    assert make_proposer("v5_retrieval", w, {}).name == "retrieval"
    assert make_proposer("v6_retrieval", w, {}).name == "retrieval_v6"
    p = make_proposer("v6_no_same_family", w, {})
    assert p.forbid_same_family is True
    assert make_proposer("v7_abstract", w, {}).name == "retrieval_v7_abstract"
