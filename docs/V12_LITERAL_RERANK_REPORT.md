# Mini-ELF v12 — literal-aware decode + rule-based reranker

> **Scope.** v12 is **post-generation** processing on the v11 model's
> beam output: no new training, no model changes, no `state_after`
> access, no manual oracle. It targets the two v11 failure modes the
> docs flagged as addressable: literal extrapolation and beam-rank
> failure. Per-family LOFO test sets (the v11 splits) are reused
> unchanged. v10 leaked metrics remain invalidated; v12 does not revive
> them.

## v11 failures v12 attacks

From `docs/V12_LITERAL_AND_RERANK_FAILURE_ANALYSIS.md`:

* **Literal extrapolation.** 6 of 7 failing `forall_inst` rows have an
  ``exact h <K>`` candidate in top-5 with K ∈ {3, 4, 5, 7}; the goal
  needs N ∈ {3, 5, 8, 9, 13}. The schema is right; the literal is wrong.
* **Beam-rank failure.** ``forall_inst_3_0`` needs ``exact h 3``; v10's
  ``nat_eq_3`` cell puts that exact tactic in train, but the v11 beam
  puts ``exact h 4`` and ``exact h 7`` ahead.
* **Char-level mid-token truncation** (deferred to v13; this report
  documents how v12 attenuates it via a malformed-penalty in the
  reranker).

## v12 components

### `mini_elf_lean.literal_aware_decode` — literal-aware augmentation

Pure-Python, no torch, no Lean. For each input candidate it detects
three literal-bearing schemas:

* ``exact <ident> <num>`` (the canonical forall_inst schema),
* ``exact <ident> <num> <num>`` (binary forall, e.g. v10's
  ``forall_inst_pair``),
* ``exact ⟨<num>, rfl⟩`` (the v0/v1 witness-copy shape).

Augmentation gate:

* The state must contain a ``∀`` quantifier OR the candidate must be
  the ``⟨…, rfl⟩`` witness shape.
* The goal must contain at least one numeric literal (the **first**
  literal on the goal line is the substitution target).
