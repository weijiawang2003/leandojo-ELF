# V42 — Verifier soundness, project-wide re-baseline, conditional LPSF next steps

**Date:** 2026-06-12 (overnight) · **Branch:** `v42-verifier-audit` off `v41-lpsf` · RTX 4080.
**Mission:** v41 caught the batched verifier under-reporting; nothing scales until the measurement
layer is trusted. Tonight: fix it, prove the fix, re-measure every v39–v41 verified claim, audit
the v41 uniques, then run the conditional LPSF follow-ups.

## 1. The fix — four defect classes, not one (and not false-negatives-only)

The brief's premise ("sound-but-incomplete — false negatives only") was **wrong**. Ground-truthing
every verdict flip against singleton compiles exposed **four** classes
(`docs/V42_01_VERIFIER_FIX.md`):

1. **Chunk timeout** — one 300 s timeout per 80-candidate file; confirm-loop repacking demotes en
   masse, permanently (the v41 "did not converge" signature). False negatives.
2. **Parse desync** — parse-broken candidates skip/garble later declarations; the v27
   sentinel+rescue covered only the unterminated-comment/string subclass. Both directions.
3. **Attribution shift (new)** — a multi-line statement was bookkept as ONE line, shifting every
   later range; `concaveOn_id` (tier-dev's only multi-line statement, 10 consecutive candidates)
   silently corrupted every v40/v41 tier-dev batch — and tier-final has none, which is exactly why
   v41 saw "dev poisoned, final clean". **Produced live false POSITIVES** (garbage "verified") and
   false negatives.
4. **maxErrors flood (new)** — Lean aborts after 100 diagnostics; everything after the abort line
   was scored as silent false success (22 token-salad "passes" in one v40 flow chunk).

**Fix:** exact physical-line bookkeeping + `verify_many_bisect` — verdicts accepted only from
parse-clean, non-aborted, normally-exited compiles, parse-suspects quarantined to singletons —
**provably equal to one-per-file isolation**; `-DmaxErrors=100000`; abnormal-exit/PANIC detection;
persistent trusted-verdict cache. **Proof:** 7 regression tests (old code fails the reproducers);
**agreement 102/102 = 100%** vs isolation on stratified real candidates (bisect also 1.6× faster
there); the live FP chunk re-checks to 0/22 matching singletons. The fix itself was caught wrong
twice by flip-ground-truthing — the protocol (never believe a flip un-isolated) is the night's
reusable lesson. Mode provenance (`verify_mode` + SHA) is now mandatory in every artifact.

A fifth pitfall closed: re-generation must use the training device's RNG stream — a CPU-venv regen
silently produced different candidates (0/44 overlap); on `.venv-gpu` generation is **deterministic
44/44**, so the regenerated v41 candidates (now persisted with their plans) ARE v41's.

## 2. Re-baseline — what survived, what changed (`docs/V42_02_REBASELINE.md`)

**Survives verbatim (the reassuring bulk):**
- **v39 24-tier headline**: AR 22/24, MDLM 22/24, FLOW@1 20/24 — zero candidate flips.
- **v40 H6**: flow whole-proof **0/45 dev, 1/44 final**, zero flips — the central flow negative is
  NOT a verifier artifact.
- **v40 H10**: final AR 20/44, MDLM 19/44, **AR∪MDLM 27/44 (+7)** — verbatim.
- **v41 e2e**: all dev cells reproduce exactly (plan-AR 20, flow 20/15, MDLM 12 of 45); final
  plan-AR 17, flow-4242 15, MDLM 12 unchanged.
- **v41 grounder ceiling 0.267 + causality** — verbatim.

**Changes (3 numbers, 1 verdict):**
- v40 dev direct-AR **19 → 20**/45 (attribution-shift victim `Mathlib.Tactic.Ring.div_congr`,
  genuine `subst_vars; rfl`; singleton-confirmed). Dev AR∪MDLM 20 → 21.
- v41 final plan-flow-3407 **18 → 20**/44 (+2 sound recoveries) — tier-final now *favors* flow
  over plan-AR (1.18×).
- **H11 retracted**: plan-AR 20 vs direct-AR 20 — v41's "+1 for planning" compared against the
  under-counted base. Planning is exactly **tied** on dev, −3 on final.
- The v41 "0/6 recheck" prose claim is now a committed artifact (direct-AR solves 0/6, old and new
  mode: `outputs/v42/rebase/v41_uniques_directAR_recheck.json`).

**Budget honesty:** the 3.5 h verify cap was exceeded (~4.3 h) on priority items 1–5; the optional
priority-6 items (v40 flow_s16, iso-vs-iso control) are **NOT RE-BASELINED** (visible debt).

## 3. The uniques audit (`docs/V42_03_UNIQUES_AUDIT.md`) — the night's main verdict change

Reproduce-rate 8/8 (deterministic generation). **Every v41 unique solve is a one-step `simp`
variant** (bare `simp` ×4; `simp [one-or-two lemmas]` otherwise) from `simp(NONE)`/`simp(LEMMA)`
plans. Mechanism, now sharp: **plan-AR mode-collapses to gold-shaped multi-step plans that the
premise-selection-limited grounder cannot fill** (it emits junk-arg `simp [, ]`), while flow's
low-fidelity short plans require zero grounding decisions. **The "strategic diversity" narrative is
refuted; flow's H13 value is diversity-toward-simplicity under a weak grounder** — real, sound,
verified union gains, with a falsifiable expiry condition (a strong grounder should shrink them).

## 4. Phase 4 verdicts (`docs/V42_04_LPSF_NEXT.md`)

- **H16 SUPPORTED (both seeds):** head-only plans give flow/AR exact-seq ratio at L=2 of
  **0.596 / 0.553** vs typed **0.034 / 0.000** — H14's collapse was **tokenization**, not
  abstraction; v40's 0.643 was real. LPSF-v2 ⇒ coarse head-mostly plans.
- **Grounder beam-2:** ceiling 0.267 → **0.311**, still < 0.35 ⇒ weak-grounder conditionality
  stays; the wall is lemma knowledge (retrieval), not search.
- **H17 PASSES its pre-registered bar:** union gains 3407 **+2**, 7331 **+2**, 4242 +1 ⇒ ≥+2 in
  2/3 seeds — **H13 finally clears at three seeds** (tier-dev; tier-final reserved). Caveat
  travels: 7331's uniques are the same two theorems, again 1-step simp variants.

## 5. Project-level conclusions after re-baselining

1. All major **negative** results of v35–v41 stand under sound measurement (token/whole-proof flow
   is genuinely ~zero; the verifier was not the story).
2. The **positive** discrete results stand verbatim (v39 parity; AR∪MDLM 27/44 ensemble).
3. v41's LPSF positive **survives numerically and now passes its 3-seed bar, but its narrative is
   corrected**: not strategy diversity — simp-simplicity diversity under a weak grounder.
4. The measurement layer is now trusted: bisect-batched == isolation (proven + 102/102), mode
   provenance everywhere, candidates+plans persisted, generation deterministic.

## 6. V43 recommendation (from the tally)

**LPSF scale-up, gated by three controls** that tonight's audit makes mandatory:
(1) **premise-selection grounder** (the 0.311 wall is lemma knowledge); (2) **simp-baseline
control** in every union table (bare-`simp` captures most current gains); (3) **coarse head-mostly
plans** (H16). If flow's union gain does not survive controls (1)+(2), the LPSF bet closes with
mechanism; if it does, scale. MDLM remains the discrete substrate either way.

**Artifacts:** `outputs/v42/{rebase,candidates,agreement.json,h16_stratified.json,vcache.jsonl}`;
docs `V42_00`–`V42_04`, this report; correction appendices in V39/V40/V41 final reports +
V41_02/V41_04 pointers; paper §2.x methods subsection + §4d addendum. Tests:
`tests/test_verifier_poison.py` (7). All pushed to `v42-verifier-audit`.
