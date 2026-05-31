# Mini-ELF v18 — Failure Taxonomy + Examples

Companion to `V18_ZERO_SHOT_TRANSFER_REPORT.md`. The taxonomy
classes are inspired by the v18 brief Part 7 list; the examples
come from `data/baselines/v18_zero_shot_v17_pipeline/policy/predictions.jsonl`.

---

## 1. Successful transfer — `v18_eq_subst_lhs` (`equality_rewrite`)

* **Theorem.** `(n m k : Nat) (h : n = m) : n + k = m + k`
* **Required tactic.** `rw [h]`
* **policy top-1:** `rw [h]` — **VERIFIED ✓**
* **Why it transfers.** v17 has hundreds of `rw [h]` shapes in
  rewrite_succ training; the rule reranker's `+rw_h_schema` feature
  promotes it to rank 0; the identifier `h` matches the hypothesis
  name (which v17 happens to use too).

The model + reranker do *exactly* what v17 was tuned for. Every
`equality_rewrite` row verifies at pass@1 (6/6).

---

## 2. Strong transfer — `v18_neg_modus_tollens` (`negation`)

* **Theorem.** `(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p`
* **Required tactic.** `intro hp\n  exact hnq (h hp)`
* **policy top-1:** verified at rank 0
* **Why it transfers.** This is the v17 brief's "classical
  contrapositive" shape; the v16 contrapositive corpus has 117
  verified examples of `intro hp; exact hnq (h hp)`. Direct
  transfer.

4 of 5 negation rows verify at pass@5.

---

## 3. Total miss — `v18_imp_p_self` (`implication`)

* **Theorem.** `(p : Prop) (hp : p) : p`
* **Required tactic.** `exact hp` — about as simple as a Lean
  proof gets.
* **policy top-10 (none verifying):**

```
rank 0: 'exact And.intro hp hnp'   unknown_identifier 'hnp'
rank 1: 'exact And.intro hp'       Type mismatch  (And.intro hp : ?m → p ∧ ?m)
rank 2: 'exact hp hnp'             Function expected at 'hp'
rank 3: 'exact And.intro hp hp'    Type mismatch  (p ∧ p vs p)
rank 4: 'exact h hp'               unknown_identifier 'h'
rank 5: 'exact h.elim'             unknown_identifier 'h.elim'
rank 6: 'exact hp\n  exact hp'     No goals to be solved
rank 7: 'exact And.intro hp =>'    parse error
rank 8: 'exact And.intro hp hq'    unknown_identifier 'hq'
rank 9: 'exact False.elim hp'      Application type mismatch
```

**Diagnosis: NO_SCHEMA_IN_BEAM + identifier confusion.** The model
emits **zero** `exact hp` candidates anywhere in the union of 5
panel beams + literal-adapt. Instead it recites `And.intro ...`
patterns from conjunction training and `False.elim ...` from
negation training. The v11 forall_inst training shaped the
forall_inst panel member to expect `exact <ident> <num>` /
`exact h <something>` patterns; "just exact a hypothesis" without
any application or constructor is **outside its distribution**.

Note rank 6 — `exact hp\n  exact hp` — the *first half* of which
would have verified. The model has the right idea but appends a
spurious second tactic that lean rejects with "No goals to be
solved".

---

## 4. Identifier confusion — `v18_imp_intro_basic` (`implication`)

* **Theorem.** `(p q : Prop) (hp : p) : q → p`
* **Required tactic.** `intro hq\n  exact hp`
* **policy top-10 (none verifying):**

```
rank 0: 'exact id'                  Type mismatch (id : ?→? vs q → p)
rank 3: 'intro hp\n  exact h'       unknown_identifier 'h'
rank 4: 'intro h\n  exact h'        Type mismatch (h : q vs p)
rank 6: 'intro hp\n  exact (h hp)'  unknown_identifier 'h'
```

**Diagnosis: STALE_HYPOTHESIS.** The model emits `intro h\n  exact
h` — confusing the introduced binder with the existing `hp`. v17's
training rarely had this exact "intro and then exact a *different*
hypothesis" pattern, so the model defaults to reusing the introduced
name. This is the v17 brief's "wrong hypothesis" failure class.

---

