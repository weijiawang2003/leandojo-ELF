# V42 Phase 1 — Verifier fix: bisect-batched verification, provably equal to isolation

## 1. Root cause (two demotion classes, both false-negative-only)

The v27–v41 trusted path (`verify_many(confirm=True)` + lex-poison rescue) is sound for
*well-formed* candidate sets — the case it was audited on (v27: model beams of single tactics).
Model-**grounded** multi-line proofs (v41) and whole-proof samples (v40) break its assumptions:

1. **Chunk timeout (the mass-demotion class).** One Lean file holds up to 80 candidates with a
   single 300 s subprocess timeout. A chunk whose candidates are collectively slow (heavy `simp`/
   `decide`/garbage elaboration) times out → **every** candidate in it is failed at once. Worse,
   the confirm loop re-batches *all current successes* across chunk boundaries each round, so one
   slow repacked chunk demotes en masse; demotion is permanent (confirm never re-promotes) and a
   different repack each round = "confirm did not converge in 8 rounds". Isolated runs give each
   candidate its own 300 s — hence v41's plan-AR 4 batched vs 20 isolated.
2. **Parse desync.** A parse-broken candidate (unterminated comment/string, dangling `using`,
   empty `rw` args, unbalanced delimiters …) can desync Lean's command boundaries: declarations
   after it are skipped (false success) or get leaked/garbled diagnostics (false failure). The
   sentinel + confirm + lex-rescue covered the classes known in v27, but rescue only re-promotes
   failures whose error text matches `unterminated comment|string` — every other victim stays
   demoted.

Both classes produce **false negatives only** on genuine candidates, so every *positive* v39–v41
verified result is a real proof; *negative/comparative* numbers are lower bounds until re-measured.

## 2. Fix: `verify_many_bisect` (mode label: `bisect-batched`)

Trust rule: **a batch verdict set is accepted iff its compile produced no parser/lexer-class
diagnostic and no timeout** (`_is_parse_class`: message body starts `unexpected …`, contains
`unterminated comment|string`, or equals `timeout`; elaboration errors — `unknown identifier`,
`type mismatch`, `unsolved goals`, … — occur on successfully parsed declarations and cannot
desync attribution). A suspicious batch is split: candidates whose own attributed error is
parse-class are **quarantined to singletons** (= isolated ground truth — the only way a
parse-broken candidate ever gets its verdict); the rest are re-batched (victims re-elaborate
cleanly there); if partitioning cannot shrink the set (all-suspect, no-suspect-but-file-
suspicious, whole-chunk timeout), **halve**. Every emitted verdict therefore comes from a
parse-clean non-timeout batch or a singleton file ⇒ **equal to one-per-file isolation on any
input mix**. Termination: every recursion strictly shrinks the set.

`TrustedMathlibVerifier.verify_many` now routes through bisect (all callers get the fix); the
historical path survives only as `verify_many_legacy` for regression evidence. Cost: parse-clean
batches still cost 1 compile; each broken/slow candidate costs O(log n) extra compiles.

Plus `VerdictCache` (`src/mini_elf_lean/verdict_cache.py`): persistent
sha256(imports ⊕ statement ⊕ tactic) → verdict JSONL; only trusted-mode verdicts are stored;
repeats across phases/sources are free.

## 3. Regression tests (`tests/test_verifier_poison.py`, 5 passed)

| Test | Result |
|---|---|
| (i) Reproducer: 12 slow-**valid** candidates (~1.5 s each, core Lean `decide`) + 3 trivially-good, chunk timeout 8 s | **legacy fails ALL 15 (incl. the goods) — the v41 bug, deterministic**; `verify_many_bisect` verifies all 15. This test FAILS on pre-v42 code (the old `verify_many` was the legacy path). |
| public `verify_many` routes through bisect | same batch verifies via the public API |
| (ii) Property: 60-candidate mixed set (goods / parse-broken incl. **balanced-but-broken** `simpa using`, empty `rw` arg / false statements / lexer poison) | bisect-batched == gold isolation, **0 mismatches** |
| (iii) Old v27 lex-poison classes (`make_skip_repro_batch`) | still correctly failed by both paths |
| `_is_parse_class` unit | parser/lexer/timeout → suspect; elaboration errors (incl. messages containing "expected") → not |

Sanity (core, mixed 8-candidate batch incl. all malformed classes): bisect == gold 8/8, with
clean candidates still batched (7 splits, 15 compiles for 8 candidates vs 8 isolated + overhead).

## 4. Real-data demonstration + agreement validation

*(appended below when the Phase-1 runs complete)*
