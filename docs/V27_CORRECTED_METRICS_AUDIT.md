# Mini-ELF v27 — Corrected v25/v26 Metric Audit (Part 2)

Question (v27 Q4): *does the corrected verifier change any previous Mathlib
conclusion materially?* Method: `scripts/recompute_v27_mathlib_metrics_corrected.py`
rebuilds each model's candidate pool from live beam search (identical pools for
both verifiers) and re-verifies the union under **both** the **trusted** (corrected:
sentinel + confirm + rescue) verifier and an old **naive** batched verifier (no
sentinel, no confirm), then recomputes best-config pass@k under each. Report:
`data/baselines/v27_corrected_metrics/report.json`.

The v25 eval used a one-candidate-per-file `lake env lean` verifier and the v26
eval used `confirm=True` batched — both sound — so the **corrected** column here
reproduces the established metrics. The naive column is the counterfactual "what
an unsound batched verifier would have reported."

## Results (best-config pass@1 / pass@5 / pass@10)

| Model @ bench | corrected (= reported) | naive (unsound) | naive cand. FPs | naive inflates? |
|---------------|------------------------|-----------------|-----------------|-----------------|
| v24 @ v25-heldout | 0.429 / 0.571 / 0.571 | 0.429 / 0.571 / 0.571 | 0 | no |
| v24 @ v26-holdout | 0.273 / 0.318 / 0.318 | 0.273 / 0.364 / 0.364 | 4 | **yes (+0.046)** |
| v25_aug @ v25-heldout | 0.643 / 0.714 / 0.786 | 0.643 / 0.714 / 0.786 | 0 | no |
| v25_aug @ v26-holdout | 0.455 / 0.591 / 0.636 | 0.500 / 0.682 / **0.727** | 8 | **yes (+0.091)** |
| **v26_base @ v25-heldout** | 0.857 / 0.929 / 0.929 | 0.857 / 0.929 / 0.929 | 0 | no |
| **v26_base @ v26-holdout** | 0.500 / 0.864 / 0.909 | 0.500 / 0.864 / 0.909 | 0 | no |
| **v26_widened @ v25-heldout** | 0.929 / 0.929 / 0.929 | 0.929 / 0.929 / 0.929 | 0 | no |
| **v26_widened @ v26-holdout** | 0.773 / 0.909 / 0.909 | 0.773 / 0.909 / 0.909 | 0 | no |

Totals: 8 cells, 12 naive candidate false positives, 0 for the v26 specialists.

## The disputed candidates are gold-confirmed garbage (adversarial check)

For the highest-impact cell (v25_aug @ v26-holdout, 8 naive false positives) the 8
disputed (theorem, candidate) pairs were re-verified **one declaration per file**
with the gold reference:

> **GOLD agrees with TRUSTED on 8/8; with NAIVE on 0/8.**

The candidates are nonsense the weak model emitted in its beam, e.g. for
`(b : Bool) : (b || b) = b`: `exact b b`, `exact g.trans b`, `exact Eq.symm b`,
`exact ⟨b, rfl⟩`, `exact Nat.zero_add b`. All genuinely fail (gold = False); only
the naive verifier marks them verified, because an earlier malformed candidate in
the same batch desynced the parser so these later candidates were skipped (no
diagnostic in their own range). The trusted verifier's confirm/rescue re-checks
them and correctly fails them — matching gold exactly.

## Per-target recompute vs the established numbers

| Target | established | corrected recompute | Δ |
|--------|-----------|---------------------|---|
| v25 zero-shot tier-C (v24 @ v25-heldout p@10) | 0.571 | 0.571 | 0 |
| v25 augmented tier-C (v25_aug @ v26-holdout p@10) | 0.636 | 0.636 | 0 |
| v26_base @ v25-heldout p@10 | 0.929 | 0.929 | 0 |
| v26_base @ v26-holdout p@10 | 0.909 | 0.909 | 0 |
| v26_widened @ v26-holdout p@10 (Set 0.75) | 0.909 | 0.909 | 0 |

Every established Mathlib number reproduces **exactly** under the corrected
verifier (it was already produced by a sound verifier).

## Conclusions

1. **No previously reported v25/v26 metric changes** — the reported pipeline used a
   sound verifier (v25 one-per-file; v26 `confirm=True`) and the corrected
   recompute reproduces every headline number exactly.
2. **The corrected verifier matters for fair comparison.** An unsound naive
   batched verifier would have **inflated the weaker baselines** — v25_aug tier-C
   0.636 → 0.727, v24 tier-C 0.318 → 0.364 — while leaving the v26 specialists
   unchanged (0 false positives). That would have *narrowed* the apparent
   specialist advantage. The corrected verifier therefore **preserves and slightly
   strengthens** the v26 conclusion that the specialist+router beats co-training;
   it overturns nothing.
3. **The v26 specialist's lead is real**, not a verifier artifact: its candidates
   are clean enough that naive and corrected agree perfectly on it.
4. v27 evaluation uses the trusted verifier exclusively, so weak-model comparisons
   (v24/v25_aug) are never inflated.

(Note: `report.json`'s `any_naive_inflation: true` refers to the **naive
counterfactual** diverging from corrected — not to any change in a *reported*
number, which this audit shows is zero.)
