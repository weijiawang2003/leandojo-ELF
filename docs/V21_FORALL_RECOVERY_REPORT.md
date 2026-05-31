# V21 forall recovery report

**Mission**: recover the v20 forall regression (0.667 → 0.000) while
preserving the v20 implication/bool gains (both 1.000). **Outcome**:
forall recovered to **1.000** via category-based **model routing**,
with **zero collateral** to any other category and the mean pass@5
lifted to **0.792** (+0.063 over v20).

## Research questions answered

1. **Why did forall regress under v20?** A single-model capacity /
   distribution tradeoff. The v20 broad-plus model's beam on forall
   goals contained **zero** `exact h <arg>` instantiation candidates —
   the 948 implication+bool rows (45 % of the 2,099-row pool) shifted
   its forall-goal output onto destructuring shapes (`exact h with
   ⟨n, hp⟩`). The schema was **absent from generation**, not demoted,
   so no reranker could recover it.
   ([`V21_FORALL_REGRESSION_AUDIT.md`](V21_FORALL_REGRESSION_AUDIT.md))
2. **Can we recover forall without losing implication/bool?** Yes —
   all three candidate fixes recover forall to 1.000 and keep
   implication+bool at 1.000.
3. **Is the right fix corpus, capacity, or routing?** **Routing.** It
   is the only fix with zero collateral damage.
   ([`V21_CAPACITY_TRADEOFF_ANALYSIS.md`](V21_CAPACITY_TRADEOFF_ANALYSIS.md))

## Headline (v18 broad-core, best rerank config = `abstract`)

| config | mean pass@1 | mean pass@5 | mean pass@10 | forall | implication | bool |
|---|---:|---:|---:|---:|---:|---:|
| v18 broad-only | 0.500 | 0.583 | 0.604 | 0.667 | 0.000 | 0.000 |
| v20 broad-plus | 0.625 | 0.729 | 0.729 | **0.000** | 1.000 | 1.000 |
| v21 B single-retrain | 0.667 | 0.729 | 0.750 | 1.000 | 1.000 | 1.000 |
| v21 D higher-capacity | 0.708 | 0.771 | 0.771 | 1.000 | 1.000 | 1.000 |
| **v21 C routed** | **0.688** | **0.792** | **0.792** | **1.000** | **1.000** | **1.000** |

**Targets — all met:**
- forall pass@5 0.000 → **1.000** (target ≥ 0.667, ideal 1.000) ✓✓
- implication pass@5 preserved at **1.000** ✓
- bool pass@5 preserved at **1.000** ✓
- mean pass@5 improved 0.729 → **0.792** ✓
- no unresolved-placeholder cliff (count = 0 in every config) ✓

## Per-category pass@5 — routing has zero collateral

| category | v20 | v21 routed (C) | Δ |
|---|---:|---:|---:|
| forall | 0.000 | **1.000** | **+1.000** |
| implication | 1.000 | 1.000 | 0.000 |
| bool | 1.000 | 1.000 | 0.000 |
| equality_rewrite | 1.000 | 1.000 | 0.000 |
| conjunction | 0.833 | 0.833 | 0.000 |
| disjunction | 0.600 | 0.600 | 0.000 |
| negation | 0.800 | 0.800 | 0.000 |
| exists | 0.250 | 0.250 | 0.000 |
| nat_succ | 0.600 | 0.600 | 0.000 |
| list | 0.800 | 0.800 | 0.000 |

Every non-forall category is **identical** to v20 — the routed broad
model *is* the v20 model, so they cannot regress. Contrast config B
(single retrain), which fixed forall but broke disjunction
(0.60→0.40), negation (0.80→0.60), and exists (0.25→0.00): the
capacity tradeoff merely relocated.

## What was built

### Part 1 — regression audit
[`scripts/audit_v21_forall_regression.py`](../scripts/audit_v21_forall_regression.py).
Classified 2 of 3 forall theorems as `schema_lost` (the third,
`forall_inst_compose`, was never solved in v18). Confirmed the
verifying schema (`exact h 7`, `exact h 3`) present in v18's beam is
absent from v20's.

### Part 2 — forall corpus
[`scripts/generate_v21_forall_corpus.py`](../scripts/generate_v21_forall_corpus.py).
**677 / 680** lean-cli-verified across 432 theorems, 5 families
(forall_inst_literal 200, forall_inst_var 200, forall_prop 40,
forall_arrow_inst 48, forall_inst_compose 189). 0 leakage drops (the 3
misses were transient WSL timeouts on valid compose candidates with
verified siblings). Capital predicate names (`P`/`Q`) keep it disjoint
from v18's lowercase `p`/`q`.

### Part 3 — training configs
[`scripts/build_v21_training_configs.py`](../scripts/build_v21_training_configs.py).
Config B pool = v20 pool + v21 forall (2,776 rows). Config C
forall-specialist pool = forall-only (689 rows). 0 v18 name leak; all
guards pass.

### Part 5 — model router
[`src/mini_elf_lean/v21_model_router.py`](../src/mini_elf_lean/v21_model_router.py).
A deterministic switch: `forall` / `instantiate_forall` → forall
specialist; implication / bool / everything else → v20 broad-plus;
fallback to broad if the specialist is unavailable. An **engineering**
layer — it selects a generator, never injects a proof template, reads
no `state_after`, uses no manual oracle.

## Honesty contract

- v18 and v20 metrics on disk are **unchanged** (pinned by
  `tests/test_v21_eval.py`); v21 publishes at parallel
  `data/baselines/v21_*` paths.
- v20's forall regression (0.000) is **not retconned** — it is pinned
  and explained; v21 is a separate, parallel recovery.
- All corpus rows lean-cli verified; 0 v18 name-leak.
- No `state_after`, no manual oracle, no Mathlib (the forall
  regression is now understood, but the brief defers Mathlib and we
  honor that).
- Not full theorem proving — templated 48-theorem core-Lean benchmark.
- Model **routing is an engineering solution, not theorem reasoning.**

## The honest caveat on routing

Routing's zero-collateral guarantee comes *because* the broad model is
frozen at v20 — it is composition of specialists, not a single model
that has learned to do everything. That is exactly the right tool for
a category-separable benchmark, but it is **not** evidence of a single
model generalizing across proof shapes. A genuinely general model
(capacity config D points the way: it recovered the most categories
from a single set of weights) remains the harder open problem. v21
buys the metric honestly via engineering; it does not claim the
representational win.
