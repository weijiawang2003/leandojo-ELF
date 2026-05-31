# V25 zero-shot tier-C report (Part 4)

Driver: [`scripts/evaluate_v25_tierc.py`](../scripts/evaluate_v25_tierc.py).
Results: `data/baselines/v25_zero_shot_tierc/<config>/`.

**The fixed v24 broad generator, evaluated zero-shot on the 36-theorem Mathlib
tier-C benchmark**, with candidates verified live by whole-file typecheck against
real Mathlib (`lake env lean`, `import Mathlib`). The v24 model never saw any
v25 / Mathlib data, so this is leakage-free by construction. Beams come only
from the generator; the verified reference candidates are **not** fed to it.

## Headline: transfer is real but **bimodal**

| config | pass@1 | pass@5 | pass@10 | MRR | no-verify |
|---|---|---|---|---|---|
| raw | 0.333 | 0.472 | 0.556 | 0.404 | 16 |
| rule | 0.250 | 0.361 | 0.556 | — | 16 |
| **learned** | **0.472** | **0.528** | 0.556 | **0.503** | 16 |
| policy | 0.250 | 0.389 | 0.556 | — | 16 |
| abstract | 0.417 | 0.528 | 0.556 | 0.468 | 16 |
| policy_abstract | 0.389 | 0.528 | 0.556 | — | 16 |

`pass@10 = 0.556` is **rerank-invariant** (the generator ceiling): the v24
generator puts a Mathlib-verifying tactic in its top-10 for **20 of 36** tier-C
theorems. Reranking (learned / abstract) lifts pass@1 from 0.333 → **0.472** and
pass@5 to 0.528, but cannot exceed the 0.556 ceiling.

## The split that explains everything: core vs Mathlib

The benchmark was designed with each theorem tagged `core` (a broad-core-style
tactic should suffice) or `mathlib` (expected to need a Mathlib lemma/tactic).
Transfer cleaves almost perfectly along that axis (raw / best):

| transfer | n | pass@1 | pass@5 | pass@10 | reachable@10 |
|---|---|---|---|---|---|
| **core** | 16 | 0.625 / 0.688 | 0.688 / **0.812** | **0.812** | **13/16** |
| **mathlib** | 20 | 0.100 / 0.350 | 0.300 / 0.350 | 0.350 | 7/20 |

- On **core-shaped Mathlib theorems the v24 generator transfers well** —
  pass@5 up to **0.812**, 13/16 reachable. Skills it already has (`rfl`,
  `omega`, `exact ⟨…⟩`, `intro`, `Or`/`And`, `rw [h]`, `simp`) carry straight
  into the Mathlib environment. Examples it solved at rank 1:
  `n + 0 = n` → `exact rfl`; `Nat.succ n = n + 1` → `omega`;
  `a = b ⊢ a+1 = b+1` → `rw [h]`; and even some `mathlib`-tagged ones:
  `xs ++ [] = xs` → `simp`, `(!!b) = b` → `cases b <;> rfl`.
- On **Mathlib-lemma-needing theorems it mostly fails** — pass@10 0.350, only
  7/20 reachable.

### Per category (best config)

| category | n | pass@5 | pass@10 |
|---|---|---|---|
| nat | 10 | 0.700 | 0.700 |
| logic | 8 | 0.750 | 0.750 |
| list | 7 | 0.571 | 0.571 |
| bool_option | 6 | 0.333 | 0.500 |
| **set** | 5 | **0.000** | **0.000** |

**All 5 Set theorems are unreachable** — the generator has *zero* Set vocabulary
(`Set.Subset.refl`, `subset_refl`, `Set.mem_univ`, `∈ {a}`, `s ∩ t ⊆ s`), so it
never proposes a verifying candidate. This is the single cleanest "wall" signal.

## Failure taxonomy (Part 4 required)

Over all failed beam candidates (raw config, 36 theorems × ≤10):

| class | count | meaning |
|---|---|---|
| **unknown_identifier** | **164** | model emits a lemma/hyp name not in scope (e.g. `hAll`, `hp`, made-up lemmas) |
| type_mismatch | 70 | right idea, wrong term/type |
| parse_error | 57 | malformed tactic syntax |
| other | 23 | misc elaboration errors |
| unknown_tactic | 4 | tactic name not available |
| shape_miss (unsolved goals) | 2 | tactic ran but didn't close the goal |
| **import_env** | **0** | **no environment/import failures at all** |

Theorem-level **no-verify reasons** (16 theorems): unknown_identifier ×11,
parse_error ×3, type_mismatch ×2. **Zero are environment/import issues.**

A vivid `mathlib` no-verify example, `n ≤ n`: the v24 beam is
`exact hAll 42`, `exact Exists.intro 42`, `exact ⟨42, hp …⟩` — it pattern-matches
the goal to forall/exists shapes it knows and **hallucinates identifiers**
(`hAll`, `hp`, `42`) that aren't in context, never reaching `omega` /
`Nat.le_refl`. And `n * 1 = n`: the beam only tries `exact rfl` / `exact Eq.refl`
(which don't reduce) — it never proposes `simp` / `Nat.mul_one` / `ring`.

## Answers to the research questions (from Part 4 evidence)

1. **Can the v24 generator transfer to tiny Mathlib theorems?** **Yes, partially
   and predictably.** Overall pass@10 0.556; but **0.812 on core-shaped** Mathlib
   theorems vs **0.350 on Mathlib-lemma-needing** ones. Transfer tracks shared
   skill, not the Mathlib label per se.
2. **Is failure env / vocabulary / shape / identifier?** **Not environment**
   (0 import/env errors — Mathlib imports cleanly). It is **identifier/lemma
   vocabulary** (164 unknown_identifier, the dominant class) **plus theorem-shape
   coverage** (Set goals and `≤` goals are wholly outside the generator's
   distribution).
3. **Does a tiny Mathlib corpus improve transfer?** → measured in Part 5
   ([`V25_TIERC_AUGMENTATION_REPORT.md`](V25_TIERC_AUGMENTATION_REPORT.md)).
4. **Is the next wall env/tooling, generator coverage, or proof-state
   supervision?** **Generator coverage** (vocabulary + shape). The Mathlib
   environment install was effectively free and produced zero env-class failures.

## Confirmation

- ✅ v24 model fixed; zero-shot; leakage-free by construction.
- ✅ live Mathlib typecheck; no mock; manual references not used as predictions.
- ✅ no state_after; no v10 leakage; no full-theorem-proving claim.
