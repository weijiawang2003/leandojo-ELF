# Mini-ELF v18 — Zero-Shot Transfer Report

**Status:** v17 pipeline evaluated zero-shot on the 48-theorem v18
broad-core benchmark. **This is the v18 brief's headline
research question.**

**The honest answer.** The v17 pipeline (token seq2seq panel + v12
literal-aware-decode + v17 policy) reaches **pass@5 = 0.500** and
**pass@10 = 0.583** on v18 — versus pass@5 = 1.000 / pass@10 =
1.000 on the v17-templated benchmark. **Roughly half** of v17
transfers. The other half is the wall v18 was built to find.

## 1. Headline numbers

| config | pass@1 | pass@5 | pass@10 | MRR | n_no_candidate_verified | malformed_top1 | top1_head_correct |
|---|---:|---:|---:|---:|---:|---:|---:|
| raw (panel union, beam order) | 0.333 | 0.458 | 0.542 | 0.379 | 22 / 48 | 2 | 26 / 48 |
| rule (v12 reranker) | 0.333 | **0.500** | **0.583** | 0.405 | 20 / 48 | 2 | 27 / 48 |
| learned (v15 reranker) | 0.292 | 0.479 | 0.562 | 0.373 | 21 / 48 | 3 | 27 / 48 |
| **policy (v17 routing)** | 0.292 | **0.500** | **0.583** | 0.377 | 20 / 48 | 3 | 26 / 48 |

Setup:
* For each v18 theorem, decode beam_width=10 from each of the 5
  v16/v17 family models (v17 for `neg_exfalso`, v16 for the other
  4); union the beams and append v12 literal-aware-decode
  additions.
* `category → required_operation` mapping:
  * `forall → instantiate_forall`,
  * `equality_rewrite / nat_succ / list → rewrite`,
  * `negation → intro_negation`,
  * everything else → `unknown` (which the v17 policy routes to
    learned).
* lean-cli verifier, timeout 120 s, with warm-up.

The four configs differ only in candidate ordering — pass@10 reflects
the **panel ceiling**, not the reranker. The panel ceiling is
**0.583**, i.e. **28 / 48** v18 theorems have at least one verifying
candidate somewhere in the union; the remaining **20 / 48** do not.

## 2. Per-category breakdown (policy config)

| category | n | pass@1 | pass@5 | pass@10 | gap vs templated |
|---|---:|---:|---:|---:|---|
| `equality_rewrite` | 6 | **1.000** | **1.000** | **1.000** | perfect — `rw [h]` generalises cleanly |
| `conjunction` | 6 | 0.500 | **0.833** | 0.833 | strong — `⟨…, …⟩` patterns transfer |
| `negation` | 5 | 0.400 | **0.800** | 0.800 | strong — v17's contrapositive corpus pays off here |
| `forall` | 3 | 0.333 | **0.667** | 0.667 | moderate — v11 forall_inst training helps but identifiers differ |
| `nat_succ` | 5 | 0.200 | 0.600 | 0.600 | moderate — `rfl` works but `Nat.zero_add` etc not seen in train |
| `list` | 5 | 0.000 | 0.400 | **0.800** | partial — beam ranks low but candidates exist |
| `exists` | 4 | 0.000 | 0.250 | 0.250 | weak — `use 3` style is unfamiliar |
| `disjunction` | 5 | 0.200 | 0.200 | 0.600 | weak at top-5 — `Or.elim` shapes underrepresented |
| **`implication`** | 6 | **0.000** | **0.000** | **0.000** | **total miss** — `intro h; exact …` shapes outside v17 distribution |
| **`bool`** | 3 | **0.000** | **0.000** | **0.000** | **total miss** — no Bool training in v17 |

**Two categories at total miss; one perfect; one near-perfect; three
moderate-to-strong; three partial — the wall is categorical, not
gradient.** The v17 pipeline has zero coverage of `implication` and
`bool` shapes because those proof patterns weren't in the v11 LOFO
training distribution.

## 3. First-verified-rank distribution (policy)

```
rank 0 : 14
rank 1 :  3
rank 2 :  4
rank 3 :  2
rank 4 :  1
rank 5 :  2
rank 6 :  0
rank 7 :  0
rank 8 :  1
rank 9 :  1
none in top-10 : 20
```

