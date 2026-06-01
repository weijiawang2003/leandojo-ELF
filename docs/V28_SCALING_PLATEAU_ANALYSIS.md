# V28 Part 8 — Scaling / Plateau Analysis

_Script: `scripts/analyze_v28_scaling_plateau.py`.
Output: `data/baselines/v28_scaling/report.json`._

Answers the v28 research questions from existing eval artifacts (no Lean run).

## 1. Did more data improve the fresh holdout? — YES

| benchmark | v27 best pass@10 | v28 best pass@10 | Δ |
|-----------|:---:|:---:|:---:|
| v25 held-out | 0.929 | **1.000** | **+0.071** |
| v26 holdout | 0.955 | 0.955 | 0.000 (already saturated) |
| **v27 holdout** | 0.714 | **1.000** | **+0.286** |
| **v28 holdout** (new, 30 thm) | 0.667 | **0.867** | **+0.200** |

The plateau was **data-volume bound**, exactly as the Part-1 audit predicted. Adding
verified sibling shapes (181 → 350 rows; residual families densified) lifted every
fresh holdout that was not already saturated. The v26 holdout was already at the
v27 ceiling (0.955) and stays there.

## 2. Did Set/order keep improving? — YES (and Finset is new)

`v28_general` per-category pass@10 on the v28 holdout: **set 0.889, order 0.889,
finset 0.833** (nat/list/logic 1.000). The polymorphic order rewrite
(`[Preorder]`/`[LinearOrder]`/`[Lattice]`) generalized the order skill beyond Nat,
and the Set residuals (`mem_inter_iff`, `union_subset`) are now solved.

## 3. Did Finset transfer work? — PARTIALLY, and informatively

* **Within the corpus** (theorem-holdout): held-out Finset members reach **0.833** —
  a new category with nontrivial held-out success.
* **Whole-category holdout** (every Finset theorem removed from train): **0.333**.

Finset shares structure with Set but has distinct lemma names
(`Finset.mem_inter` vs `Set.mem_inter_iff`, `[DecidableEq]` binders), so a model that
has *never* seen Finset only partially transfers from Set. Order transfers best
(0.778 whole-category-holdout) because its `≤` shapes overlap Nat. Set is lowest
(0.237) — removing all 84 Set siblings leaves nothing to generalize from.

## 4. Did category balancing help or hurt? — HURT (mild)

pass@10 on the v28 holdout: `general 0.867` > `set_order_heavy 0.833` >
`finset_specialist 0.800` > **`category_balanced 0.700`**. Capping per-category
volume **removes the very sibling density** that drives generalization — the same
lesson as v27 ("balancing harms the gap category"). The unweighted `general` config
wins. Set/order upsampling (`set_order_heavy`) is roughly neutral-to-slightly-down
vs `general` on this holdout.

## 5. Where is the wall now?

Residual buckets for the best model across the v27+v28 holdouts (n = 5 residuals):
`proof_shape (API/arity) 2, syntax/parse 1, multi-step planning 1,
insufficient_shape_diversity 1`.

* **Data/coverage (vocab + shape density): still the dominant regime.** The
  surviving misses are single-sibling shapes — Finset projection
  (`Finset.mem_of_mem_inter_left` vs `.1`), `PartialOrder` antisymm
  (`le_antisymm h1 h2`, 1 sibling), `comp_assoc` under a renamed binder, a
  `union_comm` elim variant. Each would be fixed by **more siblings**, exactly the
  v28 lever.
* **Multi-step planning: 1 of 5 — not yet the bottleneck.**
* **Architecture: not implicated** — the model proposes the right neighbourhood; it
  needs denser exemplars, not a bigger network (the small seq2seq's val-exact rose
  0.235 → 0.263 with more data, i.e. it is still absorbing signal, not saturating).

**LeanDojo next-state (`state_after`) supervision: still premature.** With only 1/5
residuals being multi-step, single-tactic coverage is not exhausted; proof-state
supervision would not help a model that already lands in the right neighbourhood for
single-tactic goals. The verdict (`leandojo_next_state_relevant = false`) is
unchanged from v27.

## Conclusion

v28 confirms the data-scaling hypothesis: **the fresh-holdout plateau was
data-volume bound, and more verified sibling shapes broke it** (v27 holdout
0.714 → 1.000; new v28 holdout 0.867), while broad-core stayed bit-identical. The
next wall is still **coverage/vocabulary**, not architecture or proof-state
supervision — so v29 should keep scaling single-tactic shapes into more categories
and densifying single-sibling residuals.
