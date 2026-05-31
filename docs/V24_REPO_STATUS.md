# V24 repo status (Part 0)

Read-only sanity at the start of Mini-ELF v24 (residual shape
augmentation). **No git history modified; no reset/abort/rebase/commit/
delete.**

## Git / process / environment

- **Interactive rebase still paused** (`.git/rebase-merge/` present,
  head-name `refs/heads/main`, onto `6852545`) — **left untouched**, as
  for v13–v23. HEAD `d392ac3` (unchanged); no commit made this session.
- Working tree: tracked-modified docs/scripts + untracked generated
  `data/` and v1–v23 artefacts. Normal working state.
- No `lean`/`lake`/`python`/`pytest`/training job running at v24 start
  (v23 work all completed).
- `lean --version` → **Lean 4.30.0** (commit `d024af0`). All corpus
  verification used the **pinned toolchain binary**
  `~/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean`, never the
  elan `lean` shim (it intermittently hangs under sustained sequential
  load — see `V22_REPO_STATUS.md`).

## Why v24 (carried from v23)

v23 proved the broad-core residual is **generator-bound**, not
ranking-bound: 8 v18 theorems have no verified candidate in the v22
plus_exists top-10, so no reranker can reach them. v24 therefore does
**not tune rerankers**; it adds targeted, lean-verified core-Lean shape
corpora for those 8 gaps and retrains the broad generator. The 8
generator-bound theorems carried in from the v23 audit:
`and_assoc_one` (conjunction), `or_inr` / `or_elim_to_common`
(disjunction), `neg_or_left` (negation), `exists_intro_eq` (exists),
`nat_zero_add` / `nat_succ_inj` (nat_succ), `list_append_nil` (list).

## Outcome (recorded after the run)

5 of the 8 closed; pass@10 0.833 → **0.938** (no_verify 8 → 3); zero
category regressions; v18/v22/v23 metrics on disk unchanged. Full detail:
[`V24_BROAD_GENERATOR_REPORT.md`](V24_BROAD_GENERATOR_REPORT.md).

## Confirmation

- ✅ git history untouched; paused rebase preserved; no file deleted.
- ✅ no commit; v18/v22/v23 metrics not retconned.
- ✅ core Lean only (no Mathlib); no state_after; no manual oracle.
