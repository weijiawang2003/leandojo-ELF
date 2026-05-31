# Mini-ELF v9 — data-scaling plan

The v8 result attributed the cliff between `family_holdout/neg_exfalso`
(`pass@5 = 0.625`, 9 novel) and `family_holdout/forall_inst` (`0/7`) to a
single mechanism: **the seq2seq composes proof-shape tokens from sibling
families that share its training distribution**. When the held family has no
sibling, the model fails. v9 plans the data-scale fix.

This document is the design + a small generator skeleton. It deliberately does
**not** report new pass@k numbers — it sets up the experiment v10 will run.
The skeleton runs cleanly today and produces a 10-theorem proof-of-concept
corpus that the v8 pipeline can ingest unchanged, but the headline data
collection is gated on either (a) a real Lean tactic-trace pull from a public
source or (b) running the existing generator at scale.

## 1. Why the current corpus blocks cross-family transfer

The planner-blind corpus was built so each "operation" — `contradiction`,
`destruct_exists`, `instantiate_forall`, `intro_negation`,
`project_conjunction`, `rewrite` — appears in **exactly one or two** families,
and the flat closing tactic of each operation is *unique* to its family. The
v7 donor audit and v8 negative control both attributed this to corpus design,
not modelling.

Concretely:

| operation | families that use it | unique flat tactic? |
|---|---|---|
| `contradiction` | `neg_exfalso`, `neg_or_cases` | mostly unique |
| `intro_negation` | `neg_imp_exfalso`, `neg_double_intro`, `neg_contrapositive` | mostly unique |
| `destruct_exists` | `exists_elim_conj`, `exists_elim_prop` | mostly unique |
| `instantiate_forall` | `forall_inst` (only) | **unique to one family** |
| `rewrite` | `rewrite_succ` (only) | **unique to one family** |
| `project_conjunction` | basic-corpus `and_elim_*` only | unique to that family group |
| `unknown` | `exists_reconstruct` (only); also basic `exists_witness` | shape overlap **between PB and basic** — this is why v8's only donorless win lives here |

v9's design goal: ensure every operation appears in **≥3 families** with
shape-compatible closing tactics, so that a held-out family always has a
sibling-family token cousin in train.

## 2. Public Lean sources we can pull from

A real fix needs more *variety* than handwritten templates can produce. Three
candidates, ranked by integration cost:

### 2.1 LeanDojo's `mathlib4` tactic-trace dataset (preferred)

- Source: <https://github.com/lean-dojo/LeanDojo> + the `mathlib4` traces it
  emits.
- Format: each tactic step is a `(state_before, tactic, state_after)` triple.
  v9 would **discard `state_after`** at the pipeline boundary (mini-ELF's
  honesty constraint) and keep only the `(theorem_statement, state_before,
  tactic)` triples used everywhere else.
- Filter: keep only tactic strings that use **core Lean 4** (no `import
  Mathlib.*`). The `mini_elf_lean.tactic_sanitizer` already screens
  `simp`/`aesop`/`omega`/etc. as "automation"; v9 will gate on
  `pattern_family` inferred from the tactic-token set (e.g. tactics using
  `Mathlib.*` lemmas are out; tactics using `Nat`/`Eq`/`And`/`Or` are in).
- Blocker today: same as the rest of the project — LeanDojo's REPL is
  unblocked for read-only access but the *interactive* run-tactic path
  produces empty stdin failures (documented in `tests/test_leandojo_runner.py`
  and the v0 PROJECT_REPORT). We can read the **pre-extracted traces** that
  ship with the dataset release without running LeanDojo ourselves; this is
  the v9-actionable path.

### 2.2 Lean 4 stdlib (`Init/*.lean`)

- Source: the lean-toolchain we already use ships its own stdlib at
  `~/.elan/toolchains/leanprover--lean4---v4.30.0/lib/lean4/library/`.
- A small Python parser (`scripts/scrape_init_proofs.py`, skeleton below) can
  extract `theorem … := by …` blocks where the body is a single tactic
  block, then verify each tactic against the v8 lean-cli verifier as a sanity
  check.
- Cost: very low. Output: a few hundred core-Lean theorem-level
  `(statement, state_before, tactic)` rows. Coverage: operator-level
  (`Bool`, `Nat`, `List`, `Option`, `Eq`); modest but **operations recur
  across families by construction** — `Eq.symm`, `Eq.trans`, `Nat.succ_eq_*`
  pattern across many families.

### 2.3 Hand-authored corpus expansion (V9 generator, this document)

