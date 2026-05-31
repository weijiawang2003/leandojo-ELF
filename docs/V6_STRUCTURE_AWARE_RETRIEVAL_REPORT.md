# Mini-ELF v6 — structure-aware retrieval report

> **Scope.** v6 changes retrieval **ranking only** — it re-scores the same candidate set (verbatim + light adaptation) with heuristic *structural* features (goal shape, hypothesis shapes, required-operation guess, conjunct position, connective overlap) instead of char-similarity alone. It is **not** proof reasoning, adds **no** proof templates, reads **no** `state_after`, and runs **no** LLM. Same `family_interpolation` split as v5 (32 test / 29 train theorems); n is small ⇒ directional. v4 template ablations remain labelled separately and are not folded into v3/v5/v6.

## 1. Headline: structure-aware ranking fixes the v5 failures

Retrieval **alone**, char-similarity ranking (v5) → structure-aware (v6):

- global pass@1 **0.357 → 1.000**, pass@5 **0.595 → 1.000**
- `forall_inst` pass@1 **0.000 → 1.000** (F1), pass@5 held at 1.000
- `exists_elim_conj` pass@5 **0.250 → 1.000** (F2)
- `neg_imp_exfalso` pass@5 **0.333 → 1.000** (F3)
- `neg_exfalso` pass@5 **0.000 → 1.000** (F4)

## 2. Configuration comparison (split test, n=32)

| config | n | pass@1 | pass@3 | pass@5 | forall_inst@1 | forall_inst@5 | rewrite_succ@5 | adapted_top1_rate | adapted_verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v5 retrieval | 32 | 0.357 | 0.524 | 0.595 | 0.000 | 1.000 | 1.000 | 0.000 | 12 |
| v6 retrieval | 32 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.131 | 11 |
| v5 fusion | 32 | 0.357 | 0.524 | 0.595 | 0.000 | 1.000 | 1.000 | 0.000 | 3 |
| v6 fusion | 32 | 0.952 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.024 | 2 |
| v6 fusion — no structural (ablation) | 32 | 0.393 | 0.524 | 0.595 | 1.000 | 1.000 | 1.000 | 0.036 | 3 |
| v6 fusion — no adapt-pref (ablation) | 32 | 0.952 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.024 | 2 |

## 3. Per-family pass@1 (split test)

| family | v5 retrieval | v6 retrieval | v5 fusion | v6 fusion | v6 fusion — no structural (ablation) | v6 fusion — no adapt-pref (ablation) |
| --- | --- | --- | --- | --- | --- | --- |
| neg_exfalso | 0.000 | 1.000 | 0.000 | 1.000 | 0.000 | 1.000 |
| neg_contrapositive | 0.333 | 1.000 | 0.333 | 1.000 | 0.333 | 1.000 |
| neg_imp_exfalso | 0.000 | 1.000 | 0.000 | 1.000 | 0.000 | 1.000 |
| neg_double_intro | 0.667 | 1.000 | 0.667 | 1.000 | 0.667 | 1.000 |
| neg_or_cases | 0.000 | 1.000 | 0.000 | 1.000 | 0.000 | 1.000 |
| exists_elim_prop | 0.333 | 1.000 | 0.333 | 1.000 | 0.333 | 1.000 |
| exists_elim_conj **(t)** | 0.000 | 1.000 | 0.000 | 0.500 | 0.000 | 0.500 |
| exists_reconstruct | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| forall_inst **(t)** | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| rewrite_succ **(t)** | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

## 4. Per-family pass@5 (split test)

| family | v5 retrieval | v6 retrieval | v5 fusion | v6 fusion | v6 fusion — no structural (ablation) | v6 fusion — no adapt-pref (ablation) |
| --- | --- | --- | --- | --- | --- | --- |
| neg_exfalso | 0.000 | 1.000 | 0.000 | 1.000 | 0.000 | 1.000 |
| neg_contrapositive | 0.667 | 1.000 | 0.667 | 1.000 | 0.667 | 1.000 |
| neg_imp_exfalso | 0.333 | 1.000 | 0.333 | 1.000 | 0.333 | 1.000 |
| neg_double_intro | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| neg_or_cases | 0.333 | 1.000 | 0.333 | 1.000 | 0.333 | 1.000 |
| exists_elim_prop | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| exists_elim_conj **(t)** | 0.250 | 1.000 | 0.250 | 1.000 | 0.250 | 1.000 |
| exists_reconstruct | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| forall_inst **(t)** | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| rewrite_succ **(t)** | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

## 5. Honest reading

- **The structural terms do the work.** The `no structural` ablation collapses back to ~v5 (negation/∃-elim pass@1 → 0), isolating goal-shape / operation / conjunct-position matching as the cause of the gains.
- **Adapted-preference is partly redundant with the tie-break.** The `no adapt-pref` ablation barely moves: ranking adapted candidates ahead of their verbatim donor on score ties already fixes `forall_inst` pass@1, so the explicit stale-literal penalty is belt-and-suspenders on this corpus.
- **Fusion lags retrieval-alone on `exists_elim_conj` pass@1.** In fusion, v3's symbolic planner still mis-fires `exact h.2` on the `∃, ∧` shape (the unfixed v4 parser bug) and occupies rank 0; we deliberately leave v3 unchanged, so retrieval-alone is the cleaner top-1 here. pass@5 is 1.00 either way.
- **Still example reuse, not reasoning.** v6 only re-orders retrieved verified blocks; with no same-family donor it would still fail. The win is a better *ranking* of reuse, not new proof construction.

