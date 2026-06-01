# V33 — Part 0: Repo / Process Status

_Start of the Mini-ELF v33 final single-tactic robustness/coverage pass._

## Git (untouched)

- `HEAD` = `b4fcd6c`; **0 new commits** (v28–v32 committed nothing). Stale
  **`.git/rebase-merge/` from 2026-05-28 present, untouched**. v33 makes zero git changes.

## Processes — the "5 shells" check

No stale `lean`/`lake`/`python`/`pytest` jobs (only `claude`). The v32 background jobs
all completed and exited. Clean start.

## Toolchain

Lean **4.30.0**, Lake **5.0.0**; external pinned Mathlib at `~/code/mini_elf_mathlib_probe`.
All four probe lemmas verify.

## The 11 v32 residuals v33 targets

| group | n | residuals |
|---|---:|---|
| adversarial identifiers (subscript `proof₁`) | 5 | `set/finset mem_inter_proj` & `mem_union_intro` `_2` variants |
| fresh shapes | 5 | `set::inter_assoc`, `order::le_trans` (4-chain), `order::min_max` (`min/max_comm`), `order::lattice` (`inf_comm`) |
| sparse shape | 1 | `set::empty_subset` (`∅∩s⊆t`) |

**All 11 are single-tactic, 0 multi-step** (v32 Part 7). v33's two levers (per the v32
saturation recommendation): **(a) harden the canonical decode** so subscript/Greek
identifiers (`proof₁`, `hα`) canonicalize cleanly (cut the 8.5 % adversarial unresolved
rate); **(b) add fresh-shape density** for the order/set shapes.

## v32 state to preserve

| metric | v32 | v33 obligation |
|---|---|---|
| routed broad-core p@5 / p@10 | 0.9375 / 0.9583 | preserve (v24 untouched) |
| routed tier-C pass@10 (202) | 0.950 | preserve ~0.950 or better |
| adversarial identifier-stress | 0.891 | keep high / improve |
| residual count | 11 (all single-tactic) | reduce if possible |
| trusted-verifier gold mismatches | 0 | maintain 0 |

## v33 plan & decision

Targeted residual coverage (Part 2) + a hardened canonical decode + a fresh robustness
holdout (Part 3) → train (Part 5) → eval/routed (Parts 6–7) → **final saturation
decision** (Part 8): if residuals stay single-tactic and stress holds, **recommend
packaging**; LeanDojo only if a genuine multi-step residual appears.

## Honesty constraints

Trusted verifier only · no `state_after` · no manual-oracle predictions · no v10
leakage · no full-proving claim · no naive verifier for headline metrics · v24
untouched · no category balancing · no capacity probe · **no LeanDojo next-state unless
v33 finds genuine multi-step residuals** · git untouched.
