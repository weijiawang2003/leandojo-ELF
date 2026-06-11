# V41 Phase 0 — Setup + carry-over fixes

**Branch:** `v41-lpsf` (off `v40-elf-objects` @ ccf3b6d) · RTX 4080 16GB · seed 3407 (+4242 for flow).

## Carry-over fixes (review-flagged on v40)
1. **Remote fast-forward:** `v39-scale-matrix` was already fully pushed (local == origin == 6edca8b2) — no-op.
2. **v40 doc fixes** (committed to `v40-elf-objects`, inherited here): (a) H9 wording → "rules out
   lattice-spacing; pretrained semantic geometry untested" + §4 placeholder filled; (b) tier-dev union
   **+1** shown next to tier-final **+7**, "productionize now" → "needs seed-2 + both-tier stability";
   (c) flow "0 verified" → **0/45 tier-dev, 1/44 tier-final (a degenerate `rw []`)**; (d) "4 genuine
   multi-tactic proofs" → "4 theorems whose *gold* is multi-tactic solved"; (e) flow's H6 dev curve is
   **non-monotone** — ratio **0.289 at the 25% checkpoint** (would have passed) then collapses; H7's
   4× is **8 vs 2 raw hits, Fisher p≈0.054**; (f) headplan manifest committed.
3. Verifier multi-tactic smoke PASS; whole-proof corpus confirmed (sha `5db8fb16`, 45,820 train).

## What LPSF changes
Flow stops generating tokens (refuted v35–v40) and generates **compact proof plans** — the one level
with a positive v40 signal (plan-probe flow/AR ratio 0.643). A shared grounder expands plans to tactics;
Lean verifies end-to-end. The bet under test: flow's *verified strategic diversity* adds union/pass@k
coverage AR misses (H13). Pre-registered exit rule: H12 ∧ H13 both fail ⇒ flow thread closed
project-wide.
