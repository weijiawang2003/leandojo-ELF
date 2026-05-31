# Mini-ELF v4 — Planner-Blind Generalization Benchmark

**v3 saturated the hard corpus (`difficulty_holdout` `pass@5` 0.06 → 1.00), but
that lift was *engineered symbolic coverage*, not learned reasoning.** v4 tests
the honest question that leaves open: **where does the Mini-ELF + symbolic
planner system fail once the proof shape is outside the planner's template
library?** It (1) audits the planner's coverage frontier, (2) builds a corpus of
*planner-blind* proof families, (3) evaluates the **unchanged** AR / v1 / v2 / v3
systems on it, and (4) runs a controlled template-addition ablation to measure
the marginal value of extending symbolic coverage.

> Scope, unchanged: **theorem-level** verification only (`state_after_is_real=
> false`); v0–v4 are prototypes of the *generation loop*, **not** full ELF over
> proof states; the planner is symbolic/heuristic, not neural; LeanDojo `run_tac`
> remains blocked (`xfail`). **n=157 eval rows → directional, not statistically
> definitive.** This is **not** a claim of full theorem proving.

## 1. Planner coverage audit (Part 1)

`scripts/audit_planner_coverage.py` (→ `docs/V4_PLANNER_COVERAGE_AUDIT.md`) runs
the planner on a fixed shape catalog. **Supported** (constructs ≥1 candidate):
conjunction projection, implication/modus-ponens chains, iff `.mp/.mpr`
composition, equality `.trans/.symm` chains, `∨`-elimination case splits, `∧`/`∨`
introduction, and `∃`-witness (delegated to witness-copy). **Planner-blind**
(zero candidates, and no other v3 source constructs them): negation /
contradiction (ex-falso), contrapositive `¬`-goals, `∃`-elimination,
`∀`-instantiation, and rewrite / substitution. The v4 corpus is built from
exactly these blind shapes.

## 2. The planner-blind corpus (Parts 2–3)

`scripts/generate_planner_blind_corpus.py` (core Lean 4, no Mathlib,
intuitionistic), collected + Lean-verified like every prior corpus.

| quantity | value |
| --- | --- |
| theorem seeds | 61 |
| pattern families | 10 (`neg_exfalso`, `neg_contrapositive`, `neg_imp_exfalso`, `neg_double_intro`, `neg_or_cases`, `exists_elim_prop`, `exists_elim_conj`, `forall_inst`, `rewrite_succ`, `exists_reconstruct`) |
| candidate attempts | 324 |
| verified / failed | 157 / 167 (0 timeouts) |
| candidate success rate | 0.485 |
| **zero-success theorems** | **0** (every theorem has ≥1 verified tactic) |

The correct compositional tactics verify (rcases 25/25, obtain 14/14,
`contradiction` 8/8, `rw` 5/5, `subst` 5/5, `congrArg`, `▸`); the near-misses
fail legitimately (`rfl` 0/17, `assumption` 0/5; top Lean errors: type mismatch
113, `rfl` failed 17, invalid projection 15). Every theorem name is disjoint from
the basic + hard corpora (tested). Metadata tags `requires_negation /
requires_exists_elim / requires_forall / requires_rewrite / planner_blind=true`.

## 3. Unchanged systems collapse on the blind corpus (Part 4)

lean-cli `pass@k`, evaluated on all 61 theorems (held-out; no model trained on
them). The v3 planner is used **unchanged** — no new templates.

| system | n | pass@1 | pass@3 | pass@5 | invalid@1 | what solved anything |
| --- | --- | --- | --- | --- | --- | --- |
| AR seq2seq | 157 | 0.00 | 0.00 | **0.00** | — | nothing |
| Mini-ELF v1 | 157 | 0.04 | 0.10 | **0.096** | 0.96 | witness-copy only (27/27) |
| Mini-ELF v2 | 157 | 0.08 | 0.10 | **0.096** | 0.92 | witness-copy (18) + flow (12) |
| **Mini-ELF v3 (planner unchanged)** | 157 | 0.10 | 0.10 | **0.096** | 0.90 | witness-copy only (30/30) |

**v3 collapses from `pass@5` 1.00 (hard difficulty) to 0.096 here — the corpus is
genuinely planner-blind.** The planner contributes **0 verified candidates**
(`rows_solved_only_by_planner = 0`); it even *mis-fires* on `exists_elim_conj`,
emitting `exact h.2` because the text parser reads `∃ _, p ∧ q` as a top-level
`∧` (`planner_projection` 0/16). The **only** family any system solves is
`exists_reconstruct` (`pass@5` 1.00), and only because the symbolic **witness-copy**
shortcut (`exact ⟨k, rfl⟩`) sidesteps the intended `∃`-elimination — a robustness
of the *non-planner* symbolic source, not of the learned model. AR/v1/v2/v3 are
otherwise flat at 0 on negation, contrapositive, `∃`-elim, `∀`-inst, and rewrite.

