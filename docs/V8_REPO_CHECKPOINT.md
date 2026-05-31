# Mini-ELF v8 — repo checkpoint (Part 0)

Recorded before any v8 code change, so a complete rollback to the post-v7 state
is always possible. **No git operation was run** on the repo (no
`rebase --abort`, no `reset`, no `commit`, no `clean`). The interactive rebase
that has been in flight since v1 is left exactly as it was.

## Pre-v8 git state

| Field | Value |
|---|---|
| Working directory | `/home/wangw/code/ELFMath` |
| Interactive rebase active | **yes** — `.git/rebase-merge/` present |
| Rebase message | "currently editing a commit while rebasing branch 'main' on '6852545'" |
| Last rebase command done | `pick a691b63 # Add Mini-ELF v0 prototype and results` |
| Remaining rebase commands | 0 (todo list empty) |
| HEAD | `d392ac3` (detached) — "Add Mini-ELF v1 reranking and witness augmentation" |
| `main` / `origin/main` | `a691b63` — "Add Mini-ELF v0 prototype and results" |
| Onto target | `6852545` — "Initial commit: mini-elf-lean trace collector" |
| Modified tracked files | 10 |
| Staged files | 0 |
| Untracked files | **381** (all v2–v7 data dirs, scripts, src modules, tests, docs) |

The repo has been in this rebase-mid-edit state for every milestone since v1.
All v1–v7 work is uncommitted (modified tracked + untracked). v8 will continue
to operate the same way — the filesystem backup below is the safety net.

## Backup artifacts (created 2026-05-29 15:48 local)

| Path | Size | Contents |
|---|---|---|
| `~/code/ELFMath_backup_20260529_154806/` | **1.4 GB** | Full working-tree mirror (excludes `.git`) |
| `~/code/ELFMath_checkpoint_20260529_154806/git_dir.tar.gz` | 5.2 MB | Complete `.git/` including live `rebase-merge/` state |
| `~/code/ELFMath_checkpoint_20260529_154806/untracked_files.tar.gz` | 6.6 MB | All 381 untracked files |
| `~/code/ELFMath_checkpoint_20260529_154806/uncommitted_diff.patch` | 80 KB | Modified tracked files vs HEAD |
| `~/code/ELFMath_checkpoint_20260529_154806/staged_diff.patch` | 0 B | (nothing staged) |
| `~/code/ELFMath_checkpoint_20260529_154806/rebase-merge_copy/` | — | Snapshot of in-flight rebase state |
| `~/code/ELFMath_checkpoint_20260529_154806/MANIFEST.txt` | — | Timestamps, sha256s, sizes |
| `~/code/ELFMath_checkpoint_20260529_154806/{git_status,git_log,untracked_files,HEAD}.txt` | — | Plain-text state dumps |

### Verification

- `sha256(git_dir.tar.gz)         = 5a7ed2d4ace94fb9521bd636b5a5c40a4433838ab5aea77076daab37cb661cf9`
- `sha256(untracked_files.tar.gz) = 20ba4bfc9629c56c48f34be6379daadb963d2f33022f7f969140e19abc21d7a2`

Round-trip spot-check (3 untracked paths): each appears in both the rsync
mirror and the tar archive.

### Restore recipe

To recover the exact post-v7 state from these artifacts on a fresh clone:

```bash
tar -xzf ELFMath_checkpoint_20260529_154806/git_dir.tar.gz   # restores .git/ incl. rebase
rsync -a ELFMath_backup_20260529_154806/ ELFMath/            # restores working tree
# (untracked_files.tar.gz is redundant with the rsync mirror but keyed independently)
```

## Three rollback options (presented but not executed)

These were proposed at checkpoint time and deliberately deferred:

- **A.** Finish the rebase and commit v1–v7 (requires `git add -A; commit;
  rebase --continue` and accepts main being rewritten / diverging from
  `origin/main`).
- **B.** Save the current tree to a new branch label, leave rebase alone.
- **C.** Abort rebase only after the backup, then re-apply the saved patch.

v8 proceeds in the same uncommitted-working-tree mode as v1–v7, with the
1.4 GB rsync + the `.git` tar acting as the rollback line.
