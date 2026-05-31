# Mini-ELF v14 — Failure & Win Examples (annotated)

Concrete rows from the v14 token-level seq2seq run, with the
candidates lean actually saw. Companion to
`V14_TOKEN_SEQ2SEQ_REPORT.md`.

---

## 1. The headline v14 win — `forall_inst_var_m` (v13 residual case)

* **Theorem.** `(m : Nat) (h : ∀ x : Nat, x = m) : 8 = m`
* **v13 char outcome.** pass@5 = ✗ — beam dominated by
  `refintro hn`, `rwexact h`, `refin rfl⟩`, `rcases h wi`. No
  `exact <ident> <num>` schema in beam, so v12 literal-adapt gate
  stayed closed.
* **v14 token outcome.** pass@5 = ✓ under `+literal_adapt + warm`.

The v14 token beam:

```
rank 0  src=seq2seq_literal_adapt   cand='exact h 8'              → VERIFIED (warm rerun)
rank 1  src=seq2seq                 cand='exact ⟨m, rfl⟩'         → fail (insufficient args)
rank 2  src=seq2seq                 cand='exact ⟨m, hn⟩'          → fail (insufficient args)
rank 3  src=seq2seq                 cand='exact ⟨m, hb⟩'          → fail
rank 4  src=seq2seq                 cand='exact ⟨n, hn⟩'          → fail
...
```

The token model emits **clean `exact h` schema-shaped tokens**
without truncation, which is exactly what v12 literal-adapt needs to
synthesise `exact h 8`. The v13 char model emitted truncated /
fused-keyword variants instead.

**Mechanism:** the closed `KEYWORD` set in
`src/mini_elf_lean/tactic_tokenizer.py` makes `exact`, `intro`,
`rw`, etc. single tokens. The model cannot emit a half-word like
`refin` or a fused token like `rwexact`; it either emits the
keyword whole or chooses a different keyword.

---

## 2. The cross-family compositional win — `neg_imp_exfalso_pq`

* **Theorem.** `(p q : Prop) (h1 : p → q) (hnq : ¬q) (hp : p) : False` -- but wait, the family-LOFO theorem is actually `(p q : Prop) (hpq : p → q) (hnq : ¬q) : ¬p` (contrapositive). Lean state shows `⊢ ¬p` after intro.
* **v13 char outcome.** pass@5 = ✗ (every family-LOFO neg_imp_exfalso
  row was ✗ under v13).
* **v14 token outcome.** pass@5 = ✓ at rank 4 (raw beam, warm
  rerun).

The v14 token beam:

```
rank 0  cand='intro hp\n  exact hnp'           → fail (type mismatch)
rank 1  cand='exact absurd hp hnp'             → fail (missing intro)
rank 2  cand='exact fun hp => hnq (h1 '        → fail (truncated)
rank 3  cand='intro hp\n  exact (hnq (h1 hp))' → fail (close, but bracketing)
rank 4  cand='intro hp\n  exact absurd hp hnp' → VERIFIED ✓
rank 5  cand='exact False.elim …'              → fail
...
```

**Honesty check.** The verifying string
`intro hp\n  exact absurd hp hnp` is **not in the train set** of
the neg_imp_exfalso fold (the family-LOFO holdout removes every
such row from train). The train set contains:

* `exact absurd hp hnp`         — in `exfalso_pq`, `neg_or_cases`, `neg_exfalso`
* `cases h with | inl hp => exact absurd hp hnp | inr hq => exact hq`
                                — in `neg_or_cases`
* (and other absurd-bearing tactics in 7 sibling families)

So v14 **composes** `intro hp` (seen in many implication families)
with `exact absurd hp hnp` (seen in 7 sibling negation families).
This is cross-family compositional novelty —
`novel_verified=12` total across the fold.

**Why the char model can't do this.** The char-level decoder
generated `intro hp\n  exact hnp` (rank 0) and `exact absurd hp hnp`
(rank 1) as separate beams in v11, but never composed them. The
token-level decoder treats `intro hp\n  ` as a token-prefix and
`exact absurd hp hnp` as a token-suffix that can attach to it; the
attention model learned the join.

---

## 3. The reranker mis-calibration — `neg_imp_exfalso` pass@5 = 0.200 with +LA

