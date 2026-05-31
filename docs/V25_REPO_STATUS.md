# V25 repo status (Part 0)

Read-only sanity at the start of Mini-ELF v25 (first Mathlib tier-C
probe). **No git history modified; no reset/abort/rebase/commit/delete.**

## Git / process / environment

- **Interactive rebase still paused** (`.git/rebase-merge/` present) —
  **left untouched**, exactly as for v13–v24. HEAD `d392ac3`
  (unchanged); **no commit made this session**.
- Working tree: tracked-modified docs/scripts + untracked generated
  `data/` and v1–v24 artefacts. Normal working state.
- No `lean` / `lake` / `python` / `pytest` / training job running at
  v25 start (only the `claude` process itself). v24 work all completed.
- `lean --version` → **Lean 4.30.0** (commit `d024af0`).
- `lake --version` → **Lake 5.0.0-src+d024af0** (Lean 4.30.0).
- `$MINI_ELF_LEAN_COMMAND` is **empty in this login shell**. All corpus
  verification therefore explicitly uses the **pinned toolchain binary**
  `~/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean`, never the
  elan `lean` shim (it intermittently hangs under sustained sequential
  load — see `V22_REPO_STATUS.md`).
- elan toolchains installed: `leanprover--lean4---v4.20.0`,
  `leanprover--lean4---v4.30.0`. **No Mathlib build cache present yet.**
- Disk free on `~`: **936 G** (ample for a Mathlib olean cache, ~5 GB).
- Machine: **16 cores, 15 GiB RAM, 13 GiB free** at start.

## Mathlib availability at start

- The repo root has **no** `lakefile`/`lake-manifest`/`lean-toolchain`.
- The only in-repo Lean project, `examples/leandojo_mini_repo/`, is a
  **deliberately minimal standalone lib with zero package dependencies**
  (lake-manifest packages list is empty) — it does **not** depend on
  Mathlib. So no Mathlib is available from the existing repo.
- Network probe (Part 1 preflight): `github.com`, the `mathlib4` repo,
  and `raw.githubusercontent.com` all return HTTP 200 — Mathlib install
  over the network is **viable** (subject to download/build time).
- Mathlib publishes a **`v4.30.0` tag pinned to `leanprover/lean4:v4.30.0`**
  (commit `c5ea00351c28e24afc9f0f84379aa41082b1188f`), which matches our
  installed toolchain exactly. This is the version v25 targets so that
  `lake exe cache get` can fetch prebuilt oleans rather than building
  Mathlib from source.

## Why v25 (carried from v24)

v24 closed 5/8 generator-bound broad-core failures with a verified
residual shape corpus: broad-core best pass@5 0.917, pass@10 0.938
(no_verify 8 → 3), zero category regressions, forall/impl/bool/equality
held at 1.000. That **cleared the broad-core generator-bound gate** the
earlier briefs set as the precondition for touching Mathlib. v25 is
therefore the **first serious Mathlib tier-C probe**: install/locate
Mathlib, build a tiny verified Mathlib-style benchmark, and measure
whether the v24 broad-core generator transfers beyond synthetic/core
Lean — or fall back to a documented core-Lean tier-C surrogate with an
honest environment report if Mathlib cannot be installed/imported.

## Confirmation

- ✅ git history untouched; paused rebase preserved; no file deleted.
- ✅ no commit; v18/v22/v23/v24 metrics not retconned.
- ✅ pinned toolchain binary used for verification; no manual oracle as
  predictions; no state_after; no v10 leakage; no full-theorem-proving
  claim.
- ⏳ Mathlib install result recorded in
  [`V25_MATHLIB_ENV_REPORT.md`](V25_MATHLIB_ENV_REPORT.md) (Part 1).
