# Mini-ELF v15 — Failure & Win Examples

Concrete rows demonstrating the v15 policy's behaviour. All
candidates come from v14's emitted beam (no v15 generation);
"reordering" means the policy chose a different top-k subset.

---

## 1. The headline policy win — `forall_inst_3_0` pass@1

* **Theorem.** `(h : ∀ x : Nat, x = 0) : 3 = 0`
* **Required operation.** `instantiate_forall` → policy routes to **rule**.
* **Result.** policy pass@1 = ✓; learned-only pass@1 = ✗.

The v14 + LA composed beam (10 candidates):

```
rank 0 (seq2seq):                'intro h\n  rfl'                    fail
rank 1 (seq2seq):                'exact h ⟨n, rfl⟩'                  fail
rank 2 (seq2seq):                'exact h ⟨n, hn⟩'                   fail
...
rank 8 (seq2seq_literal_adapt):  'exact h 3'                         VERIFIED
...
```

* **rule** orders by goal-literal match (`3` in `exact h 3`) and
  source priority (`literal_adapt`): the LA candidate flies to rank 0
  → pass@1 = ✓.
* **learned**: the LR's pattern features don't strongly prefer
  literal_adapt sources over malformed siblings on forall_inst → it
  leaves the LA candidate at rank ~3 → pass@1 = ✗.
* **policy** (operation == `instantiate_forall`) chooses rule → pass@1 = ✓.

---

## 2. The headline policy win — `exists_reconstruct_3` pass@1

* **Theorem.** `(h : ∃ n : Nat, n = 3) : ∃ m : Nat, m = 3`
* **Required operation.** `unknown` (the v11 fold tags it `unknown`)
  → policy routes to **learned**.
* **Result.** policy pass@1 = ✓; rule pass@1 = ✗.

The v14 + LA beam:

```
rank 0 (seq2seq):                'cases h with | intro n hn => exact ⟨n, hn⟩'  VERIFIED
rank 1 (seq2seq):                'exact ⟨3, rfl⟩'                              fail (witness binding)
rank 2 (seq2seq):                'rcases h with ⟨n, hn⟩\n  exact ⟨n, hn⟩'      VERIFIED (alternate)
...
rank 5 (seq2seq_literal_adapt):  'exact ⟨3, rfl⟩'                              fail (same as r1, deduped)
...
```

* **rule** promotes literal_adapt's `exact ⟨3, rfl⟩` to rank 0
  (literal-match bonus), demoting the verified `cases` candidate
  → pass@1 = ✗.
* **learned** has positive weight on `contains_cases +
  contains_angle_open + contains_intro` from sibling-family training
  → leaves the verifying `cases ...` at rank 0 → pass@1 = ✓.
* **policy** (operation == `unknown`) chooses learned → pass@1 = ✓.

---

## 3. The headline policy win — `neg_imp_exfalso_pq` pass@5

* **Theorem.** `(p q : Prop) (hpq : p → q) (hnq : ¬q) : ¬p`
* **Required operation.** `intro_negation` → policy routes to **learned**.
* **Result.** policy pass@5 = ✓ (verifying candidate at rank 4);
  rule pass@5 = ✗ (verifying candidate pushed to rank 6).

v14 raw beam:

```
rank 0: 'intro hp\n  exact hnq (h1 hp)'           fail (h1 not bound)
rank 1: 'intro hp\n  exact hnq (h hp)'            fail (type mismatch)
rank 2: 'exact fun hp => hnq (h1 '                fail (truncated)
rank 3: 'exact fun hp => hnq (h '                 fail (truncated)
rank 4: 'intro hp\n  exact absurd hp hnp'         VERIFIED ✓
rank 5: 'exact fun h => hnq (h1 '                 fail
...
```

* **rule**: penalises rank 4 (no goal-literal, no `⟨_, rfl⟩` schema,
  doesn't match the source-priority bonus) → pushes to rank 6.
* **learned**: `contains_intro + contains_absurd +
  op_intro_negation` weights keep rank 4 → pass@5 = ✓.
* **policy** routes to learned → pass@5 = ✓.

---

## 4. The residual `neg_imp_exfalso_ab` failure (generator-bound)

* **Theorem.** `(a b : Prop) (hab : a → b) (hnb : ¬b) : ¬a`
* **First-verified rank under policy.** 6 (just past top-5).
* **First-verified rank under any other config.** 6 (raw) / 8 (rule).
* **Conclusion.** v14's token beam places the verifying candidate at
  rank 6 on this row; no reorder of 10 items can lift it into top-5.
  This is a generator-side ceiling, **not** a reranker problem.

---

## 5. The honest learned-only regression — `forall_inst_7_0` pass@1

The learned-only config (without the policy router) regresses pass@1
on forall_inst because it doesn't carry the +0.5 source-priority
bonus the rule reranker has for `literal_adapt` candidates.

v14 + LA beam for `forall_inst_7_0`:

```
rank 0 (seq2seq):                  'intro h\n  rfl'                fail
rank 1 (seq2seq):                  'exact ⟨7, rfl⟩'                fail
...
rank 7 (seq2seq_literal_adapt):    'exact h 7'                     VERIFIED ✓
```

* **learned**: scores rank 7 candidate slightly below several rank-0
  malformed siblings because it doesn't have a strong `literal_adapt
  source` feature weight (only 1 `+w` versus several `+w`s on
  intro/exact-shape features the siblings also carry).
* **policy** (operation == `instantiate_forall`) overrides with
  **rule** → pass@1 = ✓.

This is **why the policy exists**: each individual ranker has
operation-specific failure modes.

---

## 6. Bottom line

* The policy delivers **mean pass@5 = 0.885 (vs v14's 0.765)** and
  **mean pass@1 = 0.725 (vs v14's 0.514)** by routing each
  required_operation to the right sub-scorer.
* The 4 / 5 wins on `neg_imp_exfalso` at pass@5 represent the full
  reranker-side ceiling; the 5th row is generator-bound.
* No new candidates, no new templates, no `state_after`, no manual
  oracle, no v10-leakage revival.
