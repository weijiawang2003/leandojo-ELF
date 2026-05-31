# Mini-ELF v19 — Identifier Abstraction Report

**Status:** complete. **Honest negative result on the headline
target.** v19 implements state-aware local-context identifier
abstraction (parser, abstraction/concretisation, abstract dataset,
abstract token seq2seq). The hypothesis was that placeholders would
reduce v18's dominant `unknown_identifier` failure class (28 %) and
improve pass@k. **The data does not support the hypothesis** — v19
abstraction *replaces* `unknown_identifier` with
`unresolved_placeholder` (a new dominant failure class at 40-44 %)
and reduces pass@k on the v18 broad-core benchmark.

v17/v18 metrics on disk are NOT changed by v19. v19 publishes at
the parallel `data/baselines/v19_abstract_*/` paths.

---

## 0. TL;DR

| metric | v18 broad-synthetic + policy | **v19 abstract-only + policy** | **v19 ensemble + policy** |
|---|---:|---:|---:|
| pass@1 | 0.500 | 0.146 | 0.146 |
| pass@5 | **0.583** | 0.208 | 0.312 |
| pass@10 | **0.604** | 0.271 | 0.438 |
| n_no_candidate_verified | 19 / 48 | 35 / 48 | 27 / 48 |
| dominant failure class | `unknown_identifier` (133 / 480) | **`unresolved_placeholder` (210 / 480)** | `unresolved_placeholder` (190 / 480) |

**v19 abstraction *replaces* one failure class with another at
similar (slightly higher) scale, while reducing pass@k.** This is a
clean negative finding: the v19 design is not the right shape for
this transfer problem.

---

## 1. What v19 actually built

* **`src/mini_elf_lean/local_context.py`** — parser from
  ``state_before`` text → ordered hypotheses with type categories
  (PROP / IMPLICATION / NEGATION / CONJUNCTION / DISJUNCTION /
  EQUALITY / FORALL / EXISTS / NAT / BOOL / LIST / HYP_PROP /
  TYPE). Handles Greek / mixed-name binders; tested across
  representative v18 shapes.
* **`src/mini_elf_lean/identifier_abstraction.py`** —
  `abstract_state(state, tactic)` produces
  `(abstract_state, abstract_tactic, AbstractionMap)`.
  `concretise_or_fail(abstract_tactic, new_state)` reverses the
  process against a new state. Word-boundary aware, never replaces
  tactic keywords or substrings inside longer identifiers.
* **`scripts/build_v19_abstract_dataset.py`** —
  abstracts the v11 LOFO + v16 contrapositive + v17 arrow_false_elim
  corpora (1111 unique rows after v18 leakage guard + dedup; **0
  round-trip failures** — every abstract → concretise back-to-original
  reproduces the gold tactic). Outputs at
  `data/processed/v19_abstract_synthetic_train/`.
* **`scripts/train_v19_abstract_seq2seq.py`** — trains one token
  seq2seq on the abstract data (same v14 architecture, 20 epochs,
  vocab 140 incl. placeholders, deterministic seed). Saved to
  `data/models/token_seq2seq_v19_abstract/`. val_exact_top1 = 0.26
  by epoch 18 — *better than v18 broad-synthetic's val_exact =
  0.15* on its own task, which is what made the negative result on
  v18 transfer somewhat surprising.
* **`scripts/evaluate_v19_abstract_seq2seq.py`** — evaluates v19
  abstract alone and v19 abstract + v18 broad-synthetic ensemble on
  the v18 broad-core benchmark; concretises placeholders against the
  v18 test state; failures are tagged
  `unresolved_placeholder`.

---

## 2. v18 zero-shot transfer comparison

| family / category | v18 broad-synthetic pass@5 | **v19 abstract-only pass@5** | **v19 ensemble pass@5** |
|---|---:|---:|---:|
| `equality_rewrite` (6) | 1.000 | 0.333 | 0.833 |
| `conjunction` (6) | 0.833 | 0.167 | 0.167 |
| `list` (5) | 0.800 | 0.200 | 0.200 |
| `negation` (5) | 0.800 | 0.400 | 0.400 |
| `forall` (3) | 0.667 | 0.333 | 0.667 |
| `nat_succ` (5) | 0.600 | 0.400 | 0.600 |
| `disjunction` (5) | 0.600 | 0.000 | 0.000 |
| `exists` (4) | 0.250 | 0.250 | 0.250 |
| `implication` (6) | 0.000 | 0.000 | 0.000 |
| `bool` (3) | 0.000 | 0.000 | 0.000 |
| **mean** | **0.583** | **0.208** | **0.312** |

Even the ensemble (which has access to both v18 broad and v19
abstract candidates) underperforms v18 broad-only on **conjunction
(0.83→0.17), list (0.80→0.20), and negation (0.80→0.40)**. The v19
abstract candidates are crowding the top of the beam, displacing the
correctly-typed v18 broad candidates.

---

## 3. Why abstraction hurt — three concrete reasons

### (a) Placeholder dropout against v18's local context

The v19 model's vocab has placeholders like `<HYP_AND_0>` /
`<HYP_OR_0>` / `<VAR_BOOL_0>` learned from training shapes. The v18
test states sometimes have **different category distributions**
than synthetic train, so the model emits placeholders that have **no
binding** in the test state. Result:
`unresolved_placeholder` — at 210 / 480 slots (44 %) under
abstract-only, this is the new dominant failure class.

