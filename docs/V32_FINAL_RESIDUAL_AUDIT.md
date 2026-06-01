# V32 — Part 1: Final-Residual Audit

_`scripts/audit_v32_final_residual.py` → `data/baselines/v32_final_residual/report.json`.
Reads the v31 normalized eval + verified corpora + a recorded single-tactic Lean probe._

## The one residual

| field | value |
|---|---|
| theorem | `v30_set_empty_inter_subset` |
| statement | `(α : Type) (s t : Set α) : (∅ : Set α) ∩ s ⊆ t` |
| family | `set::empty_subset` |
| family train siblings | 3 (all `∅ ⊆ s`, **not** the `∅ ∩ _` shape) |
| model top beams | `Set.inter_subset_left`, `intro x h; exact` (truncated), `Set.inter_subset_right`, `Set.empty_subset s` |
| error classes | type_mismatch / parse_error / unknown_identifier |
| **classification** | **`sparse_shape_single_tactic`** |

## Is it single-tactic? — Yes (Lean-probed)

A direct Lean probe (recorded in the audit) confirmed the goal closes by **several
single tactics**: `simp`, `intro x hx; cases hx.1`, `intro x hx; simp at hx`,
`intro x hx; exact hx.1.elim`. So it is **not** multi-step, **not** proof-state-bound,
**not** an API/arity gap — it is a **sparse-shape coverage gap on the single-tactic
tier**: the `∅ ∩ _ ⊆ _` shape is underrepresented (the `empty_subset` family trained
only `∅ ⊆ s`), so the model reaches for the generic `inter_subset_left`/`empty_subset s`
instead of `simp`.

## Answers

- **RQ1 (what is the residual?)** A single underrepresented Set shape, `∅ ∩ s ⊆ t`.
- **RQ2 (fixable by density, or a true limit?)** **Fixable by density** — it is
  single-tactic; a few verified `∅ ∩ _` siblings with `simp` should close it (Part 2).
- **LeanDojo justified by this residual?** **No** (`leandojo_justified_by_residual:
  false`) — 0 multi-step residuals.

→ Part 2 attempts the minimal repair (single-tactic ⇒ add 10–40 verified `∅∩`/empty
siblings). No `state_after`; expected proofs are Lean-verified references.
