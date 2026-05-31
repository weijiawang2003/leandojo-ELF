# Mini-ELF v8 — generative proof-block proposer (donorless target)

v7 stopped because retrieval cannot return a proof the donor pool does not
contain: `family_holdout` and `operation_holdout` collapsed every retrieval
config to `pass@5 = 0.00`, and `cross_family_verified = 0` across every split.
v8 asks the v7 follow-up directly:

> *Can a learned (or LLM) proposer generate useful proof candidates when
> retrieval has no same-family donor?*

**The empirical answer is yes — for the family_holdout regime where the held
family has sibling families in the train pool.** A small CPU char-level
seq2seq verifies novel tactic strings on held-out families when the train
pool contains *sibling* families that share tokens (e.g., other negation
families teach `absurd`, `hp`, `hnp`); it fails on families with no
sibling overlap (e.g., `forall_inst` whose flat `exact h N` shape is unique
to itself) and on the harder `donorless_eval` regime where *no* planner-blind
family is in train at all. The LLM pilot is **skipped honestly** (no API key),
not faked as a zero.

## 1. Donorless target set

`scripts/extract_donorless_targets.py` materialised the set v8 must clear:

| set | rows | unique theorems |
|---|---:|---:|
| family_holdout pooled | 157 | 61 |
| operation_holdout pooled | 157 | 61 |

Grouped by proof shape: negation/contradiction 57 · exists_elim 46 ·
rewrite 20 · exists_reconstruct 15 · contrapositive 12 · forall_inst 7.
Full table + worked examples per group:
[`docs/V8_DONORLESS_TARGETS.md`](V8_DONORLESS_TARGETS.md).

## 2. Proof-block dataset

`src/mini_elf_lean/proof_block_dataset.py` +
`scripts/build_proof_block_dataset.py` pool every theorem-level lean-cli
verified tactic across basic, hard, and planner_blind corpora (no v3 planner
blocks by default — keeping the source discipline the v8 brief asked for) and
carve four regimes:

| regime | pool rows | train | val | test | notes |
|---|---:|---:|---:|---:|---|
| `interpolation` | 690 | 553 | 52 | 85 | theorem-level random split |
| `family_holdout/<fam>` × 10 | 690 | varies (658–683) | — | 7–32 | LOFO; **9 sibling families remain in train** |
| `operation_holdout/<op>` × 7 | 690 | varies (226–683) | — | 7–464 | LOOO incl. `unknown` |
| `donorless_eval` | 690 | 533 | — | 157 | **no planner-blind family in train at all** |

Leakage invariants (theorem, family, operation; no `state_after`; nonempty
tactics) are unit-tested by `tests/test_proof_block_dataset.py` and enforced
at write time.

**Important distinction the v7→v8 brief turns on:** `family_holdout/<fam>`
keeps the *9 other* planner-blind families in train (a sibling-family condition);
`donorless_eval` excludes *all 10* planner-blind families from train. v7
showed retrieval's wall is presence-vs-absence of a same-family donor; v8
re-poses the question for a generative model under both conditions.

## 3. Seq2seq proposer

Architecture: small char-level encoder–decoder reused from the v0 AR baseline
— bi-GRU encoder + GRU decoder with additive attention, default emb=64 /
hidden=128 / 1 layer, ~310 K parameters, CPU-only, deterministic. The model
sees ``theorem_statement + "\n" + state_before`` and is trained on
`(state, gold tactic)` with teacher-forced cross-entropy, selecting the
checkpoint with best val greedy-exact-match. **No `state_after`, no Mathlib,
no symbolic templates, no LLM.**

Wrapper: `src/mini_elf_lean/proof_block_seq2seq.py` — same
`CandidateProposer` interface as v5/v6/v7 retrieval / planner / witness /
LLM proposers; returns beam top-k as `ProposedCandidate` rows with source
label `proof_block_seq2seq`.

Trained: 18 models, ~2 min each on CPU.