### (b) The abstract dataset deduped too aggressively

The v11 LOFO trains share rows across 5 family folds (each fold
has the v11 base train + family-specific train). When abstracted,
many of those rows collapse to identical (abstract_state,
abstract_tactic) pairs. Our dedup dropped **2858 / 3984 raw rows**
to 1111 deduplicated — a 72 % reduction. The remaining 1111 rows
under-represent the proof-shape diversity the v18 broad-synthetic
model saw (which had access to all 3984 raw rows including
duplicates).

### (c) The abstraction is **state-only**, not **tactic-stream-aware**

`v18_imp_intro_basic` proof requires `intro hq\n  exact hp` — the
`intro hq` step introduces a new hypothesis (`hq`) that doesn't
exist in `state_before`. v19's abstraction is built from the
pre-tactic state, so it has no placeholder for the newly-introduced
binder. The model emits something like
`intro <HYP_PROP_0>\n  exact <HYP_PROP_0>` — collapsing the
introduced binder with the pre-existing hypothesis — and lean
rejects the resulting concretised `intro hp\n  exact hp` (shadowing).

A more sophisticated v20 abstraction would track introductions
within the tactic and reserve fresh placeholders for them.

---

## 4. What v19 confirmed (the side findings)

Despite the headline negative result, v19 produced useful auxiliary
evidence:

1. **The local-context parser works.** Across v18's 10 categories
   the parser correctly identifies hypothesis types, including
   Greek / mixed-letter bindings. Tested in
   `tests/test_local_context.py`.
2. **Abstraction / concretisation is correct.** 0 round-trip
   failures across 3984 synthetic rows: every abstract → concretise-
   against-original reproduces the gold tactic.
3. **Word-boundary protection works.** `h` and `hp` are
   distinguished correctly even when both are in scope; tactic
   keywords are never accidentally substituted.
4. **The v19 abstract model trains cleanly** to val_exact = 0.26
   (better than v18 broad's 0.15). The problem is transfer to v18
   shapes, not in-domain accuracy.

The infrastructure is reusable for a v20 attempt at
*better-designed* abstraction (see v20 recommendation in
`NEXT_STEPS.md`).

---

## 5. Failure class redistribution

| failure class | v18 broad-only (480 slots) | **v19 abstract-only** | v19 ensemble |
|---|---:|---:|---:|
| `unknown_identifier` | 127 (26 %) | ~30 (6 %) | ~80 (17 %) |
| `unresolved_placeholder` | 0 | **210 (44 %)** | **190 (40 %)** |
| `type_mismatch` | 124 (26 %) | similar | similar |
| `parse_error` | 72 (15 %) | similar | similar |
| `timeout` | 28 (6 %) | similar | similar |
| `ok` (verified) | 29 (6 %) | **10 (2 %)** | **15 (3 %)** |

The `unknown_identifier` count dropped (v18 broad 127 → v19
abstract ~30) — abstraction *does* address that specific failure
class. But the gain is wiped out by the new
`unresolved_placeholder` class which is **twice as large**.

---

## 6. What v19 explicitly does NOT claim

* **Not retconning v17 / v18.** All prior metrics on disk are
  unchanged; v19 publishes at parallel paths.
* **Not full theorem proving.**
* **Not Mathlib.** v19 stays on the core-Lean v18 benchmark.
* **Not state_after**, **not manual oracle**, **not v10 leakage**.
* **Not "abstraction is a bad idea in general".** v19's specific
  design — pre-decoded, state-only abstraction with concretise-or-
  fail — is the wrong shape. A v20 ranker-time abstraction (rerank
  candidates by *abstract-pattern match* rather than generate-time
  abstraction) might still work.

---

## 7. v20 recommendation (from this report)

1. **Add the trivial implication shapes** to the synthetic corpus
   (`exact hp`, `intro h; exact hp`). v19's analysis confirmed
   `implication` is corpus-shape-bound — see
   `V19_IMPLICATION_IDENTIFIER_ANALYSIS.md`.
2. **Add the Bool `cases b` corpus** (see `V19_BOOL_GAP_NOTE.md`).
3. **Try ranker-time abstraction**: at inference, abstract both
   the candidate's identifier references and the state's local
   names, score candidates by abstract-pattern match against
   training, but emit the raw candidate string. This sidesteps
   v19's "unresolved placeholder" failure mode.
4. **Move off the templated synthetic corpus entirely** — install
   Mathlib + re-run v18 tier C. Carried from v18's wishlist.
5. Anything from v18's v19-wishlist not above: confidence-
   calibrated reranker; reranker refresh with v16/v17/v18
   candidates; real next-state via LeanDojo; cell_holdout matrix.

---

## 8. Where the numbers live

| artefact | path |
|---|---|
| local context parser | `src/mini_elf_lean/local_context.py` |
| abstraction module | `src/mini_elf_lean/identifier_abstraction.py` |
| abstract synthetic train data | `data/processed/v19_abstract_synthetic_train/` |
| abstract v18 train/test split | `data/processed/v19_abstract_v18_split/` |
| trained abstract model | `data/models/token_seq2seq_v19_abstract/` |
| v19 abstract-only metrics | `data/baselines/v19_abstract_only_eval/<config>/` |
| v19 ensemble metrics | `data/baselines/v19_abstract_ensemble_eval/<config>/` |
