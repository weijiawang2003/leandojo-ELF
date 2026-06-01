# V28 Part 3 — Verification & Gold Sampling

_Script: `scripts/verify_v28_mathlib_expanded_corpus.py`.
Output: `data/baselines/v28_corpus_integrity/report.json`._

This is the integrity gate over the v28 corpus. Every training positive is
re-verified with the **trusted** verifier, and a category-stratified random sample is
cross-checked against the **gold** one-declaration-per-file verifier
(`GoldMathlibVerifier`, `batch_size=1` — complete isolation, the ground-truth
reference). The trusted verifier is **sound iff gold accepts everything trusted
accepted** (zero false positives).

## Re-verification (trusted)

| check | result |
|-------|--------|
| verified rows re-checked | 350 |
| still pass under `import Mathlib` | **350 / 350** |
| verified regressions (now fail) | **0** |
| failed rows that silently became valid | **0** |

No stale positives: every row used for training still typechecks.

## Gold sampling (one declaration per file)

| | value |
|---|---|
| sample size | **24** (≥ 20 required) |
| categories covered | all 7 — set 7, order 5, nat 4, function 3, logic 3, finset 1, list 1 |
| gold ↔ trusted mismatches | **0** |
| **gold false positives** (trusted said pass, gold said fail) | **0** |
| sampling | deterministic (`random.Random(seed=0)`), one guaranteed pick per category then random fill |

**`integrity_ok = True`.** The trusted verifier is sound and complete on the v28
corpus — there are zero trusted-vs-gold mismatches on the sampled candidates, meeting
the v28 target of *zero trusted-verifier/gold mismatches on sampled candidates*.

## Verifier provenance

* **TrustedMathlibVerifier** — sentinel render + `confirm=True` success re-batching +
  lexer-poison rescue. `confirm=False` raises (`UnsafeVerifierError`); the unsound
  path is unreachable by accident. Used for all headline metrics.
* **GoldMathlibVerifier** — `batch_size=1`, one Lean process per candidate, no
  cross-candidate interaction possible. Ground-truth reference for the audit only.
* **NaiveBatchMathlibVerifier** — UNSAFE, used **only** in the soundness regression
  test; never for any reported metric.

## Honesty

Real `import Mathlib` typecheck (no mock). No `state_after`. Manual targets are
Lean-verified corpus targets, never model predictions. Mathlib real & external.
