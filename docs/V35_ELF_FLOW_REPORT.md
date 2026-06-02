# Mini-ELF v35 — A faithful, CPU-scale ELF-style embedded-flow tactic generator

**Status:** results pending the first full verified run (see §8/§9 — populated
from `data/baselines/v35_flow_eval/`). Methodology, faithfulness mapping, and the
ablation design below are final.

Single-tactic, theorem-level. This is a **scaled-down, ELF-*style*** model — not
a reproduction of ELF, not a proof-state model, and not a full theorem prover.

---

## 1. Research question

The v24–v33 product (a token-AR seq2seq + an environment router) already saturates
the curated Mathlib single-tactic tier (v33 routed tier-C pass@10 = 0.992). So the
question for v35 is **not** higher pass@k. It is whether an **embedded-flow**
generator has a *different, useful generation profile*:

* candidate **diversity** (distinct@k, self-BLEU proxy),
* **novel-but-verified** tactics (verified strings absent from the train set),
* low-density-family coverage,
* a **sampling-step compute/quality trade-off** that AR decoding does not expose.

**A clean negative result is a valid outcome** and is reported as such.

---

## 2. Faithfulness to ELF (and contrast with the abandoned Mini-ELF v0)

ELF (arXiv 2605.10938) flows over the **per-token embedding sequence**, stays
continuous until `t=1`, and discretizes there with a **shared-weight
(tied-embedding)** network; it is trained with `L2(flow) + CE(decode)`,
self-conditioning, and classifier-free guidance.

| ELF choice | Mini-ELF v0 (abandoned at v7) | **v35 (this work)** |
|---|---|---|
| Representation | single pooled 48-d latent | **per-token embedding sequence `Z=E[ids]`, `(B,T,D)`** |
| Discretization | separate GRU decoder | **tied nearest-embedding readout** (no separate head) |
| Objective | L2 only | **L2 + CE-anchor + self-conditioning + CFG** |
| Time schedule | `U(0,1)` | **logit-normal `sigmoid(N(-1.5, 0.8))`** |
| Guidance | none | **classifier-free guidance (learned null condition)** |

The single most important fix: the readout is **nearest-embedding**, not a plain
`z·Eᵀ` dot product. With

```
logit_i = (z·E_i − 0.5·‖E_i‖²) / τ ,
```

`argmax_i logit_i == argmin_i ‖z − E_i‖²` (because `‖z‖²` is constant across `i`),
so `embed → readout → argmax` round-trips the embedded token exactly. A plain
dot-product head does **not** have this property once embedding norms differ —
it is a real bug, and `tests/test_v35_flow.py::test_plain_dot_head_would_not_roundtrip`
pins both directions (tied readout recovers the ids; plain dot does not).

---

## 3. Data and the matched comparison

`scripts/build_v35_flow_dataset.py` assembles **Lean-verified** `(condition,
tactic)` rows from two pools, all `tactic_source == "verified"`:

* **Mathlib tier-C** — the v33 canonical specialist corpus
  (`v33_general_residual_train_rows.jsonl` + `val_rows.jsonl`); the exact data the
  v24/v33 token-AR engine trained on. Verified under `import Mathlib`.
* **Core** — `v24_broad_plus_residual/train_rows.jsonl`; verified under core Lean.

Rows are de-duplicated by `(theorem_name, tactic)` and split **by `theorem_name`**
(deterministic md5 buckets, 80/10/10). The builder asserts the train/val/test
theorem sets are pairwise disjoint, and emits a single shared `TokenVocab` built
from the **train split only** plus pre-tokenized `cond_ids` / `tgt_ids` and the raw
`theorem_statement` / `state_before` (Lean needs the raw text). Dataset shape:

* 4642 verified rows / 1973 theorems; split 3689 / 456 / 497 rows.
* tiers: 1232 Mathlib, 3410 core; test tiers: 116 Mathlib, 381 core.
* vocab 377; condition length p50/p95 = 61/96 tokens, target p50/p95 = 9/22 tokens.

**Matched comparison.** Both the v35 flow model and the token-AR baseline (the
v24/v33 engine, `token_seq2seq`) are trained on the *same* train/val split with the
*same* `TokenVocab`, so the comparison is matched at the token level. A retrieval
baseline (k-NN over train texts) is the floor. The learned reranker is kept **out**
of the headline flow-vs-AR comparison (§6 of the brief).

---

## 4. Model and training

* `elf_v35_embed.py` — `TokenEmbedding` (table + tied nearest-embedding readout),
  `ConditionEncoder` (bi-GRU → per-step memory + pad mask; packed so pad never
  flows backward into real tokens), `LatentStats` + `compute_latent_stats`,
  `padding_mask`.
* `elf_v35_flow.py` — `SeqVelocityField` (non-causal Transformer decoder over the
  target positions, cross-attention to the condition memory, additive time
  embedding, learned positional embeddings, self-conditioning input) and
  `ElfV35Model` (learned **null condition**; `build_memory` implements the CFG
  condition-drop in a single pass by masking the real condition steps).
