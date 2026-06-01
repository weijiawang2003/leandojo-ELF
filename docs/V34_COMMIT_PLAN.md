# V34 — Part 8: Commit Plan

_**Do not commit until explicitly asked.** This is the plan only. Current state:
branch `v27-mathlib-specialist` @ `b4fcd6c`; `main` @ `a691b63` (a divergent old
initial commit — see the branch note below); 1646 files already tracked; ~5161
untracked entries from the v8–v34 work; 5 modified tracked docs._

## Size context (why exclusions matter)

| Class | Size | Files | Disposition |
|---|---:|---:|---|
| code (`src` / `scripts` / `tests`) | ~10 MB | — | **commit** |
| `docs/*.md` | 1.6 MB | — | **commit** |
| `data/seeds/` | 1.3 MB | — | **commit** (corpus provenance) |
| `data/manual/` | 3.1 MB | — | **commit** (verified candidate rows) |
| `data/baselines/**/*.json` (metrics/summaries) | 28.7 MB | 2162 | **commit** (recorded headline numbers) |
| `data/baselines/**/routing_log.jsonl` | 0.2 MB | 7 | **commit** (small, useful) |
| `data/baselines/**/predictions.jsonl` | **65.5 MB** | 1935 | **exclude** (regenerable eval byproduct) |
| `data/**/*.log`, `*_stdout.log` | 0.1 MB | 29 | **exclude** (build/train stdout) |
| `data/processed/` (tokenized corpora + splits) | **98 MB** | — | **exclude** (regenerable from seeds) |
| `data/models/**/*.pt` (weights) | **180.5 MB** | 106 | **LFS or selective** — see decision below |
| `.venv`, `.tmp`, `.cache`, `data/traces/*.jsonl` | 1.3 GB | — | already **gitignored** |

## Files to COMMIT

1. **All source**: `src/mini_elf_lean/**` (incl. `mathlib_batched_verifier.py`,
   `v31_identifier_normalization.py`, `v{26..33}_mathlib_router.py`), `scripts/**`,
   `tests/**`.
2. **All docs**: `docs/**.md` — including the v34 set
   (`MINI_ELF_MATHLIB_FINAL_REPORT.md`, `V34_GIT_RECOVERY_PLAN.md`,
   `V34_ARTIFACT_INVENTORY.md`, `REPRODUCIBILITY.md`, `V34_CONSISTENCY_AUDIT.md`,
   `V34_COMMIT_PLAN.md`) and the modified README / PROJECT_REPORT / RESULTS_SUMMARY
   / NEXT_STEPS / RESUME_BULLETS / the two v10 leakage-caveat edits.
3. **Corpus provenance**: `data/seeds/**`, `data/manual/**`.
4. **Recorded metrics**: `data/baselines/**/*.json` + `routing_log.jsonl`
   (the numbers behind the final report) + `data/baselines/v34_inventory/`,
   `data/baselines/v34_consistency/`.
5. **Config**: `pyproject.toml`, `.gitignore`, `.github/`, `.env.example`,
   `examples/*.lean` (small).

## Files to EXCLUDE (add to `.gitignore`)

Append:

```gitignore
# v34 packaging — large / regenerable data artifacts (kept out of git history)
data/baselines/**/predictions.jsonl     # raw per-candidate eval output; metrics.json is the summary
data/processed/                          # tokenized corpora + splits; regenerable from data/seeds via build_*.py
data/**/*.log                            # build / training stdout

# Local Claude Code session state (not project source)
.claude/projects/
.claude/scheduled_tasks.lock
```

(`.venv/`, `.tmp/`, `.cache/`, `data/traces/*.jsonl`, `verification_cache.json`,
`.claude/settings.local.json` are **already** ignored.)

## Large artifacts — model weights decision (180 MB)

The bulk of repo size is `data/models/**/*.pt` (180 MB, 106 files; biggest single
4 MB). Pick one:

- **A. Git LFS (recommended).** `git lfs track "data/models/**/*.pt"` — keeps
  full one-command reproducibility (all weights available) without bloating git
  history. 180 MB is comfortable for LFS.
- **B. Selective commit (lightweight fallback).** Commit only the essential
  weights and gitignore the rest:
  - `token_seq2seq_v24_broad_residual` (2.1 MB — protected broad-core),
  - `token_seq2seq_v33_general_residual` (~2 MB — final specialist),
  - `token_seq2seq_v31_canonical_general` (canonicalization baseline).
  Document that intermediate/ablation models regenerate via `train_v{N}_*.py`.
- **C. Exclude all** (`data/models/` ignored), document full regeneration. Loses
  one-command repro of the routed eval; not recommended.

**Default if unspecified: A (LFS).** It best matches the reproducibility doc's
"run the eval" commands.

## NEVER committed (structurally outside the repo)

- `~/code/mini_elf_mathlib_probe` — the 7.0 GB external Mathlib v4.30.0 Lake
  project (its own repo; cloned/built separately per `REPRODUCIBILITY.md`).
- `~/code/ELFMath_git_recovery_backup_20260601_035811/` — the v34 git backup
  (outside the repo tree; retain locally until the commit is confirmed good).

## Branch note (needs a human decision before pushing)

`main` (`a691b63`) is the *original* initial commit and has **diverged** from the
work branch `v27-mathlib-specialist` (`b4fcd6c`), which carries everything. The
v34 git recovery only removed the orphaned rebase metadata; it did **not**
reconcile the branches. Before any push, decide whether to (a) fast-forward/merge
`main` to the work branch, (b) rename `v27-mathlib-specialist` → `main`, or
(c) open a PR from the work branch. **This plan does not rewrite history**; pick
the reconciliation explicitly.

## Suggested commit (when approved)

```bash
# 1. add the .gitignore exclusions (above), then:
git add -A
# 2. (if Option A) configure LFS for weights first:
#    git lfs install && git lfs track "data/models/**/*.pt" && git add .gitattributes
git commit -m "Finalize Mini-ELF Mathlib specialist phase

Specialist + router over a broad-core model with theorem-level (single-tactic)
verification by a trusted Mathlib verifier. v24->v33 arc: probe -> specialist +
router -> trusted verifier -> density law -> targeted repair -> identifier
canonicalization -> adversarial robustness -> single-tactic saturation.
Routed broad-core 0.9375/0.9583 (bit-for-bit, v24 untouched); routed tier-C
0.992 over 244 held-outs; all six single-tactic benches pass@10 1.00.
Theorem-level verification only; no state_after; no full-proving claim;
no LeanDojo next-state (0 multi-step residuals). Tests 1511 passed, 3 skipped.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**Reminder: do not run the above until the user explicitly asks.**
