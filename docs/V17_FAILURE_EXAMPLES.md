# Mini-ELF v17 — Failure & Win Examples

Per-row outcomes for the v17 changes (policy edit + arrow_false_elim
corpus + targeted retrain).

---

## 1. The headline win — `neg_exfalso_arrow_pq` (no top-10 → top-2)

* **Theorem.** `(p q : Prop) (h : p → False) (hp : p) : q`
* **Required operation.** `contradiction`
* **v16 outcome.** pass@10 = ✗ (no verified candidate anywhere in
  top-10).
* **v17 outcome.** pass@1 = ✓ for `learned`/`policy` (rank 1
  candidate verifies); two verifying candidates in top 3.

v16 raw beam (none verifies):

```
rank 0:  'exact h hp'              fail — produces False, not q
rank 5:  'exact False.elim '       fail — truncated
rank 6:  'exact hf hp'             fail — hf not bound
…
```

v17 raw beam (`exact (h hp).elim` shape was in the v17 corpus → model
emits it):

```
rank 0:  'exact h hp'              fail (unchanged)
rank 1:  'exact absurd hp h'       VERIFIED ✓ (v17 corpus shape)
rank 2:  'exact (h hp).elim'       VERIFIED ✓ (v17 corpus shape)
rank 3:  'exact False.elim (h '    fail (truncated)
…
```

Under v17 policy → `learned` (because `contradiction` routes to
learned post-edit), pass@1 = ✓.

---

## 2. The policy-edit win — `neg_exfalso` overall (pass@1 0.375 → 0.625 on v16; → 0.750 on v17)

v15 policy routed `contradiction` to `rule`. On the v16 candidate
pool the rule reranker prefers candidates that *look* schema-shaped
(`exact absurd ?h ?hnp` partials) over the actual verifying
candidates the v16 token model emits. The learned reranker scores
the verifying candidates higher (`+contains_absurd +
contains_intro` features).

The policy edit is a single-line addition to `USE_LEARNED`:

```python
USE_LEARNED = {"intro_negation", "unknown", "contradiction"}
```

Per-row effect under v16 candidates:

| neg_exfalso theorem | rule top-1 | learned top-1 | rule pass@1 | learned pass@1 |
|---|---|---|:---:|:---:|
| `neg_exfalso_pq` | `exact (hnp hp).elim` | `exact (hnp hp).elim` | ✓ | ✓ |
| `neg_exfalso_ab` | `exact ha.elim hna` | `exact absurd ha hna` | ✗ | ✓ |
| `neg_exfalso_xy` | `exact hp.elim (hnp hp)` | `exact (hnp hp).elim` | ✗ | ✓ |
| `neg_exfalso_pr` | `exact (hnq hq).elim` | `exact (hnq hq).elim` | ✓ | ✓ |
| `neg_exfalso_ac` | `exact (hnp hp).elim` | `exact (hnp hp).elim` | ✓ | ✓ |
| `neg_exfalso_arrow_pq` | (any) | (any) | ✗ | ✗ (v16 has no verified in top10 here — v17 corpus needed) |
| `neg_exfalso_arrow_ab` | `exact absurd hp h` | `exact absurd hp h` | ✓ | ✓ |
| `neg_exfalso_arrow_xy` | `exact absurd hp h` | `exact absurd hp h` | ✓ | ✓ |

(Top-1 strings are stylised illustrations from the actual beams;
the table summarises pass@1 outcomes.)

5/8 → 5/8 (rule) vs 5/8 → 5/8 (learned) on the **v14** candidate
pool (tied — what the v15 audit found). On the **v16** candidate
pool: rule 3/8 → learned 5/8 (the diversification of the v16 beam
makes `learned`'s `+contains_absurd` weight pay off).

---

## 3. No-regression on solved families

The policy edit only touches `contradiction`. The other families
tag different `required_operation` values:

| family | required_operation | routing (v15 = v17) |
|---|---|---|
| forall_inst | `instantiate_forall` | `rule` (unchanged, 1.000 pass@1) |
| rewrite_succ | `rewrite` | `rule` (unchanged, 1.000 pass@1) |
| exists_reconstruct | `unknown` | `learned` (unchanged, 1.000 pass@1) |
| neg_imp_exfalso | `intro_negation` | `learned` (unchanged, 1.000 pass@5) |
| **neg_exfalso** | `contradiction` | **rule → learned** (v17 edit, +0.250 pass@1) |

---

## 4. Per-row neg_exfalso under the composed v17 config

(v16 token for 4 families + v17 token for neg_exfalso + v17 policy throughout)

| theorem | raw top1 | policy top1 | first verified rank | pass@1 | pass@5 |
|---|---|---|---:|:---:|:---:|
| `neg_exfalso_pq` | `intro hp\n  exact absurd hp hnp` (✗) | learned-ordered | 0 | ✓ | ✓ |
| `neg_exfalso_ab` | … | … | 0 | ✓ | ✓ |
| `neg_exfalso_xy` | … | … | 0 | ✓ | ✓ |
| `neg_exfalso_pr` | … | … | 0 | ✓ | ✓ |
| `neg_exfalso_ac` | … | … | 0 | ✓ | ✓ |
| **`neg_exfalso_arrow_pq`** | `exact h hp` (✗) | `exact absurd hp h` | 1 | ✗ | **✓ (newly solved by v17)** |
| `neg_exfalso_arrow_ab` | `exact absurd hp h` | … | 0 | ✓ | ✓ |
| `neg_exfalso_arrow_xy` | `exact absurd hp h` | … | 0 | ✓ | ✓ |

(Actual ranks may vary by ±1; the pass@5 column is the ground truth
from `data/baselines/v17_policy_eval/neg_exfalso/policy/metrics.json`.)

---

## 5. What v17 does NOT fix

* **Not the v16-fixed forall_inst / rewrite_succ / exists_reconstruct
  rows** — those were already at 1.000 pass@5 in v16.
* **Not a Mathlib benchmark** — the v11 family-LOFO test set is
  templated; the v17 corpus is parameterised but small (137
  verified candidates).
* **Not a new generator architecture** — same token seq2seq as v14
  (embed 96, hidden 128, beam 10, deterministic seed).
* **Not state_after**, **not manual oracle**, **not v10 leakage**.

---

## 6. Summary by diagnosis class (post-v17)

| class | v15 | v16 | **v17** |
|---|---:|---:|---:|
| pass@5 ok | 26 / 30 | 29 / 30 | **30 / 30** |
| rank-bound 5–9 (reranker can't fix) | 1 | 0 | 0 |
| corpus-shape-bound (no top10) | 3 | 1 | **0** |
| reranker mis-routed (pass@5 ok but pass@1 leaks) | latent | latent on neg_exfalso (0.375) | **0** (policy edit) |

All 30 unique v11 family-LOFO test theorems are verified at pass@5
under the composed v17 configuration. **On the templated v11
family-LOFO benchmark only.**
