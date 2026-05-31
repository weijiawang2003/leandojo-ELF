# Mini-ELF v12 — failure examples (literal_adapt_rerank)

Verbatim from
`data/baselines/v12_eval/<fam>/literal_adapt_rerank/predictions.jsonl`.
`[ADAPT]` = candidate emitted by `literal_aware_decode`; `[s2s]` =
original v11 model beam output. `OK` = lean-cli verified; `FAIL`
includes the first line of the lean error.

## `forall_inst` — v11 1/7 → v12 3/7 (pass@5 0.143 → 0.429)

### `forall_inst_7_0` — **PASS** (no v12 change needed; gold was at rank 0 already)

```
[0]   OK   [s2s]  'exact h 7'                                ← MATCH (gold)
[1] FAIL   [s2s]  'exact h'                                  | timeout
[2] FAIL   [s2s]  'exact h ⟨n, hn⟩'                          | Invalid ⟨…⟩
[3] FAIL   [s2s]  'exact h.sexact'                           | invalid field
[4] FAIL   [s2s]  'exact h ⟨7, rfl'                          | unexpected end
```

### `forall_inst_3_0` — **v12 UNBLOCK** (literal-adapt promotes to rank 0)

```
[0]   OK [ADAPT]  'exact h 3'                                ← LITERAL-ADAPT WIN
[1] FAIL   [s2s]  'exact h'                                  | Type mismatch
[2] FAIL   [s2s]  'exact h w'                                | unknown ident
[3] FAIL   [s2s]  'exact h q'                                | unknown ident
[4] FAIL   [s2s]  'exact h h'                                | Application type
```

The v11 beam never emitted ``exact h 3`` (the v10 ``nat_eq_3`` cell
exists in train but the beam picked ``exact h 4``/``exact h 7``).
The literal-adapt module observed
``exact h 4`` schema match + goal literal 3 → emits ``exact h 3``.
The reranker's goal-literal-match (+2.0) puts it at rank 0.

### `forall_inst_9_4` — **v12 UNBLOCK** (literal-adapt again)

```
[0]   OK [ADAPT]  'exact h 9'                                ← LITERAL-ADAPT WIN
[1] FAIL   [s2s]  'exact h w'                                | unknown ident
[2] FAIL   [s2s]  'exact h q'                                | unknown ident
[3] FAIL   [s2s]  'exact h (h'                               | timeout
[4] FAIL   [s2s]  'exact h ▸'                                | unexpected end
```

Hypothesis is ``∀ x : Nat, x = 4`` and goal is ``9 = 4`` — but
``exact h 9`` instantiates to ``9 = 4`` which is exactly the goal.
Verifies.

### `forall_inst_5_2` — **v12 ADAPTED CANDIDATE TIMED OUT** (honest)

```
[0] FAIL [ADAPT]  'exact h 5'                                | timeout      ← would likely verify
[1] FAIL   [s2s]  'exact h'                                  | Type mismatch
[2] FAIL   [s2s]  'rcases h with ⟨n, hn⟩'                    | rcases (Mathlib)
[3] FAIL   [s2s]  'cases h with | intro n'                   | Tactic `cases`
[4] FAIL   [s2s]  'rcases h with hn => exa'                  | unsolved goals
```

The literal-adapt produced ``exact h 5`` at rank 0; lean-cli hit a
20 s cold-start timeout. With a warmer verifier this row would
likely verify (the v11 forall_inst_7_0 / 3_0 / 9_4 rows verified
``exact h <N>`` quickly). Reported as FAIL — honest lower bound.

### `forall_inst_13_6` — **same: adapted candidate timed out**

```
[0] FAIL [ADAPT]  'exact h 13'                               | timeout      ← would likely verify
[1] FAIL   [s2s]  'exact h w'                                | unknown ident
[2] FAIL   [s2s]  'exact h ▸'                                | unexpected end
[3] FAIL   [s2s]  'exact h (h'                               | unexpected end
[4] FAIL   [s2s]  'exact h'                                  | timeout
```

### `forall_inst_var_m` — **OUT OF V12 REACH** (no schema in top-5)

```
[0] FAIL   [s2s]  'exact h'                                  | Type mismatch
[1] FAIL   [s2s]  'refine hq ='                              | unexpected end
[2] FAIL   [s2s]  'rcases h wi'                              | unknown ident   ← truncation
[3] FAIL   [s2s]  'refine hq'                                | unknown ident
[4] FAIL   [s2s]  'refine hq⟩'                               | unknown ident
```

