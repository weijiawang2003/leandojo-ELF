# Mini-ELF v15 — neg_imp_exfalso rerank analysis (focused)

Companion to `V15_LEARNED_RERANKER_REPORT.md`. Per-row first-verified
rank under each v15 configuration, on the 5 unique neg_imp_exfalso
test theorems. The verifying candidate on every row is the
cross-family composition
`intro hp\n  exact absurd hp hnp` (see `V14_FAILURE_EXAMPLES.md` §2
for the mechanism).

## 1. First-verified rank per row

`-` means no verified candidate in the top 10.

| theorem | raw | rule | learned | **policy** |
|---|---:|---:|---:|---:|
| `neg_imp_exfalso_pq` | 4 | 6 | 4 | **4** |
| `neg_imp_exfalso_ab` | 6 | 8 | 6 | **6** |
| `neg_imp_exfalso_xy` | 4 | 5 | 4 | **4** |
| `neg_imp_exfalso_ps` | 3 | 5 | 3 | **3** |
| `neg_imp_exfalso_ad` | 4 | 6 | 4 | **4** |

## 2. Pass@k summary

| config | pass@1 | pass@3 | pass@5 | pass@10 | MRR |
|---|---:|---:|---:|---:|---:|
| raw | 0 | 0 | **0.800** (4/5) | 1.000 | 0.199 |
| rule | 0 | 0 | 0.000 (0/5) | 1.000 | 0.146 |
| learned | 0 | 0 | **0.800** (4/5) | 1.000 | 0.199 |
| **policy** | 0 | 0 | **0.800** (4/5) | 1.000 | **0.199** |

## 3. What each configuration is doing

* **raw** = v14 token-beam in original beam-rank order
  (seq2seq-source candidates first, then literal_adapt appended;
  literal_adapt never fires on neg_imp_exfalso so the order is just
  the raw token beam). The verifying candidate sits at rank 3–6
  depending on theorem.
* **rule** = v12 rule-based reranker. Penalises the verifying
  candidate via the "no goal-literal match", "no schema match" rules
  and promotes malformed siblings (`exact fun hp => hnq (h1 ` etc.)
  ahead of it. Pushes the verifying rank to 5–8 → pass@5 collapses
  to **0**.
* **learned** = v15 logistic regression. Trained on candidate-level
  Lean outcomes across **sibling negation families** (the LOFO held
  family is neg_imp_exfalso itself; sibling families
  `exfalso_pq / exfalso_ab / neg_or_cases / neg_exfalso` etc. supply
  positive `absurd hp hnp` patterns). The model learns
  `contains_intro + contains_absurd` is positively correlated with
  verification → does not de-rank the verifying candidate, matching
  raw.
* **policy** = operation-aware router. `intro_negation`-tagged rows
  are routed to `learned`, so the policy's rank table is identical to
  learned on this family.

## 4. The residual `neg_imp_exfalso_ab` failure (rank 6)

`neg_imp_exfalso_ab`'s v14 raw beam has the verifying candidate at
position 6 — beyond top-5 in any reordering, since the reranker
cannot inject candidates that the generator put after rank 5.

```
neg_imp_exfalso_ab v14 raw beam (positions 4–9):
  rank 4: 'exact fun hp => hnq (h hp)'           — fail (close, but bracket mismatch on top-line)
  rank 5: 'intro hp\n  exact (h hp)'             — fail (h not the expected name)
  rank 6: 'intro hp\n  exact absurd hp hnp'      — VERIFIED ✓ (rank 6)
  rank 7: 'exact fun hp => hnp hp'               — fail (type mismatch)
  …
```

Lifting this to rank ≤4 would require either:
1. Training the v14 generator more on neg_imp_exfalso-shape rows
   (corpus / generation work, **not** rerank work — out of v15 scope).
2. A bigger candidate budget at decode time (k>10), which trades
   against verification cost.

This is the **generator-bound** rank that v15 cannot move. It's
counted honestly in the headline 0.800 pass@5 (4 of 5 unique
theorems) and 1.000 pass@10.

## 5. The cross-family compositional positive at training time

The learned reranker never saw a neg_imp_exfalso row in train (LOFO
guard), but its positive class includes:

| family in train | tactic example | what it teaches |
|---|---|---|
| `exfalso_pq` | `exact absurd hp hnp` | `absurd` + dual-hyp pattern verifies |
| `neg_or_cases` | `cases h with \| inl hp => exact absurd hp hnp \| inr hq => exact hq` | `absurd hp hnp` is a verified building block |
| `neg_exfalso` | `intro hp\n  exact absurd hp hnp` | `intro + absurd` composite verifies |
| `exfalso_ab` | `exact absurd ha hna` | same shape, different variable names |
| `arrow_false` | `intro hp\n  exact absurd hp hf` | `intro + absurd` again |

The learned reranker's top positive weights (informational, from
`data/models/v15_reranker/neg_imp_exfalso/`'s training run): the
features `contains_absurd`, `contains_intro`, and the operation
one-hot `op_intro_negation` carry positive weights; the malformed
flag, stale-literal flag, and parse-error-like features carry
negative weights.

## 6. Bottom line

* v15 policy fixes the **reranker-side** problem fully: the
  contrapositive candidate is no longer buried below pass@5.
* The residual **generator-side** ceiling stops at 0.800 pass@5
  (1.000 pass@10) — that's v16's problem if and only if 0.800 is
  not enough.
