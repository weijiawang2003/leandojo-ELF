# V42 Phase 1 — Verifier fix: bisect-batched verification, provably equal to isolation

## 0. Headline

Tonight found **four** independent defect classes in the batched verification path that produced
**both false negatives AND false positives** in v39–v41 batched numbers. The brief's premise
("sound-but-incomplete — false negatives only") is **wrong**: two of the classes silently mark
unelaborated candidates as *verified*. All four are fixed; the fixed path is validated against
one-candidate-per-file isolation (ground truth) on crafted and real data.

## 1. Root cause — four defect classes

| # | Class | Mechanism | Direction | Found by |
|---|---|---|---|---|
| 1 | **Chunk timeout** | one 300 s subprocess timeout covers an 80-candidate file; slow chunks fail wholesale; the confirm loop re-batches successes ACROSS chunk boundaries each round, so one slow repack demotes en masse, permanently (confirm never re-promotes) → "did not converge in 8 rounds" | false **negatives** | deterministic core repro: 24 slow-valid `decide`s + 3 trivially-good; legacy fails all 27 |
| 2 | **Parse desync** | a parse-broken candidate (dangling `using`, empty `rw` arg, unterminated comment/string, unbalanced brackets) desyncs Lean's command boundaries; later candidates are skipped or get leaked diagnostics; the v27 sentinel+rescue covered only the `unterminated comment/string` subclass | both | v27-era known, subclasses found in v41's grounded proofs |
| 3 | **Attribution shift (NEW)** | a **multi-line statement** was appended as ONE bookkeeping line, so every later line range in the file is shifted by its extra physical lines; with 10 consecutive multi-line candidates the shift compounds → wholesale misattribution with **zero** parse diagnostics. `concaveOn_id` is the only v40-tier statement with embedded newlines — and tier-final has none, which is exactly why v41's tier-final batched looked clean while tier-dev was poisoned | both — produced **false positives** live (garbage "verified" in v40 dev re-runs) and false negatives (`Mathlib.Tactic.Ring.div_congr`, a genuine `subst_vars; rfl` solve, sat right after the block and was demoted) | v42 re-baseline diff + singleton ground-truth |
| 4 | **maxErrors flood (NEW)** | Lean aborts elaboration after 100 diagnostics ("maximum number of errors … reached, exiting") — every candidate after the abort line gets NO diagnostic and was scored as a silent false **success**. Garbage-heavy batches (flow token salad: ~2 diagnostics per candidate) hit the cap halfway through the file | false **positives** | 22 token-salad flow candidates "verified" in one v40 dev chunk; direct compile shows the abort at line 256 of 354 |

A fifth latent hole closed on the way: a **crashed/aborted Lean process** (returncode ∉ {0,1},
PANIC output) used to yield an all-success chunk; now any abnormal exit marks the compile untrusted.

## 2. Fix (two layers)

**(a) Exact bookkeeping** — `_render` now appends exact physical lines (`split("\n")` matching the
join) for statements and tactics; the rendered file is unchanged, only the line ranges. This kills
class 3 at the source.

**(b) `verify_many_bisect`** (mode label `bisect-batched`) — trust rule: a batch verdict set is
accepted **iff** its compile produced no parser/lexer-class diagnostic (`_is_parse_class`: body
starts `unexpected …`, contains `unterminated comment|string` or `maximum number of errors`, or is
a chunk `timeout`), exited normally (returncode ∈ {0,1}, no PANIC), and wasn't a subprocess
timeout. Parse-clean files cannot desync — every declaration elaborates at its own (now exact)
range, so attribution equals isolation. A suspicious batch is split: candidates whose own
attributed error is parse-class are **quarantined to singletons** (= isolated ground truth); the
rest are re-batched (victims re-elaborate cleanly); if partitioning cannot shrink the set, halve.
Every emitted verdict therefore comes from a trusted batch or a singleton file ⇒ equal to
isolation on any input mix. Termination: every recursion strictly shrinks the set.

Also at invocation: `-DmaxErrors=100000` (keeps whole-file elaboration on garbage-heavy batches;
the abort diagnostic stays suspect-flagged as belt-and-braces), and elaboration-error messages
*containing* "expected" (type mismatch etc.) are deliberately NOT suspect — only real parser
messages — so clean batches still cost one compile.

`TrustedMathlibVerifier.verify_many` routes through bisect (every caller gets the fix); the
pre-v42 path survives only as `verify_many_legacy` for regression evidence.

**During Phase 1 the fix itself was caught wrong twice by ground-truthing** — (1) the first bisect
accepted batches whose parse errors hid behind the `error: :` double-colon prefix (`_is_parse_class`
never fired → the live flow_s1 false positives), and (2) the first re-baseline ran before the
maxErrors hole was found. Both were found by singleton-checking every old→new flip — the protocol
that stays in force for the night: **every verdict change is ground-truthed in isolation before it
is believed.** The tainted verdict cache and re-baseline outputs were deleted both times.

Plus `VerdictCache` (`src/mini_elf_lean/verdict_cache.py`): persistent
sha256(imports ⊕ statement ⊕ tactic) → verdict JSONL; only trusted-mode verdicts are stored.

## 3. Regression tests (`tests/test_verifier_poison.py` — 7; all pass)

| Test | Result |
|---|---|
| (i) Timeout reproducer: 24 slow-valid `decide`s (~2 s singleton, ~17 s batched) + 3 goods, timeout 8 s | **legacy fails ALL 27 incl. the goods** (the v41 bug, deterministic); bisect verifies all 27. FAILS on pre-v42 code. |
| public `verify_many` = bisect | same batch verifies via the public API |
| (ii) Property: 60-candidate mixed set (goods / parse-broken incl. balanced-but-broken / false stmts / lexer poison) | bisect == gold isolation, 0 mismatches |
| (iv) Attribution shift: 8 consecutive 3-line-statement candidates + tails | bisect+fix == gold. Recorded old-code behavior: genuine `simp [h]` passes and a trailing `exact h` all DEMOTED (false negatives); on real v40 data the same shift produced false POSITIVES. |
| (v) maxErrors flood: 60 junk candidates (≥120 diagnostics) + false/good tails | trusted == gold; no false success at the tail. Old code marked post-abort candidates verified. |
| (iii) Old v27 lex-poison classes | still correctly failed by both paths |
| `_is_parse_class` unit | incl. the `error: :` double-colon regression |

## 4. Real-data demonstration + agreement validation

*(appended when the Phase-1 runs complete: flow_s1 chunk re-check vs singletons; n=100 stratified
bisect-vs-isolated agreement across v40/v41 sources)*
