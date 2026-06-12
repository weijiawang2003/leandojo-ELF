# V42 Phase 4 — Conditional LPSF next steps: H16, grounder upgrade, H17

All verification: sound bisect-batched mode; all generation: `.venv-gpu` (deterministic).

## H16 — the H14 confound resolver: head-only vs typed plans

Same eval code path for both representations (`scripts/v42_h16_eval.py`, pass@4 exact-seq on the
corpus dev split, stratified by gold plan length; 10M models, matched 1e8-token budgets).

| Cell (L=1 / L=2 / L=3+ exact-seq) | L=1 | L=2 | L=3+ |
|---|---|---|---|
| head-only AR (3407) | 0.594 | 0.239 | 0.019 |
| head-only flow (3407) | 0.477 | **0.142** | 0.000 |
| head-only flow (4242) | 0.484 | **0.132** | 0.000 |
| typed AR (3407) | 0.397 | 0.147 | 0.020 |
| typed flow (3407) | 0.032 | **0.005** | 0.000 |
| typed flow (4242) | 0.052 | **0.000** | 0.000 |

**flow/AR ratio at L=2: head-only 0.596 / 0.553 (seeds 3407/4242) — both ≥ 0.4; typed 0.034 /
0.000 — both < 0.1.** Pre-registered verdict: **H16 SUPPORTED (both seeds)** — the H14 collapse
was **tokenization** (multi-token typed steps reinstate the coherence gap), not a failure of
plan-level abstraction; v40's head-plan ratio 0.643 was real. (Honest note: at L=3+ flow is 0.000
even head-only, vs AR's own near-zero 0.019 — the abstraction win is at L≤2.)
**LPSF-v2 design consequence: coarse, head-mostly plans; argument selection belongs to the grounder.**

## Grounder upgrade pass — beam-2

True beam search (width 2, sum-logprob, deterministic) replacing near-greedy decode:
**ceiling 0.267 → 0.311 (14/45)**; corrupted-plan 0.044 (causality holds).
Still **< 0.35** ⇒ the weak-grounder conditionality on H12/H13 readings is **not lifted**; the
premise-selection wall stands (the grounder lacks retrieval, beam can't fix lemma knowledge).

## H17 — H13 at three seeds (tier-dev, sound, mode-symmetric)

plan-flow seeds {3407, 4242, 7331} (7331 trained tonight, v41 recipe verbatim); uniques over
iso-{direct-AR 20 ∪ plan-AR 20} = base-25:

| Seed | pass@10 | unique verified solves over base | gain |
|---|---|---|---|
| 3407 | 20/45 | `MulRingNorm.isPowMul`, `sup_himp_self_left` | **+2** |
| 4242 | 15/45 | `sdiff_le_iff'` | +1 |
| 7331 | 18/45 | `MulRingNorm.isPowMul`, `sup_himp_self_left` | **+2** |

**Pre-registered criterion (union gain ≥ +2 in ≥ 2/3 seeds): MET → H13 PASSES at three seeds**,
and per the registration V43 = full LPSF scale-up.

**The audit caveat travels with the verdict:** seed 7331's uniques are the same two theorems as
3407, solved again by one-step `simp` variants (`simp [hn]`, `simp [le_himp_iff]`, bare `simp`)
from `simp(LEMMA)`/`simp(NONE)` plans — the diversity-toward-simplicity mechanism of
`docs/V42_03_UNIQUES_AUDIT.md`, not multi-step strategy. A trivial **simp-baseline control**
(append bare `simp` to every source's candidate list) would capture most of these gains; V43 must
include it before any LPSF scale-up claim is bankable.

## V43 recommendation (from the tally, no middle narrative)

H13 passes its 3-seed bar ⇒ **V43 = LPSF scale-up**, but the audit defines the three controls
that decide whether the bet is real:
1. **Premise-selection (retrieval) grounder** — the 0.311 beam ceiling says lemma knowledge, not
   search, is the wall. Falsifiable: if flow's union gain shrinks/inverts as the grounder
   strengthens, the "diversity" value was an artifact of grounder weakness (tonight's prediction).
2. **simp-baseline control** — every union table must include {source ∪ bare-`simp`} columns; flow
   only earns credit for gains the trivial baseline doesn't capture.
3. **Coarse plan representation** (H16): head-mostly plans, ≤2-step focus, typed args dropped or
   delegated to the grounder.
MDLM remains the discrete token-level substrate (v40 H10 verbatim-sound: AR∪MDLM 27/44).
