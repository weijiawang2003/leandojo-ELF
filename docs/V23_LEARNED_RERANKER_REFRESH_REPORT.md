# V23 learned-reranker refresh report

**Mission.** v22's headline used the `abstract` reranker, which demotes a
verified negation candidate (negation pass@5 0.800 → 0.600). v23 refreshes
the reranker on v16–v22 candidate-outcome data — **especially the v22
broad-core outcomes** — to stop demoting verified candidates and improve
broad-core pass@1/pass@5 **without touching the generator**. Everything
here is **ranking-only** and **offline** (the v22 eval `predictions.jsonl`
already record each candidate's verification, so re-ranking + pass@k is a
pure reshuffle).

## Research questions — answered

1. **Can a reranker trained on v22 outcomes recover the raw negation
   advantage?** **Yes, trivially** — every v23 config keeps negation at
   0.800@5 (vs `abstract`'s 0.600). But `raw` beam order already had
   0.800, so this is "match raw", not "beat raw". The abstract reranker
   was the only thing that had broken negation.
2. **Can reranker refresh push pass@5 above 0.812 / pass@1 above 0.729?**
   **Above the `abstract` headline, yes** (hybrid: pass@5 0.833, pass@1
   0.771); **above `raw`, no** (raw is 0.833 / 0.792).
3. **Does ranker-time abstraction help as a feature without
   over-demoting?** The abstract-pattern feature (folded into the LR, not
   used as the sole ranker) does **not** improve over plain grounding
   features, and the pure learned LR **over-demotes** (pass@1 0.792 →
   0.688). Only the **conservative hybrid** limits demotion — and it is
   still net −1 vs raw at pass@1.
4. **Is the remaining broad-core gap generator-bound or ranking-bound?**
   **Generator-bound.** Of 48 theorems: 39 solved@1, **1 ranking-bound**
   (`neg_not_intro`, and even it is feature-unfixable), **8
   generator-bound** (no verified candidate in the top-10).

## Headline (fixed v22 plus_exists pool, 48 theorems)

| ranker | pass@1 | pass@5 | pass@10 | MRR | negation@5 | demote@1 | promote@1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **raw** (the bar) | **0.792** | **0.833** | 0.833 | **0.804** | 0.800 | — | — |
| v22 `abstract` (headline) | 0.729 | 0.812 | 0.833 | 0.774 | **0.600** | — | — |
| v15 `learned` | 0.646 | 0.833 | 0.833 | 0.725 | 0.800 | — | — |
| v23 plain (B), LOTO | 0.688 | 0.833 | 0.833 | 0.744 | 0.800 | 6 | 1 |
| v23 category-aware (C), LOTO | 0.688 | 0.833 | 0.833 | 0.738 | 0.800 | 6 | 1 |
| **v23 hybrid (D)**, LOTO | 0.771 | 0.833 | 0.833 | 0.792 | 0.800 | **2** | 1 |

`pass@10 = 0.833` for **every** ranker — the generator ceiling (reranking
cannot change which candidates exist). LOTO = leave-one-theorem-out (the
LR + pattern bag exclude the scored theorem's rows; no leakage).

## What v23 found

- **`raw` beam order is the best ranker.** The v22 generator's beam is
  already well-calibrated; no learned or hybrid reranker beats it.
- **The learned reranker is a precision tax.** v23 plain/category lift one
  theorem (`list_length_cons`: `exact rfl` promoted to rank 0) but demote
  six raw-correct rank-0s → net pass@1 0.792 → 0.688. The conservative
  **hybrid** (probability bucketed to 0.1, raw beam-rank tie-break) cuts
  demotions 6 → 2, recovering to 0.771 — still net −1 (it keeps the
  `list` win but demotes 2 conjunction rank-0s).
- **The abstract reranker was the real problem, and v23 fixes it by
  retirement.** vs the v22 *headline* (`abstract`), v23 hybrid is strictly
  better on every metric (pass@1 +0.042, pass@5 +0.021, negation +0.200).
- **The gap is generator-bound.** 8 of the 10 misses are generator-bound
  (unknown_identifier ×4, other ×3, type_mismatch ×1); the lone
  ranking-bound theorem (`neg_not_intro`) is feature-unfixable. Max
  ranking headroom ≈ +1–2 pass@1, and a learned reranker cannot capture it
  without collateral.

## Best-system selection

- **Best ranker = `raw` beam order** (equivalently the conservative
  hybrid, which ties raw on pass@5/pass@10 and is within one theorem on
  pass@1 while guaranteeing it never demotes on a near-tie).
- **Retire the `abstract` reranker** for the v22 generator — it is the
  only config that loses ground (negation 0.600).
- A per-category raw-vs-learned switch is **not adopted**: on 5–6
  theorems/category its apparent wins/losses are within noise, and tuning
  it on the 48-theorem test would overfit. `v23_rerank_policy.py` ships the
  conservative hybrid (a-priori, not test-tuned) for reuse.

## v24 recommendation

The residual is **generator/corpus-bound** → v24 should apply the **v22
exists-corpus recipe** (small, lean-verified, leakage-guarded shape
corpora) to the 8 generator-bound theorems' categories
(disjunction / nat_succ / conjunction / list / the one negation shape),
**not** more ranking work. The v22 brief's "no Mathlib until the
general-model question is tested" gate is cleared, so Mathlib tier-C is
also unblocked as an alternative coverage source.

## Honesty contract

- **v23 changes ranking only**, never the generator; the candidate pool
  and its verifications are the fixed v22 `plus_exists` output.
- **Ranker-time abstraction is scoring-only** — the abstract pattern is a
  feature used to look up training frequency; the reranker reorders the
  **raw-name** candidates and **never emits a placeholder** (pinned by
  test).
- v22 metrics on disk are **not retconned** — `abstract` 0.812 remains the
  v22 headline; v23 publishes at `data/baselines/v23_rerank_eval/`.
- No `state_after`, no manual oracle (the v15 family donors and broad-core
  rows are all lean-verified outcomes, never decoder inputs), no Mathlib,
  no v10-leakage revival, **not full theorem proving** (a 48-theorem
  core-Lean benchmark, directional).
- Leakage controlled by leave-one-theorem-out; honest negative result
  reported in full (no reranker beats raw).
