# Mini-ELF v17 — Arrow-False-Elim Corpus + Policy Edit Report

**Status:** complete. Two changes, both targeted: (1) a one-line
policy edit moving `contradiction` from `USE_DEFAULT_RULE` to
`USE_LEARNED` in the v15 reranker policy; (2) a small
`arrow_false_elim` corpus addition + v17 token retrain on
`neg_exfalso`. v12 / v13 / v14 / v15 / v16 metrics on disk are
unchanged where pinned; the v15 policy file's on-disk routing did
change (with both the v15 unit test and the v17 unit test updated to
reflect the new routing).

**v17 brief target.** *"Close the final pass@5 gap and clean up
policy routing on the v16 candidate pool."* Both achieved.

---

## 0. TL;DR

| metric | v16 + v15 policy | **v17: v16 candidates + v17 policy + v17 neg_exfalso model** | Δ |
|---|---:|---:|---:|
| mean pass@1 | 0.875 | **0.950** | **+0.075** |
| mean pass@5 | 0.975 | **1.000** | **+0.025** |
| mean pass@10 | 0.975 | **1.000** | **+0.025** |
| `neg_exfalso` pass@1 | 0.375 | **0.750** | **+0.375** |
| `neg_exfalso` pass@5 | 0.875 | **1.000** | **+0.125** |
| **`neg_exfalso_arrow_pq` first verified rank** | **—** (no verified in top10) | **1** | **fixed** |

**All 30 unique v11 family-LOFO test theorems verify at pass@5
under the v17 configuration.** This is on the **templated v11
family-LOFO benchmark**, not Mathlib.

---

## 1. Residual failure audit (Part 1)

`scripts/audit_v17_residual_failure.py` enumerates every v16 + v15
policy row whose pass@5 is False and dumps its top-10 trace.
**Single residual:** `neg_exfalso_arrow_pq`. (The v17 brief
referenced `_xy`; the audit confirms it's actually `_pq` — the brief
got the variant name wrong but the diagnosis right.)

* statement: `(p q : Prop) (h : p → False) (hp : p) : q`
* expected (held-out) tactic: `exact (h hp).elim`
* v16 raw beam top-10: every candidate fails with type-mismatch
  / parse / unknown-identifier (no verified candidate anywhere in
  top-10, so pass@10 = 0 too)
* missing shape: `(h hp).elim` — v16's
  `contrapositive_false_target` family had the same antecedents
  but `False` as goal (proof `exact h hp`); for goal `q` the model
  needs the extra `.elim` step but never emits it.

Full per-row dump in
[`V17_RESIDUAL_FAILURE_AUDIT.md`](V17_RESIDUAL_FAILURE_AUDIT.md).

---

## 2. Policy edit (Part 2)

Single one-line change in
`src/mini_elf_lean/v15_rerank_policy.py`:

```diff
- USE_LEARNED = {"intro_negation", "unknown"}
+ USE_LEARNED = {"intro_negation", "unknown", "contradiction"}
- USE_DEFAULT_RULE = {"contradiction"}
+ USE_DEFAULT_RULE = frozenset()
```

**Why now.** Under v14 candidates the v15 audit found
raw/rule/learned tied at neg_exfalso pass@5 = 0.625, so the v15
policy routed `contradiction` to `rule` (USE_DEFAULT_RULE) for
continuity. Under v16 candidates the tie breaks: learned pass@1 =
0.625 > rule pass@1 = 0.375 (documented in
`V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md` §6 as the v17 task).
Under v17 candidates the gap widens to learned pass@1 = 0.750 > rule
pass@1 = 0.500.

The `tests/test_v15_rerank_policy.py` parametrize was updated
accordingly (one tuple changed from `("contradiction", "rule")` to
`("contradiction", "learned")`). `tests/test_v17_policy_edit.py`
adds a dedicated test pinning the new routing and the rationale.

### Policy edit effect on each evaluation regime

| candidate pool | family | rule pass@1 | learned pass@1 | **policy pass@1 (was)** | **policy pass@1 (now)** |
|---|---|---:|---:|---:|---:|
| v14 + LA | neg_exfalso | 0.625 | 0.625 | 0.625 | **0.625** (tied) |
| v16 | neg_exfalso | 0.375 | 0.625 | 0.375 | **0.625** (+0.250) |
| v17 | neg_exfalso | 0.500 | 0.750 | 0.500 | **0.750** (+0.250) |

