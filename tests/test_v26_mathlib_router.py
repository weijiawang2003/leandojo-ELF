"""v26 router unit tests (pure Python, no Lean)."""

from __future__ import annotations

from mini_elf_lean.v26_mathlib_router import (
    BROAD_CORE, MATHLIB_SPECIALIST, MathlibRouter,
)


def _router():
    return MathlibRouter(available={BROAD_CORE, MATHLIB_SPECIALIST})


def test_import_mathlib_routes_to_specialist():
    r = _router()
    assert r.route(imports=["import Mathlib"]) == MATHLIB_SPECIALIST
    assert r.route(imports=["import Mathlib.Data.Set.Basic"]) == MATHLIB_SPECIALIST


def test_no_import_routes_to_broad_core():
    r = _router()
    assert r.route(imports=[]) == BROAD_CORE
    assert r.route(imports=None) == BROAD_CORE


def test_mathlib_flag_and_source_route_to_specialist():
    r = _router()
    assert r.route(mathlib_flag=True) == MATHLIB_SPECIALIST
    assert r.route(source="v25_mathlib_tierc") == MATHLIB_SPECIALIST
    assert r.route(source="mini_elf_v3_hard_tierc_test") == MATHLIB_SPECIALIST
    assert r.route(source="v18_broad_core") == BROAD_CORE


def test_route_seed_reads_dict_fields():
    r = _router()
    assert r.route_seed({"imports": ["import Mathlib"], "theorem_name": "t"}) == MATHLIB_SPECIALIST
    assert r.route_seed({"imports": [], "mathlib": True}) == MATHLIB_SPECIALIST
    assert r.route_seed({"imports": [], "uses_mathlib": False}) == BROAD_CORE


def test_fallback_when_specialist_unavailable():
    r = MathlibRouter(available={BROAD_CORE})  # specialist not loaded
    # a mathlib theorem degrades to broad-core rather than crashing
    assert r.route(imports=["import Mathlib"]) == BROAD_CORE


def test_explain_is_inspectable():
    r = _router()
    ex = r.explain({"theorem_name": "v25_set_subset_refl", "imports": ["import Mathlib"]})
    assert ex["chosen_model"] == MATHLIB_SPECIALIST
    assert ex["wants_mathlib"] is True
    assert "specialist" in ex["reason"]
    ex2 = r.explain({"theorem_name": "v18_imp_p_self", "imports": []})
    assert ex2["chosen_model"] == BROAD_CORE
    assert ex2["wants_mathlib"] is False
