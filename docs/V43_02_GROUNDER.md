# V43 Phase 1 — Premise-selection grounder, A3 ceiling, C2 coverage

## The build
`src/mini_elf_lean/grounder_retrieval.py`: a BM25 retriever over the **241,756-premise** Mathlib
pool extracted from the LeanDojo corpus (`scripts/v43_build_premise_index.py`: full_name +
signature, camelCase/dot/underscore tokenized, idf+postings; vocab 46,725, avgdl 21.6). Given a
theorem statement it retrieves in-scope candidate premises (self-excluded), then fills a plan's
argument slots by template (`rw [p…]`, `exact p`, `simp [p…]`, …), ranked best-first by BM25
rank-sum. Drop-in `plan → tactic` interface. This is the ReProver-style premise pool realized
lexically — training-free and sound; a dense retriever is the documented ceiling (LeanSearch v2,
graph-augmented selection).

## A3 — does premise selection lift the gold-plan ceiling?

Gold proofs factorized to plans, retrieval-grounded (K=24 fills), verified (bisect). Tier-dev,
n=45 (`outputs/v43/grounder/ceiling_retrieval.json`):

| grounder | ceiling pass@1 | pass@K |
|---|---|---|
| V42 neural greedy | 0.267 | — |
| V42 neural beam-2 | 0.311 | — |
| **V43 retrieval (BM25)** | **0.200** | **0.222** |
| causality control (corrupted plan) | 0.022 | 0.044 |

**A3 falsifier MET → the ceiling stays well below 0.35.** Lexical premise retrieval does **not**
lift the ceiling — it lands *below* the neural copy-grounder (0.20 vs 0.267). The 10 theorems it
grounds are dominated by no-argument heads (`simp`/`rfl`/`ring`-closable: `Finset.sigma_nonempty`,
`Matrix.posDef_intCast_iff`, `concaveOn_id`, …); the premise-heavy plans fail because BM25 surfaces
*topically* related premises but rarely the *exact* gold lemma (e.g. for `sup_himp_self_left` it
returns `bihimp_fst`/`isGreatest_himp`, not the gold `sup_himp_distrib`/`himp_self`/`top_inf_eq`).
Causality holds strongly (corrupting plan heads drops pass@1 9× to 0.022 — the grounder genuinely
uses the plan).

**Interpretation.** V42 predicted the grounder wall is *lemma knowledge*, not search. A3 confirms
and sharpens it: even an explicit 241k-premise retriever can't break 0.35 with lexical matching —
the wall is **dense/semantic premise selection** (a trained retriever or LLM premise ranker), which
is beyond an overnight build. Critically for the LPSF verdict: **no grounder we can build lifts the
ceiling, so a "strong grounder" that could rescue flow's e2e does not exist tonight** — A2 inherits
a weak grounder by necessity, and the A2 close-out leg ("gain doesn't survive the strong grounder")
is read with that caveat: there is no strong grounder to survive.

## C2 — coarse-plan coverage (is the abstraction too lossy?)

`coarse_plan` factorizes **100%** of tier gold proofs (45/45 dev, 44/44 final); 7 dev / 3 final
contain an `OTHER` head (a tactic outside the head vocabulary). So the coarse representation is
**expressive enough** — the lossiness is not in *what plans can be written* but in *grounding the
arg slots* (A3). C2's pass-bound ("coarse-plan ceiling ≥ direct-AR") is read from the A2 e2e: the
coarse-AR + retrieval pipeline's solved count vs direct-AR 20 (see `docs/V43_04_DECISION.md`).
