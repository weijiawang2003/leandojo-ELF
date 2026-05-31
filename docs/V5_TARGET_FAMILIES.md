# Mini-ELF v5 — target-family audit (V5 Part 1)

v4 (`docs/V4_PLANNER_BLIND_REPORT.md`) showed the v3 system collapses to
lean-cli `pass@5` **0.096** on the planner-blind corpus, and that a controlled
template-addition ablation recovers families **only** if a human authors a
template for them — pure whack-a-mole. Two families resisted **every** ablation:

| family | v3 unchanged | +neg | +∃-elim | +both |
| --- | --- | --- | --- | --- |
| **forall_inst** | 0.00 | 0.00 | 0.00 | **0.00** |
| **rewrite_succ** | 0.00 | 0.00 | 0.00 | **0.00** |

These are the **primary v5 targets**: shapes for which no symbolic template was
written and no current candidate source produces anything. The research question
is whether a *proposer that reuses/generates from data* (retrieval / LLM /
learned) — rather than a hand-written rule — can produce useful proof blocks.

Sources audited: `data/seeds/planner_blind_seeds.jsonl`,
`data/traces/planner_blind_lean_cli_{verified,failed}.jsonl`,
`data/baselines/planner_blind_{v3_test,v4_template_*}/metrics.json`.

## 1. `forall_inst` (primary) — 7 theorems

∀-instantiation: `h : ∀ x : Nat, x = c ⊢ N = c`. The proof instantiates the
hypothesis at the goal's **left-hand-side literal**: `exact h N`.

| theorem | state goal | verified tactic |
| --- | --- | --- |
| `forall_inst_7_0` | `7 = 0` (h : ∀ x, x = 0) | `exact h 7` |
| `forall_inst_3_0` | `3 = 0` | `exact h 3` |
| `forall_inst_5_2` | `5 = 2` | `exact h 5` |
| `forall_inst_9_4` | `9 = 4` | `exact h 9` |
| `forall_inst_13_6` | `13 = 6` | `exact h 13` |
| `forall_inst_var_m` | `8 = m` (m : Nat) | `exact h 8` |
| `forall_inst_var_k` | `8 = k` | `exact h 8` |

One verified tactic per theorem (7 verified rows). The witness is always the
goal's LHS number; the RHS (`0`, `2`, `m`, …) is the ∀-body's constant and must
**not** be used.

**Failed near-misses** (from `..._failed.jsonl`): `rfl` (LHS ≠ RHS, e.g. `7`/`0`),
`exact h` (type mismatch: `∀ (x:Nat), x = 0` vs `7 = 0`), and crucially
`exact h 0` / `exact h 2` / `exact h m` — instantiating at the **RHS** constant,
which yields `0 = 0` / `2 = 2` / `m = m`, not the goal. So the hard part is
choosing the *right* literal to copy into the `∀`-application — exactly what a
numeric-substitution adaptation rule must get right.

## 2. `rewrite_succ` (primary) — 5 theorems

Rewrite / congruence: `h : a = b ⊢ a.succ = b.succ`. The hypothesis name is the
constant `h` across all five; the variable pair changes (`n m`, `a b`, `x y`,
`i j`, `k l`).

| theorem | state goal | verified tactics |
| --- | --- | --- |
| `rewrite_succ_nm` | `n.succ = m.succ` | `rw [h]`, `exact congrArg Nat.succ h`, `subst h⏎rfl`, `exact h ▸ rfl` |
| `rewrite_succ_ab` | `a.succ = b.succ` | (same four) |
| `rewrite_succ_xy` | `x.succ = y.succ` | (same four) |
| `rewrite_succ_ij` | `i.succ = j.succ` | (same four) |
| `rewrite_succ_kl` | `k.succ = l.succ` | (same four) |

Four verified tactics per theorem (20 verified rows). Because the hypothesis is
always named `h`, **all four tactics are verbatim-reusable** across the five
theorems — no literal/identifier adaptation is needed.

**Failed near-misses**: `exact h` (`a = b` vs `a.succ = b.succ`), `rfl`
(`a.succ` not defeq `b.succ`), `exact h.symm` (wrong direction).

## 3. Secondary families (also planner-blind, recovered only by v4 templates)

| family | n thm | verified-tactic shape | adaptation needed |
| --- | --- | --- | --- |
| `neg_exfalso` | 8 | `exact absurd hp hnp` / `(hnp hp).elim` / `contradiction` | none (hyp names `hp`/`hnp`/`h` constant) |
| `neg_contrapositive` | 6 | `intro hp⏎exact hnq (h hp)` | none (`h`/`hnq` constant) |
| `neg_imp_exfalso` | 5 | `intro hp⏎exact absurd hp hnp` | none |
| `neg_double_intro` | 5 | `intro hnp⏎exact hnp hp` | none |
| `neg_or_cases` | 6 | `cases h with …` / `rcases h with hp | hq …` | none |
| `exists_elim_prop` | 6 | `rcases h with ⟨n, hp⟩⏎exact hp` | none |
| `exists_elim_conj` | 8 | `rcases h with ⟨n, hp, hq⟩⏎exact hp/hq` | none |
| `exists_reconstruct` | 5 | `exact ⟨c, rfl⟩` / `exact h` | numeric (already solved by witness-copy) |

The corpus deliberately uses **constant hypothesis names within each family**
(`h`, `hp`, `hnp`, `hnq`, …), so a same-family donor's verified tactic is
verbatim-correct on a sibling theorem. This is what makes *retrieval* a credible
non-template approach — and is also the honest caveat (§5).

## 4. What current sources produce on the targets (nothing)

From `planner_blind_v3_test/metrics.json` and the `v4_template_*` runs:

- **v3 planner** — emits **0** candidates on `forall_inst`/`rewrite_succ`
  (`rows_with_any_planner_candidate` covers only the mis-parsed `∃,∧` shape; the
  planner is structurally blind to ∀-instantiation and rewrite). `rows_passed_via_planner = 0`.
- **v4 negation / ∃-elim templates** — `forall_inst` and `rewrite_succ` stay
  `0.00` (no template authored), confirmed in all three ablation metrics files.
- **witness-copy** — does not fire (goals are equalities, not `∃`).
- **flow decoder** — `candidate_invalid_rate ≈ 0.96`; produces only garble on
  these shapes.

So the targets have **zero verified candidates from every existing source** — a
clean test bed: any non-zero `pass@k` on `forall_inst`/`rewrite_succ` in v5 is
attributable entirely to the new proposer.

## 5. Implications for the v5 proposers

- **Retrieval** can solve `rewrite_succ` and the secondary families by *verbatim
  reuse* of a same-family donor (constant hyp names), and `forall_inst` by
  *numeric-literal substitution* (copy the goal's LHS number into `exact h _`).
  It needs same-family donor examples → v5 builds a per-family train/test split
  (`family_interpolation`) so retrieval has held-out donors without leaking the
  test theorem. **Honest caveat:** this is in-family interpolation/example reuse,
  **not** compositional reasoning, and it depends on the corpus's consistent
  naming. Reported as such.
- **LLM** is the only source that could solve these with *no* same-shape donor;
  pilot gated on an API key (Part 3).
- **Learned proposer** (Part 5): a small seq2seq trained on verified blocks —
  compared against retrieval/LLM if implemented.

See `docs/V5_RESULTS_SUMMARY.md` for the measured outcomes.
