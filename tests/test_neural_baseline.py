"""Tests for the pure-Python neural (softmax-ngram) tactic baseline + the
pattern-family / sibling-confusion analysis. No Lean, no numpy/torch, fast.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import mini_elf_lean.neural_baseline as nb_mod
from mini_elf_lean.baseline_eval import (
    per_family_pass_at_k,
    sibling_confusion,
)
from mini_elf_lean.baselines import Example
from mini_elf_lean.neural_baseline import (
    NeuralTacticBaseline,
    NgramVectorizer,
    SoftmaxClassifier,
    _goal_line,
)


def _ex(name, state, tactic, *, stmt=None, split="train") -> Example:
    return Example(
        theorem_name=name,
        theorem_statement=stmt or f"({name})",
        state_before=state,
        tactic=tactic,
        split=split,
    )


# ---- vectorizer ----


def test_vectorizer_is_deterministic_across_instances() -> None:
    v1 = NgramVectorizer(dim=4096)
    v2 = NgramVectorizer(dim=4096)
    f1 = v1.transform("(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p")
    f2 = v2.transform("(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p")
    assert f1 == f2 and f1, "stable hashing must give identical, non-empty features"


def test_goal_line_extraction() -> None:
    assert _goal_line("p q : Prop\nh : p ∧ q\n⊢ q") == "⊢ q"
    # no turnstile -> whole state
    assert _goal_line("just some text") == "just some text"


def test_goal_field_distinguishes_sibling_goals() -> None:
    """The goal-field features must differ for `⊢ p` vs `⊢ q` even when the rest
    of the input is identical — that is the signal siblings hinge on."""
    v = NgramVectorizer(dim=8192)
    left = v.transform("(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p")
    right = v.transform("(p q : Prop) (h : p ∧ q) : q", "p q : Prop\nh : p ∧ q\n⊢ q")
    assert left != right


def test_vectorizer_buckets_within_dim() -> None:
    v = NgramVectorizer(dim=256)
    feats = v.transform("(p : Prop) : p → p", "p : Prop\n⊢ p → p")
    assert all(0 <= b < 256 for b in feats)


# ---- classifier learns ----


def test_softmax_classifier_reduces_loss_and_fits_separable_data() -> None:
    v = NgramVectorizer(dim=2048)
    # Two clearly-separable classes.
    rows = (
        [("⊢ p", 0)] * 5
        + [("⊢ q ∧ r", 1)] * 5
    )
    X = [v.transform("stmt", s) for s, _ in rows]
    y = [c for _, c in rows]
    clf = SoftmaxClassifier(n_classes=2, epochs=25, seed=0).fit(X, y)
    losses = [e["avg_cross_entropy"] for e in clf.training_log]
    assert losses[-1] < losses[0], "training should reduce cross-entropy"
    # Predicts the right class on the training inputs.
    assert _argmax(clf.predict_scores(v.transform("stmt", "⊢ p"))) == 0
    assert _argmax(clf.predict_scores(v.transform("stmt", "⊢ q ∧ r"))) == 1


def _argmax(xs):
    return max(range(len(xs)), key=lambda i: xs[i])


def test_training_is_deterministic_with_seed() -> None:
    train = [
        _ex("a", "⊢ p", "exact h"), _ex("b", "⊢ q", "assumption"),
        _ex("c", "⊢ r", "rfl"), _ex("d", "⊢ s", "trivial"),
    ]
    b1 = NeuralTacticBaseline(dim=1024, epochs=10, seed=7).fit(train)
    b2 = NeuralTacticBaseline(dim=1024, epochs=10, seed=7).fit(train)
    e = _ex("z", "⊢ p", "exact h", split="val")
    assert b1.predict(e, k=4) == b2.predict(e, k=4)
    assert b1.training_log == b2.training_log


# ---- top-k / dedup ----


def test_predict_returns_distinct_topk() -> None:
    train = [_ex(f"t{i}", f"⊢ g{i}", t, split="train")
             for i, t in enumerate(["a", "b", "c", "d", "e", "f"])]
    b = NeuralTacticBaseline(dim=1024, epochs=5).fit(train)
    preds = b.predict(_ex("z", "⊢ g0", "a", split="val"), k=3)
    assert len(preds) == 3
    assert len(set(preds)) == 3  # distinct (classes are distinct tactics)


def test_predict_before_fit_returns_empty() -> None:
    assert NeuralTacticBaseline().predict(_ex("z", "⊢ p", "x", split="val"), k=5) == []


# ---- never reads state_after ----


def test_example_has_no_state_after_field() -> None:
    """Structural guarantee: the model consumes Example, which has no
    state_after, so it cannot train on it."""
    assert not hasattr(Example("t", "s", "sb", "tac", "train"), "state_after")
    assert "state_after" not in Example.__dataclass_fields__


def test_neural_module_source_never_accesses_state_after() -> None:
    """The docstring *mentions* state_after to document the guarantee; what must
    not appear is any actual access — attribute (`.state_after`) or key
    (`["state_after"]` / `['state_after']`)."""
    src = inspect.getsource(nb_mod)
    assert ".state_after" not in src
    assert '["state_after"]' not in src
    assert "['state_after']" not in src


def test_training_config_flags_no_state_after() -> None:
    b = NeuralTacticBaseline(dim=512, epochs=3).fit([_ex("a", "⊢ p", "rfl")])
    assert b.training_config["uses_state_after"] is False
    assert b.training_config["model"].startswith("softmax")


# ---- pattern-family analysis ----


def _pred_row(theorem, preds, pass5, top5any=True):
    return {
        "theorem_name": theorem,
        "predictions": preds,
        "lean_pass_at_k": {"1": pass5, "3": pass5, "5": pass5},
        "topk_any_verified": {"1": top5any, "3": top5any, "5": top5any},
    }


def test_per_family_pass_at_k_groups_by_family() -> None:
    thm2fam = {"and_left_pq": "and_elim_left", "and_left_ab": "and_elim_left",
               "or_inl_pq": "or_intro_left"}
    preds = [
        _pred_row("and_left_pq", ["exact h.1"], True),
        _pred_row("and_left_ab", ["exact h.2"], False),
        _pred_row("or_inl_pq", ["exact Or.inl h"], True),
    ]
    out = per_family_pass_at_k(preds, thm2fam)
    assert out["and_elim_left"]["n_rows"] == 2
    assert out["and_elim_left"]["pass_at_k"]["5"]["count"] == 1
    assert out["and_elim_left"]["pass_at_k"]["5"]["rate"] == 0.5
    assert out["or_intro_left"]["pass_at_k"]["5"]["rate"] == 1.0


def test_sibling_confusion_uses_top1_tactic_family() -> None:
    thm2fam = {"L1": "and_elim_left", "L2": "and_elim_left", "R1": "and_elim_right"}
    # tactic -> family: h.1 is and_elim_left, h.2 is and_elim_right
    tac2fams = {"exact h.1": {"and_elim_left"}, "exact h.2": {"and_elim_right"},
                "rfl": {"nat_rfl", "eq_refl"}}
    preds = [
        _pred_row("L1", ["exact h.1"], True),    # correct
        _pred_row("L2", ["exact h.2"], False),   # confused with sibling
        _pred_row("R1", ["rfl"], False),         # ambiguous tactic -> other
    ]
    conf = sibling_confusion(preds, thm2fam, tac2fams)
    g = conf["and_elim"]
    assert g["matrix"]["and_elim_left"]["and_elim_left"] == 1
    assert g["matrix"]["and_elim_left"]["and_elim_right"] == 1
    assert g["matrix"]["and_elim_right"]["<ambiguous/other>"] == 1
    # 1 of 3 sibling rows had top-1 family == true family
    assert g["top1_family_accuracy"] == pytest.approx(1 / 3)


def test_load_family_maps_reads_seeds(tmp_path: Path) -> None:
    import json
    from mini_elf_lean.baseline_eval import load_family_maps

    p = tmp_path / "seeds.jsonl"
    p.write_text(
        json.dumps({"theorem_name": "and_left_pq", "metadata": {
            "pattern_family": "and_elim_left",
            "expected_success_tactics": ["exact h.1", "exact h.left"]}}) + "\n"
        + json.dumps({"theorem_name": "and_right_pq", "metadata": {
            "pattern_family": "and_elim_right",
            "expected_success_tactics": ["exact h.2"]}}) + "\n",
        encoding="utf-8",
    )
    thm2fam, tac2fams = load_family_maps(p)
    assert thm2fam == {"and_left_pq": "and_elim_left", "and_right_pq": "and_elim_right"}
    assert tac2fams["exact h.1"] == {"and_elim_left"}
    assert tac2fams["exact h.2"] == {"and_elim_right"}
