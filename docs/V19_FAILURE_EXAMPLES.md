# Mini-ELF v19 — Failure Examples

Concrete per-theorem traces showing the v19 abstraction layer's
failure modes. Companion to
`V19_IDENTIFIER_ABSTRACTION_REPORT.md`.

---

## 1. `unresolved_placeholder` — the new dominant failure

* **Theorem**: `v18_or_swap` — `(p q : Prop) (h : p ∨ q) : q ∨ p`
* **Required tactic**: `cases h with | inl hp => exact Or.inr hp | inr hq => exact Or.inl hq`
* **v19 abstract beam (top 3)**:
  ```
  rank 0: 'cases <HYP_OR_0> with | inl <HYP_PROP_0> => exact ...'
            → concretises to 'cases h with | inl p => exact ...'
            → fails: `p` is already a Prop name, not a fresh binder
  rank 1: 'exact <HYP_OR_0>.elim (fun <HYP_PROP_1> => Or.inr ...)'
            → unresolved: <HYP_PROP_1> has no binding
            → flagged as `unresolved_placeholder`
  rank 2: 'cases <HYP_OR_0> with | inl <HYP_AND_0> => ...'
            → unresolved: state has no <HYP_AND_0>
  ```

The abstract model emits placeholder patterns it learned in train
(`<HYP_PROP_1>`, `<HYP_AND_0>`) that don't exist in v18's
parsed local context. Concretisation correctly rejects them as
`unresolved_placeholder`. **This is the v19 brief's anticipated
"new dominant failure" class.**

## 2. Mid-tactic binder shadowing

* **Theorem**: `v18_imp_intro_basic` — `(p q : Prop) (hp : p) : q → p`
* **Required tactic**: `intro hq\n  exact hp` (introduce hq, then
  use hp).
* **v19 abstract emission (rank 0)**:
  `intro <HYP_PROP_0>\n  exact <HYP_PROP_0>`
* **Concretised**: `intro hp\n  exact hp`
* **Lean verdict**: type mismatch (the introduced `hp` shadows the
  outer `hp` and has type `q`, not `p`).

The v19 abstraction is built from the *pre-tactic* state, so
`<HYP_PROP_0>` was bound to the original `hp`. The decoder
re-emits the same placeholder for the *introduced* binder name,
collapsing two distinct identifiers. A v20 placeholder map would
need to track introductions tactic-internally.

## 3. Category mis-match across train and test

* **Theorem**: `v18_conjunction_intro` — `(p q : Prop) (hp : p) (hq : q) : p ∧ q`
* **Required tactic**: `exact ⟨hp, hq⟩` — verifies cleanly in v18
  broad-synthetic.
* **v19 abstract emission**: `exact ⟨<HYP_PROP_0>, <HYP_PROP_0>⟩`
  (same placeholder twice — the model collapsed two distinct
  hypotheses).
* Concretised: `exact ⟨hp, hp⟩`
* Lean verdict: type mismatch.

v18 broad-synthetic emits `exact ⟨hp, hq⟩` correctly (it has the
literal names in its training data). v19's placeholder system
treats `hp` and `hq` as both `<HYP_PROP_X>` and the model fails
to distinguish them by index.

The state had:
```
p q : Prop
hp : p
hq : q
```
which abstracts to:
```
<PROP_0> <PROP_1> : Prop
<HYP_PROP_0> : <PROP_0>
<HYP_PROP_1> : <PROP_1>
```
So the correct abstract tactic *is* `exact ⟨<HYP_PROP_0>,
<HYP_PROP_1>⟩`. The model learned `exact ⟨<HYP_PROP_0>,
<HYP_PROP_0>⟩` instead — because in v17 contrapositive training
the conjunction shape rarely appeared with two **distinct**
HYP_PROP slots.

## 4. The keyword-protection ✓

The abstraction layer correctly protects Lean tactic keywords from
substitution:

```
input  : 'exact hp'  with state 'p : Prop\nhp : p\n⊢ p'
output : 'exact <HYP_PROP_0>'   ← `exact` preserved as keyword
```

And word-boundary protection:

```
state 'p : Prop\nh : p\nhp : p\n⊢ p'
input  : 'exact h'   → 'exact <HYP_PROP_0>'   (single-char ident `h`)
input  : 'exact hp'  → 'exact <HYP_PROP_1>'   (two-char ident `hp`)
```

These work correctly — pinned by `tests/test_identifier_abstraction.py`.

## 5. Where v19 abstraction *does* help (minor)

* **v18 equality_rewrite rows**: the abstract model emits
  `rw [<HYP_EQ_0>]` which concretises cleanly across different
  hypothesis names. This is one of the few categories where
  abstraction matches or near-matches the v18 broad-synthetic
  baseline (ensemble pass@5 = 0.833 vs broad's 1.000 — a small
  regression because `rw [h]` is *already* what the v18 broad
  model emits, so abstraction adds no signal but also doesn't hurt
  much).
* **forall_inst rows**: abstract emission of `exact <HYP_FORALL_0>
  <NUMBER>` concretises correctly when the v18 state has a single
  forall hypothesis. Ensemble preserves v18's 0.667 pass@5.

## 6. Summary by failure class redistribution

| class | v18 broad-only | v19 abstract-only | v19 ensemble |
|---|---:|---:|---:|
| `unknown_identifier` | 127 (26%) | ~30 (6%) | ~80 (17%) |
| `unresolved_placeholder` | 0 | **210 (44%)** | **190 (40%)** |
| `type_mismatch` | 124 (26%) | ~115 (24%) | ~115 (24%) |
| `parse_error` | 72 (15%) | ~70 (15%) | ~70 (15%) |
| `timeout` | 28 (6%) | ~30 (6%) | ~30 (6%) |
| `ok` | 29 (6%) | **10 (2%)** | **15 (3%)** |

**Headline**: v19 trades `unknown_identifier` for
`unresolved_placeholder` at a worse exchange rate (≈2× the
slots), while halving the `ok` count.

## 7. What this analysis tells v20

* **Don't abstract on the generator side.** Try ranker-time
  abstraction: keep generation in raw names (v18 broad-synthetic),
  but score candidates by how well their abstract pattern matches
  training distribution.
* **Add the missing implication and Bool shapes to corpus.**
  v19 confirmed these are corpus-shape-bound, not name-bound.
* **Track tactic-introduced binders** if abstraction is revisited
  in v21+: the placeholder map must extend mid-tactic to handle
  `intro h` correctly.
