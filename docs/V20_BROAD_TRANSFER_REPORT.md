# V20 broad-transfer report

This document records how v20's broad-synthetic-plus model — same
v14/v18 token-seq2seq architecture, trained on the union of
v11+v16+v17+`v20_implication`+`v20_bool` after v18 leakage guards —
transfers to the v18 broad-core benchmark.

The exact metric values are pinned at
[`data/baselines/v20_broad_plus_eval/summary.json`](../data/baselines/v20_broad_plus_eval/summary.json)
and per-config under `data/baselines/v20_broad_plus_eval/<config>/`.
Test pins live at [`tests/test_v20_eval.py`](../tests/test_v20_eval.py).

## What v20 changes versus v18

* **Training corpus**: v18 broad gathered v11+v16+v17 (~1,151 rows).
  v20 adds `v20_implication_corpus` (266 theorems × ~3 proofs) and
  `v20_bool_corpus` (77 theorems × ~3 proofs) — both lean-cli
  verified, both v18-leakage-guarded.
* **Generator**: identical v14/v18 token seq2seq (96 embed, 128
  hidden, beam 10, seed 0, 20 epochs CPU). Pure raw-name
  generation. No placeholder/abstract output anywhere.
* **Reranker**: six configs published. The brief asks specifically
  about **abstract** (Part 6) and **policy_abstract** in addition
  to the v15-pattern raw / rule / learned / policy.
* **Pattern bag**: built from the v20 broad-plus training rows by
  abstracting each verified tactic against its own `state_before`.
  Stored at
  `data/baselines/v20_broad_plus_eval/pattern_bag.json`.

## v18 → v19 → v20 baseline grid

Best config is the **abstract** / **policy_abstract** ranker-time-
abstraction config (identical pass@k; `policy_abstract` has a hair
higher MRR). Two v20 numbers are reported: the **raw eval** (first
lean-cli pass, depressed by spurious WSL subprocess timeouts) and the
**timeout-corrected** eval (after a warm rerun of the 35 timed-out
candidate pairs — see "Evaluation-reliability correction" below).

| metric (best config) | v18 broad-only | v19 abstract-only | v19 ensemble | v20 raw-eval | **v20 corrected** |
|---|---:|---:|---:|---:|---:|
| pass@1 | 0.500 | 0.146 | 0.146 | 0.562 | **0.625** |
| pass@5 | 0.583 | 0.208 | 0.312 | 0.688 | **0.729** |
| pass@10 | 0.604 | 0.271 | 0.438 | 0.688 | **0.729** |

**The pass@10 lift (0.604 → 0.729) proves a real generator change** —
reranking can only reorder a fixed candidate set, so it cannot move
pass@10. The corpus addition put new verifying shapes into the beam.

Per-category pass@5 (best config, timeout-corrected):

| category | n | v18 broad-only | v19 ensemble | **v20 corrected** | gap from v18 |
|---|---:|---:|---:|---:|---:|
| implication | 6 | 0.000 | 0.000 | **1.000** | **+1.000** |
| bool | 3 | 0.000 | 0.000 | **1.000** | **+1.000** |
| conjunction | 6 | 0.833 | 0.167 | 0.833 | 0.000 |
| disjunction | 5 | 0.600 | 0.000 | 0.600 | 0.000 |
| negation | 5 | 0.800 | 0.400 | 0.800 | 0.000 |
| equality_rewrite | 6 | 1.000 | 0.833 | 1.000 | 0.000 |
| exists | 4 | 0.250 | 0.250 | 0.250 | 0.000 |
| forall | 3 | 0.667 | 0.667 | **0.000** | **−0.667** |
| nat_succ | 5 | 0.600 | 0.600 | 0.600 | 0.000 |
| list | 5 | 0.800 | 0.800 | 0.800 | 0.000 |

**Both primary targets hit and exceeded**: implication 0.000 → 1.000
(target was ≥ 0.500), bool 0.000 → 1.000. Every non-targeted category
is **preserved exactly** except **forall, which regressed 0.667 →
0.000** — the one honest negative (see below).

### The forall regression (honest negative)

v18's broad-synthetic *panel* included a dedicated `forall_inst` v16
family model. v20 collapses to a **single** broad-plus model whose
training pool is now ~36 % implication rows (759 / 2099). That
rebalancing diluted the forall-instantiation capacity: the v20 model
emits malformed forall candidates such as `exact h with ⟨n, hp⟩`,
`exact h hp hq` (wrong arity), and `exact h ⟨ha, hb⟩` (wrong shape)
— none of which verify. This is a **single-model capacity tradeoff**,
not a timeout artifact (the failures are `type_mismatch`, confirmed in
[`V20_FAILURE_EXAMPLES.md`](V20_FAILURE_EXAMPLES.md)). v21 should
either (a) add a small forall-instantiation corpus to rebalance, or
(b) restore a per-family panel member for forall. Reported honestly;
not hidden by the headline mean.

### Evaluation-reliability correction (warm timeout rerun)

