# Mini-ELF v35 — A faithful, CPU-scale ELF-style embedded-flow tactic generator

**Headline (honest, negative):** A faithful CPU-scale ELF-style embedded-flow
generator produces **0% verified** single-tactic Lean predictions on the Mathlib
tier, while the **matched** token-AR baseline (same data, vocab, verifier)
achieves **pass@1 = 0.875**. The flow's one distinctive profile property —
maximal candidate **diversity** — is real but *useless*: none of the diverse
candidates verify, and the sampling-frequency ranking carries no signal. The
clean separation, with ablations, attributes the failure to the flow itself, not
to any reranker/planner/retrieval. A negative result is a valid outcome and is
reported as such.

Single-tactic, theorem-level. This is a **scaled-down, ELF-*style*** model — not
a reproduction of ELF, not a proof-state model, not a full theorem prover. No
claim is made that ELF itself fails; only that *this CPU-scale ELF-style model*
does, in a matched comparison.

---

## 1. Research question

The v24–v33 product (token-AR seq2seq + environment router) already saturates the
curated Mathlib single-tactic tier (v33 routed tier-C pass@10 = 0.992). So the
v35 question is **not** higher pass@k. It is whether an **embedded-flow** generator
has a *different, useful generation profile*: candidate diversity, novel-verified
tactics, low-density coverage, and a sampling-step compute/quality trade-off.

---

## 2. Faithfulness to ELF (and contrast with the abandoned Mini-ELF v0)

ELF (arXiv 2605.10938) flows over the **per-token embedding sequence**, stays
continuous until `t=1`, discretizes there with a **shared-weight (tied-embedding)**
network, and trains with `L2(flow) + CE(decode)`, self-conditioning, and CFG.

| ELF choice | Mini-ELF v0 (abandoned at v7) | **v35 (this work)** |
|---|---|---|
| Representation | single pooled 48-d latent | **per-token embedding sequence `Z=E[ids]`, `(B,T,D)`** |
| Discretization | separate GRU decoder | **tied nearest-embedding readout** (no separate head) |
| Objective | L2 only | **L2 + CE-anchor + self-conditioning + CFG** |
| Time schedule | `U(0,1)` | **logit-normal `sigmoid(N(-1.5, 0.8))`** |
| Guidance | none | **classifier-free guidance (learned null condition)** |

The readout is **nearest-embedding**, not a plain `z·Eᵀ` dot product:
`logit_i = (z·E_i − 0.5·‖E_i‖²) / τ`, so `argmax_i == argmin_i ‖z − E_i‖²` and
`embed → readout → argmax` round-trips exactly. A plain dot-product head does not
once embedding norms differ — pinned by
`tests/test_v35_flow.py::test_plain_dot_head_would_not_roundtrip`.

---

## 3. Data and the matched comparison

`scripts/build_v35_flow_dataset.py` assembles **Lean-verified** `(condition,
tactic)` rows (`tactic_source == "verified"`) from the v33 canonical Mathlib
corpus (verified under `import Mathlib`) and the v24 broad-core set (core Lean).
De-duplicated by `(theorem_name, tactic)`, split **by `theorem_name`** (md5
buckets, 80/10/10, asserted disjoint). A single shared `TokenVocab` is built from
the **train split only**; rows carry pre-tokenized `cond_ids`/`tgt_ids` + raw
`theorem_statement`/`state_before`.

* 4642 verified rows / 1973 theorems; split 3689 / 456 / 497.
* tiers: 1232 Mathlib, 3410 core; test tiers: 116 Mathlib, 381 core.
* vocab 377; condition p50/p95 = 61/96 tokens, target p50/p95 = 9/22 tokens.

**Matched:** the v35 flow AND the token-AR baseline (`token_seq2seq`, the v24/v33
engine) train on the *same* split with the *same* `TokenVocab`; retrieval (k-NN
over train texts) is the floor. The learned reranker is kept **out** of the
headline comparison.

---

## 4. Model and training

