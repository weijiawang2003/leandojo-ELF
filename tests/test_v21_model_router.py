"""Tests for the v21 category-based model router."""

from __future__ import annotations

from mini_elf_lean.v21_model_router import (
    BROAD_PLUS, FORALL_SPECIALIST, ModelRouter,
)


def _router_both():
    return ModelRouter(available={BROAD_PLUS, FORALL_SPECIALIST})


def test_forall_category_routes_to_specialist():
    r = _router_both()
    assert r.route(category="forall") == FORALL_SPECIALIST


def test_forall_operation_routes_to_specialist():
    r = _router_both()
    assert r.route(required_operation="instantiate_forall") == FORALL_SPECIALIST


def test_implication_routes_to_broad():
    r = _router_both()
    assert r.route(category="implication") == BROAD_PLUS


def test_bool_routes_to_broad():
    r = _router_both()
    assert r.route(category="bool") == BROAD_PLUS


def test_unknown_category_routes_to_broad():
    r = _router_both()
    assert r.route(category="disjunction") == BROAD_PLUS
    assert r.route(category=None, required_operation=None) == BROAD_PLUS


def test_fallback_when_specialist_unavailable():
    # Only broad available -> forall falls back to broad, never crashes.
    r = ModelRouter(available={BROAD_PLUS})
    assert r.route(category="forall") == BROAD_PLUS


def test_case_insensitive_and_whitespace():
    r = _router_both()
    assert r.route(category="  FORALL ") == FORALL_SPECIALIST
    assert r.route(required_operation="Instantiate_Forall") == FORALL_SPECIALIST


def test_explain_reports_reason():
    r = _router_both()
    e = r.explain(category="forall")
    assert e["chosen_model"] == FORALL_SPECIALIST
    assert "specialist" in e["reason"]
    e2 = r.explain(category="implication")
    assert e2["chosen_model"] == BROAD_PLUS
    assert "broad" in e2["reason"]


def test_explain_fallback_reason():
    r = ModelRouter(available={BROAD_PLUS})
    e = r.explain(category="forall")
    assert e["chosen_model"] == BROAD_PLUS
    assert "fallback" in e["reason"]


def test_router_has_no_state_after_dependency():
    # The router only sees category/operation strings — never a proof
    # state. Assert via the function signatures, not prose.
    import inspect
    from mini_elf_lean.v21_model_router import ModelRouter
    for fn in (ModelRouter.route, ModelRouter.explain):
        params = set(inspect.signature(fn).parameters)
        assert "state_after" not in params
        assert "state_before" not in params
        assert params <= {"self", "category", "required_operation"}