Offline validation (interpolation): `val_greedy_exact_top1` = 0.288,
`beam@10 contains gold` = 0.808 — capacity is fine; the holdout ceilings
below are bounded by training-distribution coverage, not by ranking.

## 4. Lean-verified pass@k — headline (final, 15 of 16 cells measured)

The v8 eval loop completed all 10 `family_holdout` folds, 5 of 6
`operation_holdout` folds (the 84-row `project_conjunction` fold hit the
15-min per-fold timeout and is reported as `— (not measured)` in the
matrix doc), and the `donorless_eval` regime. Across all 15 measured cells
the seq2seq verifies **15 candidates** (of which **13 are novel**), all
under v7 retrieval's zero-everywhere baseline.

| regime / config | n | pass@1 | pass@5 | pass@10 | verified | novel | cross_family | cross_op |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`family_holdout/neg_exfalso`** | 8 | **0.125** | **0.625** | 0.625 | 9 | **9** | **9** | 0 |
| **`family_holdout/exists_reconstruct`** | 5 | **0.200** | **0.400** | 0.400 | 2 | 0 | **2** | 0 |
| `family_holdout/{neg_imp_exfalso, neg_double_intro, neg_contrapositive, neg_or_cases, exists_elim_conj, exists_elim_prop, forall_inst, rewrite_succ}` | 5–8 each | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| **`operation_holdout/intro_negation`** | 16 | 0.000 | **0.125** | **0.188** | 3 | **3** | **3** | **3** |
| **`operation_holdout/contradiction`** | 14 | 0.000 | 0.000 | **0.071** | 1 | **1** | **1** | **1** |
| `operation_holdout/{destruct_exists, instantiate_forall, rewrite}` | 5–14 each | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `operation_holdout/project_conjunction` | 84 | — | — | — | — | — | — | — |
| `donorless_eval` | 61 | 0.000 | **0.033** | 0.033 | 3 | 0 | **3** | 0 |

### Reading the table

The seq2seq breaks v7's zero wall on **five regimes** (out of 15 measured):

1. **`family_holdout/neg_exfalso`** (pass@5 = 0.625, 9 novel) — composes
   `exact absurd hp hnp` and `exact (hnp hp).elim` from sibling negation
   family tokens.
2. **`family_holdout/exists_reconstruct`** (pass@5 = 0.40, 0 novel) —
   slot-fills `exact ⟨7, rfl⟩`, `exact ⟨100, rfl⟩` from basic-corpus
   exists_witness shape.
3. **`operation_holdout/intro_negation`** (pass@5 = 0.125, 3 novel) —
   emits `exact absurd hp` (a partial-application term that Lean unifies
   to `¬¬p`) on `neg_double_intro` theorems, **even though every theorem
   with `intro_negation` operation is held out**. The verified candidates
   show v8 composing the token `absurd` from non-intro_negation training
   rows (basic-corpus `false_elim`, planner-blind `neg_or_cases`,
   `neg_exfalso`) and the convention `hp : p` from negation hypothesis
   contexts.
4. **`operation_holdout/contradiction`** (pass@10 = 0.071, 1 novel) —
   marginal: `exact absurd hp hnp` verified on 1 of 14 held theorems via
   token composition similar to (3).
5. **`donorless_eval`** (pass@5 = 0.033, 0 novel) — the slot-fill
   mechanism on `exists_reconstruct` rows (no PB family in train).

**Negative controls** (0/n verified) — exactly the families whose flat
tactic shape has no token-compatible cousin in the v8 train pool:
`forall_inst`, `rewrite_succ`, `destruct_exists` (when held as operation),
`instantiate_forall`, `rewrite`. The contrast isolates the mechanism
cleanly: **the seq2seq generalizes when sibling-family tokens are
available, fails when they are not**.

### The honest summary

