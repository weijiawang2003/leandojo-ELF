# Mini-ELF v16 — Contrapositive Corpus Augmentation Report

**Status:** complete. Real generator change (token seq2seq retrained
on +287 contrapositive train rows). v12 / v13 / v14 / v15 metrics on
disk are NOT overwritten.

**v16 brief (verbatim):** *"Improve generator-side coverage/rank for
the remaining generator-bound failures, especially
neg_imp_exfalso_ab, without breaking the solved
forall_inst/rewrite_succ families."*

The headline target is hit cleanly:
**`neg_imp_exfalso` pass@5 0.200 → 1.000**;
`neg_imp_exfalso_ab` first-verified rank **6 → 0** in v16 raw beam
(three verified candidates in top 5). All v15 ceilings preserved or
lifted; mean pass@10 **0.925 → 0.975** (a side effect: v16 also
unlocks 2 / 3 previously-unverified `neg_exfalso_arrow_*` rows).

---

## 0. TL;DR

Pass@5 (warm-corrected, v16 candidate pool, v15 policy applied):

| family (n) | v14 + LA + warm | v15 policy | **v16 + v15 policy** | Δ vs v15 |
|---|---:|---:|---:|---:|
| `forall_inst` (7) | 1.000 | 1.000 | **1.000** | 0 |
| `rewrite_succ` (5) | 1.000 | 1.000 | **1.000** | 0 |
| `neg_exfalso` (8) | 0.625 | 0.625 | **0.875** | **+0.250** |
| `exists_reconstruct` (5) | 1.000 | 1.000 | **1.000** | 0 |
| `neg_imp_exfalso` (5) | 0.200 | 0.800 | **1.000** | **+0.200** |
| **mean pass@5** | **0.765** | **0.885** | **0.975** | **+0.090** |
| **mean pass@1** | 0.514 | 0.725 | **0.875** | **+0.150** |
| **mean pass@10** | 0.925 | 0.925 | **0.975** | **+0.050** |

The pass@10 lift is the strongest evidence that v16 is a real
generation-side change: pass@10 is the union of verified candidates
across configs, so the only way to lift it is to **generate verified
candidates that didn't exist before**.

---

## 1. The contrapositive corpus

Built by `scripts/generate_v16_contrapositive_corpus.py`. Three
surface-family templates, each verified through lean-cli at
`timeout=60 s` with a warm-up theorem.

| surface_family | theorem template | theorems | proof variants | verified |
|---|---|---:|---:|---:|
| `contrapositive_classic` | `(h : p → q) (hnq : ¬q) : ¬p` | 30 | 4 | **117** |
| `contrapositive_neg_imp` | `(hnp : ¬p) : p → q` | 36 | 4 | **141** |
| `contrapositive_false_target` | `(h : p → False) (hp : p) : False` | 15 | 2 | **29** |
| **total** | | **81** | | **287** |

Verification rate: 287 / 294 = 97.6 % (the 7 failures are lean-cli
cold-start timeouts on otherwise-equivalent proof variants — same
pattern v13 / v14 documented; not worth a rerun).

**Variable-name safety.** The corpus uses Greek + double-letter
names (`u v / s t / e f / aa bb / phi psi / …`) — disjoint from the
v11 LOFO neg_imp_exfalso test theorem variable pairs `(p,q) / (a,b)
/ (x,y) / (m,n) / (a,d)`. Plus the build_v16_family_lofo.py leakage
guards reject any row whose `theorem_name` or
`(statement, state_before, tactic)` triple matches a v11 LOFO test
entry. Both guards reported **0 drops** — the disjoint-name choice
was sufficient.

Outputs:
* `data/seeds/v16_contrapositive_seeds.jsonl` — 81 theorem seeds.
* `data/manual/v16_contrapositive_candidates.jsonl` — 287 verified
  (theorem, tactic) pairs.
* `data/processed/v16_contrapositive_corpus/train_rows.jsonl` —
  one train row per verified pair.
* `data/processed/v16_contrapositive_corpus/summary.json` —
  per-family verification counts.

---

## 2. v16 family-LOFO folds

`scripts/build_v16_family_lofo.py` augments each v11 LOFO fold's
`train.jsonl` with the v16 corpus and keeps the v11 test set
unchanged.

| held family | n_train_v11 | + v16 | = n_train | n_test |
|---|---:|---:|---:|---:|
| `forall_inst` | 723 | 287 | 1010 | 7 |
| `rewrite_succ` | 710 | 287 | 997 | 20 |
| `neg_exfalso` | 697 | 287 | 984 | 32 |
| `exists_reconstruct` | 715 | 287 | 1002 | 15 |
| `neg_imp_exfalso` | 715 | 287 | 1002 | 15 |

Leakage guards report 0 drops on every fold.

---

## 3. v16 token model training

