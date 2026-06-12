# V42 Phase 0 — Setup: branch, artifact presence, verifier smoke

**Date:** 2026-06-12 (overnight) · **Branch:** `v42-verifier-audit` off `v41-lpsf`.
**Mission:** fix the batched-verifier false-negative bug found in v41, re-baseline every v39–v41
verified number in trusted mode, audit the v41 uniques, then (conditionally) LPSF next steps.

## Artifact presence

| Artifact | Status | Notes |
|---|---|---|
| v40 per-theorem detail w/ `topk` candidates | **PRESENT** | `outputs/v40/wholeproof/detail_devtier/{ar,mdlm,flow_s1,flow_s16}.json`, `detail_finaltier/{ar,mdlm,flow_s1}.json` — 45/44 theorems × top-10 candidates each. Re-verification needs **no regeneration**. |
| v41 e2e candidate proofs | **ABSENT (deviation)** | `outputs/v41/e2e_*.json` hold aggregates + solved-name sets only; `--detail-dir` in `scripts/v41_e2e.py` is parsed but never used (the dead code the brief flags). v41 re-baseline (P2 priority 1, 4) therefore **regenerates** candidates from committed snapshots — same seeds/configs; GPU nondeterminism may wobble candidate sets, reported as such. |
| v41 snapshots | **PRESENT** | grounder `scale_ar_30M_U79530.pt`; plangen s3407 {ar, flow, mdlm}; s4242 {flow} (flow-only is sufficient — 4242 was a flow seed). |
| v40 snapshots | **PRESENT** | `outputs/v40/wholeproof/snapshots/` (ar/mdlm/flow 30M). |
| Tiers | **PRESENT** | `data/v40/tiers/tier_{dev,final}.jsonl` (45/44), reused verbatim. |
| Persistent verifier cache | **DOES NOT EXIST (deviation)** | The brief's guardrail 3 assumed one. No on-disk verification cache exists anywhere in the eval path. P1 adds one (key = sha256(imports ⊕ statement ⊕ tactic) → verdict), so repeats across phases/sources are free from now on. |

## Verifier smoke (isolated)
`TrustedMathlibVerifier` via `get_verifier()` (scratch = mini_elf_mathlib_probe, pinned v4.30.0 binary):
`(a b : Nat) : a + b = b + a` ⊢ `rw [Nat.add_comm]` → **verified=True**, 8.4 s warm (cold olean load ~30 s
on warmup). Isolated throughput ≈ 6–9 s/candidate → pure-isolated re-baseline of ~4.5k candidates would
blow the 3.5 h verify cap ⇒ **bisect-batched mode (P1) is load-bearing**, with isolated as ground truth
and for spot agreement.

## Mode provenance rule (in force tonight)
Every verification JSON written carries `"verify_mode": "isolated" | "bisect-batched"` + verifier git SHA.
Every number quoted in docs names its mode.

## Known mechanism going in (to be pinned empirically in P1)
The trusted verifier's rescue pass covers only the *unterminated comment/string* lexer-poison class
(`_is_lex_poison`). v41's grounded candidates exhibit a different class (unbalanced brackets, dangling
`using`, empty args) that (a) desyncs attribution in the first pass, and/or (b) enters the confirm loop's
success set and poisons recheck batches — confirm only demotes, never re-promotes, so genuine passes are
demoted permanently ("confirm did not converge in 8 rounds" observed). A chunk-level subprocess timeout
also fails an entire batch at once. P1 reproduces, fixes (bisect-on-poison + bisect-on-timeout +
bisect-on-nonconvergence), and proves agreement vs isolated.
