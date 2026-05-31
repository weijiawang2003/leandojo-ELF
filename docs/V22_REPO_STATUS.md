# V22 repo status (Part 0)

Read-only sanity check at the start of Mini-ELF v22. **No git history
was modified; no reset/abort/rebase/commit/delete was performed.**

## Git state (unchanged from the v21 checkpoint)

- **Interactive rebase still paused** (`.git/rebase-merge/` present) —
  the same `rebase -i` of `main` onto `6852545` stopped mid-edit since
  2026-05-28. **Left untouched**, exactly as for v13–v21.
- **HEAD**: `d392ac3be19f5e817bd625df955891c6f70855f0` (unchanged).
- **Working tree**: 10 tracked-modified files, 0 staged, ~2,533
  untracked files (the generated `data/` + v1–v21 source/docs/tests;
  recursive count). Nothing committed — the repo's normal working
  state.

## Process / environment

- No `lean` / `lake` / `python` / `pytest` job running at v22 start.
- `lean --version`: **Lean 4.30.0** (x86_64-unknown-linux-gnu, commit
  `d024af0`, Release) via elan at `~/.elan/bin/lean`. Healthy.
- Invocation contract (carried): always `MINI_ELF_LEAN_COMMAND=lean`
  + `PATH=$HOME/.elan/bin:$PATH`; never `lake env lean` (hangs on this
  repo's lakefile discovery).

## Checkpoint

- The v20/v21 checkpoint tarball
  `../ELFMath_v20_checkpoint_20260530_225849.tar.gz` (100 MB,
  preserves `.git` incl. the paused rebase) is present and was the
  pre-v21 safety copy. v22 continues to layer on the same working
  tree; no new destructive action.

## Carried baseline

- v21 full suite: **1,188 passed / 3 skipped**.
- Best system to beat: **v21 routed**, v18-broad-core mean pass@5
  **0.792** (forall/implication/bool all 1.000; exists 0.250).

## Confirmation

- ✅ git history untouched (no reset/abort/rebase/continue/commit).
- ✅ paused rebase preserved.
- ✅ no file deleted.

## Session addendum (2026-05-31, v22 build/eval session)

Re-ran the Part-0 sanity at the start of the build/eval session:

- `git status --short`: same 10 tracked-modified files + untracked
  generated `data/`. **Interactive rebase still present** under
  `.git/rebase-merge/` (head-name `refs/heads/main`, onto `6852545`,
  msgnum 1/1) — **left untouched**, no reset/abort/continue/commit/delete.
- No `lean`/`lake`/`python`/`pytest` job running at session start.
- `lean --version` → **Lean 4.30.0** (commit `d024af0`). Healthy.

**Verifier-invocation fix (important).** The prior session's exists-corpus
generation stalled twice: after ~33 fast verifications every subsequent
`lean` call hung at ~0 % CPU and timed out, while memory/CPU/load were all
idle. Root cause: `~/.elan/bin/lean` is the **elan shim** and
`default_toolchain = "stable"` in `~/.elan/settings.toml`, so each
invocation re-resolves "stable" and intermittently blocks under sustained
sequential load. **Fix:** point `MINI_ELF_LEAN_COMMAND` at the pinned
toolchain binary
`/home/wangw/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean`
(the real ELF binary; bypasses elan resolution). Stress test: 50
sequential verifications → max 0.25 s, mean 0.19 s, 0 hangs. With this the
exists corpus regenerated cleanly (471/471 verified). The environmental
issue is **not** a Lean-semantics or resource problem; no shape failed
once the shim was bypassed. (`lake env lean` is still never used — it
hangs on lakefile discovery.)