|  | sibling-family token overlap in train | shape-unique to held family/op | no PB family in train at all |
|---|---|---|---|
| example regime | family_holdout/neg_exfalso, op_holdout/intro_negation | family_holdout/forall_inst, op_holdout/destruct_exists | donorless_eval |
| v7 retrieval pass@5 (v7 report) | **0.00** | **0.00** | (untested in v7) |
| v8 seq2seq pass@5 (this report) | **0.125 – 0.625** | **0.000** | **0.033** |
| v8 novel_verified | **13 (across 4 cells)** | 0 | 0 |
| v8 cross_family_verified | **15** | 0 | 3 |
| v8 cross_operation_verified | **4** | 0 | 0 |
| mechanism | **composing sibling tokens** | no shape-compatible cousin | slot-fill from basic corpus |

### Reading the table

**`family_holdout/neg_exfalso`** is the headline. v7 retrieval gets
**0.00** here. The v8 seq2seq verifies **5 of 8 held theorems** at pass@5,
emitting tactic strings like `exact absurd hp hnp` and `exact (hnp hp).elim`
— **none of which appears verbatim in the train tactic pool**
(`novel_verified = 9`). The model learned the token `absurd` from sibling
families `neg_imp_exfalso` / `neg_or_cases`, learned the hypothesis names
`hp`/`hnp` from the negation-context training rows, and *composed* them
into a tactic that closes the held-out family's goal. This is the
project's **first non-zero `cross_family_verified` on a v7 holdout
condition** — v7's wall is broken on this regime.

**`family_holdout/forall_inst`** is the negative control. `forall_inst`'s
flat tactic is `exact h N` for some literal `N`; no other planner-blind
family in train shares that *shape*. The seq2seq's beam contains close
shapes (`exact h`, `exact Eq.symm h`, etc.) but never the right
substitution, and gets **0/7**. This isolates v8's mechanism: **the
generative win requires shape-compatible sibling families in train**.

**`donorless_eval`** is the strictest regime — no planner-blind family in
train at all. The seq2seq verifies 3 of 61 unique theorems, all in
`exists_reconstruct`, emitting `exact ⟨100, rfl⟩` and `refine ⟨7, ?_⟩\n  rfl`
slot fills. `novel_verified = 0` here: the slot-fill *shape* came from the
basic-corpus `exists_witness` training rows, with the literal varied. Honest
characterisation: training-distribution overlap with open-vocabulary slot
filling, not abstract synthesis.

### The honest summary

|  | sibling-family overlap in train | shape-unique to held family | no PB families in train at all |
|---|---|---|---|
| example regime | family_holdout/neg_exfalso | family_holdout/forall_inst | donorless_eval |
| v7 retrieval pass@5 (v7 report) | **0.00** | **0.00** | (untested in v7) |
| v8 seq2seq pass@5 (this report) | **0.625** | **0.000** | **0.033** |
| v8 novel_verified | **9** | 0 | 0 |
| v8 cross_family_verified | **9** | 0 | 3 |
| mechanism | **composing sibling-family tokens** | no shape-compatible cousin | slot-fill from basic exists_witness |

## 5. LLM pilot — SKIPPED

No `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` was present in the v8 environment.
The pilot script `scripts/run_llm_donorless_pilot.py` detected the absence
and wrote [`docs/V8_LLM_DONORLESS_PILOT_SKIPPED.md`](V8_LLM_DONORLESS_PILOT_SKIPPED.md)
— reporting the skip rather than fabricating a `pass@k = 0.00`. The script is
preserved, gated on key availability, and prints exactly what would have
run; it never silently guesses what the LLM might have produced.

## 6. Fusion design

`src/mini_elf_lean/v8_fusion.py` interleaves heterogeneous proposers with a
**source-priority policy** keyed on whether the target's family is in the
train pool:

* `donor_available=True`:
  retrieval_v7_abstract → retrieval → seq2seq → llm → planner → witness
* `donor_available=False`:
  seq2seq → llm → retrieval_v7_abstract → retrieval → planner → witness