## 5. Total miss — `v18_bool_true_or_false` (`bool`)

* **Theorem.** `(b : Bool) : b = true ∨ b = false`
* **Required tactic.** `cases b with | true => exact Or.inl rfl | false => exact Or.inr rfl`
* **All 3 bool theorems fail at pass@10 with 0 verified candidates.**
* **Diagnosis: NO_SCHEMA_IN_BEAM (corpus-shape-bound).** v17 has
  **zero** Bool training. The model has never seen `cases b` (Bool
  cases as opposed to Or cases), so it emits malformed-shape
  candidates like `cases b with hp hq => ...` borrowed from
  exists_reconstruct patterns. The `cases` keyword is in the
  tokenizer vocab but the model's contextual usage is wrong.

---

## 6. Identifier-name leak — generic across categories

The dominant error class (133 / 480 = 28 % of all candidates in
top-10) is **unknown_identifier**. v17's models learned specific
names (`h`, `hp`, `hnp`, `hpq`, `hnq`) and reference them
indiscriminately. v18 uses mixed names (`xs`, `hand`, `hImp`,
`prf`, `b`, `n`, `α`) and the model writes tactics referring to
identifiers that aren't bound.

Mitigations a v19 model could try:
* **Constrained decoding** — refuse tokens that name unbound
  identifiers (Lean would tell us via the local context).
* **State-aware tokenisation** — emit `<local-hyp>` placeholders
  during training, substitute at inference.
* **Training-data diversity** — explicitly vary hypothesis names
  in synthetic corpus.

---

## 7. Stale-literal artefact — `v18_forall_inst_at_7` (`forall`)

* **Theorem.** `(p : Nat → Prop) (h : ∀ n, p n) : p 7`
* **Required tactic.** `exact h 7`
* **policy top-10:** `exact h 7` verifies at rank 0 (via literal-
  adapt schema).
* **But** rank 2 / 3 / 4 emit `exact h 3`, `exact h 8`, `exact h 13`
  (literals from v11 forall_inst training data leaking through).
* **Effect on metric:** none — top-0 already verifies. But the leak
  illustrates v17's training-distribution overfit.

---

## 8. The 20 no-top-10 theorems (corpus-shape-bound failures)

By category, count of "no-verified-in-top-10" theorems:

| category | total | no-top-10 |
|---|---:|---:|
| implication | 6 | **6** |
| bool | 3 | **3** |
| exists | 4 | 3 |
| list | 5 | 3 (in raw; 1 in policy after rerank) |
| disjunction | 5 | 2 (at pass@10) |
| nat_succ | 5 | 2 |
| forall | 3 | 1 |
| equality_rewrite | 6 | 0 |
| conjunction | 6 | 1 |
| negation | 5 | 1 |

The bulk of the wall is in `implication` (every row fails) and
`bool` (no training). These two categories alone account for 9 of
the 20 missing theorems. Closing them requires **corpus / training
work**, not reranking.

---

## 9. Failure-class summary (the v18 brief's taxonomy applied)

| brief class | observed | dominant in v18? |
|---|---|---|
| no schema in beam | yes | **YES — primary failure mode** (e.g. `exact hp`, `cases b`) |
| wrong tactic head | yes | partial (1 / 48 wrong-head at top1 vs expected_head) |
| malformed candidate | yes | rare (3 / 480 top-1 slots) |
| stale literal / stale variable | yes | identifier-leak version, very common |
| wrong hypothesis | yes | `intro h\n  exact h` confusion is canonical |
| wrong rewrite direction | not observed in this run | — |
| missing intro | yes | implication category misses the intro step |
| missing constructor | yes | exists rows miss `⟨_,_⟩` constructor |
| missing cases | yes | bool rows miss `cases b` |
| type mismatch | yes | 118 / 480 occurrences |
| timeout | yes | 23 / 480 occurrences |
| environment / import issue | none | (no Mathlib by design) |
| unsupported Mathlib tactic | none | (no Mathlib by design) |
| verifier backend issue | none | (lean-cli stable on Lean 4.30.0) |

The **single biggest blocker** is *no-schema-in-beam* — the v17
generator simply doesn't emit the right shape for `implication`
and `bool`. Reranking cannot fix this; only a broader generator
training distribution can.
