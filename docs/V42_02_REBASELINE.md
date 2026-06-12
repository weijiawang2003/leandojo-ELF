# V42 Phase 2 — Project-wide re-baseline (every number, old → new, with mode provenance)

All "new" numbers: `verify_mode = bisect-batched` (proven == one-per-file isolation, see
`docs/V42_01_VERIFIER_FIX.md` + `tests/test_verifier_poison.py`), fixed `_render`, fresh
`VerdictCache`. v41 plan rows are re-derived from **GPU-faithful regenerated candidates**
(`outputs/v42/candidates/`, `.venv-gpu`, per-theorem seeded generation proven deterministic
44/44 run-vs-run — i.e. these ARE v41's candidates; an initial CPU-venv regen could not
reproduce them because torch Generator streams differ by device, and is quarantined in
`candidates_cpu/` + `*_cpugen.json` as a recorded pitfall).

## 1. The old→new table

| Cell (pass@10 base) | OLD (mode) | NEW (bisect) | Verdict change |
|---|---|---|---|
| v40 dev direct-AR | 19/45 = 0.422 (batched-legacy) | **20/45 = 0.444** | +1: `Mathlib.Tactic.Ring.div_congr` via `subst_vars; rfl` — an attribution-shift victim (sat right after `concaveOn_id`'s multi-line block); singleton-confirmed |
| v40 dev MDLM | 16/45 = 0.356 (batched-legacy) | **16/45 = 0.356** | unchanged (2 candidate-level recoveries on already-solved `concaveOn_id`) |
| v40 dev flow_s1 | 0/45 (batched-legacy) | **0/45** | **unchanged — H6 survives** (0 candidate flips) |
| v40 final direct-AR | 20/44 = 0.455 (batched-legacy) | **20/44** | unchanged, 0 flips |
| v40 final MDLM | 19/44 = 0.432 (batched-legacy) | **19/44** | unchanged, 0 flips |
| v40 final flow_s1 | 1/44 = 0.023 (degenerate `rw []`) | **1/44** | unchanged, 0 flips |
| v40 final AR∪MDLM | 27/44 (+7 over AR) | **27/44 (+7)** | **verbatim** |
| v40 dev AR∪MDLM | 20/45 (+1 over AR) | **21/45 (+1)** | +1 from the AR recovery; MDLM dev-unique stays 1 (`MulRingNorm.isPowMul`) |
| v41 dev plan-AR | 20/45 = 0.444 (isolated, v41 candidates) | **20/45 = 0.444** | reproduced exactly (GPU determinism) |
| v41 dev plan-flow 3407 | 20/45 = 0.444 (isolated) | **20/45** | reproduced exactly |
| v41 dev plan-flow 4242 | 15/45 = 0.333 (isolated) | **15/45** | reproduced exactly |
| v41 dev plan-MDLM | 12/45 = 0.267 (isolated) | **12/45** | reproduced exactly |
| v41 final plan-AR | 17/44 = 0.386 (batched, clean) | **17/44** | unchanged |
| v41 final plan-flow 3407 | 18/44 = 0.409 (batched) | **20/44 = 0.455** | **+2 sound recoveries** — v41's final batched run under-counted flow |
| v41 final plan-flow 4242 | 15/44 = 0.341 (batched) | **15/44** | unchanged |
| v41 final plan-MDLM | 12/44 = 0.273 (batched) | **12/44** | unchanged |
| v41 grounder ceiling | 0.267 (12/45) (batched) | **0.267 (12/45)** | verbatim; corrupted-plan 0.022 → 0.067, still ≪ ceiling ⇒ **causality holds** |
| v39 24-tier AR / MDLM / FLOW@1 | .917 / .917 / .833 (batched-legacy) | **22/24, 22/24, 20/24 — identical** | **zero candidate flips; v39 headline confirmed verbatim** |

The infamous v41 *poisoned* intermediates (plan-AR 0.089, plan-flow 0.000/0.022 batched on
tier-dev) are explained: tier-dev contains `concaveOn_id` (the only multi-line statement →
attribution shift) and garbage-heavy chunks (timeout + maxErrors classes); tier-final contains
none of these, which is why it was clean. See V42_01 §1.

## 2. Re-derived hypothesis verdicts

- **H6 (v40, flow whole-proof "0 verified"): SURVIVES.** flow_s1 = 0/45 dev, 1/44 final with
  zero candidate flips under sound verification. The retraction rule (isolated flow ≥3 on either
  tier) is not met. v40's framing stands; no doc retraction needed.
- **H10 (v40, MDLM≈AR + complementarity): SURVIVES verbatim on tier-final** (AR 20, MDLM 19,
  union 27 = +7) — the productionizable ensemble claim's numbers are sound. Tier-dev union
  becomes 21 (+1 over the new AR 20); the dev-vs-final union asymmetry noted in the v40 review
  stands.
- **H11 (v41, planning ≥ direct +1 on dev): now FAILS its criterion** — mode-symmetric, plan-AR
  20 vs direct-AR **20** (v41's +1 was an artifact of comparing isolated plan-AR against the
  under-counted batched direct-AR 19). Final stays 17 vs 20 (−3). Verdict: **planning is
  exactly tied with direct generation on dev and behind on final** — the "marginal support"
  language is retracted in favor of "≈tied".
- **H12 (flow ≥ 0.8 × plan-AR, both seeds): BORDERLINE, unchanged** — dev ratios 1.00 (3407) /
  **0.75** (4242); final 1.18 / 0.88. Seed-4242-dev still misses by one notch; tier-final now
  *favors* flow (plan-flow-3407 20 > plan-AR 17).
- **H13 (flow union gains): structure unchanged, now fully sound + mode-symmetric.**
  Base = {direct-AR ∪ plan-AR} (iso): dev 25, final 25. Flow uniques: seed 3407 **+2 dev
  (`MulRingNorm.isPowMul`, `sup_himp_self_left`) / +3 final (`Rep.ρ_inv_self_apply`,
  `codisjoint_inf_right`, `upperBounds_closure`) → PASS**; seed 4242 **+1 dev (`sdiff_le_iff'`)
  / +2 final → FAIL on dev** (needs ≥2). plan-MDLM: 0 uniques both tiers. **Two-seed bar still
  not met; the gains themselves are genuine** — the "0/6 recheck" is now a committed artifact
  (`outputs/v42/rebase/v41_uniques_directAR_recheck.json`): direct-AR (sound, full top-10 sets)
  solves **0 of the 6** v41-claimed unique theorems, old AND new mode.
- **Exit-rule status: unchanged.** H12 borderline-pass + H13 single-seed-pass + ceiling 0.267
  (< 0.35, fallback leg active) ⇒ the v41 exit rule still does **not** fire; conditionality
  ("under a weak grounder") still applies.
- **v39 spot audit: confirmed, zero flips** (`v39_24tier_spot_v42iso.json`).

## 3. Verification budget (cap 3.5 h)

Lean wall-clock spent on re-baselining ≈ **4.3 h** (v40 six cells ≈ 2.9 h — flow's garbage
candidates dominate: 58 min for dev flow_s1 alone; v41 eight cells ≈ 54 min; v39 audit ≈ 6 min;
ceiling ≈ 5 min). The cap was exceeded by ~0.8 h **on priority items 1–5 only**; the optional
priority-6 items (v40 flow_s16 re-verify, iso-vs-iso reproducibility control) were **dropped —
NOT RE-BASELINED** (visible debt). The agreement validation (P1.4) ran in addition.

## 4. Mode provenance

Every `outputs/v42/rebase/*.json` carries `verify_mode` + verifier git SHA. v41 plan rows:
candidates from `outputs/v42/candidates/*.json` (GPU, deterministic); per-candidate verdicts
persisted in each rebase file (`topk[].verified_new`), so the P3 uniques audit reads plans +
proofs + verdicts straight from committed artifacts.