Per-family `pass@5` (all four systems, except `exists_reconstruct`): **0.00**.

## 4. Controlled template-addition ablation (Part 5)

We then add the **optional, explicitly-labelled** template families
(`src/mini_elf_lean/proof_planner_v4.py`: `planner_negation`,
`planner_exists_elim`) on top of unchanged v3 — **not** folded into v3 — and
measure the marginal recovery (`scripts/run_v4_template_ablation.sh`).

| config | global pass@5 | new-template verified/attempted |
| --- | --- | --- |
| v3 (unchanged) | 0.096 | — |
| v3 + negation templates | **0.611** | planner_negation 241/241 |
| v3 + ∃-elim templates | **0.312** | planner_exists_elim 68/68 |
| v3 + both | **0.828** | 241/241 + 68/68 |

Per-family `pass@5`:

| family | v3 | +neg | +∃-elim | +both |
| --- | --- | --- | --- | --- |
| neg_exfalso / neg_contrapositive / neg_imp_exfalso / neg_double_intro / neg_or_cases | 0.00 | **1.00** | 0.00 | **1.00** |
| exists_elim_prop / exists_elim_conj | 0.00 | 0.00 | **1.00** | **1.00** |
| exists_reconstruct | 1.00 | 1.00 | 1.00 | 1.00 |
| **forall_inst** | 0.00 | 0.00 | 0.00 | **0.00** |
| **rewrite_succ** | 0.00 | 0.00 | 0.00 | **0.00** |

The result is **exactly whack-a-mole**: adding a template for a family takes it
0.00 → 1.00 with 100% precision (every new-template candidate that reached the
top-5 verified), and adds **nothing** to families it does not target.
Decisively, **`forall_inst` and `rewrite_succ` stay at 0.00 even with both
template sets** (we added no template for them), so the corpus is *still* not
saturated after the ablation. This is the point: symbolic coverage is per-shape
and never complete — each new proof shape needs a hand-written template, which is
*engineered coverage, not learned reasoning*. (The `+both` `pass@1` 0.78 trails
`pass@5` 0.83 because the base planner's `∃,∧` mis-parse puts a failing `exact h.2`
at rank 1 on `exists_elim_conj`; the correct `rcases … hb.2` verifies at rank 2–3.)

## 5. LLM proposal pilot (Part 6)

**Skipped — no API key configured** (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` unset;
only `.env.example`). Not faked. A real-LLM candidate generator is the natural
way to attack the families with *no* template (`forall_inst`, `rewrite_succ`) and
to escape the whack-a-mole entirely; it remains the headline v5 task.

## 6. Honest conclusions

- The v3 planner's strength is a **closed catalog**. On proof shapes outside it,
  the *entire* Mini-ELF system (learned generator + reranker + planner) drops to
  `pass@5` **0.096** — essentially the witness-copy shortcut alone. The learned
  components contribute almost nothing off-distribution, exactly as v2 found.
- **Adding templates recovers precisely the targeted families** (negation,
  `∃`-elim) at 100% precision, and **nothing else** — `forall_inst` and
  `rewrite_succ` remain 0.00. This quantifies "engineered symbolic coverage": it
  is real and high-precision, but it does not generalize beyond what was authored.
- The benchmark is **not too easy** (every prior system fails it) and **not
  trivially saturable** (two families resist even the ablation). It is a durable
  planner-blind robustness probe.
- Everything remains theorem-level, small-sample, and a generation-loop
  prototype — **not** full theorem proving, **not** full ELF.

## 7. What remains for v5

1. **Learned candidate generation (real LLM pilot)** — the only path that does
   not require a human to pre-author every proof shape; target the
   template-less families (`forall_inst`, `rewrite_succ`) first.
2. **A parser that does not mis-read `∃ _, p ∧ q`** — a small AST/precedence fix
   so the planner stops emitting `exact h.2` on `∃`-elim (surfaced here).
3. **A self-expanding planner-blind generator** — auto-mine proof shapes the
   current templates cannot construct, so the benchmark grows as coverage grows.
4. **Real next-state supervision** (LeanDojo `run_tac` unblock) — still the
   prerequisite for modeling actual proof-state flow rather than tactic strings.
