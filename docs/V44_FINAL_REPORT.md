# V44 — Discrete proving on a hard tier: the wall is generation-given-premises, not retrieval

**Date:** 2026-06-12/13 (overnight) · **Branch:** `v44-discrete-retrieval` · RTX 4080 · seed 3407.
All verification `verify_many_bisect` (V42 sound path, `verify_mode` stamped); generation on
`.venv-gpu` (deterministic). Continuous flow stays closed (v43). This was a build-and-measure night.

## Headline
Built the discrete keeper into a system — a non-simp-closable **hard tier**, a premise-conditioned
AR + MDLM, and a dense premise retriever — and ran the **gold-premise oracle decomposition**. The
pre-registered *surprise branch* fired: **even perfect premise knowledge barely helps a generative
prover on hard theorems.** On hard_dev (n=26):

| | none | retrieved (BM25) | gold (oracle) | `exact?` (Lean search) |
|---|---|---|---|---|
| AR (30M) | 0/26 | 0/26 | **1/26** | — |
| MDLM (30M) | 0/26 | 0/26 | **1/26** | — |
| Lean unification search | — | — | — | **18/26** |

**The 18-vs-1 gap (exact? search vs gold-conditioned generation) is the result: the wall on
non-trivial theorems is converting premise knowledge into a verified tactic — a *search* problem
Lean's `exact?` solves and a generator does not.**

## Pre-registered verdicts
| ID | Result | Evidence |
|----|--------|----------|
| **S1** (hard tier) | **DONE, n=52** (26 dev/26 test); n≥100 infeasible | gold-compile 9.9%, core-simp-closable 91%/49%; non-trivial∧compiling ≈ 1% of pool |
| **S2** (oracle decomp) | **SURPRISE BRANCH: generation-bound** | gold−none = +1/26 both families; `exact?` 18/26; control proves AR uses premises (+0.137 in-dist) ⇒ not a confound |
| **R1** (dense > BM25) | **FALSIFIER MET (dense < BM25)** | dense recall@10 0.0 vs BM25 0.10 (from-scratch 10M encoder; both weak) |
| **R2** (retrieval moves e2e) | **FALSIFIER MET (retrieved ≈ none)** | BM25 retrieved 0/26 = none (recall 0.10 misses gold premises) |
| **E1** (AR∪MDLM ensemble) | **FALSIFIER MET on hard tier** | AR∪MDLM = 1/26 (same theorem); v40's 27/44 was the simp-closable majority |
| **E2/E3** (scaling) | **DROPPED — justified, not just time** | gold-oracle = 1/26 ⇒ scaling the *generator* cannot move the hard tier; the lever is search/retrieval, not generator size |
| **the `exact?` finding** | **83% (43/52) of the hard tier is exact?-solvable** | premise + unification closes 5 in 6; the theorems ARE premise-addressable — for *search*, not generation |

## The decomposition, stated cleanly
Three quantities on non-simp-closable theorems:
1. **Premise-addressability (upper bound):** `exact?` solves 18/26 (dev) / 43/52 (full) — a single
   library lemma, unified, closes most of them.
2. **Generation-given-gold-premises (what a generator achieves):** 1/26. Knowing the lemma *name* is
   not enough; emitting the exact verifying tactic (right arguments, right multi-step structure) is
   the hard part.
3. **Realistic retrieval:** BM25 recall@10 0.10, dense ≈ 0 — neither surfaces the gold premise, so
   retrieved = none.

**The retrieval-vs-generation split V43 left open:** on hard theorems the binding constraint is
**generation/search** (turn premise → verified tactic), with retrieval a *second*, also-unsolved
wall. This **refines, not contradicts, V43**: premise knowledge is necessary (V43's 0.267 ceiling on
mixed tiers) but *far from sufficient* on genuinely hard theorems.

## Project-level conclusion
- Prior "competitive pass@k" results lived on the **simp-closable majority** (V43: 42/45; V44: 91%
  of compiling test theorems). On a tier where that majority is removed, a 30M discrete generative
  prover — even with a gold-premise oracle and an AR∪MDLM ensemble — solves **1/26**.
- The standing discrete positive (AR∪MDLM 27/44, v40) is real but is **automation of the easy
  majority**, not hard-theorem proving.
- The path to hard theorems is **tactic execution / proof search** (unification-driven `exact?`/
  `apply`, hammer-style), fed by a **pretrained-LM premise retriever** — *not* larger token
  generators (the gold-oracle ceiling says generation scale won't help) and *not* continuous flow
  (closed, v43).

## V45 recommendation (from the tally)
1. **Tactic-execution/search loop**, not generation-only: integrate `exact?`/`apply`-with-unification
   and a hammer-style backend; measure on this hard tier (exact? already gets 18/26 — the search
   ceiling to beat).
2. **Pretrained-LM dense retriever** (ReProver-ByT5 / LeanSearch-v2 class), since the from-scratch
   encoder (R1) and BM25 both fail (recall ≤ 0.10); retrieval feeds the *search*, not a generator.
3. **Keep the hard tier as the benchmark** and grow it via the val pool + a Mathlib-version-matched
   trace (the 9.9% gold-compile-rate, a version-skew artifact, is the main thing capping n).

## Honest scope / drops
- **n=52** (not the brief's ≥100): the intersection {non-simp-closable ∧ gold-compiling ∧
  convertible} is ~1% of the 2000-theorem test pool; n≥100 needs a version-matched re-trace
  (deferred). Reported with the rates; the rarity is itself a finding.
- **E2/E3 scaling** and **D1–D3 breadth**: dropped. E2/E3 is *justified* (gold-oracle 1/26 ⇒ generator
  scaling is the wrong lever); D-probes were designated-droppable.
- **Dense retriever** is a from-scratch 10M encoder (a negative); a pretrained-LM retriever is V45.
- Artifacts: `outputs/v44/{hard_tier,gens,oracle,retriever}/*` with `verify_mode`+SHA; docs
  V44_00–V44_04; the hard tier (`outputs/v44/hard_tier/hard_{dev,test}.jsonl`) is a reusable
  benchmark.
