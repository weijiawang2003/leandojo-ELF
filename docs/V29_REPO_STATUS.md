# V29 — Part 0: Repo / Environment Status

_Generated 2026-05-31 at the start of the Mini-ELF v29 sibling-density scaling run._

## Git (history untouched — constraints forbid abort/reset/rebase/commit)

- `HEAD` = `b4fcd6c` "Mini-ELF v27: scaled Mathlib specialist + hardened verifier"
  on branch `v27-mathlib-specialist`. **No new commits made by v28 or v29.**
- A **stale `.git/rebase-merge/` directory from 2026-05-28 is still present and is
  left completely untouched** (constraints forbid `git rebase --abort`/`--continue`,
  reset, or commit). It does not affect the working tree; `git status` is clean of
  any staged changes. v29 makes **zero git changes**.
- Working tree: only the expected v28-era doc edits (`README.md`,
  `docs/{NEXT_STEPS,PROJECT_REPORT,RESULTS_SUMMARY,RESUME_BULLETS}.md`) plus
  untracked `data/baselines/*` eval outputs and `.claude/` are modified/untracked.
  No source or history mutation.

## Toolchain

- `lean --version` → **Lean 4.30.0** (`d024af0`, Release).
- `lake --version` → **Lake 5.0.0-src+d024af0 (Lean 4.30.0)**.
- External Mathlib scratch project: `~/code/mini_elf_mathlib_probe`,
  `lean-toolchain` = `leanprover/lean4:v4.30.0` (real, pinned, **not a mock**).
- Verifier uses the **pinned direct toolchain binary**
  `/home/wangw/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean` with a
  **precomputed `LEAN_PATH`** cached at `.tmp/v27_lean_path.txt` — never the elan
  `lean` shim (hang risk; see memory `lean-verifier-use-direct-toolchain-binary`).
- No stray `lean`/`lake`/`python`/`pytest` processes running at start.

## Lemma probes (via `TrustedMathlibVerifier`, sentinel+confirm+rescue)

All four required probes — plus the new sparse-residual targets — **resolve and
verify** against `import Mathlib` (warmup OK, 4 invocations, 47.2 s warm):

| probe | tactic | verdict |
|---|---|---|
| `Finset.mem_union` (`x∈s → x∈s∪t`) | `exact Finset.mem_union.mpr (Or.inl h)` | ✅ |
| `le_antisymm` (`a≤b → b≤a → a=b`) | `exact le_antisymm h1 h2` | ✅ |
| `Function.comp_assoc` (`(h∘g)∘f = h∘(g∘f)`) | `rfl` | ✅ |
| `Set.union_subset` (`s⊆u → t⊆u → s∪t⊆u`) | `exact Set.union_subset h1 h2` | ✅ |
| `Finset.mem_of_mem_inter_left` (`x∈s∩t → x∈s`) | `exact Finset.mem_of_mem_inter_left h` | ✅ |

The trusted verifier is **sound & complete** (gold-tested in v27/v28 with 0
mismatches); `confirm=False` raises `UnsafeVerifierError`. Headline metrics use it
exclusively. The naive batched verifier is never used for any reported number.

## v28 baselines to **preserve** and **beat** (v29 targets)

| metric | v28 value | v29 obligation |
|---|---|---|
| routed broad-core pass@5 / pass@10 | **0.9375 / 0.9583** | preserve (v24 untouched) |
| v25 held-out pass@10 | **1.000** | preserve |
| v26 holdout pass@10 | **0.955** | preserve or improve |
| **fresh v27 holdout pass@10** | **0.857** (best cfg 1.000) | improve |
| **fresh v28 30-thm holdout pass@10** | **0.867** | **improve** (primary) |
| Finset held-out pass@10 | **0.833** | improve if possible |
| Finset whole-category transfer | **0.333** | improve |
| Set whole-category transfer | **0.237** | improve |
| order whole-category transfer | **0.778** | improve |
| trusted-verifier gold mismatches | **0** | maintain 0 |

## v28 corpus (the pool v29 extends)

158 theorems → **350 verified rows, 0 coverage gaps** (set 132, order 61,
finset 51, nat 41, logic 30, function 22, list 13). Configs:
`v28_general` 554 / `set_order_heavy` 816 / `category_balanced` 442 /
`finset_specialist` 606; shared val 137; fresh 30-theorem v28 holdout (70 rows).

## v28 conclusion that frames v29

Improvement came from **within-family sibling density**, not generic category
transfer (whole-category transfer stayed weak: set 0.237, finset 0.333). v29
therefore scales sibling density **directly** in residual / low-transfer families
and quantifies the density↔held-out-success relationship. Category **balancing was
harmful** in v27 and v28 (0.700 vs 0.867) — v29 re-runs it only as a labelled
negative control, never adopted.

## Honesty constraints in force for v29

Trusted verifier only · no `state_after` · no manual-oracle candidates as model
predictions · no revived v10 leaked metrics · no claim of full theorem proving ·
no naive verifier for headline metrics · v24 broad-core model never overwritten ·
do not adopt a router that regresses routed broad-core · do not category-balance
except as an explicit negative control.