Where v17 transfers (28 / 48 theorems), it transfers **strongly**:
14 of 28 verifying candidates are at rank 0, 24 of 28 are in top-5.
The reranker is doing its job on shapes the model knows. The 20
no-top-10-verify rows are not a reranker problem — the **generator**
didn't produce a verifying candidate at all on those 20.

## 4. Error taxonomy (across all top-10 slots × 48 theorems = 480
   slots; policy config)

| class | count |
|---|---:|
| `unknown_identifier` | 133 |
| `type_mismatch` | 118 |
| `parse_error` | 86 |
| `other` | 61 |
| `timeout` | 23 |
| `unsolved_goals` | 2 |
| `unknown_tactic` | 1 |
| `ok` (verified) | ~56 |

**`unknown_identifier` is the dominant failure** (133 / 480 = 28 % of
candidates). v17's models learned specific identifier patterns
(`h`, `hp`, `hnp`, `hpq`, `hnq`); v18 introduces unfamiliar names
(`hf`, `hImp`, `hand`, `prf`, list / Bool variables) and the model
references identifiers that don't exist in the test theorem's local
context.

## 5. What the comparison tells us

| dimension | v17 templated benchmark | v18 broad-core benchmark | gap |
|---|---:|---:|---|
| n test theorems | 30 unique | 48 unique | 1.6 × larger |
| category coverage | 5 narrow families | 10 broader categories | 2 × broader |
| variable namings | hand-curated, ~7 pairs | mixed, dozens of names | mixed |
| **mean pass@5 (best config)** | **1.000** | **0.500** | **−50 %** |
| **mean pass@10 (best config)** | **1.000** | **0.583** | **−42 %** |
| n no-candidate-verified | 0 / 30 | **20 / 48** | catastrophic on the missing categories |

The 50 % drop is not gradual — it's bimodal: v17 either crushes a
category (1.000 / 0.800+) or completely misses it (0.000). This is
the wall.

## 6. What v18 explicitly does NOT claim

* **Not full theorem proving.** The 48 v18 theorems are still
  small relative to Mathlib (~200 k). 0.500 pass@5 on v18 ≠ general
  theorem proving.
* **Not retconning v17 metrics.** v17 closed the v11 LOFO
  benchmark; that result stands as a *templated-benchmark* result.
  v18 is the next wall, not a downgrade of v17.
* **Not Mathlib.** Tier C skipped honestly (Mathlib unavailable in
  this env).
* **No state_after**, **no manual oracle counted as model
  prediction**, **no v10-leakage revival**.
* **Not "v15 learned beats rule globally".** On v18 the rule and
  policy configs tie at pass@5 = 0.500; learned alone is slightly
  worse (0.479). The v15 audit finding holds: each ranker wins on
  different distributions.
* **The 56 verified candidates** in this run are model-generated
  + lean-cli-verified; the 109 hand-authored verified rows from
  the v18 corpus are gold labels, *not* model outputs.

## 7. Part 5 — single broad-synthetic model on v18

`scripts/train_v18_broad_synthetic_model.py` trains **one** token
seq2seq on the *union* of clean synthetic verified rows:

| source | rows contributed |
|---|---:|
| v11 LOFO train (5 families, deduplicated) | 1010 |
| v16 contrapositive corpus | 137 |
| v17 arrow_false_elim corpus | 144 (incl. siblings) |
| **after v18 leakage guards (name + triple)** | **1151 unique training rows** |

* 156-token vocab, same v14 architecture (embed 96, hidden 128,
  beam 10), 20 epochs, deterministic seed, ~2 min CPU.
* val_greedy_exact_top1 at last epoch: **0.152** — modest but
  consistent with a small CPU model on a multi-shape corpus.
* Saved to `data/models/token_seq2seq_v18_broad_synthetic/`.

### Broad-synthetic-only eval on v18 (no v17 family panel)

This is **the cleanest scaling test**: one general model trained on
all synthetic data, evaluated on v18.

| config | pass@1 | pass@5 | pass@10 | MRR | no_verify | malformed_top1 |
|---|---:|---:|---:|---:|---:|---:|
| raw | **0.500** | **0.562** | 0.604 | 0.527 | 19 | 0 |
| rule | **0.521** | **0.583** | 0.604 | 0.555 | 19 | 0 |
| learned | 0.458 | 0.562 | 0.604 | 0.508 | 19 | 0 |
| **policy** | **0.500** | **0.583** | **0.604** | 0.537 | 19 | 0 |

