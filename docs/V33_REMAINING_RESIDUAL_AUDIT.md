# V33 — Part 1: Remaining-Residual Audit

_`scripts/audit_v33_remaining_residuals.py` →
`data/baselines/v33_remaining_residual/report.json`. No Lean run._

The 11 v32 residuals, classified:

| classification | count | residuals |
|---|---:|---|
| **canonicalization_gap** | **5** | the `_2` adversarial variants (set/finset `mem_inter_proj`/`mem_union_intro`) — they use the **subscript identifier `proof₁`** |
| theorem_shape_density_gap | 3 | `set::inter_assoc`, `order::le_trans` (4-hop chain), `set::empty_subset` (`∅∩`) |
| vocabulary_gap | 3 | `order::min_max` (`min_comm`/`max_comm`), `order::lattice` (`inf_comm`) |
| **true_multi_step_gap** | **0** | — |

## The decisive cause of the 5 canonicalization-gap residuals

`parse_binders` **failed to recognize `proof₁`** as a binder — the subscript `₁` was
outside the identifier regex — so the hypothesis was not canonicalized, the canonical
model's `exact c4.1` had no `c4` slot, and the candidate was **rejected** (this is the
8.5 % adversarial unresolved rate v32 reported). **v33 hardens the canonical decode**:
`v31_identifier_normalization` now includes Unicode subscripts/superscripts
(`proof₁`, `h₂`, `f¹` all parse), purely additively (existing identifiers unchanged;
all v31/v32 module tests still pass). With the fix, `exact proof₁.1` canonicalizes to
`exact c4.1` and round-trips — so the 5 subscript residuals should now resolve.

## The other 6

Theorem-shape / vocabulary gaps fixed by the **residual-coverage corpus** (Part 2):
verified siblings for `inter_assoc`/`union_assoc`, `le_trans` 3–4-hop chains,
`min_comm`/`max_comm`/`inf_comm`/`sup_comm`, and more `∅∩` shapes.

## Headline

**0 of 11 residuals are multi-step.** Every one is a single-tactic
canonicalization / vocabulary / shape gap — so v33's two levers (hardened decode +
targeted coverage) should close most, and **LeanDojo next-state is not justified by any
residual**. No `state_after`; expected proofs are references.
