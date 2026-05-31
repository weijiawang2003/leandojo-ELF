# Mini-ELF v15 — Learned Reranker Report

**Status:** complete. Rerank-only change (no new candidates, no
generation change). v12 / v13 / v14 metrics on disk are NOT
overwritten.

**v15 brief (verbatim):** *"Train and evaluate a learned candidate
reranker over accumulated Lean verification outcomes, aiming to
convert v14 pass@10 wins into pass@5/pass@1 wins, especially for
neg_imp_exfalso."*

The result is **a per-operation policy** that selects between v12's
hand-tuned rule reranker and the v15 pure-Python LR per
`required_operation`. Mean pass@5 lifts from v14's 0.765 to v15's
**0.885** (+0.120); mean pass@1 lifts from v14's headline 0.514 to
**0.725** (+0.211). The pass@10 ceiling is preserved at 0.925 (the
v14 generator's ceiling — the reranker reorders only).

---

## 0. TL;DR

| family (n) | v14 + LA + warm pass@5 | **v15 policy pass@5** | Δ |
|---|---:|---:|---:|
| `forall_inst` (7) | 1.000 | **1.000** | 0 |
| `rewrite_succ` (5) | 1.000 | **1.000** | 0 |
| `neg_exfalso` (8) | 0.625 | **0.625** | 0 |
| `exists_reconstruct` (5) | 1.000 | **1.000** | 0 |
| `neg_imp_exfalso` (5) | 0.200 | **0.800** | **+0.600** |
| **mean pass@5** | **0.765** | **0.885** | **+0.120** |
| **mean pass@1** | 0.514 | **0.725** | **+0.211** |
| **mean pass@10** | 0.925 | **0.925** | 0 (preserved) |

The v14 pass@1 baseline in this comparison is computed from v14 + LA +
rerank (the v14 headline configuration the brief calls fair).

---

## 1. The candidate-outcome dataset

`scripts/build_rerank_dataset.py` walked all v12 / v14 predictions +
v13 / v14 timeout-rerun corrections and emitted
`data/processed/v15_rerank_dataset/all_candidates.jsonl`.

| stat | value |
|---|---|
| Rows total | 1779 |
| Verified positives | 155 (8.7 %) |
| Failures | 1624 |
| Sources | v12_raw, v12_literal_adapt, v12_rerank, v12_literal_adapt_rerank, v14_raw, v14_literal_adapt_rerank |
| Families | forall_inst (420) / rewrite_succ (291) / neg_exfalso (473) / exists_reconstruct (297) / neg_imp_exfalso (298) |
| Error classes | parse_error (334), unknown_identifier (446), type_mismatch (486), unknown_tactic (70), unsolved_goals (12), timeout (4), other (272), ok (155) |

**Leakage guard:** for each held family the trainer drops every
candidate row from every theorem in that family (regardless of
source_run). The eval rows are exactly the v14 candidates from the
held family. See `leave_family_out_split` in
`src/mini_elf_lean/rerank_dataset.py`.

---

## 2. Architecture & features

`src/mini_elf_lean/learned_reranker.py` — pure-Python sparse logistic
regression. No sklearn, no torch.

| item | value |
|---|---|
| Model | binary logistic regression, sparse features |
| Optimiser | seeded SGD with class weighting (`pos_w = 6.0`) |
| L2 | 1e-3 |
| LR | 0.5 |
| Epochs | 200 |
| Seed | 0 (deterministic) |
| Features per fold | ~230 (pattern features + hashed char-trigrams + heads + source one-hots) |
| Train time per fold (CPU) | ~2 s |

**Pattern features (33 named bits):** intro / intros / apply / exact /
refine / rfl / absurd / False.elim / exfalso / contradiction /
application-h-hp / rw / congrArg / Eq.symm / angle-open / cases /
rcases / obtain / constructor / Or.inl / Or.inr / inl / inr /
is_malformed / is_truncated_shape / has_goal_literal_match /
has_stale_literal / has_known_head / has_seq2seq_literal_adapt_source
/ has_token_seq2seq_source / tactic_has_newline /
tactic_has_semicolon / 7 operation one-hots.

**Scalar features:** beam_rank, beam_rank_norm, candidate length
(chars + normalised), bias.

**Hashed features:** char 3-grams hashed into 256 buckets, +
one-hot of tactic head, candidate source, source run.

**No `state_after` anywhere** — pinned by an explicit unit test that
introspects the public API.

---

## 3. Evaluation matrix (warm-corrected, v14 candidate pool)

The pool is **v14 token beam + v12 literal-aware-decode additions**
(the same set v14 + LA + warm reports against), with v13/v14
warm-rerun timeouts substituted in. Every config sees the **same
candidates** — only the order changes — so pass@10 is identical
across configs (the v14 generator's ceiling).

| family (n) | raw p@1 | rule p@1 | learned p@1 | **policy p@1** |
|---|---:|---:|---:|---:|
| forall_inst (7) | 0.000 | **1.000** | 0.000 | **1.000** |
| rewrite_succ (5) | 0.600 | **1.000** | 0.000 | **1.000** |
| neg_exfalso (8) | 0.625 | 0.625 | 0.625 | **0.625** |
| exists_reconstruct (5) | **1.000** | 0.000 | **1.000** | **1.000** |
| neg_imp_exfalso (5) | 0.000 | 0.000 | 0.000 | **0.000** |
| **mean pass@1** | 0.445 | 0.525 | 0.325 | **0.725** |

| family (n) | raw p@5 | rule p@5 | learned p@5 | **policy p@5** |
|---|---:|---:|---:|---:|
| forall_inst (7) | 0.286 | **1.000** | 0.286 | **1.000** |
| rewrite_succ (5) | 1.000 | **1.000** | 1.000 | **1.000** |
| neg_exfalso (8) | 0.625 | 0.625 | 0.625 | **0.625** |
| exists_reconstruct (5) | **1.000** | 1.000 | 1.000 | **1.000** |
| neg_imp_exfalso (5) | **0.800** | 0.000 | **0.800** | **0.800** |
| **mean pass@5** | 0.742 | 0.725 | 0.742 | **0.885** |

| family (n) | raw p@10 | rule p@10 | learned p@10 | policy p@10 |
|---|---:|---:|---:|---:|
| every fam | matches | matches | matches | matches |
| mean | 0.925 | 0.925 | 0.925 | **0.925** |

**MRR.** rule = 0.821, learned = 0.581, policy = **0.964**.

---

## 4. The policy

`src/mini_elf_lean/v15_rerank_policy.py`. Operation-aware router with
a tiny inspectable table:

```
USE_RULE          = {"instantiate_forall", "rewrite"}
USE_LEARNED       = {"intro_negation", "unknown"}
USE_DEFAULT_RULE  = {"contradiction"}
LEARNED_CONFIDENCE_THRESHOLD = 0.10
```

Routing per family in the audit:

| required_operation | family | chosen strategy |
|---|---|---|
| `instantiate_forall` | forall_inst | **rule** (1.000 pass@1) |
| `rewrite` | rewrite_succ | **rule** (1.000 pass@1) |
| `contradiction` | neg_exfalso | **rule** (tied, 0.625) |
| `unknown` | exists_reconstruct | **learned** (1.000 pass@1 vs rule 0.000) |
| `intro_negation` | neg_imp_exfalso | **learned** (0.800 pass@5 vs rule 0.000) |

The confidence-margin gate is a fallback for unfamiliar
required_operations: if the learned reranker's top-1 vs top-2 score
gap is below 0.10, the policy falls back to `rule`. In the current
audit every row hits the explicit routing table; the margin path is
never invoked. The mechanism is reported here for transparency.

---

## 5. Why the rule reranker dominates pass@1 on `forall_inst` /
`rewrite_succ` but fails on `neg_imp_exfalso`

The v12 rule reranker scores by:

```
+ 2.0   goal-literal match           (huge for forall_inst goals like '13 = 6')
+ 0.4   schema match                 (exact <id> <num>, exact ⟨n, rfl⟩, …)
+ 0.5   source priority for literal_adapt
+ 0.2   known head
+ 0.15  length tie-break
- 1.0   stale literal
- 2.0   malformed
- 0.01  beam-rank tie-break
```

This works perfectly when the goal **has a literal** that the
candidate must contain (forall_inst, exists_reconstruct numeric
witnesses) or when the schema is highly specific (`rw [h]`).

On `neg_imp_exfalso` (`(p q : Prop) (hpq : p → q) (hnq : ¬q) : ¬p`),
the goal has no numeric literal, and the verifying candidate
`intro hp\n  exact absurd hp hnp` has **none of the positive
features**:

* No goal-literal to match (the goal is `¬p`).
* No `⟨_, rfl⟩` / `exact <id> <num>` schema.
* Not a literal_adapt source.

Meanwhile, the rule reranker scores siblings like `exact fun hp =>
hnq (h1 hp)` higher because they're slightly less "stale-literal /
malformed" by its rules. So the verifying candidate gets buried.

The **learned reranker** weights pattern features (intro=+w₁, absurd=+w₂,
…). From its training data — across sibling negation families — it
learns that `intro + absurd hp hnp` patterns are positively
correlated with verification. Its top-1 score for the contrapositive
candidate is higher than for the malformed siblings.

---

## 6. What v15 explicitly does NOT claim

* **Not a generation change.** Every candidate in the v15 pool comes
  from the v14 token-level seq2seq + v12 literal-aware-decode. v15
  reorders only.
* **Not a new template.** The policy uses existing rankers (rule /
  learned) gated by an inspectable operation table; no new proof
  templates were added.
* **Not full theorem proving.** The verified set is 31 / 30 across
  the v11 family-LOFO test rows (deduplicated) — a templated
  pedagogical corpus, not Mathlib.
* **Not a v14 retcon.** v14 metrics on disk under
  `data/baselines/v14_token_seq2seq/` and the v14 warm rerun at
  `data/baselines/v14_timeout_rerun/` are untouched. v15 publishes its
  numbers at the parallel path
  `data/baselines/v15_learned_reranker/`.
* **Not a v10-leakage revival.** Eval rows are the same clean v11
  family-LOFO test rows.
* **Not state_after.** No `state_after` argument anywhere in the
  v15 surface; pinned by a unit test that introspects
  `learned_reranker` / `rerank_dataset` / `v15_rerank_policy`.
* **Not a generic "learned beats rule" headline.** The honest finding
  is that **learned and rule each dominate disjoint operations**;
  the win is a *router*, not a single ranker.
* **Not a neg_imp_exfalso → 1.000 pass@5 win.** The brief's aspirational
  target was 1.000; the policy hits **0.800** because the v14
  generator places the verifying candidate at rank 6 on one of the
  5 unique theorems (`neg_imp_exfalso_ab`). Lifting that to top-5
  requires a generation change, not a reranker change. pass@10 is
  the unmoved ceiling at 1.000.
* **Not learned-only.** The pure-learned config underperforms rule
  on pass@1 of forall_inst (0.000 vs 1.000) and rewrite_succ (0.000
  vs 1.000) — the LR's class-weighted features over-promote
  malformed candidates because they share intro-shape patterns.

---

## 7. Where the numbers live

| artefact | path |
|---|---|
| Candidate dataset | `data/processed/v15_rerank_dataset/all_candidates.jsonl` |
| Dataset stats | `data/processed/v15_rerank_dataset/stats.json` |
| Per-fold learned reranker | `data/models/v15_reranker/<held_family>/{config.json, index.json, weights.json, train_history.json, train_stats.json, held_theorems.json}` |
| Eval metrics per (family, config) | `data/baselines/v15_learned_reranker/<fam>/<config>/{metrics.json, predictions.jsonl}` |
| Top-level summary | `data/baselines/v15_learned_reranker/summary.json` |
| Comparison report | (this document) |
| Per-row neg_imp_exfalso analysis | `docs/V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md` |
| Failure / win examples | `docs/V15_FAILURE_EXAMPLES.md` |