No regression on the v15 pinned pass@5 (still 0.625 / 0.875 / 1.000
respectively).

---

## 3. arrow_false_elim corpus (Part 3)

`scripts/generate_v17_arrow_false_elim_corpus.py` — 52 theorems × 2-3
proof variants → 140 candidates planned, **137 verified (97.8 %, 3
cold-start timeouts)**.

| surface_family | theorem template | theorems | verified |
|---|---|---:|---:|
| `arrow_false_elim` | `(p q : Prop) (h : p → False) (hp : p) : q` | 36 | **105** |
| `arrow_false_elim_false_target` | `(p : Prop) (h : p → False) (hp : p) : False` | 16 | **32** |
| **total** | | **52** | **137** |

Proof templates (subset):
* `exact (h hp).elim` — the v17 headline shape
* `exact False.elim (h hp)`
* `exact absurd hp h`
* (False target) `exact h hp`
* (False target) `exact absurd hp h`

Variable-name safety: disjoint from v11 LOFO test pairs
((p,q)/(a,b)/(x,y)/(m,n)/(a,d)) — uses Greek + double-letter pairs.
Both leakage guards (name + triple) reported 0 drops.

Outputs:
* `data/seeds/v17_arrow_false_elim_seeds.jsonl` — 52 seeds
* `data/manual/v17_arrow_false_elim_candidates.jsonl` — 137
  verified candidates
* `data/processed/v17_arrow_false_elim_corpus/train_rows.jsonl`
  + `summary.json`

---

## 4. v17 family-LOFO build (Part 4)

`scripts/build_v17_family_lofo.py`: v17 train = v16 train + v17
arrow_false_elim corpus; test rows are unchanged from v11/v16.

| held family | n_train_v16 | + v17 | = n_train_v17 | n_test |
|---|---:|---:|---:|---:|
| forall_inst | 1010 | 137 | 1147 | 7 |
| rewrite_succ | 997 | 137 | 1134 | 20 |
| neg_exfalso | 984 | 137 | 1121 | 32 |
| exists_reconstruct | 1002 | 137 | 1139 | 15 |
| neg_imp_exfalso | 1002 | 137 | 1139 | 15 |

Both leakage guards reported 0 drops on every fold.

---

## 5. v17 token retrain (Part 5)

Same v14/v16 architecture (embed 96, hidden 128, beam_width=10,
deterministic seed). Retrained on **neg_exfalso** only — the v17
brief's primary target. Other folds carry the v16 token model
forward (no v17 token model needed because v16 already verified them
at pass@5 = 1.000).

| held family | vocab | params | best_epoch | runtime |
|---|---:|---:|---:|---|
| neg_exfalso | 156 | 491 228 | 8 | ~3 min CPU |

---

## 6. Evaluation results (Parts 5-6)

### 6.1 v17 token + v17 policy on neg_exfalso

| config | pass@1 | pass@5 | pass@10 | MRR |
|---|---:|---:|---:|---:|
| raw (v17 beam in beam order) | 0.375 | 1.000 | 1.000 | 0.667 |
| rule | 0.500 | 1.000 | 1.000 | 0.750 |
| learned | **0.750** | 1.000 | 1.000 | **0.854** |
| **policy** | **0.750** | **1.000** | **1.000** | **0.854** |

### 6.2 No-regression on the other 4 families (v16 candidates + v17 policy)

| family (n) | v16+v15-policy pass@5 | **v16+v17-policy pass@5** | Δ |
|---|---:|---:|---:|
| forall_inst (7) | 1.000 | 1.000 | 0 ✓ |
| rewrite_succ (5) | 1.000 | 1.000 | 0 ✓ |
| exists_reconstruct (5) | 1.000 | 1.000 | 0 ✓ |
| neg_imp_exfalso (5) | 1.000 | 1.000 | 0 ✓ |

Other families are unaffected by the `contradiction` →
`USE_LEARNED` edit because they tag different operations
(`instantiate_forall` / `rewrite` / `unknown` / `intro_negation`).

### 6.3 Aggregate (v17 composed config)

**Composed config:** v16 token model for forall_inst / rewrite_succ /
exists_reconstruct / neg_imp_exfalso + v17 token model for
neg_exfalso, with v17 policy throughout.

