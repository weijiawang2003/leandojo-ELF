# Mini-ELF v27 — Data-Scaling Analysis (Part 8)

Source: `scripts/analyze_v27_remaining_failures.py` →
`data/baselines/v27_data_scaling/report.json`, plus the Set/order category-holdout
transfer probes (`data/baselines/v27_{set,order}_transfer/`).

## Q1 — Does scaling verified Mathlib shape diversity keep improving the specialist?

**Yes, for the gap categories.** Adding 181 verified v27 rows (Set 53, order 40, …)
to the v26 pool:

| Benchmark | v26 best | v27 best | Δ |
|-----------|----------|----------|---|
| v25 held-out p@10 | 0.929 | **1.000** (cat_balanced) | +0.071 |
| v26 held-out p@10 | 0.909 | **0.955** (set_heavy) | +0.046 |
| v26 held-out **Set** p@10 | 0.75 | **1.00** (set_heavy) | +0.25 |
| v27 fresh holdout p@10 | 0.714 (v26_widened) | 0.714 | 0.000 |

The established benchmarks improve; the *fresh, novel-shape* holdout plateaus
(0.714) — diminishing returns appear on genuinely new shapes the corpus does not
yet cover (see Q-failures).

## Q3 — Can Set pass@10 approach 1.0 with moderate widening?

**Yes.** Two complementary results:
- **With Set training:** `v27_set_heavy` (Set rows upsampled 2×) reaches **Set
  pass@10 = 1.00** on the v26 held-out Set residual (was 0.75). The last residual
  `set_inter_comm_subset` is now solved.
- **Pure cross-category transfer (0 Set rows in training):** a model trained with
  the *entire Set category held out* still reaches **Set pass@10 = 0.75** on 16
  held-out Set theorems — Set is substantially reachable from generic
  `intro x h; exact …` patterns, and the explicit Set corpus closes the rest.

## order / ≤

- **With training:** order pass@10 = **1.00** (v27 holdout).
- **Pure transfer (0 order rows):** **0.90** on 10 held-out order theorems
  (solved by `omega` / `simp` / `Nat.le_*`). order is the easiest tier — robustly
  reachable. v27 makes it a documented first-class category (v26 folded it under
  `nat`).

## Q — Is category balancing helpful or harmful?

**Harmful for the gap category.** `v27_category_balanced` (per-category cap) hit
1.00 on v25-heldout but **regressed Set on v26-holdout to 0.50** (vs 0.75 widened,
1.00 set_heavy). Equal weighting starves the category that needs the most signal.
The winning recipe is the opposite — **upweight the weak category** (`set_heavy`).

## Q — Does the specialist still beat co-training?

**Decisively, everywhere.** v27_set_heavy/widened vs v25_aug (co-trained):

| Bench | specialist p@10 | co-train p@10 |
|-------|-----------------|---------------|
| v25 held-out | 0.929–1.000 | 0.786 |
| v26 held-out | 0.955 | 0.636 |
| v27 holdout | 0.714 | 0.429 |

And the specialist+router preserves broad-core exactly (0.938/0.958), which
co-training cannot (v25 regressed it). Specialist+router remains the right design.

## Q — What are the remaining failures, and what would they need?

Best-model (v27_widened) residuals classify as **2 lemma-vocabulary + 3
proof-shape (API/arity)** — *not* environment or planning failures. The two
hardest fresh Set shapes:
- `x ∈ s ∩ t ↔ x ∈ s ∧ x ∈ t` (`mem_inter_iff`) — needs the membership-iff
  rewrite / `Iff.rfl` in the right beam slot;
- `s ⊆ u → t ⊆ u → s ∪ t ⊆ u` (`union_subset`) — needs union elimination
  (`Set.union_subset` / `hx.elim`), a 2-hypothesis shape.

These are **shape/vocabulary** gaps, addressable with more verified rows of those
exact shapes — *not* yet a planning wall. The character-level beam reaches the
right tactic family but mis-ranks or mis-spells the specific lemma.

## Are failures now likely to require LeanDojo next-state supervision?

**Not yet.** Every residual is a single-tactic shape the model almost produces;
none requires intermediate proof states. The next lever is still **more verified
single-tactic shape diversity** (the v27 recipe), with multi-step / `state_after`
supervision deferred until single-tactic coverage saturates — which it has not, on
the fresh-shape holdout (0.714).

## Plateau diagnosis

The v27 *fresh-holdout* plateau (0.714) is **data-coverage-bound, not
architecture-bound**: identical ~0.5 M-param models reach 0.955 on v26-holdout and
1.0 on v25-heldout — capacity is ample. The fresh holdout simply contains shapes
(`mem_inter_iff`, `union_subset`) under-represented in training. More targeted
verified rows of those shapes is the predicted fix (v28).