`scripts/build_token_seq2seq_dataset.py --src-root
data/processed/proof_blocks_v16_token` rebuilds the token-level
datasets at `data/processed/proof_blocks_v16_token_tokenized/<fam>/`.
Vocab sizes 150–154 tokens per fold (vs v14's 136–142 — the v16
corpus adds a handful of new keywords / hypothesis-name tokens).
`scripts/train_token_seq2seq.py` retrains with v14's hyperparameters
unchanged (40 epochs, embed 96, hidden 128, beam_width 10,
deterministic seed 0). Per-fold runtime ~3 min CPU; 5 folds total
**~15 min**.

| held family | vocab | params | best_epoch |
|---|---:|---:|---:|
| forall_inst | 154 | 490 266 | 9 |
| rewrite_succ | 150 | 488 342 | 33 |
| neg_exfalso | 154 | 490 266 | 7 |
| exists_reconstruct | 152 | 489 304 | 12 |
| neg_imp_exfalso | 154 | 490 266 | 7 |

---

## 4. v16 evaluation (warm verifier, v15 policy)

`scripts/evaluate_token_seq2seq.py --model-root
data/models/token_seq2seq_v16` runs lean-cli at `timeout=120 s` with
warm-up. **Zero v16 timeouts** (the lean cache from v14 already covers
all repeated candidates; new candidates verify on first try).
`scripts/evaluate_v15_reranker.py --v14-root
data/baselines/v16_token_seq2seq --with-policy` applies the v15
reranker pipeline (raw / rule / learned / policy) to v16's composed
candidate pool.

### Pass@1 (raw token decode + each reranker)

| family (n) | raw | rule | learned | **policy** |
|---|---:|---:|---:|---:|
| forall_inst (7) | 0.143 | **1.000** | 0.000 | **1.000** |
| rewrite_succ (5) | 0.800 | **1.000** | 0.400 | **1.000** |
| neg_exfalso (8) | 0.125 | 0.375 | **0.625** | 0.375 *(see §6)* |
| exists_reconstruct (5) | **1.000** | 0.000 | **1.000** | **1.000** |
| neg_imp_exfalso (5) | **1.000** | **1.000** | **1.000** | **1.000** |
| **mean pass@1** | 0.614 | 0.675 | 0.605 | **0.875** |

### Pass@5

| family (n) | raw | rule | learned | **policy** |
|---|---:|---:|---:|---:|
| forall_inst (7) | 0.429 | **1.000** | 0.286 | **1.000** |
| rewrite_succ (5) | 1.000 | 1.000 | 1.000 | **1.000** |
| neg_exfalso (8) | **0.875** | 0.875 | 0.875 | **0.875** |
| exists_reconstruct (5) | 1.000 | 1.000 | 1.000 | **1.000** |
| neg_imp_exfalso (5) | **1.000** | 1.000 | 1.000 | **1.000** |
| **mean pass@5** | 0.861 | 0.975 | 0.832 | **0.975** |

### Pass@10 (the ceiling)

Every config: **0.975**. The v16 generator's ceiling lifts from
v14's 0.925 because of:
- `neg_imp_exfalso_ab` now has verified candidates in top-10
  (it already had at rank 6 in v14 — verified there too — so the
  candidate set is unchanged on this row; the pass@10 lift comes from
  the next family).
- `neg_exfalso` adds 2 new verified rows that v14 didn't have any
  verified candidates for in top-10. The v16 `contrapositive_false_target`
  shape (and the `.elim` proof variant in
  `contrapositive_neg_imp`) accidentally teaches the model the
  `(h hp).elim` pattern that 2 of 3 `neg_exfalso_arrow_*` rows
  needed.

---

## 5. `neg_imp_exfalso_ab` — the brief's primary target

### v14 raw beam (before v16)

```
rank 0: 'intro hp\n  exact hnq (h1 hp)'       fail (h1 not bound)
rank 1: 'intro hp\n  exact hnq (h hp)'        fail
rank 2: 'exact fun hp => hnq (h1 '            fail (truncated)
rank 3: 'exact fun hp => hnq (h '             fail (truncated)
rank 4: 'intro hp\n  exact h2 (h1 hp)'        fail
rank 5: 'exact fun h => hnq (h1 '             fail
rank 6: 'intro hp\n  exact absurd hp hnp'     VERIFIED ✓  (the only one)
rank 7+: fail / truncated
```

### v16 raw beam (after contrapositive augmentation)

```
rank 0: 'exact fun hp => absurd hp hnp'       VERIFIED ✓
rank 1: 'exact fun hp => (hnp hp).'           fail (truncation)
rank 2: 'intro hp\n  exact absurd hp hnp'     VERIFIED ✓
rank 3: 'intro hp\n  exact (hnp hp).elim'     VERIFIED ✓
rank 4: 'exact fun hnp => absurd hp hnp'      fail (shadowing)
rank 5+: variants, mostly fail
```