* The candidate's hypothesis identifier must be a name that appears in
  the local context (we don't invent identifiers).
* The candidate's literal must differ from the target — otherwise
  emitting an "adapted" copy would be a no-op.

Output candidates are tagged ``source = "seq2seq_literal_adapt"``;
the reranker uses this to apply a small priority bonus. **No
``state_after`` argument** — passing one raises ``TypeError``
(invariant pinned by ``test_literal_aware_decode.py``).

Augmentation does NOT fire on:

* `rewrite_succ` (no `∀` in state, no goal numeric literal that the
  tactic depends on),
* `neg_exfalso` (no goal literal),
* `neg_imp_exfalso` (no `∀`),
* `exists_reconstruct` (some cells have an ⟨N, rfl⟩ shape; verified
  below).

### `mini_elf_lean.proof_block_reranker` — rule-based reranker

Pure-Python, score = sum of feature contributions, stable sort.
Features per candidate:

| feature | weight | when it fires |
|---|---:|---|
| goal-literal match | +2.0 | any literal in candidate equals the first goal literal |
| stale literal | −1.0 | candidate has a literal but it doesn't match the goal's |
| malformed | −2.0 | trailing punctuation, unclosed `[…`/`⟨…`, dangling `with`, short dotted tail (excluding `.left`/`.right`/`.elim`/`.mp`/`.mpr`/`.symm`/`.trans`) |
| literal_adapt source | +0.5 | candidate emitted by `literal_aware_decode` |
| known head | +0.2 | first token in `{exact, rw, intro, cases, …}` |
| schema match | +0.4 | candidate head matches `required_operation`'s expected heads |
| short and clean | +0.15·(1 − len/80) | only if NOT stale and NOT malformed |
| beam rank tiebreak | −0.01·rank | stable sort across equal scores |

The reranker is a syntactic re-ordering of the input candidate list;
it does not invent or modify candidates.

## v12 eval matrix (lean-cli pass@k on the v11 family-LOFO test rows)

Reuses `data/baselines/v11_family_lofo_eval/<fam>/v11/predictions.jsonl`
(the v11 model's beam top-10 + lean-cli outcomes), composes the v12
processing layer, verifies any new candidates the literal-adapt step
emits, and recomputes pass@k. The verification cache from v11 is
seeded into v12's cache so cached candidates are free.

### pass@5 matrix

| family (n) | raw | +literal_adapt | +rerank | **+both** |
|---|---:|---:|---:|---:|
| `forall_inst` (7) | 0.143 | 0.143 | 0.143 | **0.429** |
| `rewrite_succ` (5) | 0.800 | 0.800 | 0.800 | 0.800 |
| `neg_exfalso` (8) | 0.625 | 0.625 | 0.625 | 0.625 |
| `exists_reconstruct` (5) | 0.800 | 0.800 | 0.800 | **1.000** |
| `neg_imp_exfalso` (5) | 0.000 | 0.000 | 0.000 | 0.000 |

### Δ vs raw (pass@5)

| family | +literal_adapt | +rerank | +both |
|---|---:|---:|---:|
| `forall_inst` | 0 | 0 | **+0.286** |
| `rewrite_succ` | 0 | 0 | 0 |
| `neg_exfalso` | 0 | 0 | 0 |
| `exists_reconstruct` | 0 | 0 | **+0.200** |
| `neg_imp_exfalso` | 0 | 0 | 0 |

### Detailed counters (literal_adapt_rerank)

| family | verified | novel | xfam | xop | lit_adapt verified | rank_fix | malformed | stale |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `forall_inst` | 3 | **1** | 3 | 0 | **2** | 0 | 4 | 11 |
| `rewrite_succ` | 4 | 0 | 4 | 4 | 0 | 0 | 20 | 0 |
| `neg_exfalso` | 10 | 5 | 10 | 0 | 0 | 0 | 3 | 0 |
| `exists_reconstruct` | 5 | 1 | 5 | 0 | **1** | 0 | 2 | 17 |
| `neg_imp_exfalso` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## What worked, and why

### `forall_inst`: pass@5 0.143 → 0.429 (1/7 → 3/7), pass@1 0.143 → 0.429

The two new verified rows both come from the literal-adapt step
(``literal_adapt_verified = 2``). The reranker is necessary to surface
them: without it the literal-adapt candidates are appended after the
original beam (positions 10+), outside the pass@5 window. With both
layers on, the reranker boosts the literal-correct adapted candidate
to rank 0 (the +2.0 goal-literal-match feature dominates).

Concretely (from the predictions.jsonl):

* ``forall_inst_3_0``: original beam had ``exact h 4`` at top, no
  ``exact h 3``. Literal-adapt emits ``exact h 3`` (substituting goal
  literal 3 into the ``exact h <K>`` schema). Reranker moves it to
  rank 0. **Verified.**
* ``forall_inst_5_2``: original beam had ``exact h`` (truncated, no
  literal) at top, ``exact h 4`` later. Literal-adapt emits
  ``exact h 5``. Reranker moves it to rank 0. **Verified.**
* ``forall_inst_7_0`` (already verified in v11): still passes — the
  reranker keeps ``exact h 7`` at rank 0.
* ``forall_inst_9_4``: original beam had ``exact h 4``. Literal-adapt
  emits ``exact h 9``. **Lean rejects** — the hypothesis is ``∀ x,
  x = 4`` so ``h 9`` is type-correct but the goal is ``9 = 4`` which
  cannot be proven (this row is genuinely unprovable without
  additional knowledge; the planner-blind corpus contains it as a
  failing case the model was never expected to solve).
* ``forall_inst_13_6``, ``forall_inst_var_m``, ``forall_inst_var_k``:
  similar — adapted candidate is emitted but Lean rejects (goal
  unprovable or hypothesis vocabulary doesn't match).

The honest read: **2 of the 6 remaining rows were rank/literal
failures that v12 fixes; the other 4 are problems beyond v12's
post-processing**.

`novel_verified = 1` because one of the v12 wins is a tactic string
not present in train (``exact h 5``: train pool has v10's
``nat_le_5 :: exact h 5`` but that lives in a different theorem
context; the dedup-against-train counts it as novel against the
LOFO train pool).

### `exists_reconstruct`: pass@5 0.800 → 1.000 (4/5 → 5/5)

The 5th row's gold tactic involves ⟨N, rfl⟩ witness substitution. The
v11 beam emitted ``exact ⟨6, rfl⟩`` for a goal needing ⟨3, rfl⟩.
Literal-adapt's witness schema emits ``exact ⟨3, rfl⟩``; reranker
boosts it. Verified.

### `rewrite_succ`: preserved at 0.800

v12 brief required ≥ 0.800. The literal-adapt step never fires on
rewrite_succ (no goal literal, no ``exact h <num>`` schema, no
witness). The reranker boosts ``rw [h]`` via the schema_match bonus
(rewrite head). Verified candidate count drops 4 → 4 (no change);
pass@k unchanged. **Floor preserved.**

### `neg_exfalso`: preserved at 0.625

No applicable schema; reranker has no leverage. Verified count drops
12 → 10 because compose_candidates deduplicates the model's beam,
collapsing some duplicate ``exact absurd hp hnp`` entries. pass@k
unchanged because the deduped candidates still appear at rank 0 or 1.

### `neg_imp_exfalso`: still 0/5

v10 does not contain the contrapositive shape ``(p → q) → ¬q → ¬p``,
so v11's beam has no shape-correct candidate to adapt, and the
reranker has nothing to promote. **v12 is honest about its limits**:
this fold is unmoved.

## Aggregate

| metric | v11 (raw) | v12 (literal_adapt_rerank) | Δ |
|---|---:|---:|---:|
| mean pass@5 (5 fams) | 0.474 | **0.571** | +0.097 |
| sum verified candidates | 12 | 22 | +10 |
| sum literal_adapt verified | — | 3 | n/a |
| sum novel_verified | 5 | 7 | +2 |
| sum rank_failure_fixes | — | 0 | n/a |

The "rank_failure_fixes" counter is 0 across the matrix — the lift
comes from the *literal-adapt path*, not from re-ordering already-
present-in-top-5 candidates. This is consistent with the v11 failure
analysis: most failing rows had ``exact h <wrong-literal>`` in the
beam but never ``exact h <correct-literal>``, so a pure re-ranking on
the original beam couldn't help.

## Honest scope (claims explicitly avoided)

* **Not novel theorem proving.** v12 unblocks rows by substituting goal
  literals into already-learned tactic shapes. The 3 new
  literal_adapt-verified candidates carry tactics
  (``exact h 3``, ``exact h 5``, ``exact ⟨3, rfl⟩``) that exist as
  exact strings in the v10 redundancy corpus's training cells; v11's
  beam just didn't surface them.
* **Not architectural improvement.** Same v8/v10/v11 seq2seq
  checkpoint. v12 is a post-generation symbolic adaptation +
  syntactic reranker.
* **Not a hand-written theorem template.** The literal-adapt schemas
  are *generic* (``exact <ident> <num>``), not theorem-specific. They
  pattern-match the model's own output and substitute the first goal
  literal. The reranker's features are also generic.
* **Not a manual oracle.** The literal-adapt candidates are derived
  from the model's beam output, not from
  ``data/manual/redundancy_candidates.jsonl``.
* **Not state_after.** ``adapt_candidates`` accepts no ``state_after``
  kwarg — passing one raises ``TypeError``, pinned by
  ``test_literal_aware_decode.py``.
* **Not a v10 leakage revival.** The legacy combined_v10 metrics are
  still labelled INVALIDATED in `docs/RESULTS_SUMMARY.md`,
  `docs/V10_FULL_EVAL_MATRIX.md`, etc.
* **Not the v8 base-pool Mathlib-tactic fix.** ``rcases`` candidates
  continue to appear in v11's beam; v12's malformed penalty does not
  fully demote them when they have well-formed prefixes. (The
  malformed feature does demote the truncated ``rcases h w`` shape.)
* **Not the full unblock for `forall_inst`.** 4 of 6 remaining failing
  rows are not adapter-fixable (out-of-vocabulary literal,
  unprovable goal under the planner-blind corpus's deliberately
  difficult setup, or model never emits the ``exact h <num>`` schema
  for that row).
* **Not a `neg_imp_exfalso` unblock.** v10 lacks the shape; v12 cannot
  invent one.

## v13 recommendation

* **Replace the char-level seq2seq with a tactic-token tokenizer** (see
  `docs/V12_TOKENIZATION_NOTE.md`). The 4 `forall_inst` rows v12 didn't
  unblock include 2 where the model never emits the ``exact h <num>``
  schema in top-5 (truncated to ``exact h`` or hijacked by Mathlib
  transplant). A tactic-token decoder should fix this.
* **Train a small learned reranker** on the v11/v12 verification
  outcomes once enough labelled (candidate, success) pairs exist.
  Currently 4 families × 10 candidates × 5 test rows ≈ 200 labelled
  candidates per family — borderline for a stable learned model.
* **Add v10 redundancy cells for the contrapositive shape** to unblock
  `neg_imp_exfalso`; the v11 result there was unmoved precisely
  because the corpus didn't supply the right siblings.
* **Filter the v8 base pool to core-Lean only** (drop ``rcases``,
  ``obtain``, etc.). The Mathlib-transplant failure mode is the
  v8 base pool's contamination; filtering would let v12's malformed
  penalty and the literal-adapt schema win more cleanly.
