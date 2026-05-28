"""Mini-ELF v1 — sampling: candidate fusion (flow + witness), dedup, reranked
ordering, source labels, determinism, and a train→save→load smoke. Torch-gated;
no Lean."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.elf_rerank import RerankConfig, RerankExample, Reranker  # noqa: E402
from mini_elf_lean.elf_v1_sample import (  # noqa: E402
    FLOW_SOURCE,
    WITNESS_SOURCE,
    MiniElfV1Baseline,
)
from mini_elf_lean.elf_v1_train import ElfV1TrainConfig, save_artifacts_v1, train_v1  # noqa: E402


def _ex(name, statement, state, tactic, split="train"):
    return Example(theorem_name=name, theorem_statement=statement,
                   state_before=state, tactic=tactic, split=split)


def _train_examples():
    return [
        _ex("a", "(p:Prop)(h:p):p", "p : Prop\nh : p\n⊢ p", "exact h"),
        _ex("b", "(q:Prop):q→q", "q : Prop\n⊢ q → q", "intro h\n  exact h"),
        _ex("c", "(p q:Prop)(h:p∧q):p", "p q : Prop\nh : p ∧ q\n⊢ p", "exact h.1"),
        _ex("d", "(p q:Prop)(h:p∧q):q", "p q : Prop\nh : p ∧ q\n⊢ q", "exact h.2"),
        _ex("e", ": ∃ n : Nat, n = 0", "⊢ ∃ n : Nat, n = 0", "exact ⟨0, rfl⟩"),
    ]


def _tiny_cfg():
    return ElfV1TrainConfig(
        ae_epochs=3, flow_epochs=4, latent_dim=8, cond_dim=16, ae_emb=16, ae_hidden=16,
        cond_emb=16, cond_raw_hidden=16, cond_goal_hidden=8, cond_shape_dim=4,
        flow_hidden=16, time_dim=8, n_samples=6, flow_steps=3, val_every=2,
        max_tactic_len=32, max_cond_len=48, max_goal_len=32,
        ae_denoise_prob=0.2, ae_latent_noise_std=0.1, seed=0,
    )


def test_train_v1_runs_and_reports():
    train_ex = _train_examples()
    val_ex = [_ex("v", ": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5", "exact ⟨5, rfl⟩", split="val")]
    art = train_v1(train_ex, val_ex, train_ex + val_ex, _tiny_cfg(), device="cpu")
    assert art.summary["uses_state_after"] is False
    assert art.summary["ae_denoise_prob"] == 0.2
    assert "top1_exact" in art.val_metrics


def test_save_load_and_modes(tmp_path):
    train_ex = _train_examples()
    val_ex = [_ex("v", ": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5", "exact ⟨5, rfl⟩", split="val")]
    art = train_v1(train_ex, val_ex, train_ex + val_ex, _tiny_cfg(), device="cpu")
    save_artifacts_v1(tmp_path, art, _tiny_cfg())
    for f in ("config.json", "vocab.json", "embed.pt", "flow_model.pt",
              "tactic_library.json", "train_log.jsonl", "val_metrics.json"):
        assert (tmp_path / f).exists()

    # decoder, no witness, no rerank
    b = MiniElfV1Baseline.load(tmp_path, n_samples=6, steps=3, seed=0)
    ex = _ex("z", ": ∃ n : Nat, n = 7", "⊢ ∃ n : Nat, n = 7", "exact ⟨7, rfl⟩", split="test")
    preds = b.predict(ex, k=5)
    assert len(preds) == len(set(preds))  # deduped
    assert b.predict(ex, k=5) == b.predict(ex, k=5)  # deterministic


def test_witness_candidates_merged_and_labeled(tmp_path):
    art = train_v1(_train_examples(), [], _train_examples(), _tiny_cfg(), device="cpu")
    save_artifacts_v1(tmp_path, art, _tiny_cfg())
    b = MiniElfV1Baseline.load(tmp_path, n_samples=6, steps=3, seed=0, use_witness=True)
    ex = _ex("z", ": ∃ n : Nat, n = 7", "⊢ ∃ n : Nat, n = 7", "exact ⟨7, rfl⟩", split="test")
    ranked = b.ranked_candidates(ex)
    tactics = [it["tactic"] for it in ranked]
    sources = {it["tactic"]: it["source"] for it in ranked}
    assert "exact ⟨7, rfl⟩" in tactics  # witness candidate present
    assert sources["exact ⟨7, rfl⟩"] == WITNESS_SOURCE
    # flow candidates keep their source label
    assert any(s == FLOW_SOURCE for s in sources.values())


def test_reranker_changes_ranking(tmp_path):
    art = train_v1(_train_examples(), [], _train_examples(), _tiny_cfg(), device="cpu")
    save_artifacts_v1(tmp_path, art, _tiny_cfg())

    # train a reranker that strongly prefers the witness tactic, save into same dir
    rex = [
        RerankExample(": ∃ n : Nat, n = 7", "⊢ ∃ n : Nat, n = 7", "exact ⟨7, rfl⟩", 1),
        RerankExample(": ∃ n : Nat, n = 7", "⊢ ∃ n : Nat, n = 7", "garblexyz", 0),
        RerankExample(": ∃ n : Nat, n = 7", "⊢ ∃ n : Nat, n = 7", "exact ⟨9, rfl⟩", 0),
    ] * 4
    rr = Reranker.fit(rex, RerankConfig(epochs=60, seed=0))
    rr.save(tmp_path)

    b = MiniElfV1Baseline.load(tmp_path, n_samples=6, steps=3, seed=0,
                               use_witness=True, use_reranker=True)
    ex = _ex("z", ": ∃ n : Nat, n = 7", "⊢ ∃ n : Nat, n = 7", "exact ⟨7, rfl⟩", split="test")
    ranked = b.ranked_candidates(ex)
    assert ranked[0]["tactic"] == "exact ⟨7, rfl⟩"  # reranker floats witness to top
    assert ranked[0]["reranker_score"] is not None
    # reranked shortlist items carry a probability in [0, 1]; the witness (highest
    # numeric-match score) leads the frequency-blended order.
    pool_scores = [it["reranker_score"] for it in ranked if it["reranker_score"] is not None]
    assert all(0.0 <= s <= 1.0 for s in pool_scores)
    assert ranked[0]["reranker_score"] == max(pool_scores)


def test_v1_sample_module_never_accesses_state_after():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"
    for fname in ("elf_v1_sample.py", "elf_v1_train.py"):
        text = (src / fname).read_text(encoding="utf-8")
        for pat in (".state_after", '["state_after"]', "['state_after']",
                    'get("state_after"', "get('state_after'"):
            assert pat not in text, f"{fname} accesses state_after via {pat!r}"
