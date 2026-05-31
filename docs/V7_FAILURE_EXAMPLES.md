# Mini-ELF v7 — failure & transfer examples (real lean-cli transcripts)

Concrete candidates the v7 retriever proposed under donor scarcity, with the
actual lean-cli verdicts. Extracted from
`data/baselines/v7_eval/<split>__<config>/predictions.jsonl`. These ground the
claims in `docs/V7_RETRIEVAL_HOLDOUT_REPORT.md`: cross-family transfer is **0**
because the held-out family's concrete proof is simply absent from the donor pool,
while same-family scarce reuse (incl. role re-concretisation) works.

## 1. family_holdout — cross-family, *same operation*, still fails

The held family's same-operation sibling supplies the top donor, but its concrete
tactic references hypotheses the target does not have.

**Target `neg_exfalso_pq`** — `p q : Prop, hp : p, hnp : ¬p ⊢ q` (op `contradiction`).
Same-family donors are held out; top donor is `neg_or_cases_pq` (also `contradiction`):

```
#0  donor=neg_or_cases_pq (neg_or_cases)   ✗
    cases h with
      | inl hp => exact absurd hp hnp
      | inr hq => exact hq
    lean: error unknownIdentifier `h`        ← target has hp/hnp, no `h : _ ∨ _`
#1  donor=neg_or_cases_pq (neg_or_cases)   ✗
    rcases h with hp | hq
      exact absurd hp hnp
      exact hq
    lean: error unknownIdentifier `h`
```

The operation label (`contradiction`) matches, but `neg_or_cases` destructs a
disjunction that `neg_exfalso` does not have. → pass@5 = 0.

## 2. family_holdout — cross-family, *same operation signature*, still fails

**Target `exists_elim_conj_l_pq`** — `h : ∃ _ : Nat, p ∧ q ⊢ p` (op `destruct_exists`).
Top donor is `exists_elim_prop_p` (same operation **and** same abstract signature
`rcases|exists` / `obtain|exists`):

```
#0  donor=exists_elim_prop_p (exists_elim_prop)   ✗
    rcases h with ⟨n, hp⟩
      exact hp
    lean: Type mismatch — hp has type `p ∧ q` but goal is `p`
#1  donor=exists_elim_prop_p (exists_elim_prop)   ✗
    obtain ⟨n, hp⟩ := h
      exact hp
    lean: Type mismatch — hp has type `p ∧ q` ...
```

Even an *identical operation signature* does not transfer: `exists_elim_conj`
needs the `.1` projection (`exact hp.1`) that the `exists_elim_prop` donor proof
never performs. The bodies differ below the operation level.

## 3. operation_holdout — no same-operation donor at all

**Target `forall_inst_7_0`** — `h : ∀ x : Nat, x = 0 ⊢ 7 = 0` (op `instantiate_forall`).
`instantiate_forall` is a sole-family operation, so holding it out leaves **no**
donor of that operation; the retriever grabs structurally-unrelated donors:

```
#0  donor=exists_reconstruct_7 (exists_reconstruct)  ✗  [adapted]
    exact ⟨0, rfl⟩
    lean: Insufficient number of fields for `⟨...⟩`
#1  donor=exists_reconstruct_7 (exists_reconstruct)  ✗
    rcases h with ⟨n, hn⟩
      exact ⟨n, hn⟩
    lean: `rcases` failed — `h : ∀ (x : Nat), …` is not destructurable
```

→ pass@5 = 0. The donor pool contains no proof of this shape.

## 4. kshot_1 — same-family scarce reuse rescued by **role re-concretisation** (v7 win)

**Target `neg_exfalso_arrow_pq`** — `p q : Prop, h : p → False, hp : p ⊢ q`. Its
negation hypothesis is written as an **arrow** `p → False`, not `¬p`. Only one
`neg_exfalso` donor is in train (1-shot).

v6_retrieval (type-exact `hyp_remap` cannot bind `hnp : ¬a` to `h : p → False`):

```
#0  donor=neg_or_cases_pq (neg_or_cases)   ✗   cases h with | inl … | inr …
    lean: `cases` failed — major premise is `p → False`, not an inductive
#1  donor=neg_or_cases_pq (neg_or_cases)   ✗   rcases h with hp | hq …
    lean: `rcases` failed — `h : p → False` is not …
→ row fails pass@5
```

v7_abstract (role re-concretisation: `p → False` is the `neg` role; re-bind the
same-family donor `exact absurd hp hnp` → `exact absurd hp h`):

```
#0  donor=neg_exfalso_ab (neg_exfalso)   ✓ [retrieval_reconcretized]   exact absurd hp h
#1  donor=neg_exfalso_ab (neg_exfalso)   ✓ [retrieval_reconcretized]   exact (h hp).elim
#2  donor=neg_exfalso_ab (neg_exfalso)   ✓ [retrieval_reconcretized]   exact False.elim (h hp)
→ row passes pass@1
```

This is **same-family** transfer (donor `neg_exfalso_ab` is `neg_exfalso`), so it
does not register as cross-family — it is a *robustness* gain in the scarce
1-shot regime (+12 rank-1 rows, all arrow-form negation hypotheses).

## 5. literal_holdout — numeric adaptation works (positive)

**Target `forall_inst_9_4`** — `h : ∀ x : Nat, x = 4 ⊢ 9 = 4`. Literal `9` is held
out of every train tactic; the schema `exact h <num>` is present (via
`forall_inst_var_m`, `exact h 8`):

```
#0  donor=forall_inst_var_m (forall_inst)  ✓ [retrieval_adapted]   exact h 9   ← literal copied from goal
#1  donor=forall_inst_var_m (forall_inst)  ✗ [retrieval_adapted]   exact h 4   (type mismatch 4 = 4)
#2  donor=forall_inst_var_m (forall_inst)  ✗   exact h 8           (type mismatch 8 = 4)
→ row passes pass@1
```

The verbatim donor (`exact h 8`) fails; the *adapted* candidate (`exact h 9`,
literal copied from the goal LHS) verifies. This is what makes
`literal_holdout` pass@5 = 1.00 for the `forall_inst` rows.
