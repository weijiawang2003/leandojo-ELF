# V29 — Part 9: Density Law / Scaling Analysis

_`scripts/analyze_v29_density_law.py` → `data/baselines/v29_density_law/report.json`.
No Lean run — joins the Part-7 eval, the dataset summary, and the Part-1 audit._

## RQ1 — does within-family sibling density predict held-out success? **Yes.**

Two independent measurements agree:

**(a) Cross-family effective-density law (Part 1, 507 held-out evaluations):**

| training siblings | pass@10 |
|---:|---:|
| 0 | 0.684 |
| 1–3 | 0.829 |
| 4–6 | 0.944 |

Monotone; reaches ≥ 0.9 at **~4 siblings**.

**(b) Clean within-difficulty comparison (the v29 causal probe).** The *same hard
lemma-binding families* (set/finset projection · subset · membership) evaluated at
two training densities:

| condition | training siblings | pass@10 | n |
|---|---:|---:|---:|
| whole-category transfer (finset) | **0** | **0.162** | 37 |
| whole-category transfer (set) | **0** | **0.263** | 38 |
| `family_density_holdout` (v29_general) | **~6** | **0.70** | 20 |

Same families, density 0 → ~6 lifts pass@10 **3–4×** (0.16–0.26 → 0.70). This is the
density law measured causally, with family difficulty held fixed.

### A confound to flag honestly

The *raw* `family_density_holdout` (0.824) vs `low_density_holdout` (1.000) contrast
looks **backwards** — but it is confounded: `low_density` families
(`add_zero`, `append_nil`, `and_symm`, `comp_app`) close by a **universal tactic**
(`simp`/`omega`/`rfl`/`tauto`) and so pass at *any* density, while `family_density`
holds out the *hard* lemma-binding families. The lesson is itself a finding:
**density is decisive for families that need a specific lemma/projection bound, and
irrelevant for families closed by a universal tactic.** The clean comparison above
controls for this.

## RQ2 — can densifying sparse residual families beat v28's 0.867? **Yes.**

v28 fresh holdout 0.867 → **0.933** (`v29_general`) / **0.967**
(`v29_set_finset_order_heavy`). The v28 residuals `comp_assoc` and `antisymm`
(1-sibling in v28) are **fixed** after densification (9 siblings each).

## RQ3 — does whole-category transfer improve with more sibling families? **No.**

set 0.237→0.292, finset 0.333→0.136, order 0.778→0.556 (mixed/worse; the v29 transfer
test sets are also larger). Cross-category transfer stays weak — **density lives
within a family, not across a category.** Each new category still needs its own
siblings.

## RQ4 — is unweighted general the best default? **Yes, with a caveat.**

`v29_category_balanced` (negative control) ≤ `v29_general` on 5/7 benches (v28 0.900
vs 0.933, v29 0.900 vs 1.000, family_density 0.765 vs 0.824) → **capping/balancing is
still unhelpful.** But *targeted upsampling* (not capping) of the weak structured
categories — `v29_set_finset_order_heavy` — gives a small extra lift (v27 1.000,
v28 0.967, family_density 0.853). So: unweighted general is the safe default;
2× upsampling of set/finset/order is a strict improvement; balancing is not.

## RQ5 — are remaining failures data-bound or proof-state-bound? **Data-bound.**

8 residuals of the best v29 model on the fresh + density holdouts: 6
`lemma_vocabulary`, 2 `api_syntax`, **0 multi-step**. `leandojo_next_state_relevant:
false`. The hardest residuals are the `_3` (`u,v` / `w,hw` surface-token) members of
the projection/membership families — density lifted them from ~0.25 to 0.70–0.82 but
the last-mile binding under unusual identifiers still misses. **Still a coverage/data
regime; LeanDojo next-state supervision remains premature.**

## Density vs breadth

v28 added breadth (new categories) and got within-family gains only where it also
added siblings; v29 added density to existing families and moved the fresh holdouts
(+0.07 to +0.10) and the hard families (+0.4 absolute). **Density beats breadth** for
this small-seq2seq single-tactic regime — until a family is dense (~4–6 siblings),
adding a *new* category barely helps its held-out members.
