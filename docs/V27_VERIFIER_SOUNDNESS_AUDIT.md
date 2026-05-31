# Mini-ELF v27 — Verifier Soundness Audit (Part 1)

Goal: prove that every verifier path used for v25/v26/v27 Mathlib evaluation is
**sound** (never reports a candidate verified that a one-declaration-per-file gold
check would reject), and that the corrected iterative success-confirmation method
catches the Lean parser/lexer recovery skip that an old *naive* batched verifier
would miss.

Artifacts: `src/mini_elf_lean/mathlib_batched_verifier.py` (canonical module),
`scripts/audit_v27_verifier_soundness.py`, report
`data/baselines/v27_verifier_soundness/report.json`,
tests `tests/test_v27_verifier_soundness.py`.

## The three verifiers compared

| Verifier | How it batches | Status |
|----------|----------------|--------|
| **Gold** (`GoldMathlibVerifier`) | one `example` per Lean file (`batch_size=1`) | ground truth — total isolation, no cross-candidate effects |
| **Trusted** (`TrustedMathlibVerifier`) | many per file + sentinel + `confirm` re-batch + rescue pass | the v27 headline verifier |
| **Naive** (`NaiveBatchMathlibVerifier`) | many per file, **no sentinel, no confirm** | **UNSAFE** — audit/regression only, never used for metrics |

Trusted builds on the v26 `BatchMathlibVerifier` (unchanged) and forces
`confirm=True` (`confirm=False` raises `UnsafeVerifierError`), so the unsound path
is unreachable by accident.

## The parser / lexer recovery skip

A candidate tactic that opens a construct the lexer cannot close inside its own
lines — most reliably an **unterminated block comment** `exact h /- …` (or an
unterminated string) — makes Lean consume the rest of the file and emit a single
diagnostic (`unterminated comment`) at the **end** of the file. Reproduced with
core Lean 4.30.0:

```
example (p : Prop) (h : p) : p := by
  exact h /- not closed          -- candidate A (a parse/lex error: should FAIL)
example (n : Nat) : n + 1 = n := by
  rfl                            -- candidate B (false equality: should FAIL)
```
→ only diagnostic: `…:5:0: error: unterminated comment`.

With **naive** attribution (each diagnostic blamed on the candidate with the
greatest start-line ≤ its line), candidate A's own range contains **no**
diagnostic → A is falsely reported **verified** (a false positive), and every
following declaration is skipped (never independently elaborated).

The milder case — a tactic like bare `exact` — makes Lean report
`unexpected token 'example'` and then **recover at the next command keyword**, so
in Lean 4.30.0 the following candidate is still elaborated and checked. The
sentinel (`example : True := True.intro` after each candidate) absorbs that
forward leak so it can never falsely blame the next real candidate; the
`confirm`/rescue machinery handles the harder comment/string case.

### How the trusted verifier stays sound *and* complete

1. **Render a sentinel** after every candidate — absorbs `unexpected token`
   forward leaks (cannot falsely blame the next candidate).
2. **`confirm` (re-batch successes)** — after round 1 the comment-eater A may be a
   false positive; re-batching only the current successes re-checks A with
   nothing valid after it to hide behind, so it surfaces its own
   `unterminated comment` error and is **demoted**. Iterates until stable. This
   removes every false positive.
3. **Rescue pass (v27 addition)** — `confirm` only re-checks *successes*, so a
   valid candidate that A ate is left falsely *failed* (it inherited A's trailing
   lex error). Each candidate that failed **with a lexer-poison error** is
   re-checked **in isolation** (one declaration per file): the true poisoner still
   fails, a victim passes and is **promoted**. Isolation cannot create a false
   positive, so this restores completeness without weakening soundness.

The v26 `mathlib_verifier.py` is left unchanged (so v26 numbers cannot shift); the
rescue lives only in `TrustedMathlibVerifier` and is a strict no-op on candidate
sets without lexer poisoning — e.g. all real model beams and all corpus targets.

## Results (`report.json`)

| Section | n | gold ✓ | trusted ✓ | naive ✓ | trusted FP | naive FP |
|---------|---|--------|-----------|---------|-----------|----------|
| core skip repro | 2 | 0 | 0 | 1 | 0 | **1** |
| core mixed (valid+invalid+comment) | 6 | 3 | 3 | 3 | 0 | **1** |
| **Mathlib mixed (20 real v26 candidates)** | 20 | 14 | 14 | 14 | 0 | 0 |
| Mathlib skip repro (`import Mathlib`) | 2 | 0 | 0 | 1 | 0 | **1** |
| **total** | | | | | **0** | **3** |

- **Trusted is sound and complete:** 0 false positives anywhere, and it matches
  the gold one-per-file reference exactly on every section (including 14/14 on 20
  real Mathlib candidates and 3/3 on the adversarial core-mixed batch).
- **Naive is demonstrably unsound:** 3 false positives (the comment-eaters), the
  exact failure mode the corrected method defends against.
- **On *real* candidates all three agree** (Mathlib-mixed 14/14/14). Real corpus
  targets and model beams are short tactics that never contain an unterminated
  comment/string, so the skip never fired in the v25/v26 corpus or evals — the
  corrected method's headline numbers are unaffected (see Part 2). The defense is
  retained because the failure is real on adversarial input and costs nothing on
  clean input.

## Verifier path inventory (which script uses which verifier)

Static scan (`audit_v27_verifier_soundness.py` → `verifier_inventory`):

- `evaluate_v25_tierc.py`, `generate_v25_mathlib_tierc_corpus.py`,
  `probe_v25_mathlib_env.py` — **v25 one-candidate-per-file** (`lake env lean`,
  one `example` per process). Isolated like gold ⇒ sound by construction (just
  slow). No batching ⇒ no skip risk.
- `generate_v26_mathlib_specialist_corpus.py`, `evaluate_v26_specialist.py`,
  `evaluate_v26_routed_system.py`, `widen_v26_set_corpus.py` — **batched corrected**
  (`BatchMathlibVerifier.verify_many`, `confirm=True` default). Sound.
- v27 scripts (corpus / dataset verify / eval) — **`TrustedMathlibVerifier`**
  (`confirm` forced, rescue). Sound and complete.

No script uses a naive (no-confirm) batched verifier for any reported metric. The
naive verifier exists only in the canonical module for this audit and the
regression test, and refuses to be used as the trusted path.

## Regression tests (`tests/test_v27_verifier_soundness.py`, 9 passing)

- naive renderer omits the sentinel; corrected renderer keeps it;
- `TrustedMathlibVerifier` raises on `confirm=False`; gold forces `batch_size=1`;
- `compare_to_gold` flags a false positive; mismatch kind classification;
- **Lean-backed (core, fast):** the skip reproduction — naive false-positives on
  the comment candidate, trusted and gold both fail it; trusted == gold on a
  mixed batch; timeout/error candidates never counted verified;
- no `state_after` is ever rendered or read.

## Conclusions

1. Headline metrics use the corrected method (`TrustedMathlibVerifier`); the
   unsound path is unreachable.
2. The corrected verifier is **sound and complete** vs the gold reference (0
   false positives, 0 false negatives on every tested batch).
3. The naive batched verifier is **demonstrably unsound** (3 false positives) and
   is quarantined to the audit/tests.
4. The skip never fired on real v25/v26 candidates, so **no previously reported
   Mathlib metric was inflated by it** — confirmed quantitatively in Part 2.