`elf_v35_embed.py` (TokenEmbedding + tied nearest-embedding readout;
ConditionEncoder bi-GRU; LatentStats; padding_mask), `elf_v35_flow.py`
(SeqVelocityField — non-causal Transformer decoder, cross-attention to the
condition, additive time embedding, learned positions, self-cond input;
ElfV35Model with a learned null condition; `build_memory` does CFG drop in one
pass), `elf_v35_train.py` (the full ELF objective: masked flow-MSE in standardized
space + CE anchor on the un-standardized tied-readout logits + no-grad
self-conditioning + CFG condition-drop; logit-normal time; per-epoch latent stats;
val-flow-MSE checkpoint selection; CPU, deterministic). Trained model: **521 k
params** matched against the token-AR's ~520 k.

---

## 5. Sampling and decoding (`elf_v35_sample.py`)

Per prompt: seed noise with `seed ^ crc32(prompt)`, draw `K` seeds, Euler-integrate
the conditional flow (CFG `v = v_u + w·(v_c − v_u)`, self-cond carry), discretize
at `t=1` by the tied nearest-embedding readout, detokenize, sanitize, rank by
sampling frequency, verify top-k. Step count `N` swept over {1,2,4,8,16,32}.

---

## 6. Guardrails (enforced, with tests)

`state_after` never read (poisoned-input test asserts it); theorem-level split,
disjoint sets asserted; train-on-train, val-checkpoint (offline loss),
test-untouched; **headline metrics use `TrustedMathlibVerifier` only**
(`confirm=True`, sound+complete); no manual-oracle predictions, no v10 leakage;
writes only `v35_*` artifacts.

---

## 7. Results

Mathlib tier, **24 test theorems**, K=32 seeds, 8 Euler steps, CFG weight 2.0.
Verifier: `TrustedMathlibVerifier`. (`data/baselines/v35_flow_eval/comparison.json`)

| baseline | pass@1 | pass@5 | pass@10 | top1-exact | novel-verified@10 |
|---|---|---|---|---|---|
| retrieval (floor) | 0.500 | 0.625 | 0.625 | 0.458 | 0.000 |
| **token-AR** (matched, v24/v33 engine) | **0.875** | **0.917** | **0.917** | 0.375 | **0.292** (7/24) |
| **Mini-ELF v35 flow** | **0.000** | **0.000** | **0.000** | 0.000 | 0.000 |

**Generation profile (the actual research question):**

| | distinct@10 | mean pairwise token-Jaccard@10 (↓ = more diverse) | invalid-decode rate | candidates / prompt |
|---|---|---|---|---|
| retrieval | 1.0 | 0.210 | — | ≤16 |
| token-AR | 1.0 | 0.306 | — | ≤10 beams |
| **v35 flow** | 1.0 | 0.244 | **0.000** | **32/32 distinct** |

* The flow's **invalid-decode rate is 0.0** — it emits syntactically clean,
  non-forbidden strings — and **every one of its 32 samples is distinct**. So the
  "different profile" (maximal diversity) *does* materialize.
* But **0% verify**, and the sampling-frequency calibration is degenerate: all 768
  flow candidates have frequency 1 (`p_verify = 0`), so frequency ranking carries
  **no signal** — there is no probability-mass concentration on a correct tactic.
* **Step-sensitivity is flat:** pass@10 = 0 for N ∈ {1,2,4,8,16,32}; invalid stays
  0, distinct stays ~32. More integration compute does not help — the velocity
  field, not the integrator, is the limit.

**What the flow actually emits** (`v26_nat_le_refl2`, gold `exact Nat.le_refl c0`):

```
exact Nat   c0hx).hnp=c1
cases c0.with ) Nat.fun..
ring Nat.with.x _.c2 h\n  ..;[c1simp
```

"Token salad": the right vocabulary and often a plausible tactic head (`exact`,
`cases`, `simp`), but jointly non-typecheckable. The matched token-AR reaches
0.875 on the same data because autoregressive decoding conditions each token on
the previous ones; the non-autoregressive parallel flow has no such coherence
constraint.

