# V43 Phase 4 — Breadth probes (D1–D4)

LPSF closed by A1; these are mechanism/bonus science. Scope trimmed to what the night's budget
allowed after the e2e verification proved slow (retrieval-grounded candidates are Lean-heavy).

## D1 — plan-level ensemble (AR ∪ MDLM ∪ flow), simp-controlled
Read from the coarse e2e (`outputs/v43/union/*.json`) + the union report. Falsifier: union == AR.
**Result:** see `docs/V43_04_DECISION.md` D1 table. The plan-level ensemble adds nothing the
simp-inclusive base lacks (every plan-source solve is simp-closable); flow contributes 0 unique
over `{AR ∪ MDLM}` at the plan level. D1 falsifier **met** (no ensemble value beyond the trivial
baseline) — consistent with v40's discrete ensemble value (AR∪MDLM 27/44) being the *token/whole-
proof*-level phenomenon, not a plan-level one.

## D2 — grounder decode frontier (beam-4 / retrieval)
Covered by A3 (`docs/V43_02_GROUNDER.md`): the BM25 retrieval grounder ceiling is **0.20** pass@1 /
**0.222** pass@K, *below* V42's neural greedy 0.267 and beam-2 0.311, and far under 0.35. Lexical
premise retrieval does not move the frontier; the wall is dense/semantic premise selection (a
trained retriever), beyond this overnight build. D2 falsifier **met** (flat / regressed).

## D3 — multi-step `have … sorry` plans
**Not run (time).** The retrieval-grounder e2e verification proved far slower than budgeted
(~40 min/source), consuming the GPU+Lean window. Deferred to V44. The B1 result already bounds the
expectation: flow's exact-seq is 0.00 at L≥3 for every granularity, so multi-step plan *generation*
by flow is near-hopeless even before grounding; a `have … sorry` scaffold would have to come from
AR/MDLM, not flow.

## D4 — x-pred vs v-pred at the plan level
**Not run (time).** All V43 flow models use x-prediction (ELF/LD4LG default, confirmed superior in
v39). Re-confirming v-pred inferiority at the plan level is low-value given LPSF is closed; deferred.

## Honest scope note
D3/D4 were the designated-droppable probes; they are dropped explicitly (not silently). The
load-bearing breadth result is D1 (no plan-level ensemble value) + D2 (= A3, the grounder frontier
is flat under lexical retrieval). Both reinforce the A1/A2 closure rather than open a new direction.
