"""Mini-ELF v3 fusion baseline + evaluator unit tests (Part 6).

The fusion logic is exercised against a lightweight *fake* v2 model (a stub with
the handful of attributes/methods :class:`MiniElfV3Baseline` reads), so the test
needs **no trained model and no Lean** — it isolates dedup, source labelling,
and the tier policy (planner/witness ahead of flow). A fake reranker checks that
the planner still leads even when the reranker scores flow candidates higher
(the off-distribution mis-calibration v3 is designed to bypass)."""

from __future__ import annotations

from pathlib import Path

from mini_elf_lean.baselines import Example
from mini_elf_lean.elf_v1_sample import FLOW_SOURCE
from mini_elf_lean.elf_v3_sample import MiniElfV3Baseline
from mini_elf_lean.elf_witness import WITNESS_SOURCE
from mini_elf_lean.proof_planner import PLANNER_SOURCES

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class _FakeReranker:
    """Scores any flow candidate high (0.9) and everything else 0.1 — the
    pathological off-distribution case the tier policy must survive."""

    def score_batch(self, stmt, state, candidates, *, family=None):
        return [0.9 if c.startswith("garbo") else 0.1 for c in candidates]


class _FakeV2:
    decode = "decoder"
    rerank_pool = 16
    rerank_blend = 0.15
    n_samples = 8

    def __init__(self, flow, *, use_witness=True, use_reranker=False):
        self._flow = flow
        self.use_witness = use_witness
        self.use_reranker = use_reranker
        self.reranker = _FakeReranker() if use_reranker else None

    @property
    def mode(self):
        return "fake_v2"

    def _flow_candidates(self, stmt, state):
        return list(self._flow)

    def distinct_flow_candidates(self, example):
        return len(self._flow)


def _ex(stmt, state, name="t", tactic="exact h"):
    return Example(theorem_name=name, theorem_statement=stmt, state_before=state,
                   tactic=tactic, split="test")


_CHAIN_STMT = "(p q r s : Prop) (h1 : p → q) (h2 : q → r) (h3 : r → s) : p → s"
_CHAIN_STATE = "p q r s : Prop\nh1 : p → q\nh2 : q → r\nh3 : r → s\n⊢ p → s"


def test_planner_candidates_lead_flow_without_reranker():
    v2 = _FakeV2([("garbo1", 9), ("garbo2", 5)], use_reranker=False)
    b = MiniElfV3Baseline(v2)
    ranked = b.ranked_candidates(_ex(_CHAIN_STMT, _CHAIN_STATE))
    # planner's constructed chain proof is first; flow garbage trails
    assert ranked[0]["source"] in PLANNER_SOURCES
    assert ranked[0]["tactic"] == "intro ha\n  exact h3 (h2 (h1 ha))"
    sources = [it["source"] for it in ranked]
    assert sources.index("planner_chain") < sources.index(FLOW_SOURCE)


def test_planner_leads_even_when_reranker_prefers_flow():
    v2 = _FakeV2([("garbo1", 9)], use_reranker=True)
    b = MiniElfV3Baseline(v2)
    ranked = b.ranked_candidates(_ex(_CHAIN_STMT, _CHAIN_STATE))
    # despite the reranker scoring "garbo1" at 0.9 and the planner block at 0.1,
    # the planner block is still ranked first (tier policy, not reranker order)
    assert ranked[0]["source"] == "planner_chain"
    # the reranker score is still recorded on the planner candidate
    assert ranked[0]["reranker_score"] == 0.1


def test_predict_with_neighbors_carries_source_and_strategy():
    v2 = _FakeV2([("garbo1", 3)])
    b = MiniElfV3Baseline(v2)
    preds, prov = b.predict_with_neighbors(_ex(_CHAIN_STMT, _CHAIN_STATE), k=3)
    assert preds[0] == "intro ha\n  exact h3 (h2 (h1 ha))"
    assert prov[0]["source"] == "planner_chain"
    assert prov[0]["strategy"] == "intro_exact"


def test_dedup_planner_claims_a_shared_tactic():
    # flow also proposes the projection the planner constructs -> attributed to planner
    state = "p q r : Prop\nh : p ∧ q ∧ r\n⊢ r"
    stmt = "(p q r : Prop) (h : p ∧ q ∧ r) : r"
    v2 = _FakeV2([("exact h.2.2", 7), ("garbo", 2)])
    b = MiniElfV3Baseline(v2)
    ranked = b.ranked_candidates(_ex(stmt, state))
    hits = [it for it in ranked if it["tactic"] == "exact h.2.2"]
    assert len(hits) == 1 and hits[0]["source"] == "planner_projection"


def test_witness_used_for_exists_and_planner_empty():
    state = "⊢ ∃ n : Nat, n = 6"
    stmt = ": ∃ n : Nat, n = 6"
    v2 = _FakeV2([("garbo", 1)], use_witness=True)
    b = MiniElfV3Baseline(v2)
    assert b.planner_candidate_count(_ex(stmt, state)) == 0
    ranked = b.ranked_candidates(_ex(stmt, state))
    sources = [it["source"] for it in ranked]
    assert WITNESS_SOURCE in sources
    # a witness candidate (constructed) precedes the flow garbage
    assert sources.index(WITNESS_SOURCE) < sources.index(FLOW_SOURCE)


def test_no_planner_ablation_disables_planner_source():
    v2 = _FakeV2([("garbo", 1)])
    b = MiniElfV3Baseline(v2, use_planner=False)
    ranked = b.ranked_candidates(_ex(_CHAIN_STMT, _CHAIN_STATE))
    assert all(it["source"] not in PLANNER_SOURCES for it in ranked)
    assert b.planner_candidate_count(_ex(_CHAIN_STMT, _CHAIN_STATE)) == 0


def test_planner_stats_counts_contribution():
    import importlib
    mod = importlib.import_module("scripts.evaluate_mini_elf_v3")
    predictions = [{
        "theorem_name": "t1", "state_before": _CHAIN_STATE,
        "predictions": ["intro ha\n  exact h3 (h2 (h1 ha))", "garbo"],
        "prediction_provenance": [
            {"source": "planner_chain", "strategy": "intro_exact", "reranker_score": 0.1, "sample_count": 0},
            {"source": FLOW_SOURCE, "strategy": None, "reranker_score": 0.9, "sample_count": 9},
        ],
        "lean_results": {"intro ha\n  exact h3 (h2 (h1 ha))": {"success": True},
                         "garbo": {"success": False}},
    }]

    class _B:
        use_planner = True

        def planner_candidate_count(self, e):
            return 2

    stats = mod._planner_stats(predictions, _B(), [object()], verifier_used=True)
    assert stats["rows_passed_via_planner"] == 1
    assert stats["rows_solved_only_by_planner"] == 1  # flow did not verify
    assert stats["rows_planner_top1_verified"] == 1
    assert stats["planner_by_source"]["planner_chain"]["verified"] == 1


def test_v3_modules_never_access_state_after():
    files = [SRC / "proof_planner.py", SRC / "elf_v3_sample.py",
             SCRIPTS / "evaluate_mini_elf_v3.py", SCRIPTS / "analyze_difficulty_failures.py",
             SCRIPTS / "compose_v3_examples.py"]
    for f in files:
        text = f.read_text(encoding="utf-8")
        for pat in (".state_after", '["state_after"]', "['state_after']",
                    'get("state_after"', "get('state_after'"):
            assert pat not in text, f"{f.name} references {pat!r}"
