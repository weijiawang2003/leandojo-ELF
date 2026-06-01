# V30 — Part 0: Repo / Process / Environment Status

_Generated at the start of the Mini-ELF v30 targeted density-repair run._

## Git (history untouched — constraints forbid abort/reset/rebase/commit)

- `HEAD` = `b4fcd6c` on branch `v27-mathlib-specialist`. **0 new commits** since
  `b4fcd6c` (v28 and v29 also committed nothing).
- The stale **`.git/rebase-merge/` from 2026-05-28 is still present and untouched**.
- v30 makes **zero git changes**; only doc/data artifacts under `docs/`, `data/`,
  `scripts/`, `tests/`, `src/` are added/edited.

## Processes

No stale `lean`/`lake`/`python`/`pytest` jobs running (only OS daemons). Clean start.

## Toolchain

- Lean **4.30.0** (`d024af0`), Lake **5.0.0-src+d024af0**.
- External pinned Mathlib at `~/code/mini_elf_mathlib_probe`
  (`leanprover/lean4:v4.30.0`); verifier uses the direct toolchain binary +
  cached `LEAN_PATH` (`.tmp/v27_lean_path.txt`), never the elan shim.

## Lemma probes (via `TrustedMathlibVerifier`, warmup OK)

The four v30-target lemmas all resolve and verify against `import Mathlib`:

| probe | tactic | verdict |
|---|---|---|
| `Nat.add_assoc` (`a+b+c = a+(b+c)`) | `exact Nat.add_assoc a b c` | ✅ |
| `Set.empty_subset` (`∅ ⊆ s`) | `exact Set.empty_subset s` | ✅ |
| `le_rfl` (`a ≤ a`, `[Preorder]`) | `exact le_rfl` | ✅ |
| `Set.mem_inter_iff` (`x∈s∩t ↔ …`) | `exact Set.mem_inter_iff x s t` | ✅ |

`Nat.add_assoc` and `Set.empty_subset` are exactly the two v25 micro-regression
targets — the correct tactics verify, so the v25 regression is a **ranking/coverage**
problem, not an unprovable goal (confirmed in Part 1).

## v29 state v30 starts from (to preserve / repair)

| metric | v29 value | v30 obligation |
|---|---|---|
| routed broad-core p@5 / p@10 | 0.9375 / 0.9583 | preserve (v24 untouched) |
| **v25 held-out pass@10** | **0.857** (regressed from 1.000) | **recover toward 1.000** |
| v26 holdout pass@10 | 1.000 | preserve |
| v28 fresh holdout pass@10 | 0.933 (general) / 0.967 (heavy) | preserve |
| v29 fresh holdout pass@10 | 1.000 | preserve/improve |
| remaining residuals | 8 (6 vocab / 2 API / 0 multi-step) | reduce if possible |
| trusted-verifier gold mismatches | 0 | maintain 0 |

## The density law v30 acts on (from v29)

Held-out pass@10 by effective training siblings: **0.684 (0) → 0.829 (1–3) → 0.944
(4–6)**; reliable (≥0.9) at **~4 siblings**. v30 is a **targeted** repair: bring only
families below the 4–6 threshold (and the v25-regression families) up to 4–6 — **no
broad random expansion**, no category balancing, no capacity probe (unless targeted
repair fails), no chasing whole-category transfer.

## Honesty constraints in force

Trusted verifier only · no `state_after` · no manual-oracle predictions · no v10
leakage · no full-proving claim · no naive verifier for headline metrics · v24
broad-core never overwritten · no category balancing · no capacity probe by default ·
git history untouched.