No ``exact h <num>`` schema appears anywhere in top-5; literal-adapt
has nothing to substitute. The failure is **char-level truncation**
(``exact h`` cut before the literal) and **Mathlib transplant**
(``rcases h wi``). Both are v13 work (tokenizer + base-pool filter).

### `forall_inst_var_k` — **adapted candidate timed out (mathlib pollution at top-5)**

```
[0] FAIL [ADAPT]  'exact h 8'                                | timeout      ← would likely verify
[1] FAIL   [s2s]  'refine hq => exact h'                     | unknown ident
[2] FAIL   [s2s]  'rcases h with ⟨n, hn⟩ \n   exact h'       | Tactic `rcases`
[3] FAIL   [s2s]  'rcases h with | intro h  | intro'         | unexpected tok
[4] FAIL   [s2s]  'rcases h with ⟨n, hq⟩ \n   exact h'       | Tactic `rcases`
```

The model's beam emits some ``exact <name> <something>`` shape
(presumably ``exact h <K>`` for some K). Literal-adapt picks it up,
emits ``exact h 8``, reranker boosts to rank 0. Lean-cli timed out.

### Potential vs honest

If the 3 cold-start timeouts (``forall_inst_5_2``, ``forall_inst_13_6``,
``forall_inst_var_k``) had verified, the v12 ``forall_inst`` pass@5
would have been **6/7 = 0.857** instead of **3/7 = 0.429**. The
reported value is the honest lower bound; do not retcon.

## `exists_reconstruct` — v11 4/5 → v12 5/5 (pass@5 0.800 → 1.000)

The 5th row (one of the v11 failures) had ``exact ⟨6, rfl⟩`` in the
v11 beam for a goal needing ⟨3, rfl⟩. Literal-adapt's witness schema
emits ``exact ⟨3, rfl⟩``; reranker boosts; verified. (Concrete dump
omitted for brevity; see
``data/baselines/v12_eval/exists_reconstruct/literal_adapt_rerank/predictions.jsonl``
row 5.)

## `rewrite_succ` — preserved at 4/5 (pass@5 0.800)

### `rewrite_succ_nm` — top-0 = ``rw [h]`` (already gold)

```
[0]   OK   [s2s]  'rw [h]'                                   ← MATCH
[1] FAIL   [s2s]  'exact Eq'                                  | Type mismatch
[2] FAIL   [s2s]  'exact h'                                   | Type mismatch
[3] FAIL   [s2s]  'rw [h] h'                                  | unexpected ident
[4] FAIL   [s2s]  'r] [h]'                                    | unknown tactic
```

Literal-adapt does NOT fire on rewrite_succ (no goal literal,
no ``exact h <num>`` shape). The reranker's schema-match for
``rewrite`` head keeps ``rw [h]`` at rank 0.

### `rewrite_succ_ij` — **still times out at rank 0** (same as v11)

```
[0] FAIL   [s2s]  'rw [h]'                                    | timeout
[1] FAIL   [s2s]  'exact Eq'                                  | Type mismatch
[2] FAIL   [s2s]  'exact h'                                   | Type mismatch
[3] FAIL   [s2s]  'exact h.'                                  | Invalid field
[4] FAIL   [s2s]  'rw [hns'                                   | unexpected end
```

The same v11 cold-start timeout on ``rw [h]`` persists into v12 (we
re-use the v11 cache). With a warmer verifier this row would verify.
Both v11 and v12 report 0.800 (4/5), not 1.000.

## What v12 does not fix

* `forall_inst_var_m`: char-level truncation; literal-adapt has no
  schema to grab. **v13: tokenizer.**
* `forall_inst_5_2`/`13_6`/`var_k`: literal-adapt emits the right
  shape, but lean-cli cold-start timeouts on those calls. **Eval-time
  noise; warm verifier would lift them.**
* `neg_imp_exfalso`: v10 lacks the contrapositive shape; nothing in
  train, nothing to adapt. **v13: extend v10 redundancy with the
  contrapositive shape.**
* Mathlib-tactic transplant (``rcases h …`` etc.) continues to
  pollute v11's beam top-5; the reranker's malformed-penalty
  attenuates the *truncated* versions but not full mathlib-style
  candidates whose syntax is locally well-formed.