* `elf_v35_train.py` — the full ELF objective:
  * standardize `Z1 = E[ids]` with per-dim train stats; `Z0 ~ N(0,I)`;
    `z_t = (1−t)Z0 + tZ1`; target `v = Z1 − Z0`; `L_fm = masked-MSE(v_θ, v)` over
    non-pad target positions;
  * **CE anchor** (prob ≈0.2): `Ẑ1 = z_t + (1−t)·v_θ`, *un-standardized* before the
    readout (`E` lives in raw embedding space), CE on the nearest-embedding logits
    ignoring pad;
  * **self-conditioning** (prob ≈0.5): a no-grad pass → detached `Ẑ1` fed back as
    the field's self-cond input;
  * **CFG** (`p_uncond ≈0.1`): condition dropped to the learned null;
  * **time** logit-normal `t = sigmoid(N(-1.5, 0.8))`.

  Per-dim latent stats are recomputed from the (learned) embedding after each
  epoch; the stats matching the **selected checkpoint** are saved, so sampling
  standardizes with exactly the stats the chosen weights trained against.
  Checkpoint selection is by an **offline** validation flow-MSE (no Lean). CPU,
  deterministic (seeded). Target capacity 0.5–2 M params (`D=128`, 3 layers).

---

## 5. Sampling and decoding (`elf_v35_sample.py`)

Per prompt: seed the noise generator with `seed ^ crc32(prompt)` (reproducible yet
prompt-diverse), draw `K` seeds, integrate `dz/dt = v_θ` with **Euler** (ODE; an
optional **SDE** churn variant exists), apply **classifier-free guidance**
(`v = v_u + w·(v_c − v_u)` from cond/uncond memories built once) and
**self-conditioning** (carry the previous step's clean estimate), then **discretize
at `t=1` by the tied nearest-embedding readout**. Decoded ids are detokenized,
sanitized (`sanitize_candidate_list`), ranked by **sampling frequency**, and the
top-k are verified. `MiniElfV35Baseline` plugs into `baseline_eval.evaluate` and
records per-prompt decode diagnostics. The step count `N` is swept over
{1,2,4,8,16,32} for the step-sensitivity curve.

---

## 6. Guardrails (enforced, with tests where possible)

* **`state_after` is never read or predicted** — condition is statement +
  `state_before` only. `tests/test_v35_dataset_no_leakage.py` poisons the input
  with a `state_after` field and asserts it never appears in any emitted row and
  that `cond_ids == encode_source(statement\nstate_before)`.
* **Theorem-level split, no leakage** — split by `theorem_name`; train/val/test
  theorem sets asserted disjoint (builder + test).
* **Train on train only; checkpoint on val (offline loss); test untouched.**
* **Headline metrics use the `TrustedMathlibVerifier` only** (`confirm=True`,
  sound + complete) — never the naive batched verifier.
* **No manual-oracle rows as model predictions; no v10 leakage data.**
* **Writes only `v35_*` artifacts**; never overwrites v24 broad-core or v33
  specialist weights/configs.

---

## 8. Results — pass@k and generation profile

> Populated from `data/baselines/v35_flow_eval/comparison.json` after the first
> full verified run (Mathlib tier, 24 test theorems, K=32 seeds, 8 Euler steps,
> CFG weight 2.0; flow and token-AR matched on the same split + vocab).

_(pending)_

---

## 9. A1–A3 ablations — attributing the effect to the flow

> Populated from `data/baselines/v35_flow_eval/ablations.json`
> (`scripts/ablate_v35_flow.py`). All offline (no Lean); these isolate the ELF
> components. No reranker/planner/retrieval is in the v35 flow path, so any
> profile difference is attributable to the flow itself.

* **A1 — representation** (per-token sequence vs single pooled latent): _(pending)_
* **A2 — discretization** (nearest-embedding vs plain `z·Eᵀ`): _(pending)_
* **A3 — objective** (full vs no-CE / no-self-cond / no-CFG): _(pending)_

---

## 10. Reproduction

```bash
# 0. dataset (regenerates data/processed/v35_elf_flow/ from verified corpora)
python scripts/build_v35_flow_dataset.py

# 1. unit tests (no Lean)
pytest tests/test_v35_flow.py tests/test_v35_dataset_no_leakage.py -q

# 2. full verified comparison (trains flow + matched token-AR, then Lean pass@k)
python scripts/evaluate_v35_flow.py --tier mathlib --max-test 24 \
    --flow-epochs 50 --ar-epochs 40 --n-samples 32 --steps 8 --cfg-weight 2.0 \
    --step-sweep

# 3. A1-A3 ablations (offline; add --retrain-ablations for the train-time A3)
python scripts/ablate_v35_flow.py --tier mathlib
```