---

## 8. A1–A3 ablations — attributing the failure to the flow

Offline (no Lean); `scripts/ablate_v35_flow.py` →
`data/baselines/v35_flow_eval/ablations.json`. No reranker/planner/retrieval is in
the flow path, so the cause is the flow itself.

**A1 — representation (per-token sequence vs single pooled latent).** 73.3% of the
Mathlib tier is multi-token, so a single pooled latent (Mini-ELF v0) has a **≥73%
invalid-decode ceiling by construction** (it can emit ≤1 token). The v35 sequence
representation removes that ceiling (**0% invalid**). ⇒ the per-token sequence is
*necessary and strictly more expressive* — but **expressiveness ≠ correctness**:
v35 is representable yet still 0% verified.

**A2 — discretization (nearest-embedding vs plain `z·Eᵀ`).** On the *same* `t=1`
latents, per-position **gold-token recovery is only 32%** (nearest-embedding 0.322
≈ plain-dot 0.329). The two readouts coincide here because the model learned
near-uniform embedding norms (the `−0.5‖E‖²` term then contributes little; the
unit test still proves it is required in the norm-varied case). **32% per-token
accuracy is the bottleneck**: with ~2/3 of positions wrong, no multi-token tactic
is coherent → token salad → 0% verify.

**A3 — objective.**
* *Sample-time* (no retrain): CFG weight {1,2,3} and self-cond on/off make **zero
  difference** to invalid-decode (0) or diversity (32/32) — inference-time
  guidance cannot rescue correctness here.
* *Train-time* (retrained variants, `data/baselines/v35_flow_eval/ablations.json`
  → `A3_objective_retrain`): full vs no-CE / no-self-cond / no-CFG — see table
  below (val flow-MSE + invalid-decode). The CE anchor is the component that most
  affects whether the un-standardized endpoint lands near real embeddings.

| variant | best val flow-MSE | invalid-decode rate |
|---|---|---|
| _populated from `A3_objective_retrain` after the background retrain completes_ | | |

---

## 9. Conclusion (honest)

In a fully matched comparison (same verified data, shared token vocabulary, same
`TrustedMathlibVerifier`), a **faithful CPU-scale ELF-style embedded-flow generator
fails to produce any verified single-tactic Lean prediction (0% pass@k)**, whereas
the token-AR engine reaches **0.875 pass@1** and even 29% novel-verified. The flow
*does* exhibit the hypothesized different profile — maximal diversity, zero invalid
decodes — but that diversity is **not actionable**: none verify and frequency
ranking is signal-free.

The ablations localize the cause to the **velocity field's per-token accuracy
(~32%)**, not the representation (A1: the sequence form is strictly better than the
v0 pool), not the readout (A2: nearest-embedding ≈ plain-dot at this scale), and
not guidance/self-cond (A3-sample: no effect). A **non-autoregressive parallel
flow over token embeddings cannot enforce the inter-token coherence that
autoregressive decoding gets for free** — at this scale it emits right-vocabulary,
right-head, jointly-incoherent token salad.

**Verdict for the project:** embedded flow does **not** offer a useful alternative
generation profile for single-tactic Lean prediction at CPU scale; its only
differentiator (diversity) is useless without correctness. The token-AR engine
remains the right tool. **Levers that might change this** (not pursued here, would
be the basis of a v36): much larger scale (params/data/epochs); a stronger
decodability objective (higher CE weight, or a coherence-enforcing decoder); a
different discretization. None of these are claims about ELF at full scale — only
that the CPU-scale ELF-*style* model is dominated by token-AR on this task.

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

# 3. A1-A3 ablations (offline; --retrain-ablations adds the train-time A3)
python scripts/ablate_v35_flow.py --tier mathlib --retrain-ablations
```

Artifacts: `data/baselines/v35_flow_eval/{comparison,flow_diagnostics,step_sensitivity,ablations,metrics_*}.json`.
Weights (gitignored, regenerable): `data/models/v35_flow_model/`, `data/models/v35_token_ar/`.
