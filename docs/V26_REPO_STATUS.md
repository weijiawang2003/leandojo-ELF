# Mini-ELF v26 — Part 0: Repo / Process / Environment Status

Date: 2026-05-31. Goal of v26: build a **Mathlib specialist + router** so the
Mathlib tier improves **without** regressing the v24 broad-core benchmark (the
v25 co-training mistake). This document records the starting state; nothing in
git history was modified.

## Git state — read-only, NOT touched

* `HEAD` is **detached** at `d392ac3` ("Add Mini-ELF v1 reranking and witness
  augmentation"). Only **two** commits exist (`d392ac3`, `6852545`).
* `.git/rebase-merge/` exists — a **stale interactive rebase from 2026-05-28
  02:23** (3 days old), rebasing `refs/heads/main` onto `6852545` (the initial
  commit), stopped at step `msgnum=1` of `end=1`. `git-rebase-todo` is empty;
  `git-rebase-todo.backup` is intact.
* **No process is holding the rebase** (the only live processes are this agent
  and system daemons — see below). It is an abandoned mid-rebase checkout.
* **Per the task constraints, this was left exactly as found.** No
  `rebase --abort/--continue`, no `reset`, no `checkout`, no commit. All v26
  work happens in the **working tree** only; nothing is committed.
* Practical consequence: the entire v2–v25 body of work (models, corpora,
  evals, docs) is **uncommitted working-tree state** — this is the project's
  established norm (only the v1 milestone was ever committed). v26 continues
  that pattern: new artifacts are added to the working tree, not committed.

## Processes

`ps aux | grep -E "lean|lake|python|pytest|claude"` showed **no stale
lean/lake/pytest** processes — only this `claude` agent and two unrelated
system `python3` daemons (`networkd-dispatcher`, `unattended-upgrade`). Nothing
was killed.

## Lean / Lake toolchain

| Check | Result |
|---|---|
| `lean --version` | Lean 4.30.0 (commit d024af0, Release) |
| `lake --version` | Lake 5.0.0-src+d024af0 (Lean 4.30.0) |
| `$MINI_ELF_LEAN_COMMAND` | **unset in this shell** |
| direct toolchain binary | `/home/wangw/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean` (real ELF) |

`MINI_ELF_LEAN_COMMAND` is not exported in the interactive shell, so every v26
script that loops the verifier **explicitly sets the direct toolchain binary**
(never the `~/.elan/bin/lean` shim, which hangs under sustained load — see the
project memory `lean-verifier-use-direct-toolchain-binary`).

## Mathlib scratch project (external, NOT in the repo)

`~/code/mini_elf_mathlib_probe/` is the external lake project from v25:

* `lean-toolchain` = `leanprover/lean4:v4.30.0` (matches our toolchain).
* `lakefile.toml` requires `mathlib` at `rev = v4.30.0`.
* `import Mathlib` typechecks; `Set.Subset.refl`, `Nat.le_refl`,
  `List.length_cons` all resolve.
* The ~7.4 G olean cache lives under its `.lake/` and is **external + untracked**.
  Only text JSONL/JSON artifacts live in the ELFMath repo.

### v26 Mathlib verification strategy (combines both memory lessons)

The two project memories appear to conflict ("use the direct binary, never the
elan shim" vs "v25 verified Mathlib with `lake env lean`"). v26 resolves this
cleanly and **faster** than either:

1. Compute the Mathlib search path **once**: `lake env printenv LEAN_PATH` in
   the scratch project (cached to `/tmp` / passed explicitly).
2. Verify with the **direct toolchain binary** + that `LEAN_PATH` exported.
   This avoids the elan shim (hang risk) **and** repeated lakefile discovery
   (`lake env` per call), while still loading the real Mathlib oleans.
3. **Batch** many candidate `theorem`/`example` declarations into a single
   `import Mathlib` file. Lean reports per-declaration errors with line numbers
   and continues past failures, so one ~4.7 s warm invocation verifies hundreds
   of candidates instead of paying the import cost per candidate.

Measured: cold `import Mathlib` file = ~30 s (loading 7.4 G oleans); **warm =
~4.7 s** regardless of how many small theorems share the file. A 6-candidate
mixed pass/fail batch verified in 4.3 s with correct per-line error attribution.
This is the throughput mechanism that makes the v26 corpus + 4-model eval
finish overnight. Implemented in `src/mini_elf_lean/mathlib_verifier.py`.

## Honesty constraints carried into v26

No `state_after`; no manual oracle candidates used as model predictions; no
revived v10 leaked metrics; no faked Mathlib; no claim of full theorem proving;
the v24 broad-core model is never overwritten; a Mathlib-improving model is
adopted only if routed to the Mathlib tier (never cannibalizing broad-core).

## Baseline numbers carried forward (established before v26)

| Benchmark | Model | metric | value |
|---|---|---|---|
| broad-core (48 thm, core Lean) | v24 | abstract p@5 / p@10 | **0.917 / 0.938** |
| broad-core | v24 | bool/impl/equality/list/negation p@10 | **1.000** |
| broad-core | v25 augmented (co-trained) | raw p@10 | 0.833 (**regressed**) |
| broad-core | v25 augmented | bool p@10 | 0.667 (**regressed** from 1.0) |
| tier-C held-out (14 thm) | v24 zero-shot | raw p@10 | 0.571 |
| tier-C held-out (14 thm) | v25 augmented | raw p@10 | **0.786** |
| tier-C full (36 thm) | v24 zero-shot | core / mathlib-lemma p@10 | 0.812 / 0.350 |

These are the bars v26 must clear (improve tier-C) and protect (broad-core).