The first eval ran on a WSL instance whose `lean` subprocess
intermittently returned spurious 30 s timeouts on trivially-correct
tactics (e.g. `exact hp` on `(p : Prop) (hp : p) : p`). A focused
warm rerun ([`scripts/rerun_v20_timeouts.py`](../scripts/rerun_v20_timeouts.py))
re-verified all **35** distinct timed-out `(theorem, candidate)`
pairs with a warm verifier and a retry: **9 flipped to success**
(all genuinely-correct proofs: `exact hp`, `exact g (f a)`,
`exact hqr (hpq hp)`, `exact And.intro hp hq`, `exact h.2.2`,
`exact And.right h`, `rcases h with ⟨hp, hq⟩\n  exact ⟨hq, hp⟩`, ...),
**26 confirmed as real errors** (correctly stay failed), **0 still
timeout**. This mirrors the v13/v14 warm-rerun precedent. The
**original** `data/baselines/v20_broad_plus_eval/` metrics are left
untouched; corrected metrics publish in parallel at
`data/baselines/v20_broad_plus_eval_timeout_rerun/`. Evaluation
reliability ≠ model improvement.

## Honesty contract

* v18 metrics on disk (`data/baselines/v18_broad_only_eval/...`)
  are unchanged. Tested
  ([`test_v20_eval.py::test_v18_broad_only_metrics_unchanged`](../tests/test_v20_eval.py)).
* v19 metrics on disk are unchanged (sanity-pinned).
* All training rows are lean-cli-verified; the corpus generator
  never persists unverified candidates.
* v18 leakage guards by name + triple, both report 0 drops by
  construction.
* No `state_after` anywhere. Every metrics.json records
  `uses_state_after: false`.
* No manual oracle — manual candidates files are derived from
  lean-cli-verified outputs of the corpus generators.
* No Mathlib in environment; no Mathlib references in seeds.
* No claim of full theorem proving — the eval is on a templated
  48-theorem benchmark.

## What the abstract-pattern reranker is *not* allowed to do

The v20 brief's third research question is whether **ranker-time**
abstraction can help without placeholder generation. The reranker:

* Never emits placeholders into the output tactic. The
  reordered candidates are the raw strings the v20 model
  generated. Tested
  ([`test_abstract_pattern_reranker.py::test_output_is_raw_names_never_placeholders`](../tests/test_abstract_pattern_reranker.py)).
* Never substitutes hypothesis names. The abstraction is only
  used to compute a score.
* Builds its pattern bag only from verified training tactics.

## Read of results

1. **Implication** — moved **0.000 → 1.000** pass@5 (and 0.833 pass@1).
   The verifying top-1 candidates are exactly the canonical bare
   shapes the v20 corpus taught: `exact hp` (identity),
   `exact g (f a)` (function composition), `exact hqr (hpq hp)`
   (Prop composition). None carries a `.elim` tail — the v17
   contradiction-pattern displacement that caused v18's 0.000 is
   gone. **Exceeds the brief's ideal ≥ 0.500 target.**
2. **Bool** — moved **0.000 → 1.000** pass@5. The `cases b <;> simp`
   and explicit `cases b\n  · exact Or.inl rfl\n  · exact Or.inr rfl`
   shapes verify; the model emits them on the v18 bool rows. The
   data-shape gap (zero Bool training in v11+v16+v17) is closed.
3. **Mean pass@5** — best config (abstract, corrected) **0.729**, well
   above v18 broad-only's 0.583 (+0.146). pass@1 0.500 → 0.625,
   pass@10 0.604 → 0.729. The pass@10 lift confirms a real generator
   improvement, not a reranking artifact.
4. **Side effects** — equality_rewrite (1.000), list (0.800),
   conjunction (0.833), negation (0.800), disjunction (0.600), exists
   (0.250), nat_succ (0.600) are **all preserved exactly**. The single
   regression is **forall 0.667 → 0.000** (single-model capacity
   tradeoff, documented above).

### Ranker-time abstraction (research question 3)

The abstract-pattern reranker is the **single best config** and the
only one that lifts pass@5 above the shared 0.708 (raw/rule/learned/
policy all tie there post-correction); abstract reaches 0.729. It
lifts pass@1 from 0.500 (raw) to **0.625** by demoting candidates with
unbound identifiers (e.g. v18's `exact (hpfalse hp).elim` on a state
whose only hypothesis is `hp`) and promoting known abstract patterns.
The reorder trace
([`data/baselines/v20_abstract_reranker_comparison.json`](../data/baselines/v20_abstract_reranker_comparison.json))
shows **11 theorems' verifying candidates moved up, 3 down, 19
unchanged**. Crucially it does this **without ever emitting a
placeholder** — sidestepping v19's unresolved-placeholder cliff
(`unresolved_placeholder` count = 0 in every v20 error taxonomy).
This is the v20 answer to "can ranker-time abstraction improve
selection without generating unresolved placeholders?": **yes.**
