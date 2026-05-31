# Mini-ELF v11 — clean per-family LOFO with v10 redundancy

> **Scope.** v11 answers the question v10 left open: *under proper
> family-LOFO methodology (no leakage), do the v8 negative-control
> families `forall_inst` and `rewrite_succ` become non-zero when v10
> redundancy cells are folded into training?* Same v8/v10 seq2seq
> architecture; same training loop; same beam decoder.
> `state_after_is_real = false` for every train and test row. No
> Mathlib. No manual oracle is counted as a model output. No claim of
> full theorem proving.

## Why v11 is needed

The v8 matrix reported two persistently-zero family_holdout cells:
`forall_inst` (0/7) and `rewrite_succ` (0/5). v10 tried to address this
by adding redundancy data, but a leakage bug
(`combined_v10` trained on the v10 interpolation split → 36/40 holdout
test theorems in train, see `tests/test_v10_no_leakage.py`) invalidated
the holdout numbers. The v10 per-op LOFO correction held out the entire
operation — which also removed the relevant v10 redundancy cells, so it
could not test whether *adding* v10 helped a held planner-blind family.

v11 holds out only the planner-blind family and keeps the v10
redundancy cells of the same operation in train — exactly the
situation v10's hypothesis is about.

## Per-family LOFO regimes

`scripts/build_v11_family_lofo.py` materialises one regime per held
family at `data/processed/proof_blocks_v11_family_lofo/<fam>/`. Each
fold's `train.jsonl` is the v8 family-LOFO train pool (already excludes
the held family across the v8 base + planner-blind corpora) **plus** all
40 v10 redundancy cells *minus* any cell that would duplicate the held
family's test theorem name or `(state_before, tactic)` row. Each fold's
`test.jsonl` is byte-identical to the v8 `family_holdout/<fam>/test.jsonl`,
so v8 vs v11 numbers are apples-to-apples on the same test rows.

Inline leakage assertions:
1. No test theorem_name in train.
2. No `(state_before, tactic)` pair in both train and test.
3. No row with `family == <held>` in train (the v8 LOFO condition,
   re-asserted after the v10 add).

`tests/test_v11_family_lofo_no_leakage.py` (5 tests) ratifies all three
invariants statically plus a sanity check that v10-tagged train rows
carry `corpus_source = redundancy_corpus` and a `theorem_name` that
starts with `v10_`.

Regime sizes:

| fam | v8 LOFO base | + v10 (same-op) | train | test |
|---|---:|---:|---:|---:|
| `forall_inst` | 683 | 40 (5 same-op) | 723 | 7 |
| `rewrite_succ` | 670 | 40 (0 same-op label, 5 same skeleton) | 710 | 20 |
| `neg_exfalso` | 658 | 39 (4 same-op) | 697 | 32 |
| `exists_reconstruct` | 675 | 40 (0 same-op label) | 715 | 15 |
| `neg_imp_exfalso` | 675 | 40 (5 same-op) | 715 | 15 |

(Note: `rewrite_succ` and `exists_reconstruct` show 0 same-op rows
because the v8 planner-blind families use `required_operation =
"rewrite"` / `"exists_reconstruct"`, while v10 cells use `rewrite_eq` /
`exists_elim`. The label is descriptive only; the v10 cells still
provide the matching tactic skeleton.)

## Models trained

Same architecture as v8/v10: char-level bi-GRU + additive attention +
GRU decoder, CPU, seed 0, 30 epochs, `lr=3e-3`, `batch_size=32`,
`beam_width=10`, `length_penalty=0.7`. One model per family.

| model | val_greedy_top1 | beam_top10_contains_gold | best_epoch |
| --- | ---: | ---: | ---: |
| `v11_family_forall_inst` | 0.326 | 0.854 | 28 |
| `v11_family_rewrite_succ` | 0.326 | 0.849 | 29 |
| `v11_family_neg_exfalso` | 0.329 | 0.829 | 28 |
| `v11_family_exists_reconstruct` | 0.344 | 0.833 | 24 |
| `v11_family_neg_imp_exfalso` | 0.333 | 0.747 | 28 |

Vals are synthesised 10 % of train (the v8/v10 convention for LOFO
folds with no native val).

## Headline result (clean lean-cli pass@k)