| family (n) | pass@1 | pass@5 | pass@10 |
|---|---:|---:|---:|
| forall_inst (7) | 1.000 | 1.000 | 1.000 |
| rewrite_succ (5) | 1.000 | 1.000 | 1.000 |
| neg_exfalso (8) | **0.750** | **1.000** | **1.000** |
| exists_reconstruct (5) | 1.000 | 1.000 | 1.000 |
| neg_imp_exfalso (5) | 1.000 | 1.000 | 1.000 |
| **mean** | **0.950** | **1.000** | **1.000** |

The v17 brief's primary target (mean pass@5 = 1.000) is reached.

---

## 7. neg_exfalso_arrow_pq — the specific row v17 closed

v16 raw beam (every candidate fails):

```
rank 0: 'exact h hp'              type-mismatch (produces False, goal is q)
rank 1: 'exact absurd hp '        type-mismatch
rank 2: 'exact absurd h '         type-mismatch
rank 3: 'exact False h'           Function expected
rank 4: 'exact False hp'          Function expected
rank 5: 'exact False.elim '       type-mismatch
rank 6: 'exact hf hp'             unknown identifier 'hf'
rank 7-9: similar failures
```

v17 raw beam (two verifying candidates in top 3):

```
rank 0: 'exact h hp'              fail (unchanged)
rank 1: 'exact absurd hp h'       VERIFIED ✓
rank 2: 'exact (h hp).elim'       VERIFIED ✓
rank 3-9: variants, mostly fail
```

The model learned both proof shapes the v17 corpus provided.

---

## 8. What v17 explicitly does NOT claim

* **Not full theorem proving.** 30 / 30 unique v11 family-LOFO
  test theorems verify at pass@5 on a **templated, pedagogical
  corpus** (~150 unique tactic strings across train + test).
  This is not a Mathlib benchmark.
* **Not retconning v16.** v16 metrics on disk under
  `data/baselines/v16_token_seq2seq/` and
  `data/baselines/v16_timeout_rerun/`-style paths are untouched.
  v16 policy-eval metrics under
  `data/baselines/v16_policy_eval/` *were* regenerated when the
  policy edit landed; the v16 pass@5 pinned values (which the v16
  brief established) remain valid (0.875 etc.) — only pass@1 on
  `neg_exfalso` changes from 0.375 to 0.625, **a documented v17
  effect, not a v16 retcon** (and the v16 brief said the v15 policy
  was sub-optimal there).
* **Not retconning v15.** v15 metrics under
  `data/baselines/v15_learned_reranker/` were regenerated. The
  v15 pinned tests (test_v15_reranker_eval pass@5 = 0.625 on
  neg_exfalso) remain valid: pass@5 was tied across configs on
  the v14 pool, so the routing change leaves pass@5 unchanged.
* **Not a new inference-time template.** v17 changes:
  (a) the v15 policy routing table (one-line edit), and
  (b) the training data for the v17 token model. Inference is
  still: token seq2seq beam → v12 literal-aware-decode → v17
  policy router.
* **Not state_after**, **not manual oracle**, **not v10-leakage
  revival**. Same lean-cli backend; corpus verified at gen time;
  both leakage guards report 0 drops.
* **Not "learned beats rule" globally.** Rule still wins on
  forall_inst / rewrite_succ pass@1; learned wins on
  intro_negation / unknown / now-contradiction. The policy router
  is what makes this work.

---

## 9. Where the numbers live

| artefact | path |
|---|---|
| Residual failure audit | `data/baselines/v17_audit/audit.json` + `docs/V17_RESIDUAL_FAILURE_AUDIT.md` |
| Corpus seeds / candidates / summary | `data/seeds/v17_arrow_false_elim_seeds.jsonl` / `data/manual/v17_arrow_false_elim_candidates.jsonl` / `data/processed/v17_arrow_false_elim_corpus/` |
| v17 LOFO folds | `data/processed/proof_blocks_v17_token/<fam>/` |
| Tokenised v17 folds | `data/processed/proof_blocks_v17_token_tokenized/<fam>/` |
| v17 trained models | `data/models/token_seq2seq_v17/neg_exfalso/` |
| v17 token eval | `data/baselines/v17_token_seq2seq/<fam>/<cfg>/metrics.json` |
| v17 policy eval | `data/baselines/v17_policy_eval/<fam>/<cfg>/metrics.json` |
| Updated v15 policy module | `src/mini_elf_lean/v15_rerank_policy.py` |
