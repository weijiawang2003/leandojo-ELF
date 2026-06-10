# V39_06 — Ensemble value, novel-string audit, CIs, seed replication (v39b)

Consolidation pass closing the last open question for continuous flow: does it add any
**verified coverage** AR lacks? Built from persisted per-theorem detail
(`outputs/v39/trackA/detail/*.json`, `ensemble.json`). All aggregates regression-match the
committed v39 numbers exactly (recomputed-from-detail == aggregate path, 0 mismatches).

## 1. Ensemble / union — flow adds **nothing**
Solved on the 24-theorem tier (any verified in frequency-ranked top-10):
`AR 22 · AR@K48 22 · MDLM 22 · FLOW@1 20 · FLOW@2 19 · FLOW@4 15 · FLOW@8 13 · FLOW@16 12`.

| union | pass@10 |
|-------|---------|
| AR (alone) | 0.917 (22/24) |
| AR @ K=48 (2× budget, AR alone) | 0.917 (22/24) |
| AR ∪ FLOW@1 | 0.917 (22/24) |
| AR ∪ FLOW@2 | 0.917 (22/24) |
| AR ∪ MDLM | 0.917 (22/24) |
| AR ∪ MDLM ∪ FLOW@1 | 0.917 (22/24) |
| all-four | 0.917 (22/24) |

**Every union equals AR alone.** FLOW and MDLM each solve a **strict subset** of AR's theorems —
**zero unique solves** for any model. Continuous flow contributes no verified coverage AR lacks.

## 2. AR's two misses — covered by **no one**
AR (and AR@K48) miss exactly `v26w_inter_subset_left_union` and `v28_ord_min_le_right_0`.
- Covered by FLOW@{1,2,4,8,16}? **No.** By MDLM? **No.** By AR at 2× budget (K=48)? **No.**

So the union story is not a budget artifact: doubling AR's samples solves neither miss, and neither
does any flow/MDLM setting. The two misses are genuinely out of reach for all 30M models here.

## 3. Novel-verified string audit — the "discovery" edge was an artifact
The v39 report credited FLOW@1/@2 with 2–3 *novel-verified* tactics (exact string ∉ train). Audited
verbatim (4 unique strings, dedup by theorem+tactic):

| theorem | tactic | found by | verdict |
|---------|--------|----------|---------|
| v29_fs_subset_inter_0 | `exact Finset.subset_inter c4 c5` | AR, AR@K48, MDLM, FLOW@1/2/4 | **truly novel** (edit-dist 4) — but **AR/MDLM find it too** |
| v28_fs_subset_union_left_0 | `apply Finset.subset_union_left` | **AR@K48 only** | truly novel (edit-dist 5) — an **AR** discovery |
| v25_option_some_isSome | `simp [ ]` | FLOW@1/2 | near-variant (edit-dist 2 → `simp []`) |
| v26_logic_imp_self2 | `intro h; exact   h` | FLOW@2 | **trivial: == a train tactic** (extra whitespace) |

**Reading:** the two *genuinely* novel tactics are found by AR/MDLM (or AR-only), not unique to flow.
Flow's *own* "novel" strings are `simp [ ]` (whitespace/empty-list variant of `simp`) and
`intro h; exact   h` (a train tactic with extra spaces — a false novel from exact-string matching).
**Flow makes no genuine out-of-train discovery here.** The earlier novel-count was inflated by
exact-string novelty over normalization-equivalent tactics.

## 4. Wilson 95% CIs (n=24 — wide; aggregate gaps are within noise)
| metric | x/24 | p | Wilson 95% |
|--------|------|---|-----------|
| AR pass@1 | 20 | 0.833 | [0.641, 0.933] |
| AR pass@10 | 22 | 0.917 | [0.742, 0.977] |
| MDLM pass@1 | 21 | 0.875 | [0.690, 0.957] |
| MDLM pass@10 | 22 | 0.917 | [0.742, 0.977] |
| FLOW@1 pass@1 | 13 | 0.542 | [0.351, 0.721] |
| FLOW@1 pass@10 | 20 | 0.833 | [0.641, 0.933] |
| FLOW@16 pass@1 | 7 | 0.292 | [0.149, 0.492] |
| FLOW@16 pass@10 | 12 | 0.500 | [0.314, 0.686] |

AR pass@10 [0.742, 0.977] and FLOW@1 pass@10 [0.641, 0.933] **overlap heavily** → the headline
pass@10 gap is not statistically resolvable at n=24. The *coverage* analysis (§1–2, flow ⊆ AR with
zero unique solves) is the load-bearing evidence, not the point aggregates.

## 5. Seed replication (FLOW headline, seed 3407 vs 4242)
_[Filled on Phase-3 completion — pass@{1,5,10} at steps {1,16} for both seeds + decision-rule outcome.]_

## 6. Verdict update
- **H3 / "flow as a novel-candidate proposer": STRUCK.** Flow covers neither AR miss, has zero unique
  solves, and makes no genuine novel discovery — its diversity is incoherent *and* redundant with AR.
  The v39 recommendation to "keep flow as a 1-step novel-candidate proposer" is **withdrawn**: at this
  scale flow proposes nothing AR/MDLM don't already find.
- The 1-step sampling finding (H4) and the per-token>AR / exact-seq~0 coherence mechanism stand.
