# V42 Phase 3 — The v41 uniques: persisted, reproduced, audited verbatim

**Inputs:** GPU-faithful regenerated candidates (`outputs/v42/candidates/`, plans + grounded
proofs persisted — fixing v41's gap), per-candidate sound verdicts (`outputs/v42/rebase/`).
**Reproduce-rate: 8/8 unique (theorem, seed, tier) solves reproduce** — generation is
deterministic on the GPU env (44/44 identical plan-lists run-vs-run), so these ARE v41's solves,
now soundly verified and committed.

## 1. Verbatim audit (every unique verified proof vs gold, with its plan)

| Tier / seed | Theorem | Gold proof | Flow's verified unique proof(s) | Plan | Class |
|---|---|---|---|---|---|
| dev/3407 | `MulRingNorm.isPowMul` | `cases n; omega; rw [map_pow]` | `simp` | `simp(NONE)` (1×/24) | **bare-simp lottery** |
| dev/3407 | `sup_himp_self_left` | `rw [sup_himp_distrib, himp_self, top_inf_eq]` | `simp [le_himp_iff, inf_comm]`; `simp [le_himp_iff]` | `simp(LEMMA[,LEMMA])` | alternative-lemma simp (1-step) |
| dev/4242 | `sdiff_le_iff'` | `rw [sdiff_le_iff, sup_comm]` | `simp [sup_comm]` (+1 simp-only variant) | `simp(LEMMA)` | gold-adjacent simp compression (`sup_comm` ∈ gold) |
| final/3407+4242 | `Rep.ρ_inv_self_apply` | `rw [← map_mul, inv_mul_cancel, map_one, Module.End.one_apply]` | `simp [mul_assoc]` | `simp(LEMMA)` (2–4×/24) | alternative-lemma simp (1-step) |
| final/3407 | `codisjoint_inf_right` | `simp only [codisjoint_iff, sup_inf_left, inf_eq_top_iff]` | `simp` | `simp(NONE)` (3×/24) | **bare-simp lottery** |
| final/3407+4242 | `upperBounds_closure` | `simp_rw [mem_upperBounds_iff_subset_Iic, isClosed_Iic.closure_subset_iff]` | `simp` | `simp(NONE)` (2×/24) | **bare-simp lottery** |

**Verdict by the v40 audit standard: the "strategic diversity" narrative is REFUTED.** Every
unique solve is a one-step `simp` (bare, or with 1–2 lemmas); none is a multi-step alternative
strategy. The union gains are **real, sound, verified** — but they are simp-variants, not
strategies.

## 2. The mechanism (sharper than v41 knew)

Why does flow get these and {direct-AR ∪ plan-AR} doesn't?

- **plan-AR mode-collapses to gold-shaped plans.** On `codisjoint_inf_right` its 24 plans are
  14× `simp_rw(LEMMA,LEMMA,LEMMA)` + rw-chains — faithful imitations of the gold plan shape.
  Grounding them requires the grounder to produce the *right lemma names*, which it can't
  (the 0.267 premise-selection ceiling); plan-AR even proposed `simp(LEMMA,LEMMA)` on
  `upperBounds_closure` and the grounder filled **junk/empty args** (`simp [, ]` — malformed).
- **plan-flow's plans are low-fidelity and shorter** (H14: exact-seq ≈ 0): it puts real
  probability mass on `simp(NONE)` / `simp(LEMMA)` — plans requiring **zero or one grounding
  decision**. Where bare `simp` happens to close the goal, flow wins by having asked for nothing.

**Honest reframing of flow's H13 value: "low-fidelity plans are accidentally well-matched to a
weak grounder" — diversity toward *simplicity*, not strategy.** Falsifiable consequence for V43:
as the grounder improves (premise selection), plan-AR's faithful plans should ground better and
flow's unique-solve advantage should shrink or invert. If flow's advantage survives a strong
grounder, the diversity story revives; tonight's data says don't bet on it.

(Trivial-baseline note: a `simp`-only baseline would solve 4 of the 6 unique theorems by
construction. The pipeline's value over that baseline is concentrated in the lemma-carrying
variants, i.e. 2 theorems.)

## 3. Artifacts

- Candidates + plans: `outputs/v42/candidates/tier_{dev,final}_plan_*.json`
- Per-candidate sound verdicts: `outputs/v42/rebase/tier_*_plan_*_v42iso.json`
- Direct-AR 0/6 recheck: `outputs/v42/rebase/v41_uniques_directAR_recheck.json`
- `scripts/v41_e2e.py --detail-dir` fixed (persists plans/proofs/ranked/vmap + verify_mode) —
  no future run can lose its candidates.
