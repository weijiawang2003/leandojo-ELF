# v23 negation rerank analysis (Part 5)

The v22 headline used the `abstract` reranker, under which **negation
pass@5 fell to 0.600**; under `raw` beam order it is **0.800**. v23 asks:
was that regression purely a ranking artefact, and can a refreshed
reranker recover (and ideally lift) negation? Fixed pool = the v22
`plus_exists` candidate set (reranking changes order only). Leave-one-
theorem-out for the v23 LR.

## Per-theorem (5 negation theorems)

| theorem | raw fvr | v23_category fvr | v23_hybrid fvr | note |
|---|---:|---:|---:|---|
| `v18_neg_absurd` | 0 | 0 | 0 | solved; raw rank0 `exact absurd hp hnp` |
| `v18_neg_double_in` | 0 | 0 | 0 | solved; raw rank0 `intro hnp; exact hnp hp` |
| `v18_neg_modus_tollens` | 0 | **1** | 0 | raw solves at rank0; **learned LR demotes it to rank1**, hybrid protects it |
| `v18_neg_not_intro` | 3 | 3 | 3 | **ranking-bound but unfixable** (see below) |
| `v18_neg_or_left` | — | — | — | **generator-bound** (no verified candidate in top-10) |

`fvr` = first-verified rank (0-indexed). Aggregate negation:
- pass@5: raw 0.800, v23_category 0.800, v23_hybrid 0.800 (all keep the 4
  solvable theorems in the top-5); the **abstract** reranker's 0.600 was
  the outlier.
- pass@1: raw 0.600, **v23_category 0.400** (demoted modus_tollens),
  v23_hybrid 0.600 (conservative bucketing protects the rank-0).

## Answers

**Was the negation regression purely ranking?** For the **abstract**
reranker, **yes** — it demoted a verified candidate that the generator's
own beam ranked inside the top-5; `raw` and every v23 config keep negation
at 0.800@5. The fix for that regression is simply *not running the
abstract reranker* (use raw or the conservative hybrid).

**Which feature fixed it / recovered the advantage?** The
**unbound-identifier penalty** is the relevant grounding signal: it
correctly down-weights `exact False.elim (h hp)` and `exact absurd hp h`
(here `hp` is not yet in context — the goal is `¬¬p`), which are the raw
rank-0/1 misses on `neg_not_intro`. But it does **not** fully fix
`neg_not_intro`: the verified `intro hp\n  exact absurd hp h` is
**feature-indistinguishable** from grounded-but-wrong siblings such as
`intro hp\n  exact absurd (h hp)` (both bind `hp`, both contain
intro+absurd; the arity error is invisible to surface features). So the
verified candidate stays at rank 3 under every reranker — this miss is
**generation-quality, not ranking** (the beam contains the proof *and*
several near-identical decoys).

**Does the reranker overfit negation?** The pure learned LR (`v23_category`)
**demotes** `neg_modus_tollens` from rank 0 to rank 1 — evidence that an
aggressive learned reranker hurts even within the category it was meant to
help. The conservative `hybrid` (probability bucketed to 0.1 + raw
beam-rank tie-break) avoids this demotion and matches raw negation exactly
(0.600@1, 0.800@5). **Net: the right negation action is to retire the
abstract reranker, not to add an aggressive learned one.**