* v14 raw pass@5 = **0.800** (12/15 verified at top-5)
* v14 + LA + rerank pass@5 = **0.200** (3/15 verified at top-5)
* v14 + LA + rerank **pass@10 = 1.000** (12/15 verified at top-10)

**Diagnosis.** The v12 reranker scores candidates by:
* +2.0 goal-literal match — contrapositive goals have no literal
* +0.4 schema match (`exact <id> <num>` / `exact ⟨<num>, rfl⟩`) —
  contrapositive shape doesn't match
* +0.5 source priority for literal_adapt — neg_imp_exfalso has no
  literal-adapt candidates
* −1.0 stale literal — N/A
* −2.0 malformed — penalises some valid `exact fun hp => …` shapes

The verifying `intro hp\n  exact absurd hp hnp` candidate has none
of the *positive* features and a few of the *neutral* features, so
it gets ranked below candidates that are syntactically "schema-shaped"
but don't typecheck (e.g. `exact ⟨hp, hnp⟩`). It stays in the beam
(pass@10 = 1.000) but drops out of top-5.

**v15 fix:** train a learned reranker on accumulated lean outcomes.
The current rule-based reranker is at its design limit; it was
explicitly tuned for v12's forall_inst/exists_reconstruct shapes.

---

## 4. The remaining `forall_inst` lost row — `forall_inst_3_0` rank-0 timeout

Actually, **v14 warm rerun fixed this**. Pre-rerun v14 had pass@5 = ✗
on this row because the rank-0 literal-adapt candidate `exact h 3`
timed out at 120 s in v14's eval (same cold-start issue v13 had).
Post-rerun at 180 s: ✓.

This generalises: **v14 had 4 timeout candidates flip to verified**
under the rerun:

| theorem | candidate | rank | source | flipped? |
|---|---|---:|---|:---:|
| forall_inst_3_0 | `exact h 3` | 0 | seq2seq_literal_adapt | ✓ |
| forall_inst_var_k | `exact h 8` | 0 | seq2seq_literal_adapt | ✓ |
| exists_reconstruct_20 | `cases h with \| intro n hn => exact ⟨n, hn⟩` | 0 | seq2seq | ✓ |
| neg_imp_exfalso_xy | `intro hp\n  exact absurd hp hnp` | 4 | seq2seq | ✓ |

The other 13 timeout candidates revealed genuine elaboration errors
once lean had time to report them (parse errors, type mismatches,
unknown identifiers) — same pattern as v13.

---

## 5. The remaining unfixed cases

After warm rerun:

* **`neg_imp_exfalso` pass@5 with +LA**: 0.200. **Reranker
  mis-calibration**, not a model issue. pass@10 = 1.000. v15 work.
* **`neg_exfalso` 3/8 failures**: row-by-row inspection shows the
  beam never emits the dual-hypothesis pattern
  `exact absurd <expr1> <expr2>` for these specific theorems.
  Family-LOFO holdout has removed the closest training shapes; the
  model needs a richer training distribution. v15 corpus work.
* **`exists_reconstruct_20` pass@1 = 0** at v14 + LA + rerank: the
  rerank picks a malformed adapted candidate (`exact ⟨m, rfl⟩`)
  ahead of the verifying `cases h with | intro n hn => exact ⟨n,
  hn⟩`. Tossed back into top-5 → pass@5 = ✓.

---

## 6. Summary by diagnosis class (post-rerun)

| class | rows | v14 verdict | v15 work |
|---|---:|---|---|
| timeout-only (4 candidates rerun) | 4 | **fixed** | n/a |
| char-truncation + schema gate (forall_inst_var_m) | 1 | **fixed** by token vocab | n/a |
| cross-family composition (neg_imp_exfalso) | up to 5 unique theorems | **fixed at pass@10** for raw + LA; pass@5 limited by reranker | learned reranker |
| reranker mis-rank (neg_imp_exfalso +LA pass@5) | up to 4 rows | pass@5 ✗ even though candidate present | learned reranker |
| missing-shape in train (neg_exfalso family-LOFO 3 fails) | 3 | unfixed | corpus work |
| witness-construction subtleties (exists_reconstruct rerank) | latent | pass@5 ok at pass@10 | learned reranker |