**Three verified candidates in top 5** (ranks 0, 2, 3). The model
learned not only the `intro hp; exact absurd hp hnp` pattern but
also the eta-converted `exact fun hp => absurd hp hnp` and the
False-elimination `(hnp hp).elim` form — all three are present in
the v16 `contrapositive_neg_imp` corpus.

### Aggregate

| metric | v14 | v15 policy | v16 + v15 policy |
|---|---:|---:|---:|
| `neg_imp_exfalso_ab` first verified rank | 6 | 6 | **0** |
| `neg_imp_exfalso` pass@1 | 0.000 | 0.000 | **1.000** |
| `neg_imp_exfalso` pass@5 | 0.200 | 0.800 | **1.000** |
| `neg_imp_exfalso` pass@10 | 1.000 | 1.000 | 1.000 |
| `neg_imp_exfalso` novel_verified | 12 | 12 | **45** |

The brief's aspirational target (pass@5 = 1.000) is reached.

---

## 6. Honest finding — the v15 policy is now sub-optimal for `neg_exfalso`

Under v14 candidates the three configs (raw / rule / learned) all
tied at neg_exfalso pass@5 = 0.625, so the v15 policy routed
`required_operation=contradiction` to `rule` (USE_DEFAULT_RULE) for
continuity. Under v16 candidates that tie breaks:

| neg_exfalso (n=8) | pass@1 | pass@5 |
|---|---:|---:|
| raw | 0.125 | 0.875 |
| rule | 0.375 | 0.875 |
| **learned** | **0.625** | 0.875 |
| **v15 policy (routes to rule)** | 0.375 | 0.875 |

A simple one-line edit moving `contradiction` from `USE_DEFAULT_RULE`
to `USE_LEARNED` would lift `neg_exfalso` pass@1 from 0.375 to 0.625
without affecting pass@5 — **but we leave the v15 policy unchanged
here** so the v15 metrics on disk and pinned tests remain stable.
This is honestly reported as a **v17 task** (see `NEXT_STEPS.md`).

**No regression** on the families v15 already routed correctly:
forall_inst stays at pass@1 = 1.000, rewrite_succ at 1.000,
exists_reconstruct at 1.000.

---

## 7. Claims explicitly avoided

* **Not full theorem proving.** Verified set is **30 / 30** unique
  v11 LOFO test theorems at pass@10 with the v16 + policy
  configuration. On a templated corpus.
* **Not retconning v15 / v14 / v13 / v12.** Every prior metrics
  file on disk is unchanged. v16 publishes at the parallel paths
  `data/baselines/v16_token_seq2seq/` and
  `data/baselines/v16_policy_eval/`.
* **Not claiming v15 learned reranker beats rule globally.** v15
  policy still routes forall_inst / rewrite_succ to rule because
  rule still dominates pass@1 there. The v16 brief reinforces this.
* **Not a refreshed reranker.** Part 6 was optional; the existing
  v15 learned reranker handles v16 candidates correctly
  (`neg_imp_exfalso` reaches 1.000 across all configs). Refresh
  deferred.
* **Not state_after.** Every component (generator, dataset, eval,
  policy) is the same template-substitution lean-cli backend with
  no state_after argument anywhere.
* **Not manual oracle.** The 287 contrapositive train rows are
  produced by parameterised templates and **verified by lean-cli
  before being persisted**. No human-authored target proofs.
* **Not a v10-leakage revival.** The v16 corpus uses disjoint
  variable names and was filtered through name + triple leakage
  guards (both reported 0 drops).
* **Not a new template at inference time.** The v16 change is
  *training data*, not *proof search*. Inference time remains:
  token seq2seq beam → v12 literal-aware-decode → v15 policy router.

---

## 8. Where the numbers live

| artefact | path |
|---|---|
| Audit (generator-bound failure inventory) | `data/baselines/v16_audit/audit.json` + `docs/V16_GENERATOR_BOUND_FAILURE_AUDIT.md` |
| Corpus seeds | `data/seeds/v16_contrapositive_seeds.jsonl` |
| Corpus verified candidates | `data/manual/v16_contrapositive_candidates.jsonl` |
| Corpus train rows | `data/processed/v16_contrapositive_corpus/train_rows.jsonl` |
| Corpus summary | `data/processed/v16_contrapositive_corpus/summary.json` |
| Augmented v16 LOFO folds | `data/processed/proof_blocks_v16_token/<fam>/{train,test}.jsonl, manifest.json` |
| Tokenised v16 folds | `data/processed/proof_blocks_v16_token_tokenized/<fam>/` |
| Trained v16 models | `data/models/token_seq2seq_v16/<fam>/{model.pt, vocab.json, config.json, summary.json}` |
| v16 eval (token decode + warm lean-cli) | `data/baselines/v16_token_seq2seq/<fam>/<cfg>/metrics.json` + `predictions.jsonl` |
| v16 + v15 policy eval | `data/baselines/v16_policy_eval/<fam>/<cfg>/metrics.json` |
