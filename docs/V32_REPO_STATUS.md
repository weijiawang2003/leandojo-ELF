# V32 — Part 0: Repo / Process Status

_Start of the Mini-ELF v32 robustness / saturation run._

## Git (untouched)

- `HEAD` = `b4fcd6c`; **0 new commits** since (v28–v31 committed nothing). Stale
  **`.git/rebase-merge/` from 2026-05-28 present, untouched**. v32 makes zero git changes.

## Processes — the "5 shells" check

No stale `lean` / `lake` / `python` / `pytest` jobs are running (only the `claude`
process itself). The background eval/train jobs launched in v28–v31 all completed and
exited; nothing to kill. Clean start.

## Toolchain

Lean **4.30.0**, Lake **5.0.0**; external pinned Mathlib at `~/code/mini_elf_mathlib_probe`.
All four probe lemmas verify (`Set.mem_inter_iff`, `Finset.mem_inter`, `Set.union_subset`,
`Nat.add_assoc`).

## v31 state v32 starts from

| metric | v31 value | v32 obligation |
|---|---|---|
| routed broad-core p@5 / p@10 | 0.9375 / 0.9583 | preserve (v24 untouched) |
| routed tier-C pass@10 | **0.985** (131 held-outs) | preserve ≥0.985 if possible |
| token-diversity (13 v30 residuals) | 0.00 → **0.92** | hold |
| remaining residuals | **1** (`∅∩s⊆t`, a sparse *shape*) | close or characterize |
| canonical unresolved (main eval / routing) | 0 / 0.9 % | keep near-zero, stress-test |
| trusted-verifier gold mismatches | 0 | maintain 0 |

## v32 plan

1. Audit the **one** v31 residual exactly (single-tactic? API? multi-step?).
2. Minimal repair if single-tactic; document for v33 if multi-step (do **not** force).
3. **Adversarial identifier-renaming** stress benchmark — does canonicalization
   generalize beyond the specific v30 residuals, or only memorize them?
4. **Fresh Mathlib micro-holdout** — robustness to unseen single-tactic theorems.
5. Routed eval; saturation analysis → v33 decision (packaging vs LeanDojo vs more coverage).

## Honesty constraints

Trusted verifier only · no `state_after` · no manual-oracle predictions · no v10
leakage · no full-proving claim · no naive verifier for headline metrics · v24
untouched · **no LeanDojo next-state work unless v32 proves the residual is genuinely
multi-step/proof-state-bound** · git untouched.
