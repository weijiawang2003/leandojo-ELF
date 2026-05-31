# V22 general-model report

**Mission.** v21 recovered the forall regression with a category
**router** but closed its own report on an open question: routing is a
*composition of specialists*, not a single model that learned to do
everything. v22 tests that question head-on — **can one model serve all
broad-core categories without the v21 category tradeoff, or is routed
specialisation necessary?** — and, secondarily, lifts the fragile
`exists` category.

## Research questions

1. Can a single (larger / balanced) model **match or exceed** the v21
   routed mean pass@5 = 0.792?
2. Is the residual gap caused by **model capacity**, **data imbalance**,
   or **category interference**?
3. Can a small targeted **exists** corpus raise `exists` without harming
   `forall` / `implication` / `bool`?
4. If routing still wins, can we justify it as the correct architecture?

## Method (held fixed from v18–v21)

- **Architecture**: token-level bi-GRU + additive attention, beam 10,
  deterministic seed 0, 20 epochs, the same `token_seq2seq.train_token`
  trainer used since v14. Only two axes vary:
  - **pool**: `A_mixed` (v21 pool + v22 exists corpus, no rebalance) vs
    `B_oversample` (minority operations up-sampled toward a 400-row cap).
  - **capacity**: base `embed 96 / hidden 128` vs large
    `embed 128 / hidden 192` (the v21 "capacity" arch).
- **Two no-exists single-model anchors are reused, not retrained**:
  `v21_single_retrain` (v21 pool, base) and `v21_capacity` (v21 pool,
  large). They isolate the effect of *adding exists* and *balancing*.
- **Evaluation**: the same `evaluate_v21_broad_core.py` in single-model
  mode on the 48-theorem v18 broad-core benchmark, six rerank configs
  (`raw` / `rule` / `learned` / `policy` / `abstract` / `policy_abstract`),
  warm lean-cli verifier (shared cache, pinned toolchain binary).
- The tokeniser sees only `theorem_statement` + `state_before` — **never
  `state_after`**. No manual oracle. No Mathlib. No routing inside any
  v22 model (each is one set of weights).

## What was built (Parts 2–4)

- **Part 2** [`scripts/build_v22_balanced_training.py`] — five pools under
  `data/processed/v22_balanced_broad/`: `A_mixed`/`E_plus_exists` (3,247),
  `B_oversample` (6,417), `C_undersample` (1,430), `D_loss_weighted`
  (advisory sidecar; the token trainer has no per-row weight hook, so D is
  documented, not trained). `destruct_exists` rises 34 → 505 rows.