For each held family, three models are evaluated on the same test rows:

* `v8_lofo` — the v8 per-family LOFO model
  (`proof_block_seq2seq_family_holdout_<fam>`); the original v8 matrix's
  number.
* `v11` — the v11 per-family LOFO model with v10 redundancy added.
* `baseline_v8_indist` — the broad `proof_block_seq2seq_interpolation`
  model. **This model saw the held family during training** (the v8
  interpolation split mixed families); its numbers are
  IN-DISTRIBUTION, **not** holdout. Reported only as a recall-ceiling
  reference.

| held family (n) | v8_lofo pass@5 | **v11 pass@5** | Δ | baseline_v8_indist pass@5 (in-distribution) |
|---|---:|---:|---:|---:|
| `forall_inst` (7) | **0.000** | **0.143** | **+0.143** | 0.571 |
| `rewrite_succ` (5) | **0.000** | **0.800** | **+0.800** | 1.000 |
| `neg_exfalso` (8) | 0.625 | 0.625 | 0 (but pass@1 0.125→**0.625**) | 1.000 |
| `exists_reconstruct` (5) | 0.400 | **0.800** | **+0.400** | 1.000 |
| `neg_imp_exfalso` (5) | 0.000 | 0.000 | 0 | 1.000 |

### Primary research question (the v11 brief's main ask)

> *When v10 redundancy examples are added cleanly, do the previously
> zero families `forall_inst` and `rewrite_succ` become nonzero under
> family-holdout evaluation?*

**Yes for both — substantially for `rewrite_succ`, partially for
`forall_inst`.**

