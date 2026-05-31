# V21 repo checkpoint (Part 0)

A **safe, non-destructive** checkpoint taken before starting Mini-ELF
v21. **No `git reset`, `git rebase --abort/--continue`, `git commit`,
branch delete, or file delete was performed.** The working tree and
`.git` directory were left exactly as found; only a read-only archive
copy was created.

## Checkpoint artifact

- **Path**: `../ELFMath_v20_checkpoint_20260530_225849.tar.gz`
  (i.e. `/home/wangw/code/ELFMath_v20_checkpoint_20260530_225849.tar.gz`)
- **Size**: 100 MB
- **Entries**: 4,624 files
- **Integrity**: `gzip -t` passed (archive not corrupt).
- **Excludes**: `.venv/` (1.3 GB, trivially `pip`-regenerable),
  `__pycache__/`, `*.pyc`. Everything else is included.
- **Preserves `.git/`** in full — including the in-progress-rebase
  metadata under `.git/rebase-merge/` (16 entries archived), so the
  exact git state below can be restored from the tarball if needed.
- Harmless `socket ignored` warnings during `tar` were stale LeanDojo
  ray sockets under `.tmp/`; no real file was skipped.

## Git state at checkpoint time

**There is an interactive rebase paused mid-edit.** This predates all
v13–v20 work (the rebase metadata is timestamped 2026-05-28) and is
**left untouched** per the v21 brief's explicit instruction.

```
interactive rebase in progress; onto 6852545
Last command done (1 command done):
   pick a691b63 # Add Mini-ELF v0 prototype and results
No commands remaining.
You are currently editing a commit while rebasing branch 'main' on '6852545'.
```

- **Branch**: `main` (rebasing); current detached HEAD =
  `d392ac3be19f5e817bd625df955891c6f70855f0`
- **Rebase onto**: `685254564e8e04af9371b380683c0fb902f6a692`
- **orig-head**: `a691b636913b307f68b3b6fb0a9e4a5cfe8eed68`
- **head-name**: `refs/heads/main`
- **Rebase todo**: empty (`No commands remaining`) — the rebase is
  stopped at the final "edit" stop, awaiting a manual
  `git rebase --continue` that the user has **not** asked for.
- **Rebase dir present**: `.git/rebase-merge/` exists. **Not removed.**

All v13–v20 work (the entire untracked tree below) was produced on top
of this paused state. The state is fragile but stable; v21 continues to
layer on top of it without resolving the rebase, exactly as v13–v20 did.

## Working-tree status at checkpoint time

- **Modified (tracked)**: 10 files
  - `.gitignore`, `README.md`, `data/seeds/leandojo_seeds.jsonl`,
    `docs/NEXT_STEPS.md`, `docs/PROJECT_REPORT.md`,
    `docs/RESULTS_SUMMARY.md`, `docs/RESUME_BULLETS.md`,
    `scripts/build_dataset.py`, `scripts/evaluate_mini_elf_v1.py`,
    `src/mini_elf_lean/dataset_builder.py`
- **Untracked**: 465 entries (all the v1–v20 scripts, modules, tests,
  docs, corpora, models, and baselines — none of it committed; this is
  the normal state for this repo's working style).
- **Staged**: none beyond the above.

## Process / environment state

- No `lean`, `lake`, `python`, or `pytest` job was running at
  checkpoint time (only unrelated system `python3` daemons:
  `networkd-dispatcher`, `unattended-upgrade-shutdown`).
- `lean --version`: the `lean` toolchain is `leanprover/lean4` v4.30.0
  via elan at `~/.elan/bin/lean` (direct-binary invocation; the project
  always sets `MINI_ELF_LEAN_COMMAND=lean`, never `lake env lean`,
  which hangs on this repo's lakefile discovery).

## Test baseline carried into v21

- v20 full suite: **1,154 passed / 3 skipped** (3 skips are the
  optional LeanDojo real-smoke + two lean_dojo-installed guards).

## Restore instructions (if ever needed)

```bash
mkdir -p /tmp/elfmath_restore
tar -xzf /home/wangw/code/ELFMath_v20_checkpoint_20260530_225849.tar.gz \
    -C /tmp/elfmath_restore
# .git/rebase-merge/ is included, so the paused-rebase state restores too.
# Recreate the venv with: python -m venv .venv && pip install -e .[ar]
```

## Confirmation

- ✅ No destructive git action taken (no reset/abort/rebase/commit/
  branch-delete).
- ✅ No file deleted from the working tree.
- ✅ `.git` (incl. paused rebase) preserved both on disk and in the
  archive.
- ✅ Archive integrity verified (`gzip -t` OK; key v20 artifacts
  present).
