# Mini-ELF v5 — results summary

> **Scope.** Theorem-level lean-cli verification only (`state_after_is_real=false`); these are prototypes of the *generation loop*, not full ELF over proof states. The v5 split test set is **32 theorems** (the `family_interpolation` within-family split, so each family has held-out test theorems **and** same-family train donors, with no theorem in both). It is therefore **not** the same set as the v4 all-test 61-theorem corpus — the all-test v4 numbers are kept separately below as the off-library headline. n is small ⇒ directional, not statistically definitive. Manual-oracle candidates are **never** counted as a model result.

## 1. Primary question: the template-less targets

On the split test set, the **retrieval** proposer takes the two families no v4 template ever recovered to `forall_inst` pass@5 = **1.000** (via numeric-literal adaptation; `verified_by_adaptation = {'numeric': 12}`) and `rewrite_succ` pass@5 = **1.000** (verbatim reuse) — with **no hand-written template**. This is the v5 result: a data-driven proposer escapes the per-shape whack-a-mole on the targets.

## 2. Configuration comparison (split test, n=32)

| config | n | pass@1 | pass@3 | pass@5 | forall_inst@5 | rewrite_succ@5 | invalid@1 | novel_verified | rows_only_proposer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v3 (unchanged) | 32 | 0.107 | 0.107 | 0.107 | 0.000 | 0.000 | 0.893 | 18 | 0 |
| v4 templates (both, labelled) | 32 | 0.774 | 0.821 | 0.821 | 0.000 | 0.000 | 0.226 | 115 | 0 |
| retrieval (alone) | 32 | 0.357 | 0.524 | 0.595 | 1.000 | 1.000 | 0.643 | 11 | 50 |
| retrieval-verbatim (no adapt) | 32 | 0.357 | 0.488 | 0.571 | 0.333 | 1.000 | 0.643 | 0 | 48 |
| v3 ⊕ retrieval | 32 | 0.357 | 0.524 | 0.595 | 1.000 | 1.000 | 0.643 | 20 | 41 |
| v3 + v4-tmpl ⊕ retrieval | 32 | 0.917 | 1.000 | 1.000 | 1.000 | 1.000 | 0.083 | 117 | 15 |
| LLM (alone) | 32 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0 | 0 |

## 3. Per-family pass@5 (split test)

| family | v3 (unchanged) | v4 templates (both, labelled) | retrieval (alone) | retrieval-verbatim (no adapt) | v3 ⊕ retrieval | v3 + v4-tmpl ⊕ retrieval | LLM (alone) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| neg_exfalso | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| neg_contrapositive | 0.000 | 1.000 | 0.667 | 0.667 | 0.667 | 1.000 | 0.000 |
| neg_imp_exfalso | 0.000 | 1.000 | 0.333 | 0.333 | 0.333 | 1.000 | 0.000 |
| neg_double_intro | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| neg_or_cases | 0.000 | 1.000 | 0.333 | 0.333 | 0.333 | 1.000 | 0.000 |
| exists_elim_prop | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| exists_elim_conj | 0.000 | 1.000 | 0.250 | 0.250 | 0.250 | 1.000 | 0.000 |
| exists_reconstruct | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| forall_inst **(target)** | 0.000 | 0.000 | 1.000 | 0.333 | 1.000 | 1.000 | 0.000 |
| rewrite_succ **(target)** | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |

## 4. Off-library headline (v4 all-test, n=61) — unchanged, for context

| config | n | pass@1 | pass@3 | pass@5 | forall_inst@5 | rewrite_succ@5 | invalid@1 | novel_verified | rows_only_proposer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v3 unchanged [all-test, n=61] | 61 | 0.096 | 0.096 | 0.096 | 0.000 | 0.000 | 0.904 | 30 | — |
| v3 + v4 both [all-test, n=61] | 61 | 0.777 | 0.828 | 0.828 | 0.000 | 0.000 | 0.223 | 339 | — |

## 5. Honest reading

- **Retrieval is example reuse + light adaptation, not reasoning.** It works on the targets only because the corpus uses consistent hypothesis names within a family (verbatim transfer) and because the ∀-witness is a literal copyable from the goal (numeric adaptation). Given same-family donors, it generalizes *within* a family; it does not compose new proof shapes.
- **Char-n-gram similarity confuses the negation siblings.** `neg_exfalso` stays at pass@5 0.00 for retrieval: its nearest neighbours by char-trigram cosine are *other* negation families (`neg_double_intro`, `neg_or_cases`), whose tactics do not transfer, so the correct same-family donor (`exact absurd hp hnp`, which is in train) is ranked out of the top-5. This is the v1 sibling-confusion problem resurfacing at the retrieval layer — reported, not hidden.
- **Adaptation matters:** compare `retrieval` vs `retrieval-verbatim` — numeric substitution is what lifts `forall_inst` off 0.00.
- **v4 templates remain separate from v3 and v5.** The `v4_templates` and `v3 + v4-tmpl ⊕ retrieval` rows are explicitly labelled ablations, never folded into the v3 planner.
- **LLM pilot:** see `docs/V5_LLM_PILOT_*.md` — gated on an API key.

