# Mini-ELF v27 — Repo / Environment Status (Part 0)

Date: 2026-05-31. Working dir: `~/code/ELFMath`. This is the v27 baseline snapshot
taken before any v27 corpus/model/verifier work.

## Toolchain

| Tool | Version |
|------|---------|
| Lean | 4.30.0 (`d024af0`, Release) |
| Lake | 5.0.0-src+d024af0 |
| `lean`/`lake` on PATH | `~/.elan/bin/*` (elan shims) |
| Trusted verify binary | `/home/wangw/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean` |

`MINI_ELF_LEAN_COMMAND` is unset in the ambient shell; per the project memory the
**direct toolchain binary** (not the elan `lean` shim) must be used for sustained
verification loops — the shim intermittently hangs under load. The batched
verifier defaults to that binary (`DEFAULT_LEAN_BIN`).

## Mathlib (real, external, untracked)

- Scratch lake project: `~/code/mini_elf_mathlib_probe/` (mathlib pinned at
  `v4.30.0`, matching the toolchain). 7.4 G olean cache lives in its `.lake/`;
  only text JSONL artifacts live in this repo.
- `LEAN_PATH` resolved once via `lake env printenv LEAN_PATH` (11 entries, 893
  chars) and cached at `.tmp/v27_lean_path.txt` for the v27 run so no further
  `lake` calls are needed during verification.
- Sanity check passed with the direct binary + cached `LEAN_PATH`:
  `import Mathlib; #check Set.Subset.refl; #check Nat.le_refl;
  #check List.length_cons` → exit 0, all three resolve.

## Git (UNCHANGED — no history operations performed or planned)

- HEAD `d392ac3` ("Add Mini-ELF v1 reranking and witness augmentation"); 2
  commits total; detached HEAD (`* (no branch, rebasing main)`).
- **A stale `.git/rebase-merge/` directory exists** (mtime 2026-05-28; empty
  `git-rebase-todo`, `done` lists one already-picked commit). This is a leftover
  from an old interrupted interactive rebase. **It is left completely untouched**
  — the v27 task forbids abort/reset/rebase and any history change. v27 does not
  commit, so this does not affect the work; it is documented here only so it is
  not mistaken for an in-progress operation.
- Working tree has the expected modified tracked files (README, docs, a few
  scripts, dataset_builder) and many untracked `data/baselines/*` eval dirs and
  `docs/V*` reports from v2–v26. No git operations will be run.

## Processes

No `lean`/`lake`/`python`/`pytest` jobs running at start (only the `claude`
session itself). Clean slate for verification/training.

## v26 artifacts inherited (the v27 starting point)

Models in `data/models/`:

| Model | Params | Best epoch | Role |
|-------|--------|-----------|------|
| `token_seq2seq_v24_broad_residual` | — | — | broad-core (DO NOT overwrite) |
| `token_seq2seq_v25_tierc_augmented` | — | — | v25 co-trained (regressed broad-core; not adopted) |
| `token_seq2seq_v26_mathlib_specialist_base` | 484,494 | 18 | v26 Mathlib specialist |
| `token_seq2seq_v26_mathlib_specialist_widened` | 488,342 | 30 | v26 recommended specialist (+Set rows) |
| `token_seq2seq_v26_mathlib_specialist_plus_core` | 495,557 | 5 | worse — not adopted |

v26 corpus (`data/processed/v26_mathlib_specialist/summary.json`): 93 theorems,
288 candidates proposed, **237 verified**, 8 Lean-rejected, 79 theorems with
training rows. By category (theorems/verified): nat 24/66, set 19/54, list 16/25,
function 5/14, logic 17/49, bool_option 12/29.

v26 splits (`data/processed/v26_mathlib_specialist_splits/`): pool 305 rows / 101
theorems; theorem_holdout train 149 / val 61 / test 67 (22 test theorems);
category_holdout_set 20 test theorems; v25 held-out benchmark 14 theorems.

### v26 headline metrics (best rerank config) — to match or beat in v27

| Model @ benchmark | pass@1 | pass@5 | pass@10 |
|-------------------|-------|-------|--------|
| v24 @ v25-heldout | 0.429 | 0.571 | 0.571 |
| v25_aug @ v25-heldout | 0.643 | 0.714 | 0.786 |
| **v26_base @ v25-heldout** | 0.857 | 0.929 | **0.929** |
| v24 @ v26-holdout | 0.273 | 0.318 | 0.318 |
| v25_aug @ v26-holdout | 0.455 | 0.591 | 0.636 |
| **v26_base @ v26-holdout** | 0.500 | 0.864 | **0.909** |
| v26_plus_core @ v25-heldout | 0.786 | 0.857 | 0.857 |
| v26_plus_core @ v26-holdout | 0.182 | 0.773 | 0.773 |

Routed system (`data/baselines/v26_routed_system/comparison.json`):
- broad-core p@1/p@5/p@10 = 0.771 / **0.938** / **0.958** (preserved vs v24 0.917/0.938)
- tier-C p@1/p@5/p@10 = 0.583 / 0.889 / 0.917

### Verifier

The current `src/mini_elf_lean/mathlib_verifier.py` is **already the corrected
verifier**: it renders a clean `example : True := True.intro` sentinel after each
candidate (absorbs forward parse-error leaks) **and** runs `verify_many(confirm=
True)` which re-batches successes until stable. v27 Part 1 hardens this into a
canonical `mathlib_batched_verifier.py` with gold/naive reference variants and a
regression test that reproduces the Lean parser-recovery skip false-positive.

## Tests

122 test files currently in `tests/`. No `v27` files exist yet (scripts, docs,
src, tests). v27 adds 6 test files (Part 11).

## Honesty invariants carried into v27

Real `import Mathlib` typecheck (no mock); no `state_after`; manual reference
candidates are corpus targets verified by Lean, never fed to a model as
predictions; no v10 leaked metrics revived; no claim of full theorem proving;
Mathlib is real and external; v24 broad-core model untouched.
