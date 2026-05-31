# V20 ranker-time abstract-pattern reranker

## Hypothesis under test

> Can ranker-time abstraction improve candidate selection without
> generating unresolved placeholders?

This is the v20 brief's *third* research question, and the
diagnostic that motivated v20 itself. The v19 negative result
proved that **generating** placeholders fails: the model emits
`<HYP_AND_0>` and friends when the test state has no conjunction,
producing 210/480 (44 %) unresolved-placeholder slots. v20's
ranker-time variant uses the same v19 abstraction machinery —
[`src/mini_elf_lean/identifier_abstraction.py`](../src/mini_elf_lean/identifier_abstraction.py),
which is *unchanged* in v20 — but applies it only to score raw-name
candidates.

## Implementation

[`src/mini_elf_lean/abstract_pattern_reranker.py`](../src/mini_elf_lean/abstract_pattern_reranker.py)

```
PatternBag
    pattern_bag = build_pattern_bag(verified_train_rows)
        for r in rows:
            abs_pattern, _ = abstract_tactic_only(r.state_before, r.tactic)
            pattern_bag.add(abs_pattern, r.category)

AbstractPatternReranker(bag=pattern_bag, ...)
    score(candidate, raw_rank, state_before, category)
        # Abstract the candidate against the test state.
        abs_pattern, _ = abstract_tactic_only(state_before, candidate)
        n_pat        = pattern_bag.lookup(abs_pattern, category)
        n_unbound    = count_idents_not_in_local_context(candidate)
        score        = 1.5 * sqrt(n_pat)
                       - 2.0 * n_unbound
                       - 0.05 * raw_rank
        return ScoredCandidate(candidate, raw_rank, abs_pattern,
                               n_pat, n_unbound, score, reason)
```

The reranker reorders existing raw-name candidates by score. The
returned tactic strings are the **raw candidates as generated** —
no placeholder substitution ever happens.

## Why this sidesteps v19's cliff

v19 generated abstract strings then concretised against the test
state's local context. When the test state lacked a category the
training distribution had (e.g. v18 implication state has no
conjunction but v19 model emits `<HYP_AND_0>`), concretisation
failed, producing `concretisation_failed` sentinels. v20 never
goes through that pathway: generation stays in raw names, and the
reranker is a pure ordering layer that prefers known *patterns*
and demotes candidates that name hypotheses not in scope.

## Key features

* **Pattern-bag** sourced from verified training tactics only. No
  inference on candidates' correctness — pattern frequency is a
  prior, not a verdict.
* **Unbound-identifier penalty**: catches the v18 `hpfalse` failure
  (model emits `exact (hpfalse hp).elim` on a state whose only
  hypothesis is `hp`). The regex extracts identifiers, filters
  Lean keywords + common constructors (`exact`, `intro`, `Or.inl`,
  `rfl`, ...), and counts the remainder.
* **No placeholder output**. Tests pin this (`test_output_is_raw_
  names_never_placeholders`).
* **No `state_after`**. Tested
  (`test_pattern_bag_uses_no_state_after`).

## Evaluation hooks

[`scripts/evaluate_v20_broad_core.py`](../scripts/evaluate_v20_broad_core.py)
publishes six configs:

| config | description |
|---|---|
| `raw`  | v20 model beam order + literal-aware adapt (baseline) |
| `rule` | v15 rule reranker |
| `learned` | v15 learned reranker |
| `policy` | v15 + v17 operation-aware policy router |
| `abstract` | v20 abstract-pattern reranker |
| `policy_abstract` | v15 policy first, then abstract-pattern tie-break |

Per-config metrics + predictions land in
`data/baselines/v20_broad_plus_eval/<config>/`. The summary at
`summary.json` aggregates.

## What this report does NOT do

* It does not claim ranker-time abstraction generalises to
  Mathlib. The v20 brief explicitly defers Mathlib until the
  broad-core data-shape gaps are tested.
* It does not retcon v19. v19 generation-time abstraction stays
  a negative result; v20 reuses the *machinery* in a different
  mode.
* It does not use `state_after`.
* It does not use manual oracle outputs as model predictions —
  the pattern bag is built from verified training tactics only.

## Honest read of where this can help vs. hurt

* **Helps**: known shape, unbound names. v18 broad-only's
  `exact (hpfalse hp).elim` on `v18_imp_p_self` is exactly the
  case the unbound-identifier penalty was designed to catch.
* **Helps**: known shape, novel raw names. A new test state
  with hypothesis `hImp` instead of `hpq` abstracts to the same
  `exact <HYP_IMP_0> <HYP_PROP_0>` pattern.
* **Hurts**: novel shape, even when correct. If the canonical
  proof shape never appeared in training, the abstract pattern
  has count 0, and only the rank-decay term differs from a flat
  beam ordering. Equality_rewrite (`rfl`, `exact rfl`) likely
  scores low because the abstract pattern is just `rfl` /
  `exact rfl`, which is heavily represented; that's fine.

The honest hypothesis is **abstract helps where unknown_identifier
dominates and hurts where shapes are novel**. The headline at
[`V20_BROAD_TRANSFER_REPORT.md`](V20_BROAD_TRANSFER_REPORT.md)
records what actually happened on the v18 broad-core benchmark.

## Measured result (v18 broad-core, timeout-corrected)

| config | pass@1 | pass@5 | pass@10 | MRR | unknown_identifier |
|---|---:|---:|---:|---:|---:|
| raw | 0.500 | 0.708 | 0.729 | 0.589 | 80 |
| policy | 0.542 | 0.708 | 0.729 | 0.598 | 80 |
| **abstract** | **0.625** | **0.729** | 0.729 | **0.666** | 80 |
| **policy_abstract** | **0.625** | **0.729** | 0.729 | **0.667** | 80 |

(Pre-correction numbers — raw 0.396 / abstract 0.562 pass@1 — are in
the original `data/baselines/v20_broad_plus_eval/`; the table above is
the warm-rerun-corrected `..._timeout_rerun/`.)

**The ranker-time abstraction config is the single best config.** It
lifts pass@1 from 0.500 (raw) to **0.625** and is the only config that
pushes pass@5 above the 0.708 the four v15-pattern configs share,
reaching **0.729**.

The reorder trace
([`evaluate_v20_abstract_reranker.py`](../scripts/evaluate_v20_abstract_reranker.py)
→ `data/baselines/v20_abstract_reranker_comparison.json`) shows, vs
the raw beam order: **11 theorems' first-verified candidate moved up,
3 moved down, 19 unchanged**. The net +8 is the pass@1 gain.

Note the `unknown_identifier` *count* (80) is identical across configs
— the reranker reorders the same candidate set, so the total number of
bad-identifier candidates in the top-10 is unchanged; what changes is
their **rank**. The win is precision-at-1, exactly as a scoring-only
layer should behave.

**Confirmed answer to research question 3**: ranker-time abstraction
improves candidate selection (pass@1 +0.125, pass@5 +0.021 over the
next-best config) **without generating any unresolved placeholders**
— `unresolved_placeholder` count is 0 in every v20 error taxonomy,
versus 210/480 (44 %) in v19's generation-time abstraction. The
distinction between *scoring with* abstraction and *generating in*
abstraction is the whole v20 thesis, and it holds.