- **Part 3** [`scripts/generate_v22_exists_corpus.py`] — **471 / 471**
  lean-cli-verified exists candidates over 168 theorems, 6 shape families
  (witness-intro 360, eq-witness 16, reconstruct-var 8, relabel 45,
  elim-prop 18, compose 24). 0 leakage drops (capital `P`/`Q` predicate
  names keep it disjoint from v18's lowercase `p`/`q`).
  ([`V22_EXISTS_FAILURE_AUDIT.md`](V22_EXISTS_FAILURE_AUDIT.md))
- **Part 4** [`scripts/train_v22_general_models.py`] — four NEW single
  models; runtimes recorded in `data/models/v22_general_manifest.json`.

## Headline (v18 broad-core, 48 theorems)

Mean metrics, `abstract` rerank config (the v21 canonical), plus the
rerank-invariant `pass@10` (= "does any top-10 candidate verify"):

| system | pool / arch | p@1 | p@5 | p@10 | MRR | no_verify |
|---|---|---:|---:|---:|---:|---:|
| v20_broad_plus | v20 / base | 0.625 | 0.729 | 0.729 | 0.666 | 13 |
| v21_single_retrain | v21 / base | 0.667 | 0.729 | 0.750 | 0.698 | 12 |
| v21_capacity | v21 / 128·192 | 0.708 | 0.771 | 0.771 | 0.734 | 11 |
| **v21_routed (the bar)** | router | 0.688 | 0.792 | 0.792 | 0.728 | 10 |
| **v22_general_plus_exists** | A_mixed / base | **0.729** | **0.812** | **0.833** | **0.774** | **8** |
| v22_general_balanced | B_oversample / base | 0.625 | 0.792 | 0.792 | 0.705 | 10 |
| v22_general_large | A_mixed / 128·192 | 0.667 | 0.771 | 0.812 | 0.725 | 9 |
| v22_general_balanced_large | B_oversample / 128·192 | 0.625 | 0.792 | 0.792 | 0.700 | 10 |

Per-category pass@5 (`abstract`):

| category | v21_routed | plus_exists | balanced | large | balanced_large |
|---|---:|---:|---:|---:|---:|
| forall | 1.000 | **1.000** | 1.000 | 1.000 | 1.000 |
| implication | 1.000 | **1.000** | 1.000 | 1.000 | 0.833 |
| bool | 1.000 | **1.000** | 1.000 | 1.000 | 1.000 |
| equality_rewrite | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| conjunction | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 |
| list | 0.800 | 0.800 | 0.800 | 0.600 | 0.800 |
| disjunction | 0.600 | 0.600 | 0.600 | 0.600 | 0.400 |
| nat_succ | 0.600 | 0.600 | 0.400 | 0.400 | 0.600 |
| negation | 0.800 | 0.600 \* | 0.600 | 0.600 | 0.600 |
| **exists** | 0.250 | **0.750** | 0.750 | 0.750 | **1.000** |

\* negation = **0.800 under `raw` beam order** for `plus_exists` (pass@10
confirms the verifying candidate is in the beam); the 0.600 is an
`abstract`-reranker mis-ordering, and it is 0.600 for `v21_single_retrain`
too — i.e. **not caused by the exists corpus**. In `raw` order
`plus_exists` mean pass@5 = **0.833**.

**Targets — met:**
- single model matches/beats v21 routed: pass@5 **0.812 ≥ 0.792**, pass@10
  **0.833 > 0.792**, MRR **0.774 > 0.728** ✓
- forall preserved at **1.000** ✓ · implication **1.000** ✓ · bool **1.000** ✓
- exists lifted **0.250 → 0.750** (+0.500) ✓
- no category tradeoff vs the same-recipe single retrain: `+exists`
  dropped **zero** categories (exists +0.75, disjunction +0.20) ✓

## What moved the needle — and what didn't

- **The exists corpus is the lever.** Adding 471 verified exists rows to
  the v21 pool (same base model) is the entire win: exists 0.00→0.75 vs
  `v21_single_retrain` (0.25→0.75 vs routed) and disjunction +0.20, with
  **no regression** anywhere.
- **Oversampling did NOT help** (`balanced` 0.792 < `plus_exists` 0.812;
  it *hurt* nat_succ −0.20). **Data imbalance was not the bottleneck.**
- **Capacity did NOT help** (`large` 0.771; it *hurt* nat_succ and list
  −0.20 each). **The base model was not capacity-bound.**
- **Pushing the minority harder re-introduces a tradeoff:**
  `balanced_large` reaches exists = **1.000** but breaks implication
  (1.0→0.833) and disjunction (0.6→0.4). `plus_exists` is the sweet spot.

So the residual gap routing was papering over was a **data-shape
coverage gap** (missing exists/forall proof shapes), not capacity,
imbalance, or category interference.
([`V22_CATEGORY_INTERFERENCE_ANALYSIS.md`](V22_CATEGORY_INTERFERENCE_ANALYSIS.md))

## Best-system selection (Part 7)

- **`v22_best_single` = `v22_general_plus_exists`** — one set of weights,
  no router: pass@5 0.812 (`abstract`) / 0.833 (`raw`), pass@10 0.833,
  forall=implication=bool=1.0, exists 0.75.
- **`v22_best_routed` = v21 routed** — pass@5 0.792.
- **Selection: the single model.** It matches/beats the routed system on
  every mean metric and recovers exists, from one decoder. **Routing is
  not necessary** on the broad-core benchmark once the exists (v22) and
  forall (v21) shapes are both present in one training pool — the v21
  routing win was a proxy for that missing coverage. Routing remains a
  cheap, zero-collateral *option* (and is still the safer choice if one
  must guarantee a specific category like negation under a fixed
  reranker), but it is no longer required for the headline.

## Conclusion (RQ1–RQ4)

1. **Can a single model match/exceed v21 routing?** **Yes.** But the
   winning single model is the **base** one with the exists corpus, not
   the larger one — `plus_exists` (base) beats routing; `large` does not
   beat `plus_exists`.
2. **Is the gap capacity, imbalance, or interference?** **None of those —
   it was a data-shape coverage gap.** Capacity and oversampling both
   failed to help (and hurt minor categories); adding the missing exists
   shapes fixed it with zero interference.
3. **Can targeted exists data improve exists without harming
   forall/implication/bool?** **Yes** — exists 0.25→0.75, those three held
   at 1.000, zero drops vs the same-recipe single retrain.
4. **If routing still won, could we justify it?** It didn't win — but
   routing stays a legitimate, cheap engineering option; the honest point
   is that **it is no longer required**, and we do not hide the one
   reranker-sensitive residual (negation under `abstract`).

## Honesty contract

- v18 / v20 / v21 metrics on disk are **unchanged**; v22 publishes at
  parallel `data/baselines/v22_*` paths.
- v21's routed result (0.792) is **not retconned** — it is the explicit
  bar v22 is measured against.
- Every exists-corpus row is lean-cli verified; 0 v18 name/triple leak.
- **No `state_after`** (tokeniser input excludes it; corpus has no such
  field). **No manual oracle** (the exists candidates are corpus targets,
  never decoder outputs). **No Mathlib.** **No revival of the invalidated
  v10 metrics.** **Not full theorem proving** — a templated 48-theorem
  core-Lean benchmark, directional not statistically powered.
- pass@10 is rerank-invariant (it is "does any of the 10 candidates
  verify"); pass@1/5 depend on the reranker, so both `raw` and `abstract`
  orderings are reported and tradeoffs are not hidden.
