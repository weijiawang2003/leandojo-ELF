# V32 — Part 3: Adversarial Identifier-Stress Benchmark

_`scripts/generate_v32_identifier_stress_benchmark.py` →
`data/seeds/v32_identifier_stress_seeds.jsonl` +
`data/manual/v32_identifier_stress_candidates.jsonl`. `TrustedMathlibVerifier` only.
EVAL benchmark — never trained; gold proofs are references, never model predictions._

## Purpose

Test whether v31's identifier invariance **generalizes** or merely memorized the
specific v30 residual identifiers. Fresh variants of *solved* families are generated
with **adversarial local identifiers the corpus never used**:

- hypotheses: `h_mem`, `hyp`, `proof₁` (subscript), `hα` (Greek), `h_1`
- elements: `obj`, `elem`, `z`, `w`, `o`
- sets: `A B C`, `U V W`, `S T`, `X Y`, `P Q`
- functions: `φ ψ χ`, `F G H`, `k l m`

## Counts

| metric | value |
|---|---:|
| theorems generated | 46 |
| **solvable (≥1 gold proof)** | **46** (0 zero-success) |
| verified gold candidates | 85 |

By category: set 15, finset 10, order 9, function 3, nat 3, list 3, logic 3 — every
one a true theorem (Greek/subscript/underscore identifiers all parse and verify).

This is a held-out **evaluation** set; the gold proofs only confirm provability. No
`state_after`; no manual oracle as predictions.
