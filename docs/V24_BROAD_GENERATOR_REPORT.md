# V24 broad generator report (residual shape augmentation)

**Mission.** v23 proved the broad-core residual is **generator-bound**: 8
v18 theorems had no verified candidate in the v22 plus_exists top-10, so
no reranker could reach them. v24 tests the implied fix — add small,
lean-verified, core-Lean **shape corpora** for exactly those gaps and
retrain the broad generator (no ranking work, no Mathlib). **Outcome:
5 of the 8 generator-bound failures closed; pass@10 0.833 → 0.938 with
zero category regressions.**

## Research questions — answered

1. **Can small verified shape corpora reduce the 8 no-top10 failures?**
   **Yes — 5 of 8 closed** (no_verify 8 → 3).
2. **Does corpus augmentation beat ranker refresh on broad-core?**
   **Decisively.** v23 (ranking) could not move pass@10 off 0.833; v24
   (corpus) lifts it to **0.938**. The bottleneck was generation, as v23
   predicted.
3. **Which residual categories are true data-shape gaps?** nat_succ,
   list, exists, and one negation shape were closable with a few verified
   examples; **disjunction (or-intro, or-elim) and conjunction
   (nested re-association) were NOT** — they need more shape diversity.
4. **Does targeted augmentation preserve solved categories?** **Yes** —
   under the abstract reranker, **zero theorems regressed** (forall /
   implication / bool / equality_rewrite stay 1.000).

## Headline (v18 broad-core, 48 theorems)

| system | config | p@1 | p@5 | p@10 | MRR | no_verify |
|---|---|---:|---:|---:|---:|---:|
| v22 plus_exists | raw | 0.792 | 0.833 | 0.833 | 0.804 | 8 |
| v22 plus_exists | abstract (headline) | 0.729 | 0.812 | 0.833 | 0.774 | 8 |
| v23 best (raw / hybrid) | — | 0.792 | 0.833 | 0.833 | 0.804 | 8 |
| **v24 broad+residual** | raw | 0.771 | 0.875 | **0.938** | 0.812 | **3** |
| **v24 broad+residual** | **abstract (best)** | **0.792** | **0.917** | **0.938** | **0.851** | **3** |

Training: 3,410 rows (3,247 v22 base + 163 residual), token bi-GRU +
attention (v22 arch, embed 96 / hidden 128), 20 epochs, seed 0, **289 s**
CPU. pass@10 = 0.938 is rerank-invariant (the generator ceiling rose).

### Per-category pass@5 (abstract: v22 → v24)

| category | v22 | v24 | Δ |
|---|---:|---:|---:|
| **negation** | 0.600 | **1.000** | **+0.400** |
| **exists** | 0.750 | **1.000** | **+0.250** |
| **nat_succ** | 0.600 | 0.800 | +0.200 |
| **list** | 0.800 | 1.000 | +0.200 |
| implication / bool / equality_rewrite / forall | 1.000 | 1.000 | 0 |
| conjunction | 0.833 | 0.833 | 0 |
| disjunction | 0.600 | 0.600 | 0 |

## The reranker flipped from harmful to helpful

In v22 the `abstract` reranker **hurt** (it demoted a verified negation
candidate: negation 0.800 → 0.600). In v24 it is the **best** config
(pass@5 0.917) and it **recovers `neg_not_intro`** — the very theorem v23
flagged as ranking-bound-but-feature-unfixable. Why: v24's generator now
emits *grounded, well-formed* candidates (`intro hgoal; exact h (Or.inl
hgoal)`, `exact ⟨n, rfl⟩`, `simp`, `Nat.succ.inj h`), and the grounding-
aware abstract reranker promotes them correctly. **Generation quality is
what makes a reranker safe** — the v22→v24 reranker reversal is the
clearest evidence the v23 "gap is generation, not ranking" call was right.

## The 8 generator-bound rows (raw beam order)

| theorem | category | old fvr | new fvr | verifying candidate |
|---|---|---|---|---|
| `v18_neg_or_left` | negation | None | **0** | `intro hgoal; exact h (Or.inl hgoal)` |
| `v18_list_append_nil` | list | None | **0** | `simp` |
| `v18_nat_zero_add` | nat_succ | None | **2** | `simp` |
| `v18_nat_succ_inj` | nat_succ | None | **3** | `exact Nat.succ.inj h` |
| `v18_exists_intro_eq` | exists | None | **8** | `exact ⟨n, rfl⟩` |
| `v18_and_assoc_one` | conjunction | None | None | still generator-bound |
| `v18_or_inr` | disjunction | None | None | still generator-bound |
| `v18_or_elim_to_common` | disjunction | None | None | still generator-bound |

## Honest residual + regression detail

- **5/8 closed.** The 3 that did not (`and_assoc_one`, `or_inr`,
  `or_elim_to_common`) are disjunction/conjunction shapes; the v24 corpus
  *included* verified `or_intro`/`or_elim`/`conj_reassoc` families but
  5–10 examples each were too few to shift the generator —
  **insufficient shape diversity**, not a missing shape.
- **No category regressed.** Under the abstract reranker the per-theorem
  flip is **+5 / −0** (gains: neg_not_intro, neg_or_left, exists_intro_eq,
  nat_zero_add, list_append_nil). Under `raw` it is +4 / −2: two theorems
  (`neg_not_intro`, `list_singleton_len`) shuffle below rank 5, offset
  within their categories by the closed residuals (net category Δ = 0).
  So the conservative claim is **no pass@5 category regression in either
  config**, and **zero per-theorem regressions under the best (abstract)
  config**. ([`V24_REGRESSION_ANALYSIS.md`](V24_REGRESSION_ANALYSIS.md))

## Targets vs achieved

| target | achieved |
|---|---|
| pass@5 above raw v23 0.833 | **0.917** (abstract) / 0.875 (raw) ✓ |
| pass@10 above raw v23 0.833 | **0.938** ✓ |
| reduce no_verified_top10 from 8 | **3** (−5) ✓ |
| preserve forall / implication / bool = 1.000 | ✓ |
| preserve or improve negation 0.800 | **1.000** (abstract) ✓ |
| avoid new category tradeoffs | ✓ (no category regression) |

## v25 recommendation

5/8 residuals closed → the generator-bound test is **measured and
positive**, so v25 may proceed to **Mathlib tier-C** (the v22/v23 gates
are cleared). The 3 unclosed shapes (disjunction/conjunction) are an
**insufficient-shape-diversity** problem: either widen those families
(more `Or.inl/inr`, or-elim, nested-conjunction variants — the issue is
diversity/volume, not a missing core-Lean tactic) **before** Mathlib, or
let Mathlib's broader tactic coverage subsume them.

## Honesty contract

- v24 changes the **generator** (retrained on verified shapes); it does
  **not** tune rerankers (per the v23 finding). The eval runs the standard
  6 rerank configs; abstract is simply v24's best.
- Every residual-corpus row is **lean-cli verified** (core Lean, no
  Mathlib); **no manual oracle** (candidates are corpus targets, never
  decoder outputs), **no state_after**, **no v10-leakage**.
- v18 leakage-guarded (0 name/triple drops); v18/v22/v23 metrics on disk
  unchanged; v24 publishes at parallel `data/baselines/v24_*` paths.
- **Not full theorem proving** — a 48-theorem core-Lean benchmark,
  directional (disjunction/conjunction are 5–6 theorems each).