**The broad-synthetic model BEATS the v17 5-family panel:**

| metric | v17 panel + policy | **broad-synthetic-only + policy** | Δ |
|---|---:|---:|---:|
| pass@1 | 0.292 | **0.500** | **+0.208** |
| pass@5 | 0.500 | **0.583** | **+0.083** |
| pass@10 | 0.583 | **0.604** | **+0.021** |
| n no-candidate-verified | 20 / 48 | 19 / 48 | −1 |
| n malformed top-1 | 3 | **0** | **−3** |

The panel of family-LOFO specialists was **over-fit** to its
narrow training distributions; a single broad-synthetic model
generalises better — even though both see exactly the same
underlying synthetic data.

### Per-category breakdown (broad-synthetic-only, policy)

| category | n | pass@1 | pass@5 | pass@10 | Δ pass@5 vs panel |
|---|---:|---:|---:|---:|---:|
| `equality_rewrite` | 6 | 1.000 | 1.000 | 1.000 | 0 |
| `conjunction` | 6 | **0.833** | 0.833 | 0.833 | 0 |
| `list` | 5 | **0.800** | **0.800** | **0.800** | **+0.400** |
| `negation` | 5 | 0.400 | 0.800 | 0.800 | 0 |
| `forall` | 3 | 0.667 | 0.667 | 0.667 | 0 |
| `nat_succ` | 5 | 0.600 | 0.600 | 0.600 | 0 |
| `disjunction` | 5 | 0.400 | **0.600** | 0.600 | **+0.400** |
| `exists` | 4 | 0.000 | 0.250 | 0.250 | 0 |
| `implication` | 6 | 0.000 | 0.000 | **0.167** | **+0.167** (pass@10 only) |
| `bool` | 3 | 0.000 | 0.000 | 0.000 | 0 (still total miss) |

**The wall remains: `bool` (zero training data in synthetic
corpus) and most of `implication` (the trivial `exact hp` shape is
absent from v17's `forall_inst`-style "exact h N" training).**

`list` and `disjunction` lift because the broad model picked up
incidental `Or.inl`-shape and `xs.length`-shape signals from
sibling families that the per-fold v17 panel ignored.

### First-verified-rank distribution (broad-synthetic, policy)

```
rank 0 : 24    (50 % of theorems — broad model has better top-1 calibration)
rank 1 :  2
rank 2 :  2
rank 9 :  1
none in top-10 : 19
```

vs panel:
```
rank 0 : 14    (29 %)
... distributed across ranks 0-9
none in top-10 : 20
```

The broad model concentrates verifying candidates at rank 0 more
than the panel does — a real-pass@1 improvement.

## 8. Part 6 — v18 fine-tune (skipped honestly)

The brief marked Part 6 *optional*: "Only after zero-shot result".
After the broad-synthetic test we have a clean reading of the
wall, and the v18 train split is **~33 theorems / ~75 verified
candidate rows** — a fine-tune would *memorise* the train set
rather than test in-domain generalisation. The v18 test split
(~8 theorems) is too small for the resulting numbers to be
statistically meaningful.

Skipped per the brief's escape hatch ("Skip if not needed"). Per
**docs/V18_BENCHMARK_DESIGN.md §7** the train/val/test split files
exist at `data/processed/v18_broad_core/{train,val,test}.jsonl`
for any future v19 work that wants to expand them with more
hand-authored theorems.

## 9. Where the numbers live

| artefact | path |
|---|---|
| zero-shot panel per-config metrics | `data/baselines/v18_zero_shot_v17_pipeline/<config>/metrics.json` |
| zero-shot panel per-row predictions | `data/baselines/v18_zero_shot_v17_pipeline/<config>/predictions.jsonl` |
| broad-synthetic-only metrics | `data/baselines/v18_broad_only_eval/<config>/metrics.json` |
| broad-synthetic + panel union | `data/baselines/v18_broad_synthetic_eval/<config>/metrics.json` (identical to panel-only — broad-synthetic candidates dedup against panel) |
| top-level summary | `data/baselines/v18_zero_shot_v17_pipeline/summary.json` |
| broad-synthetic model | `data/models/token_seq2seq_v18_broad_synthetic/` |
| failure taxonomy | `data/baselines/v18_audit/{failure_taxonomy.json, classified.jsonl}` |
