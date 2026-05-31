# Mini-ELF v10 — redundancy corpus report

## What the v10 corpus is

v8 isolated a specific mechanism for the seq2seq's only non-zero
holdout regimes: **token composition across sibling families that share a
proof operation**. When the train pool contained shape-compatible siblings,
the model verified novel tactics on a held-out family
(`family_holdout/neg_exfalso` pass@5 = 0.625; nine novel verified tactic
strings). When no sibling was present (`family_holdout/forall_inst`,
`family_holdout/rewrite_succ`) the model stayed at 0/n.

v10 tests the **data-scaling** hypothesis behind that observation: *if we
build a corpus where each proof operation is intentionally redundant across
multiple sibling surface families, does the seq2seq generalise more
reliably to held-out families/operations?* No new architecture; same
char-level seq2seq from v8.

The corpus is built by `scripts/generate_redundancy_corpus.py` and committed
to:

- `data/seeds/redundancy_seeds.jsonl` — **40** verified theorem seeds
- `data/manual/redundancy_candidates.jsonl` — one candidate per seed (the
  verified tactic)
- `data/processed/redundancy_lean_cli/next_tactic.jsonl` — **40**
  processed rows in the v6/v7/v8 schema
- `data/traces/redundancy_lean_cli_verified.jsonl` — verified-trace audit
  file (40 rows)
- `data/traces/redundancy_lean_cli_failed.jsonl` — refused-cell audit
  file (currently 0 rows; preserved as a header-only file for the
  trace-auditor's discovery convention)

## Design

40 design cells covering **8 proof operations × 5 surface families** each.
Each cell shares the operation's *closing-tactic shape* with its siblings,
but uses a distinct surface form: different variable names (`p/q` vs
`a/b` vs `r/s`), different proposition names, hypothesis order, and
theorem-statement nesting. The 8 operations are:

| operation | shared tactic shape | example tactic |
| --- | --- | --- |
| `contradiction` | `exact absurd <hp> <hnp>` | `exact absurd hp hnp` |
| `intro_negation` | `intro <h>; exact <hnq> (<h> <hp>)` | `intro hp; exact hnq (h hp)` |
| `instantiate_forall` | `exact <h> <args>` | `exact h 7` |
| `rewrite_eq` | `rw [<h>]` | `rw [h]` |
| `exists_elim` | `cases <h> with \| intro n hn => exact …` | `cases h with \| intro n hn => exact ⟨n, hn⟩` |
| `implication_chain` | `exact <hk> ( … (h1 hp))` or `intro hp; exact …` | `exact h2 (h1 hp)` |
| `conjunction_projection` | `exact <h>.left` / `<h>.right` | `exact h.left` |
| `disjunction_cases` | `cases <h> with \| inl … => … \| inr … => …` | `cases h with \| inl hp => exact hp \| inr hp => exact hp` |

Each cell carries metadata:

- `operation`, `surface_family`, `redundancy_group` (= operation),
  `required_operation` (mirror for v6/v7/v8 compatibility);
- `requires_intro`, `requires_rewrite`, `requires_quantifier`,
  `requires_exists_elim` flags (inferred from the operation; per-cell
  override supported);
- `source = "redundancy-corpus"`, `redundancy_corpus = true`;
- `difficulty = "medium"`, `expected_success_tactics = [<the tactic>]`.

## Verification

Every cell's tactic is verified by the `lean-cli` runner (`LeanCliRunner` →
`lean`/`lake env lean`) **before commit**; a cell whose tactic fails or
times out is *not* written into the verified set and is recorded in
`redundancy_lean_cli_failed.jsonl` with `success: false` and the original
error/timeout. There is no fake corpus.

The run-summary table (per operation, verified / refused):

| operation | verified | refused |
| --- | ---: | ---: |
| `conjunction_projection` | 5 | 0 |
| `contradiction` | 5 | 0 |
| `disjunction_cases` | 5 | 0 |
| `exists_elim` | 5 | 0 |
| `implication_chain` | 5 | 0 |
| `instantiate_forall` | 5 | 0 |
| `intro_negation` | 5 | 0 |
| `rewrite_eq` | 5 | 0 |
| **total** | **40** | **0** |

### Initial run had 8 timeouts; all recovered on rerun

The first generator run refused 8 cells as WSL/lean cold-start timeouts
at the per-cell 60–120 s cap. All 8 are correct Lean 4 tactics; they
were re-attempted with `--timeout 180` after purging the failed cache
entries (`.tmp/purge_failed_redundancy_cache.py` does this surgically
without invalidating the 32 already-verified entries). All 8 verified on
the rerun; `data/traces/redundancy_lean_cli_failed.jsonl` is now empty.

The historical 32-of-40 verified count is preserved in git history; the
documentation now reflects the current 40-of-40 state. The
refuse-or-write contract held throughout: at no point did a refused cell
land in the verified set.

### Forbidden-tactic check

`scripts/generate_redundancy_corpus.py` does not emit any of `sorry`,
`admit`, or `unsafe`; the v10 corpus generator test
(`tests/test_redundancy_corpus_generator.py::test_no_forbidden_tactics`)
asserts this on every DESIGN cell.

## No overlap with prior corpora

Every v10 theorem name is prefixed `v10_`. `tests/test_redundancy_corpus_generator.py::test_design_no_overlap_with_prior_corpora`
asserts the v10 design table shares no `theorem_name` with
`basic_lean_seeds.jsonl`, `hard_lean_seeds.jsonl`,
`planner_blind_seeds.jsonl`, or `v9_validation_seeds.jsonl`.

## Trace audit (verified file)

`./.venv/bin/python scripts/evaluate_traces.py data/traces/redundancy_lean_cli_verified.jsonl`
yields:

| Quantity | Value |
| --- | --- |
| total records | 40 |
| successful transitions | 40 |
| success rate | 1.0000 |
| automation tactic count | 0 |
| automation tactic ratio | 0.0000 |
| duplicate transition pairs | 0 |
| unique theorems | 40 |
| unique tactics | 30 |
| backend distribution | `lean-cli` = 40 |

`uses_state_after = false` for every row — v10 is theorem-level
verification, **not** full ELF over proof states.

## Honest scope

* The corpus is **synthetic**; every cell was authored by hand for the
  redundancy structure. Verification is real but the variety is bounded.
* `state_after_is_real = false` — no real next-state supervision.
* `cross_operation_verified` is what we measure, not "full theorem
  proving". A cell verifying does not imply the seq2seq has learned the
  *concept* of the operation; it has learned to compose the right tokens
  from sibling families.
* No Mathlib imports; everything typechecks against pure Lean 4 / Init.
* No manual oracle counted as a model output; oracle candidates live in
  `data/manual/redundancy_candidates.jsonl` and are used *only* for
  pre-commit verification, never as a model decoder output.