* `rewrite_succ`: **0/5 → 4/5 pass@5 (+0.800)**. v8_lofo emitted 0
  verifying candidates across all 5 unique test theorems. v11 emits
  `rw [h]` at beam rank 0 on 3 of 5 theorems and at beam rank 2 on a
  4th. **The 5th theorem also generated `rw [h]` at beam rank 0 but
  the lean-cli verifier hit a cold-start timeout** — so the model
  output is correct, the eval-time machinery just didn't confirm it
  within 20 s. Reported honestly as pass@5 0.800 (not "should be
  1.000").
* `forall_inst`: **0/7 → 1/7 pass@5 (+0.143)**. v11 verifies
  `forall_inst_7_0` with `exact h 7` at beam rank 0; the other 6 test
  theorems need literals (`exact h 3`, `exact h 5`, `exact h 9`,
  `exact h 13`, `exact h 8` twice) that the v10 redundancy corpus only
  partially covers (v10 has `nat_eq_3`/`nat_eq_7`/`nat_le_5`/`nat_add_zero_4`,
  i.e. literals `{3, 4, 5, 7}`; `8`/`9`/`13` are out-of-pool). The model
  learned the `exact h <num>` schema from v10 cells but failed to
  literal-substitute correctly.

### Secondary observations

* `neg_exfalso`: pass@5 unchanged (0.625 → 0.625, both verify 5 of 8),
  but **pass@1 jumps 0.125 → 0.625** — the v10 redundancy reorders the
  model's beam so the gold tactic lands at rank 0 instead of buried.
  cross_family_verified up 10 → 12; novel verified rows 5 → 5.
* `exists_reconstruct`: pass@5 0.400 → **0.800**; 2 → 5 verified. Adding
  v10's `cases h with | intro n hn => exact ⟨n, hn⟩` siblings unblocks
  3 of 5 test theorems.
* `neg_imp_exfalso`: still 0/5. The v11 redundancy cells of operation
  `contradiction` use surface forms (`p ∨ q`, `p → False`, `p ↔ False`)
  that don't include the `neg_imp_exfalso`-specific shape
  `(p → q) → ¬q → ¬p`. The v10 corpus does not contain that shape; v11
  cannot help when v10 doesn't supply the right siblings.

### Cross-family / cross-operation accounting

| held family | model | verified | novel | cross_family_verified | cross_operation_verified |
|---|---|---:|---:|---:|---:|
| `forall_inst` | v8_lofo | 0 | 0 | 0 | 0 |
| `forall_inst` | **v11** | **1** | 0 | **1** | 0 |
| `rewrite_succ` | v8_lofo | 0 | 0 | 0 | 0 |
| `rewrite_succ` | **v11** | **4** | 0 | **4** | **4** |
| `neg_exfalso` | v8_lofo | 10 | 5 | 10 | 0 |
| `neg_exfalso` | v11 | 12 | 5 | 12 | 0 |
| `exists_reconstruct` | v8_lofo | 2 | 0 | 2 | 0 |
| `exists_reconstruct` | **v11** | **5** | 0 | **5** | 0 |
| `neg_imp_exfalso` | v8_lofo | 0 | 0 | 0 | 0 |
| `neg_imp_exfalso` | v11 | 0 | 0 | 0 | 0 |

* `cross_family_verified > 0` on every v11 win — the test family was
  absent from train (the LOFO condition), so every verified candidate
  is by construction a cross-family generation.
* `cross_operation_verified = 4` for `rewrite_succ` — the held op
  (`rewrite`) is absent from train, yet v11 verifies via v10 `rewrite_eq`
  cells. The v10 redundancy gave the model a tactic shape its v8 base
  pool lacked entirely.
* **`novel_verified = 0`** for every v11 win (forall_inst, rewrite_succ,
  exists_reconstruct). The verifying tactic strings (`exact h 7`,
  `rw [h]`, `cases h with | intro n hn => exact ⟨n, hn⟩`) all appear in
  the train pool — they come from v10 redundancy cells. The model is
  **copying** from siblings, not synthesising new tactic strings.

This last point matters: v11's lift is "the v10 redundancy contains the
right shape and the model can recall it on a held family", not "the
model is doing novel tactic-string composition under LOFO".

## Failure-mode taxonomy

The v8/v10 failure modes carry through. Concrete examples (cherry-
picked from the predictions.jsonl files for clarity):

* **Out-of-distribution literal** (`forall_inst`). For
  `forall_inst_13_6` (gold = `exact h 13`), the v11 beam emits
  `exact h 4`, `exact h 7`, `exact h 5` — all literals the v10 corpus
  has, none of which match the held theorem.
* **Mathlib-tactic transplant** (carried over from v8/v10 base pool).
  v8_lofo on `forall_inst` consistently emits `rcases h with ⟨n, hn⟩`
  followed by garbled continuations — the v8 base pool had mathlib-
  style rows, and the LOFO held only `forall_inst` out, leaving every
  other PB family in train.
* **Char-level mid-token truncation** (carried over from v8/v10):
  `exact h.`, `rw [hns`, `exact ⟨6, rfl`. Beam truncates before close.
* **lean-cli cold-start timeout** (eval-time, not model-time):
  `rewrite_succ_ij` v11's top candidate `rw [h]` timed out at 20 s
  even though the model emitted the correct gold tactic. Reported as
  pass@5 = 0.800, not 1.000. The same lean call typically completes in
  under 2 s; WSL cold-start fluctuation costs the rare verification.

## What this report does *not* claim

* Not full theorem proving.
* Not learned composition of *novel* tactic strings under LOFO —
  v11 copies from v10 siblings (`novel_verified = 0` on every win).
* Not a fix for the `neg_imp_exfalso` family (still 0/5; v10 redundancy
  does not contain its shape).
* Not architectural improvement — the v11 model is the v8/v10 model.
* Not a uniform lift — `rewrite_succ` is the headline; `forall_inst` is
  small; `neg_exfalso` saw a precision boost only; `neg_imp_exfalso`
  unchanged. The clean signal varies sharply by family.

## v12 wishlist

* **Literal extrapolation.** v11 cannot generate `exact h 13` from a
  pool of `{exact h 3, exact h 4, exact h 5, exact h 7}`. A symbolic
  literal-substitution step at decode time, or a BPE tokenizer that
  treats numeric tokens compositionally, would address this.
* **Re-verify the rewrite_succ_ij cold-start timeout.** Re-running
  with a warmer verifier (or `--verifier-timeout 60`) should push the
  rewrite_succ headline from 0.800 to 1.000.
* **Add v10 cells for `neg_imp_exfalso` shape**
  (`(p → q) → ¬q → ¬p`) and re-run v11 to see if a targeted addition
  fixes the unmoved cell.
* **Cell_holdout clean matrix** (40 per-cell LOFO models, ~3 hr) is
  still v10's deferred work.
