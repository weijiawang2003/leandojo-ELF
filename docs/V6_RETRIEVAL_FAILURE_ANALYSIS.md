# Mini-ELF v6 — v5 retrieval failure analysis (Part 1)

v5's retrieval proposer solved the template-less targets (`forall_inst`,
`rewrite_succ` → pass@5 1.00) but ranked by **char-n-gram similarity only**, which
mis-ranks in four ways (`docs/V5_FAILURE_EXAMPLES.md`). v6 asks: can
**structure-aware** scoring + adapted-candidate ranking fix these *without* new
hand-written proof templates? For each mode below: target, top retrieved donor,
correct donor, why char-sim failed, and the structural feature that distinguishes
it. Evidence is verbatim from the v5 `predictions.jsonl`.

## F1 — adapted candidate ranked below verbatim (`forall_inst` pass@1 = 0)

- **Target**: `forall_inst_13_6`, goal `13 = 6`, hyp `h : ∀ x, x = 6`. Correct: `exact h 13`.
- **Top donor**: `forall_inst_3_0` → verbatim `exact h 3` (rank 0, **fails**);
  the adapted `exact h 13` is rank 1.
- **Correct donor**: same donor, *adapted* form.
- **Why char-sim failed**: char-sim has no signal that the donor's literal `3` is
  *stale* for a `13 = 6` goal; it emits the verbatim copy first.
- **Structural fix**: a **stale-literal penalty** on a verbatim donor whose
  numeric literal is absent from the target, and an **adapted-candidate
  preference** — rank `exact h 13` (literal present in target) above `exact h 3`.

## F2 — left/right sibling confusion (`exists_elim_conj` pass@5 = 0.25)

- **Target**: `exists_elim_conj_l_ab`, hyp `h : ∃ _, a ∧ b`, goal `a` (the **left**
  conjunct). Correct: `rcases h with ⟨n, hp, hq⟩ ; exact hp`.
- **Top donor**: `exists_elim_conj_r_ab` → `exact hpq.2` / `exact hq` (the
  **right** conjunct) — same variables `a b`, so highest char-sim.
- **Correct donor**: `exists_elim_conj_l_ps` / `_l_xy` (left projection, different
  letters → lower char-sim).
- **Why char-sim failed**: it rewards *variable-letter* overlap (`a`,`b`) over
  *projection direction*.
- **Structural fix**: a **conjunct-position feature** — does the goal equal the
  left or right side of the ∃-body's `∧`? Penalize a donor whose
  `goal_conjunct_position` differs from the target's.

## F3 — missing `intro` cross-family (`neg_imp_exfalso` pass@5 = 0.33)

- **Target**: `neg_imp_exfalso_ab`, goal `a → b` (implication), hyp `hnp : ¬a`.
  Correct: `intro hp ; exact absurd hp hnp`.
- **Top donor**: `neg_exfalso_ab` → `contradiction` / `exact absurd hp hnp` (no
  `intro`; its goal is a bare atom, hyp already in context).
- **Correct donor**: `neg_imp_exfalso_ps` / `_xy` (implication goal, `intro` first).
- **Why char-sim failed**: `neg_exfalso` and `neg_imp_exfalso` share almost all
  surface text; the discriminator is the **goal shape** (`atom` vs `→`).
- **Structural fix**: `goal_shape` match (implication_goal ≠ contradiction_goal)
  + an **"intro required" penalty** on donor tactics lacking `intro`/`fun` when the
  target goal is an implication/negation.

## F4 — wrong negation family (`neg_exfalso` pass@5 = 0.00)

- **Target**: `neg_exfalso_pq`, goal `q` (atom), hyps `hp : p`, `hnp : ¬p`.
  Correct: `exact absurd hp hnp` (**is** in train, from `neg_exfalso_ab`/`_ac`).
- **Top donors**: `neg_double_intro_q` (`exact fun hnp => hnp hp`),
  `neg_or_cases_pq` (`cases h ...`) — shorter / letter-sharing → higher cosine.
- **Correct donor**: `neg_exfalso_ab` / `_ac`, ranked out of the top-5.
- **Why char-sim failed**: shorter neighbours and the shared letter `q` win on
  cosine; the discriminators are **goal shape** (`neg_double_intro` is a `¬¬`
  goal) and **hypothesis shape** (`neg_or_cases` has an `∨`-hyp; `neg_exfalso`
  does not).
- **Structural fix**: `goal_shape` + `has_or_hyp`/`has_neg_hyp` matching, and an
  **operation match** (target `required_operation = contradiction` should prefer
  donors whose operation is also `contradiction`, not `intro_negation`/case-split).

## F5 / F6 — LLM skipped, learned deferred

Unchanged from v5 (`docs/V5_LLM_PILOT_SKIPPED.md`,
`docs/V5_LEARNED_PROPOSER.md`); out of scope for v6's retrieval-ranking work.

## Summary — features v6 needs

| failure | discriminating feature |
| --- | --- |
| F1 | numeric stale-literal penalty + adapted-candidate preference |
| F2 | `goal_conjunct_position` (left/right) match |
| F3 | `goal_shape` (implication vs atom) + "intro required" penalty |
| F4 | `goal_shape` + `has_*_hyp` shape match + `required_operation` match |

These are all **heuristic parse features over `theorem_statement` + `state_before`**
— no Lean AST, no `state_after`, and **not** new proof templates. v6 changes
*ranking*, not proof construction.
