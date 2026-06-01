# V34 — Part 1: Git Recovery Plan (stale rebase metadata)

_Written **before** any destructive action. A full backup was taken first
(Part 0): `~/code/ELFMath_git_recovery_backup_20260601_035811/` containing
`git_dir.tar.gz` (12 MB, the entire `.git`), `uncommitted_diff.patch`,
`status_short.txt`, `log.txt`, `untracked_files.txt` (5161 entries), and a
forensic copy of `.git/rebase-merge` (`rebase-merge_snapshot/`)._

## 1. Observed state

```
On branch v27-mathlib-specialist
You are currently editing a commit while rebasing branch 'main' on '6852545'.
Last command done (1 command done):  pick a691b63 # Add Mini-ELF v0 prototype and results
No commands remaining.
```

Branch / object topology:

| Ref | SHA | Meaning |
|---|---|---|
| `HEAD` → `v27-mathlib-specialist` | `b4fcd6c` | current work branch (all v25–v33 work lives here, uncommitted) |
| `main` | `a691b63` | the rebase's `orig-head`/`stopped-sha` — still the **old** initial commit |
| rebase `onto` | `6852545` | "Initial commit: mini-elf-lean trace collector" |

`.git/rebase-merge/` (mtime **2026-05-28**, while `.git` itself is current):

| File | Value | Reading |
|---|---|---|
| `head-name` | `refs/heads/main` | the branch that *was* being rebased |
| `onto` | `6852545…` | target base |
| `msgnum` / `end` | `1` / `1` | single-command plan |
| `done` | `pick a691b63 …` | that one command already ran |
| `git-rebase-todo` | **empty (0 bytes)** | **no commands remaining** |
| `git-rebase-todo.backup` | 1 `pick` + help text | original 1-command plan |
| `stopped-sha` / `orig-head` | `a691b63` | where it stopped (= current `main`) |
| `message` | lists `# Conflicts:` (40+ paths) | it stopped on a conflict on 2026-05-28 |

## 2. What happened (reconstructed from `git reflog`)

```
a691b63 HEAD@{4}: commit (initial): Add Mini-ELF v0 prototype and results
6852545 HEAD@{3}: pull --rebase origin main (start): checkout 6852545…
d392ac3 HEAD@{2}: commit: Add Mini-ELF v1 reranking and witness augmentation
b4fcd6c HEAD@{0}: commit: Mini-ELF v27: scaled Mathlib specialist + hardened verifier
```

A `git pull --rebase origin main` on 2026-05-28 began replaying `main`'s commit
`a691b63` onto the freshly fetched `6852545`. It hit merge conflicts (the
`# Conflicts:` list in `message`) and **stopped** in the "editing a commit"
state. Rather than finishing the rebase, subsequent work was committed onto
`6852545` (`d392ac3`, then `b4fcd6c`) under the branch `v27-mathlib-specialist`,
which is now `HEAD`. The `.git/rebase-merge/` directory was **orphaned** and has
sat stale ever since. `main` was never advanced past `a691b63`.

## 3. Determinations (the Part 1 questions)

- **Active conflict right now?** **No.** `git diff --diff-filter=U` = 0 unmerged
  paths; `git diff --check` finds no conflict markers. The conflicts named in
  `message` are from 2026-05-28 and are no longer present in the index.
- **Remaining todo commands?** **No.** `git-rebase-todo` is empty (0 bytes);
  status says "No commands remaining".
- **Completed or stale metadata?** **Stale / orphaned.** The rebase never
  completed (`main` is still at the pre-rebase `a691b63`), but work moved on to a
  different branch, leaving the metadata abandoned.
- **Does git say "rebase in progress"?** **Yes** — "currently editing a commit
  while rebasing branch 'main' on '6852545'". This is the stale indicator we are
  clearing.
- **Why is the working tree dirty?** **Project files only.** 5 modified tracked
  docs (the v33/v34 doc edits) + 5161 untracked v25–v33 artifacts. No conflict
  markers, 0 unmerged entries.

## 4. Recovery action — `git rebase --quit` (NOT abort, NOT reset)

```bash
git rebase --quit
```

**Why `--quit`:** it removes `.git/rebase-merge/` and clears the
"rebase-in-progress" state while leaving `HEAD`, the current branch, the index,
and the working tree **exactly as they are** (on `v27-mathlib-specialist` @
`b4fcd6c`). No file or commit moves.

**Why NOT `--abort`:** abort restores to `orig-head` (`a691b63`) and re-checks
out branch `main` — it would **move `HEAD` and the working tree off `b4fcd6c`**,
risking the uncommitted v25–v33 work. Explicitly disallowed by the V34 brief.

**Why NOT `reset`:** a `reset` would rewrite branch state; unnecessary and risky
when only orphaned metadata needs removing.

**No data loss:** `a691b63` (the stopped commit) is still reachable from `main`,
so quitting discards nothing — it only deletes the stale metadata directory.

> **EXECUTED 2026-06-01.** `git rebase --quit` returned exit 0. Post-conditions
> verified: no rebase banner, `.git/rebase-merge/` removed, `find .git … grep
> rebase` empty, `HEAD` still `b4fcd6c`, `main` still `a691b63`, still on branch
> `v27-mathlib-specialist`, all 440 modified/untracked project entries intact.

## 5. Expected post-conditions (verified in Part 2)

- `git status` → clean "On branch v27-mathlib-specialist" header, **no** rebase
  banner; still lists the same modified + untracked project files.
- `find .git -maxdepth 2 -type d | grep rebase` → empty.
- `HEAD` unchanged = `b4fcd6c`; `main` unchanged = `a691b63`.

## 6. Fallback

If `git rebase --quit` fails or behaves unexpectedly: **stop and report.** Do
**not** force-`rm` `.git/rebase-merge` unless the backup is confirmed restorable
and the failure is understood. The backup tarball can fully reconstruct `.git`.