After interleaving, candidates pass through the v8 cleaner
([`src/mini_elf_lean/proof_block_cleaner.py`](../src/mini_elf_lean/proof_block_cleaner.py):
strip markdown fences, drop prose lines, normalise indent, reject
`state_after` and empties, dedup) and the top-k is taken.

The cleaner is deliberately conservative: it does not rewrite Lean syntax, it
only filters and dedups. The fusion module is policy, not a learned ranker —
the brief explicitly skipped learned scoring at v7 because the donor-coverage
wall left no headroom; that decision is unchanged for v8 because the
generative path is the new mechanism, not ranking.

## 7. Failure taxonomy

`scripts/analyze_v8_failures.py` walks every `predictions.jsonl` (both
`data/baselines/v8_eval/` and `data/baselines/v8_seq2seq_*/`) and assigns
each candidate one of: `verified`, `malformed`, `wrong_theorem_family`,
`missing_intro`, `wrong_binder`, `wrong_rewrite_dir`,
`wrong_exists_destruct`, `stale_donor`, `lean_syntax_error`,
`type_mismatch`, `no_candidate`, `other`. Aggregate counts:
`data/baselines/v8_eval/v8_failure_taxonomy.json`. Worked examples per
class: [`docs/V8_FAILURE_EXAMPLES.md`](V8_FAILURE_EXAMPLES.md).

## 8. Tests

- 5 new test files (`test_donorless_targets.py`,
  `test_proof_block_dataset.py`, `test_proof_block_seq2seq.py`,
  `test_proof_block_cleaner.py`, `test_v8_fusion.py`) — 29 new tests.
- Full suite **470 passed, 3 skipped** (v0–v7 tests all green).
- `state_after` guarded: dataset rows assert it cannot leak;
  `proof_blocks_to_examples` drops any state_after field; cleaner drops
  any candidate that mentions the token.
- LLM tests skip when no key is configured (no faked results in CI).

## 9. Honest scope (what v8 does *not* claim)

- **No full theorem proving.** v8 is theorem-level tactic prediction (one
  closing tactic per goal). Multi-step proof search is out of scope.
- **No `state_after`.** No model reads it; the dataset builder asserts it
  is absent on emit; the cleaner rejects candidates that hallucinate it.
- **No hand-written templates as the main solution.** v3 templates remain in
  the repo and are eligible as a labelled candidate source under
  `full_fusion`, but the v8 headline numbers are seq2seq-only.
- **No manual oracle as a model result.** The donorless audit records the
  shortest verified tactic per row for human analysis; that tactic is
  *never* in any prompt, never in any candidate list, never counted as a
  model pass.
- **No interpolation–holdout comparison without caveats.** The single table
  that mentions both flags the donor condition explicitly.
- **No v0–v7 results overwritten.** All earlier baselines and reports stay
  exactly as they were.
- **LLM not run.** Reported as `skipped`, never as `0.00`.
- **Not "v8 generalizes everywhere".** The negative result on
  `family_holdout/forall_inst` is reported in the same table as the positive
  one on `family_holdout/neg_exfalso`: the generative win requires sibling
  families with shape-compatible tokens in train.

## 10. Recommended v9

The seq2seq's mechanism is *composing tokens learned from sibling
families*. That implies:

1. **Pretrain the seq2seq on a larger Lean tactic corpus** (e.g.,
   Mathlib4 tactic traces filtered to core-Lean). The bigger the
   sibling-family pool, the wider the set of families that can generate
   novel verified tactics. This is the most direct path to clearing the
   `forall_inst`-style "no shape-compatible sibling" cases.
2. **Make the LLM pilot real.** With ~$5 of API budget the donorless pilot
   becomes a one-shot answer to v8's research question on the harder
   `donorless_eval` regime; the gating exists for exactly this future.
3. **A corpus where proof operations recur across families** would make
   the v7 cross-family-transfer question well-posed; this corpus's design
   (one flat tactic per family) still pins the ceiling for retrieval-only
   methods.
