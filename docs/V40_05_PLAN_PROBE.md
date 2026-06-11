# V40 Phase 5 — Plan-level probe (LPSF-lite)

Does flow's per-token-vs-exact-seq **coherence gap** depend on the *object's structural complexity*?
Factor each whole proof into a **head-plan** (sequence of tactic-head tokens only, e.g. `intro simp
exact`, mean 1.74 heads). Train a tiny FLOW@1 and tiny AR (≈4M, `tiny` preset) on `statement →
head-plan`, matched 4e7-token budget. No verification (plans aren't executable) — a mechanism probe.

## Result — the gap LARGELY CLOSES at the plan level
| model | plan exact-seq | plan per-token | distinct |
|-------|------------|------------|----------|
| AR | 0.132 | 0.505 | 17.4 |
| FLOW@1 | 0.085 | 0.537 | 15.8 |

**flow/AR plan exact-seq ratio = 0.643.** Context:
| object | granularity | flow/AR exact-seq ratio |
|--------|------------|------------------------|
| plan (head sequence) | coarse / short | **0.643** |
| single tactic (v39) | medium | 0.073 |
| whole proof (V40 token-level) | fine / long | 0.023 |

The coherence gap is a **monotone function of object granularity**, not a fixed property of continuous
flow: on a short, structured, low-inter-token-coupling object (the plan), flow reaches **64% of AR's
exact-seq** (and per-token 0.537 > AR 0.505) — vs 2–7% at the token level. This is the clearest positive
signal in the whole v35–v40 line for *where* continuous embedded flow belongs: **the plan / abstraction
level**, exactly the LPSF hypothesis. Building full LPSF (plan-flow that emits a tactic skeleton, filled
by an AR/MDLM head + Lean verifier) is therefore the warranted V41 direction — the one place flow's
single-shot decoding is not fighting a coherence wall it cannot climb.
