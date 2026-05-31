# Mini-ELF v6 — remaining failures & taxonomy

v6 structure-aware retrieval **alone** reaches global pass@1 = pass@5 = **1.000**
on the planner-blind split, fixing all four v5 ranking failures (F1–F4, see
`docs/V6_RETRIEVAL_FAILURE_ANALYSIS.md`). So the "failures" below are the honest
*residuals*: where the fusion still trails, and the structural limits that remain.
Evidence is verbatim from the v6 `predictions.jsonl`
(`scripts/_v6_inspect.py DIR thm`).

## R1 — fusion trails retrieval-alone on `exists_elim_conj` pass@1 (v3 parser bug)

v6 **retrieval-alone** gets `exists_elim_conj` pass@1 = 1.00; v6 **fusion** gets
0.50. Cause: we deliberately leave the v3 planner unchanged, and it still
mis-parses `∃ _, p ∧ q` as a top-level `∧` (the v4-surfaced bug), emitting
`exact h.2` / `exact h.right` into the symbolic tier **above** the retrieval tier:

```
THM exists_elim_conj_r_pq  GT='rcases h with ⟨n, hp, hq⟩  exact hq'
  0 ok=False <planner_projection> 'exact h.2'        <- v3 mis-fire, rank 0
  1 ok=False <planner_projection> 'exact h.right'
  2 ok=True  <retrieval> 'rcases h with ⟨n, hp, hq⟩  exact hq'   <- correct, rank 2
  3 ok=True  <retrieval> 'obtain ⟨n, hpq⟩ := h  exact hpq.2'
```

The *left*-projection theorems are unaffected (planner emits nothing usable, so
retrieval's correct candidate is rank 0). pass@5 is 1.00 either way. Fixing this
means a v3 parser fix or letting structure-aware retrieval out-rank a
known-low-confidence planner candidate — both deferred to keep v3 frozen
(v5/v6 must not modify v3). **Retrieval-alone is the cleaner top-1 source here.**

## R2 — structure-aware retrieval is still example reuse, not reasoning

v6 only *re-ranks* retrieved verified blocks. The `no structural` ablation
(global pass@1 0.393, negation/∃-elim pass@1 → 0) shows the gains come entirely
from matching structural features of **existing donors** — with **no same-family
donor**, v6 has nothing correct to rank and would fail exactly as v5 did. v6 buys
a better *ranking of reuse*; it does not construct proofs for unseen shapes. The
`family_interpolation` split guarantees donors exist; a family-holdout split would
expose this limit (a v7 probe).

## R3 — adapted-preference is redundant with the tie-break (not a failure, a finding)

The `no adapt-pref` ablation is identical to full v6 (pass@1 0.952 fusion / would
be 1.000 retrieval-alone). The explicit stale-literal penalty is **belt-and-
suspenders**: ranking adapted candidates ahead of their verbatim donor on score
ties — in goal-LHS-first generation order — already fixes `forall_inst` pass@1.
Reported so the weight is not mistaken for load-bearing.

## R4 / R5 — LLM skipped, learned deferred

Unchanged from v5: no API key ⇒ LLM pilot skipped (`docs/V5_LLM_PILOT_SKIPPED.md`,
not faked); the learned seq2seq proposer remains deferred
(`docs/V5_LEARNED_PROPOSER.md`). Both are out of scope for v6's ranking work.

## What would close R1–R2 (v7 directions)

- **Confidence-gated tier fusion** — let a high structural-score retrieval
  candidate out-rank a *known-low-confidence* v3 planner candidate (e.g. the
  `∃,∧` projection), instead of a fixed symbolic-first tier. Or fix the v3
  `∃ _, p ∧ q` parser precedence (small AST fix, surfaced since v4).
- **A family-holdout probe** — measure v6 when *no* same-family donor exists, to
  quantify how much is interpolation vs transferable structure.
- **A learned scorer / real-LLM proposer** — for shapes with no donor at all.
