# Mini-ELF v12 — literal + rerank failure analysis (v11 candidates)

Per-row classification of v11's beam top-5 on the `forall_inst`
LOFO fold, plus the other v11 families for context. Source data:
`data/baselines/v11_family_lofo_eval/<fam>/v11/predictions.jsonl` and
`data/processed/proof_blocks_v11_family_lofo/<fam>/test.jsonl`.

## forall_inst (n=7, v11 pass@5 = 0.143)

| theorem | goal literal | gold tactic | v11 top-0 | v11 stale-literal hits in top-5 | correct literal in top-5? | verified rank |
|---|---:|---|---|---:|:-:|---:|
| `forall_inst_7_0` | 7 | `exact h 7` | `exact h 7` | 1 | yes | **0** ✓ |
| `forall_inst_3_0` | 3 | `exact h 3` | `exact h 4` | 3 | no | — |
| `forall_inst_5_2` | 5 | `exact h 5` | `exact h` | 1 | no | — |
| `forall_inst_9_4` | 9 | `exact h 9` | `exact h 4` | 3 | no | — |
| `forall_inst_13_6` | 13 | `exact h 13` | `exact h 4` | 3 | no | — |
| `forall_inst_var_m` | 8 | `exact h 8` | `exact h` | 0 | no | — |
| `forall_inst_var_k` | 8 | `exact h 8` | `rcases h with ⟨n, hn⟩\n  exact ` | 1 | no | — |

### Key observation

**6 of 7 failing rows have at least one `exact h <K>` candidate in top-5
with K ≠ goal-literal.** The model learned the SHAPE `exact h <num>` from
the v10 redundancy cells (`nat_eq_3`, `nat_eq_7`, `nat_le_5`,
`nat_add_zero_4`); it just emits the literal from its v10-pool
vocabulary `{3, 4, 5, 7}` instead of the goal literal.

**1 row (`forall_inst_var_m`) has no `exact h <K>` candidate in top-5
at all** — beam emits `exact h` (truncated) and Mathlib variants. The
schema isn't reached.

**Per-row failure class**:

| theorem | class | notes |
|---|---|---|
| `forall_inst_7_0` | (passed) | gold literal `7` happens to be in v10's training pool |
| `forall_inst_3_0` | **rank_failure / stale_literal** | shape present in top-5 but with wrong literal (`4`, `7`); v10's `nat_eq_3` taught the right tactic, beam ordering failed |
| `forall_inst_5_2` | **stale_literal + truncation** | top-0 = `exact h` (no literal); top-2 = `exact h` (Type mismatch); literals 4/7 in other slots |
| `forall_inst_9_4` | **missing_literal** | v10 has no `exact h 9`; closest is `exact h 4` |
| `forall_inst_13_6` | **missing_literal** | v10 has no `exact h 13`; closest is `exact h 4` |
| `forall_inst_var_m` | **schema_missed** | model didn't emit `exact h <num>` schema in top-5 at all |
| `forall_inst_var_k` | **mathlib_transplant + schema_missed** | top-0 = `rcases h …`; no clean numeric schema |

## Predicted v12 unblocks

A conservative `exact h <K> → exact h <goal-literal>` post-processing
step would convert each of the **`stale_literal`** and
**`missing_literal`** rows (4 of 6 failing rows) into a correct gold
tactic, since the schema is present and the goal literal is parseable.

`forall_inst_var_m` and `forall_inst_var_k` won't be unblocked by
literal-substitution alone — the model never emits the `exact h <num>`
schema in top-5 for those two. They are out of reach of v12 without
additional candidate generation.

**Expected v12 forall_inst pass@5**: up from 1/7 = 0.143 to roughly
**5/7 = 0.714** (the 4 stale/missing literal rows + the 1 row that
already passes), with the 2 schema-missed rows still failing.

## rewrite_succ (n=5, v11 pass@5 = 0.800)

No literal in the goal that the test row's gold tactic depends on
(`rw [h]`, `exact congrArg Nat.succ h`, `subst h\n  rfl`, `exact h ▸ rfl`
all use `h` directly with no numeric substitution). v12's literal
adaptation should **not** modify rewrite_succ candidates — verified by
the literal-adapt module's conservative gate (skip when no `exact h
<num>` schema is detected).

v12 must therefore preserve v11's `rewrite_succ` 4/5 pass@5 (the v12
brief requires `rewrite_succ ≥ 0.800`).

## neg_exfalso, exists_reconstruct, neg_imp_exfalso

The reranker may slightly reorder candidates for these families but
literal adaptation is not relevant (`exact absurd hp hnp`,
`cases h with | intro …`, contrapositive `intro hp; …` use no
adaptable numeric literals).

## Beam-rank failure (the v12 reranker target)

The clearest reranker case is **`forall_inst_3_0`**: v11 top-5 contains
some `exact h <K>` candidates, but none with K=3 even though
`exact h 3` is in train (v10 `nat_eq_3`). The beam ordering puts `4`
and `7` ahead. A goal-literal-aware reranker that boosts candidates
whose first numeric literal matches the goal's first numeric literal
should surface `exact h 3` if generated, or — when paired with the
literal-adapt module — re-rank the *adapted* candidate `exact h 3` to
beam rank 0.

## Mid-token truncation (out of v12 scope)

`exact h` (no literal), `exact h.`, `rcases h with ⟨n, hn⟩\n  exact `,
`rw [hns` continue to appear. v12 explicitly leaves the char-level
tokenizer untouched (the brief defers BPE to v13). A
*malformed-penalty* feature in the reranker can demote them without
fixing them.

## Failure-mode counts (top-5 across all 5 v11 families)

| failure class | rough count (top-5 per row) |
|---|---:|
| `stale_literal` (`exact h <K>` with K wrong) | ~10 (forall_inst) |
| `mathlib_transplant` (`rcases`/`obtain`) | ~14 |
| `type_mismatch` (`exact rfl`, `exact h.symm`) | ~20 |
| `truncation` (`exact h.`, `rw [hns`) | ~12 |
| `schema_missed` (no `exact h <num>` for forall_inst) | 2 of 7 forall_inst |
| `rw_h_correct` (rewrite_succ gold) | ~5 across rewrite_succ |
| `cases_h_intro` (exists_reconstruct gold) | ~5 across exists_reconstruct |

v12 directly attacks `stale_literal` (literal adaptation) and
`rank_failure` cases (reranker). It does NOT attack the char-level
truncation (deferred), the Mathlib transplant (deferred), or the
schema_missed cases on `forall_inst_var_{m,k}` (the model never
generates the right schema; out of v12 reach).
