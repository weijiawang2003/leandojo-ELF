# V41 Phase 2 — Grounder + ceiling + causality control (the keystone)

**Grounder:** AR seq2seq, 42.2M (30M preset × 32k vocab), input `statement PLAN: <plan> STEP: <step>
PREV: <grounded tactics>`, greedy output tactic. Trained 1.2e8 tokens (~4.5 epochs), 738 s. Standalone
dev tactic exact-seq **0.177**, per-token 0.554.

## Ceiling (gold-plan + grounder, greedy pass@1) — **0.267 (12/45)**
Ground the GOLD plans of tier-dev → verify. This is the **pipeline upper bound** under greedy grounding.
**0.267 < direct-AR's tier-dev pass@10 (0.422)** and **< the 0.35 bar** → the **grounder, not the plan
generator, is the bottleneck.** Failure mode (from samples): no-arg tactics ground fine (`simp`,
`simp [div_eq_mul_inv]` verify), but **premise selection fails** for TERM/LEMMA slots —
`simpa only [← not_le, ] using` (term left blank), `simpa [] using 𝕜 𝕜 𝕜 …` (degenerate). Recovering the
exact Mathlib lemma/term for a *novel* theorem from an abstract slot is premise selection, which a 42M
model on 79k examples does weakly.

## Causality control — **PASS (plan is causally used)**
Ground **corrupted** plans (random head swaps) → verify: **0.022 (1/45)** vs gold-plan **0.267**. The
12× drop confirms the grounder **uses the plan**, not ignoring it — the LPSF abstraction is real, the
pipeline logic holds. (This was the make-or-break control; it passed.)

## Consequence for the verdicts (pre-registered fallback)
Per the brief's fallback ("grounder ceiling < 0.35 after improvement → e2e verdicts become conditional
'under a weak grounder'; H12/H13 failures are **INCONCLUSIVE, not refuted**; the exit rule does **not**
fire"). So the LPSF bet **cannot be cleanly refuted tonight** — the grounder caps the pipeline below
direct-AR before plan quality even enters. All Phase-4 e2e numbers are read against this 0.267 ceiling
and reported as "under a weak (premise-selection-limited) grounder." A stronger grounder (retrieval-
augmented premise selection) is the prerequisite for a clean LPSF test — the V42 implication.

Artifact: `outputs/v41/ceiling.json` (greedy ceiling + causality + sample grounded proofs).