- A controlled, deterministic generator that produces multiple families per
  operation. Used as a smoke test that the seq2seq generalises better when
  the operation recurs (v9's hypothesis). Implemented as
  `scripts/build_v9_corpus.py` (skeleton in this commit) — output is a
  validation-only corpus (~10 theorems per operation × 5 families per
  operation = 50 theorems). Verification still required: the LLM/seq2seq
  results on this expanded corpus are the v10 deliverable, not v9's.

## 3. The v9 corpus design (10 operations × 5 families)

Each cell is one family with a closing tactic that uses the same Lean
*operator* (e.g. `absurd` for `contradiction`) but a different surface form
(positional vs `.elim`, `(h x).elim`, etc.). Holding any one family for the
v8-style LOFO test then **always** leaves at least four sibling families in
train that share the operator token.

| operation | sibling families (≥5 per operation) |
|---|---|
| `contradiction` | `neg_exfalso`, `neg_or_cases`, `neg_imp_exfalso`, `neg_double_neg_intro`, `neg_iff_false` |
| `instantiate_forall` | `forall_inst_nat`, `forall_inst_prop`, `forall_inst_eq`, `forall_inst_le`, `forall_inst_pair` |
| `destruct_exists` | `exists_elim_conj`, `exists_elim_prop`, `exists_split`, `exists_pair_witness`, `exists_imp` |
| `project_conjunction` | `and_elim_left`, `and_elim_right`, `and_elim_iff`, `and_elim_imp`, `and_elim_or` |
| `intro_negation` | `neg_imp_exfalso`, `neg_double_intro`, `neg_contrapositive`, `neg_and_distrib`, `neg_or_split` |
| `rewrite` | `rewrite_succ`, `rewrite_eq_symm`, `rewrite_eq_trans`, `rewrite_subst`, `rewrite_congr` |
| `apply_eq` | new family group — `eq_refl_apply`, `eq_symm_chain`, `eq_trans_iff`, `eq_iff_left`, `eq_substr` |
| `apply_iff` | new — `iff_mp`, `iff_mpr`, `iff_chain`, `iff_and`, `iff_or` |
| `cases_pattern` | new — `cases_or`, `cases_nat`, `cases_bool`, `cases_option`, `cases_decidable` |
| `unknown` (kept as control) | `exists_reconstruct`, anything our heuristic abstains on |

That target — **50 theorems with operation×family redundancy** — is what
the v9 generator skeleton emits a small subset of (10 theorems
proof-of-concept; the parameterisation supports scaling up). Adding the
LeanDojo/`Init` rows on top would push to 200–500 theorems with similar
structure.

## 4. Implementation status

- `docs/V9_DATA_SCALING_PLAN.md` — this document.
- `scripts/build_v9_corpus.py` — **skeleton**: declares the
  operation→families table, walks it deterministically, emits a small
  validation seeds file + manual candidate file in the same format
  `proof_block_dataset.load_pool` already consumes, and verifies each
  generated tactic against the lean-cli verifier (the same verifier the rest
  of the project uses). The skeleton emits the 10-theorem proof of concept
  by default; running `--full` emits the planned 50-theorem cell, but the
  user gates the expanded run to keep this report honest about coverage.

What the skeleton **does** today:

- Round-trips a deterministic 10-theorem seed through the v8 pipeline (the
  pool, the regime builder, and the seq2seq trainer can ingest it
  unchanged).
- Verifies each emitted tactic with `make_lean_cli_verifier` before
  emission, so the skeleton refuses to produce a seed with an unverified
  closing tactic. (No corpus fabrication.)
- Carries the same `state_after_is_real = False` metadata convention.

What the skeleton **does not** do (gated on a later run):

- It does not pull from LeanDojo or stdlib. Those integrations are sketched
  here but are outside the v9 commit, since the v9 brief asks to "implement
  corpus generator skeleton, but do not fake results".
- It does not retrain the seq2seq on the expanded corpus. That is v10's
  pass@k measurement: take the new corpus, rebuild the proof-blocks
  regimes, train per fold, compare against v8.

## 5. v10 dependencies and risks

A v10 that actually tests the data-scaling hypothesis needs:

1. **Either** a real-LLM pilot (Step 2 of v9 — SKIPPED for no key, see
   `docs/V9_LLM_DONORLESS_REPORT.md`) **or** a >5× larger Lean tactic
   corpus.
2. The corpus must be **verified** (every closing tactic accepted by
   lean-cli) to preserve the mini-ELF honesty contract.
3. The model retrained per regime; the v8 training script is already
   parametric on the regime directory, so no model code change is required.
4. A re-run of the v8 eval matrix on the new corpus's regimes — the same
   `scripts/run_v8_seq2seq_eval_loop.sh` script works as-is.

The biggest open risk is **lean-cli throughput**: v8 took ~15 min/fold on
~10 unique theorems × 10 candidates. A 5× corpus is 5× longer, plus the
verifier slows on novel tactic strings. v10 should either parallelise
verification (multiple lean-cli runners) or cache more aggressively across
runs. Neither is in v9's scope.

## 6. Recap of v9's deliverables

- `docs/V8_FULL_EVAL_MATRIX.md` — snapshot of measured v8 cells (Step 1)
- `docs/V9_LLM_DONORLESS_REPORT.md` — SKIPPED record (Step 2)
- `docs/V9_DATA_SCALING_PLAN.md` — this document (Step 3)
- `scripts/build_v8_full_matrix.py` — re-generates the matrix from disk
- `scripts/run_v9_llm_donorless_pilot.py` — pilot script (gated)
- `scripts/build_v9_corpus.py` — corpus generator skeleton

**No new pass@k numbers were measured in v9.** All performance claims still
rest on v8's eval matrix; v9 is design + plumbing for the next experiment.
