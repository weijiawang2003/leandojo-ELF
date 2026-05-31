# Mini-ELF v10 — failure examples

A scratchpad of concrete model-output failures on the v10 redundancy
holdout cells, surfaced from
`data/baselines/v10_eval/<regime>/<fold>/<model>/predictions.jsonl`. The
intent matches `V2_FAILURE_EXAMPLES.md`, `V5_FAILURE_EXAMPLES.md`, etc. —
to show *what kind of mistake* each model is making rather than just a
number.

> Examples below were taken from real predictions; if you re-run
> `scripts/run_v10_eval_focused.sh` the same predictions.jsonl files are
> rewritten and the failures listed here can be re-extracted by grepping
> for rows whose `"verifications"` array has no `"success": true` entry.

## Failure-mode taxonomy (carried over from v8)

The v8 retrospective surfaced three recurring failure modes when the
seq2seq generates on a held-out cell. v10 inherits all three; the v10
question is whether the redundancy corpus makes any of them less common.

1. **Mid-token truncation**. Char-level decoder emits a partial keyword
   (`And.righ`, `constructo`, `cases h with | inl hp => exact hp | inr hp => exa`).
   pass@1 misses; sometimes pass@10 has a longer beam entry that completes.
2. **Wrong-sibling pick within an operation**. The model picks the wrong
   member of the sibling family — e.g. `exact h.left` when the goal needs
   `exact h.right` — because both are statistically valid for sibling
   shapes. v6's structure-aware retrieval cured this for retrieval; the
   seq2seq still picks wrong on cell_holdout when nothing else
   disambiguates.
3. **Wrong-operation token transplant**. On `operation_holdout`, the
   model splices tokens from a *different* operation that was in train —
   e.g. emitting `exact h.left` for a `disjunction_cases` test because
   `conjunction_projection` rows dominated the train pool.

v10's eval surfaces an additional v10-specific failure:

4. **Out-of-vocabulary tactic transplant**. The v8 baseline trained on
   pooled basic/hard/planner-blind rows uses Mathlib-style `rcases`/
   `obtain`; the v10 corpus uses only core-Lean `cases h with | intro
   n hn => …`. When `baseline_v8` is evaluated on a v10 cell, its top
   beam entry is often `rcases h with ⟨n, hn⟩` followed by a Mathlib-
   style continuation — Lean rejects the file because `rcases` is not in
   scope without `import Mathlib`.

## Concrete examples

### `exists_elim__reuse_witness_3` — baseline_v8 (pass@1 False, pass@5 **True**)

Gold tactic: `cases h with | intro n hn => exact ⟨n, hn⟩`

Beam top-10:

| rank | candidate (`pass`) |
| ---: | --- |
| 0 | `rcases h with ⟨n, hn⟩\n  exact ⟨n, hn⟩` ❌ Mathlib `rcases` not in scope |
| 1 | `exact ⟨3, rfl⟩` ✓ verified — slot-fills the literal witness |
| 2 | `rcases h with ⟨n, hn⟩\n  exact ⟨3, rfl⟩` ❌ Mathlib `rcases` |
| 3 | `rcases h with ⟨n, hn⟩\n  exact ⟨n, ?_⟩` ❌ `?_` placeholder |
| 4 | `rcases h with ⟨n, hn⟩\n  exact ⟨n, rfl⟩` ❌ Mathlib `rcases` |
| 5 | `exact h` ✓ verified — accidentally typechecks because goal/`h` unify |
| 6 | `cases h with ⟨n, hn⟩\n  exact ⟨n, hn⟩` ❌ wrong `cases` syntax (`with ⟨…⟩` is `rcases`-style) |
| 7-9 | `rcases h with ⟨n, hn⟩\n  exact ⟨n, h…⟩` ❌ various |

Failure mode 4 (Mathlib transplant) dominates the v8 baseline on every
exists_elim cell; pass@5 is non-zero only because the model also emits
the basic-corpus literal-substitution `exact ⟨3, rfl⟩` from its
`exists_reconstruct` training rows.

### `exists_elim__reuse_witness_3` — redundancy_only (pass@1 False, pass@5 False)

Trained on 23 rows; gibberish decode:

| rank | candidate |
| ---: | --- |
| 0 | `exact h]` ❌ malformed |
| 1 | `exact h => exact h => exact` ❌ malformed |
| 2 | `cases h]` ❌ malformed |
| 3-9 | various `exact h => …` malformed strings |

This is the failure mode the v10 brief expects from a 23-row training
pool: the model has not learned the tactic-string distribution; every
beam entry is character-level garbage. The model is included as a
**negative control** to isolate the contribution of the v8 base pool to
the combined-v10 result.

### `disjunction_cases__or_self` — combined_v10 (pass@1 False, pass@5 **True**)

Gold tactic: `cases h with | inl hp => exact hp | inr hp => exact hp`

The combined_v10 model emits a longer beam entry that verifies (1 verified
candidate, 1 novel, 1 cross-family-verified). The single verified
candidate is **novel** — not present in any train tactic — demonstrating
the v8 mechanism (sibling-family token composition) survives the
combined-pool retrain.

## Cross-operation observations

`cross_operation_verified` counts model outputs that verify on a fold
whose `required_operation` is absent from train. So far on the partial
matrix the strongest signal is:

- `redundancy_cell_holdout/disjunction_cases__or_self`: baseline_v8 and
  combined_v10 both verify; redundancy_only does not (0/n).
- The cell_holdout regime keeps a same-operation sibling in train (the
  v10 redundancy condition), so `cross_operation_verified` is not the
  target metric here — the target is `cross_family_verified`, which
  baseline_v8 and combined_v10 each achieve.

For the cross-operation signal, see `operation_holdout` cells in
`V10_FULL_EVAL_MATRIX.md` once those folds complete.

## Limits of this report

- Failure curation is post-hoc; the model was selected/trained without
  reference to specific examples here.
- Mid-token truncation is a char-level artifact, not a Mathlib /
  ontological failure. It can be mitigated by longer beams or BPE
  tokenisation (not pursued in v10 — out of scope, brief says "do not
  change the main model first").
- Mathlib-tactic transplant (failure mode 4) is a v8-corpus contamination
  signal, not a v10 model failure per se: the v8 pool contains rows that
  used `rcases`/`obtain`, so the model learned to emit them. v11 could
  address this by filtering the v8 pool to core-Lean only, or by adding
  more core-Lean redundancy examples; v10 explicitly does not pursue
  either path.
- v10 does not claim to fix any of these failure modes; it measures
  whether the corpus broadens the *coverage* over which they appear.
