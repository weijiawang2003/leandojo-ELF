# V23 repo status (Part 0)

Read-only sanity at the start of Mini-ELF v23 (reranker refresh). **No
git history modified; no reset/abort/rebase/commit/delete.**

## Git / process / environment

- **Interactive rebase still paused** (`.git/rebase-merge/` present,
  head-name `refs/heads/main`, onto `6852545`) — **left untouched**, as
  for v13–v22. HEAD `d392ac3` (unchanged); no commit made.
- Working tree: tracked-modified docs/scripts + untracked generated
  `data/` and v1–v22 artefacts. Normal working state.
- No `lean`/`lake`/`python`/`pytest`/training job running at v23 start
  (v22 training + eval all completed).
- `lean --version` → **Lean 4.30.0** (commit `d024af0`). For any verifier
  loop use the **pinned toolchain binary**
  `~/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean`, not the elan
  `lean` shim (it intermittently hangs under sustained load — see
  `V22_REPO_STATUS.md`). **v23 is offline (no Lean needed):** the v22
  eval `predictions.jsonl` files already record each candidate's
  verification, so re-ranking + pass@k is a pure reshuffle.

## v22 is complete — do not rerun it

The scheduled 02:10 fallback heartbeat (from the v22 wait) is recognised
as a no-op: v22 is finished (single `v22_general_plus_exists` beats v21
routing; metrics on disk). v23 changes **ranking only**, never the
generator, and does not retcon v22 metrics.

## Starting point measured (v22 plus_exists candidate pool, 48 theorems)

Per rerank config (already on disk):

| config | p@1 | p@5 | p@10 | MRR | negation@5 |
|---|---:|---:|---:|---:|---:|
| **raw** | **0.792** | **0.833** | 0.833 | **0.804** | 0.800 |
| rule | 0.771 | 0.833 | 0.833 | 0.793 | 0.800 |
| learned (v15) | 0.646 | 0.833 | 0.833 | 0.725 | 0.800 |
| policy (v15) | 0.688 | 0.833 | 0.833 | 0.745 | 0.800 |
| abstract (v22 headline) | 0.729 | 0.812 | 0.833 | 0.774 | **0.600** |
| policy_abstract | 0.708 | 0.812 | 0.833 | 0.764 | 0.600 |

**Key facts that scope v23:**
- **`raw` beam order is already the best config** (p@1 0.792, p@5 0.833).
  The v22 generator's beam is well-ordered.
- The **`abstract` reranker is the only harmful one** — it demotes one
  verified negation candidate (negation 0.800 → 0.600). The v22 headline
  used `abstract`, so that is the number v23 must beat; but the bar to not
  regress is `raw`.
- The **v15 learned reranker tanks pass@1** (0.646) — miscalibrated for
  the v22 generator's beam distribution (trained on v11–v14 family data).
- **pass@5 == pass@10 == 0.833 under raw** ⇒ every solvable theorem
  already has a verified candidate in the **top 5**; ranking headroom is
  **pass@1 only**.

**Ranking-bound vs generator-bound (from raw predictions):**
- **8 generator-bound** (no verified candidate in top-10; reranking cannot
  help): and_assoc_one, or_inr, or_elim_to_common, neg_or_left,
  exists_intro_eq, nat_zero_add, nat_succ_inj, list_append_nil.
- **2 rank-bound** (verified candidate present but not at rank 0):
  `v18_neg_not_intro` (verified `intro hp; exact absurd hp h` at rank 3) and
  `v18_list_length_cons` (verified `exact rfl` at rank 2).

So the ranking ceiling is **pass@1 0.792 → 0.833**; pass@5/10 are
generator-capped. v23 tests whether a refreshed reranker reaches that
ceiling without demoting the 38 raw-correct theorems, and confirms the
residual gap is generator-bound.

## Confirmation

- ✅ git history untouched; paused rebase preserved; no file deleted.
- ✅ no commit; v22 metrics not retconned.
