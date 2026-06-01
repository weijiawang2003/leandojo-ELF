# V34 — Part 7: Final Test & Consistency Audit

_Test run: `.venv/bin/python -m pytest -q` → **1511 passed, 3 skipped** (3 skips
are the LeanDojo `run_tac` / smoke tests, which require an unblocked LeanDojo
backend). Consistency checks: `scripts/v34_consistency_audit.py` →
`data/baselines/v34_consistency/report.json`, **ALL OK: True**._

## Result summary

| # | Check | Verdict | Evidence |
|---|---|---|---|
| — | Full test suite | ✅ | **1511 passed, 3 skipped**, 1 warning |
| 1 | No `state_after` in v25–v33 data | ✅ | 0 offenders across **42023 rows / 129 files** (processed + seeds + manual) |
| 2 | Every "full theorem proving" mention is a disclaimer | ✅ | **74 mentions, 0 violations** |
| 3 | v10 leakage guarded, not revived | ✅ | guard test `test_v10_no_leakage.py` present + passing; every doc citing `combined_v10` frames the leakage |
| 4 | Naive verifier never the headline verifier | ✅ | 6 headline eval scripts all use `TrustedMathlibVerifier`, none use `NaiveBatch` |
| 5 | Headline metrics agree across docs | ✅ | broad-core `0.9375/0.9583`, tier-C `0.992`, `n=244` all present in README, RESULTS_SUMMARY, NEXT_STEPS, FINAL_REPORT |

## Detail

### 1 — No `state_after`
Scanned every `*.jsonl` under `data/processed`, `data/seeds`, `data/manual`
whose path matches `v25`–`v33` (129 files, 42023 rows). Checked both the JSON
key `state_after` and the raw substring `"state_after"`. **0 hits.** Consistent
with the build-time guard `assert "state_after" not in r` in each dataset
builder. Verification remains theorem-level / single-tactic.

### 2 — "Full theorem proving" is always disclaimed
74 doc lines match `full[\s-]?(theorem[\s-]?)?prov`. After normalising markdown
emphasis (`**no**` → `no`) and checking the prior line for cross-line
disclaimers, **all 74 are negations** ("**no** full-theorem-proving", "**not**
full theorem proving", "does **not** indicate full theorem proving", "imply full
theorem proving** — the test set is a small templated…", etc.). 0 lines assert
the system performs full theorem proving.

> _Audit-tool note._ The first pass reported 8 false "violations" — all genuine
> disclaimers whose negation was markdown-bolded or on the preceding line. The
> heuristic was tightened (strip `*_`>\`` `, inspect the previous non-empty line)
> rather than the docs changed; re-run → 0 violations.

### 3 — v10 leakage not revived
The `combined_v10` checkpoint was trained on the v10 *interpolation* split and so
saw 36/40 holdout cells — its strong numbers are in-distribution memorisation,
not generalisation. This is pinned by `tests/test_v10_no_leakage.py` (passing)
and the corrected clean signal lives at `data/baselines/v10_eval_clean/per_op/`
(`combined_v10_per_op`, LOFO). The audit flagged two v10-era docs
(`V10_SCALING_ANALYSIS.md`, `V10_FAILURE_EXAMPLES.md`) that cited `combined_v10`
**without** a local leakage caveat; a leakage-caveat banner was **added to each**
(no numbers changed) cross-linking the corrected analysis. After that, every doc
mentioning `combined_v10` frames the leakage. **No leaked metric is presented as
a headline anywhere.**

### 4 — Naive verifier is never the headline
The 6 v3x headline eval scripts (`evaluate_v3{1,2,3}_routed_system.py`,
`evaluate_v3{1,2,3}_mathlib_specialists.py` — matched by glob) all construct
`TrustedMathlibVerifier` and **none** reference `NaiveBatchMathlibVerifier`.
`NaiveBatch` appears only in `mathlib_batched_verifier.py` (its definition) and in
test files (where it is exercised as the *unsafe* baseline, never for reported
numbers). Per-corpus gold re-checks use `GoldMathlibVerifier` (batch_size=1).

### 5 — Metric agreement across top-level docs
`README.md`, `docs/RESULTS_SUMMARY.md`, `docs/NEXT_STEPS.md`, and
`docs/MINI_ELF_MATHLIB_FINAL_REPORT.md` each contain the broad-core
`0.9375 / 0.9583`, the routed tier-C `0.992`, and `n=244`. No conflicting
headline figure was found.

## Re-run

```bash
.venv/bin/python -m pytest -q                  # 1511 passed, 3 skipped
python3 scripts/v34_consistency_audit.py       # ALL OK: True (exit 0)
```
