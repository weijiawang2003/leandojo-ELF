# Mini-ELF v19 — Implication Identifier Analysis

Companion to `V19_IDENTIFIER_ABSTRACTION_REPORT.md`. The v18 brief
called out `implication` as the worst-transferring v18 category
(pass@5 = 0.000 under both v17 panel and v18 broad-synthetic). v19
asked specifically whether *identifier abstraction* would lift it.

**Direct answer: no.** Under v19 abstract-only and v19+broad
ensemble, `implication` pass@5 stays at **0.000** on v18. The
abstraction layer does not solve the underlying problem because the
problem is *missing shape*, not *missing name*.

---

## 1. `v18_imp_p_self` — the canonical case

* **Theorem**: `(p : Prop) (hp : p) : p`
* **Required tactic**: `exact hp`
* **v18 broad-synthetic top-3**: `exact And.intro hp hnp`,
  `exact And.intro hp`, `exact hp hnp` — three wrong shapes.
* **v19 abstract model top-3** (concretised): same three wrong
  shapes, because the abstract model's training data ALSO never had
  the bare `exact <HYP_PROP_0>` shape — every "exact <ident>"
  example in v17 corpora had an application (`exact h hp` not just
  `exact hp`).
* Under the v19 abstract beam the model produces
  `exact <HYP_PROP_0> <HYP_OTHER_N>` style — which concretises to
  `exact hp <unbound>` if `<HYP_OTHER_N>` has no v18 binding →
  `unresolved_placeholder` failure → counted as model failure (and
  this happens on most ranks).

The honest conclusion: the trivial `exact hp` shape is **absent
from every synthetic training corpus**. v19 abstraction layers
*do not invent shapes*; they just rename existing ones. So
`implication`'s wall is **corpus-shape-bound**, not identifier-bound.

## 2. `v18_imp_intro_basic` — the identifier-confusion case

* **Theorem**: `(p q : Prop) (hp : p) : q → p`
* **Required tactic**: `intro hq\n  exact hp` (introduce a new
  hypothesis named `hq`, then `exact hp`).
* **v18 broad-synthetic top emissions**: `intro hp\n  exact h`
  (the model **shadows** the existing `hp` with the introduced
  name, then references unbound `h`).
* **v19 abstract emissions**: in principle, after `intro` the
  decoder should emit
  `intro <PROP_X>\n  exact <HYP_PROP_0>`. In practice, the v19
  abstract model emits `intro <HYP_PROP_0>\n  exact <HYP_PROP_0>`
  — collapsing the introduced binder with the pre-existing
  hypothesis. Concretisation produces `intro hp\n  exact hp` which
  is **incorrect** (it shadows the original `hp`).
* The structural problem: the abstraction layer **does not extend
  the placeholder map** when a tactic introduces a new binder.
  v19's abstraction is pre-decoded, fixed at the input state's
  context; mid-tactic introductions are not represented in the
  placeholder space.

A more sophisticated v20 abstraction would have to track
introduced binders within the tactic and reserve fresh
placeholders for them.

## 3. The "preserve solved categories" violation

The v19 brief asked: "preserve equality_rewrite / conjunction /
list performance". v19 violated this:

| category | v18 broad-synthetic pass@5 | v19 abstract+broad ensemble pass@5 | Δ |
|---|---:|---:|---:|
| equality_rewrite | 1.00 | 0.83 | **−0.17** |
| conjunction | 0.83 | 0.17 | **−0.66** |
| list | 0.80 | 0.20 | **−0.60** |
| negation | 0.80 | 0.40 | **−0.40** |

**Why preservation fails**: the abstraction layer takes up beam
slots with malformed/unresolved candidates, *displacing* the
broad-synthetic candidates that did work. The ensemble's top-10
union has the v19 abstract model's outputs first (they're emitted
first in the panel iteration), and after dedup the broad-synthetic
beam ends up at ranks 10+.

A v20 fix would invert priority: emit broad-synthetic candidates
first, then *only* concretised v19 abstract candidates whose
placeholders fully resolve.

## 4. The honest takeaway for `implication`

The v19 brief was explicit that v19 attacks **identifier transfer,
not proof reasoning**. The data confirms: even with perfect
identifier transfer (placeholders that always resolve), `implication`
would still fail because the missing shapes
(`exact hp`, `intro hq; exact hp`) are missing from the *training
corpus*, not from the *name mapping*.

v20's correct target is **corpus shape coverage for trivial
implication patterns**: add `(p : Prop) (hp : p) : p` and
`(p q : Prop) (hp : p) : q → p` examples to the synthetic train
pool. This is the same corpus-augmentation pattern v16 used for
contrapositive and v17 used for arrow-false-elim — proven to work
when the shape is genuinely missing.
