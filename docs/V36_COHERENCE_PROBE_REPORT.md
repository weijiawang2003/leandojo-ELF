# Mini-ELF v36 — Is the flow's inter-token incoherence closable at CPU scale?

**Verdict (decisive negative): No.** Neither a coherence-enforcing
iterative/discrete sampler (§3) nor a scale·objective ladder (§4, including the
canonical discrete-self-conditioning fix) moves the v35 flow off its incoherence
floor. Per-token gold recovery stays pinned at **0.32–0.36** across *every* probe
— depth 3→6, width 128→256, ce_weight 0.2→4.0, epochs 50→150, continuous **and**
discrete self-conditioning, sampler steps 1→32 — and exact-sequence recovery
never exceeds **0.9%**. The verification gate did not fire, so the Lean run was
skipped by design. At CPU scale the gap is **fundamental**, not a tuning issue.

> **v37 sharpening (`docs/V37_OVERFIT_CONTROL_REPORT.md`):** the overfit control
> shows this is a **sample-efficiency limit**, not a representational one — the
> flow reproduces exact Lean-verified tactics when overfitting M=4 theorems (train
> exact-seq 0.55) but collapses to 0.00 by M=64 on its own training data. The
> held-out 0.32–0.36 floor is the average-L2 hedge of a sample-inefficient flow,
> not an architecture that "cannot represent coherence."

The single most important new fact: **flow-MSE is decoupled from coherence.** The
D=256 cells drive validation flow-MSE far *down* (0.62–0.74 vs the D=128 cells'
0.83–0.86) yet recover the *same* ~0.34 of tokens — minimizing the training
objective does not buy the discrete coherence verification needs.

Scope unchanged from v35: CPU-scale, ELF-*style*, single-tactic, theorem-level.
No full-theorem-proving or proof-state claim. v36 wrote only `v36_*` artifacts and
did not modify v35/v24/v33 weights, configs, or reports (other than a 2-line
forward-reference appended to the v35 "levers/v36" note).

---

## 1. Setup

The v35 negative result localized the flow's failure to **inter-token
incoherence**: a non-autoregressive flow recovers ~32% of gold tokens per
position and decodes to "token salad" (right vocabulary, often the right tactic
head, garbled body), so 0% verify. v36 asks whether that is closable by (a) a
better sampler or (b) scale·objective. Everything except a (skipped) gated Lean
run is **offline** (no Lean).

**Coherence metric** (`scripts/v36_coherence_probe.py`, gates everything). For the
Mathlib-tier val rows (124 theorems), using **true generation from noise**
(`elf_v35_sample.integrate` / the v36 sampler — *not* teacher forcing):

| metric | meaning |
|---|---|
| `per_token_gold_recovery` | mean per-position match of decoded ids vs the gold target ids (the v35 ≈0.32 bottleneck) |
| `exact_seq_recovery_rate` | fraction of *samples* decoding exactly to a gold tactic (v35 ≈0) |
| `head_correct_body_wrong_rate` | right tactic head, wrong body (quantifies "salad") |
| `mean_pairwise_jaccard` | token-set diversity (confirms we have not collapsed to one string) |

**v35 baseline** (`baseline_v35.json`, K=16, N=8): per-token **0.356**, exact-seq
**0.003**, head-correct-body-wrong **0.477**, jaccard 0.247. Nearly half of all
samples get the head right and the body wrong — the salad, quantified.

---

## 2. §3 — Iterative / discrete-diffusion sampler (the canonical decode-side fix)

`src/mini_elf_lean/elf_v36_sample.py` adds `integrate_discrete`: at each Euler
step it snaps the clean estimate to the nearest token embeddings, **self-conditions
on that discrete estimate** (analog-bits style), and **re-noises low-confidence
positions** (MaskGIT-style remasking). Compared on the v35 model vs the v35
continuous-self-cond sampler over N ∈ {1,4,8,16,32} (`sampler_compare.json`):

| N | v35 per-token | v35 exact | v36 per-token | v36 exact |
|---|---|---|---|---|
| 1 | 0.407 | 0.003 | 0.407 | 0.003 |
| 4 | 0.363 | 0.003 | 0.359 | 0.000 |
| 8 | 0.356 | 0.003 | 0.365 | 0.000 |
| 16 | 0.353 | 0.003 | 0.365 | 0.003 |
| 32 | 0.352 | 0.003 | 0.367 | 0.000 |

**No gain.** The iterative sampler keeps per-token at ~0.36 and exact-seq at ~0.
It *concentrates* on the head (head-correct-body-wrong rises 0.45→0.65) and
*reduces* diversity (jaccard 0.24→0.16), but cannot fix bodies. Notably **N=1
single-shot is best per-token (0.407)** — more integration steps slightly hurt, so
the integrator is not the bottleneck. (Caveat: applying a discrete-conditioning
sampler to a model *trained* with continuous self-cond is out-of-distribution;
§3's verdict is corroborated by §4's discrete-self-cond *training* cells, which
also fail.)

---

## 3. §4 — Scale·objective ladder (`ladder.json`, 13 cells, ~2.4 h)

Each cell trained on the same v35 train split + shared vocab; early-stop on val
flow-MSE (patience 8) + 900 s/cell cap; probed with **both** samplers (K=8, N=8,
80 rows). `_disc` = trained with discrete self-conditioning.

| cell | params | val flow-MSE | timed out | v35 per-tok / exact | v36 per-tok / exact |
|---|---|---|---|---|---|
| d3 D128 ce0.2 ep50 | 1.0M | 0.833 | – | **0.358** / 0.009 | 0.353 / 0.000 |
| d3 D128 ce1.0 ep50 | 1.0M | 0.859 | – | 0.349 / 0.009 | 0.348 / 0.000 |
| d3 D128 ce4.0 ep50 | 1.0M | 0.855 | – | 0.331 / 0.000 | 0.328 / 0.000 |
| d6 D128 ce1.0 ep50 | 1.6M | 0.861 | – | 0.346 / 0.000 | 0.337 / 0.000 |
| d3 D256 ce1.0 ep50 | 3.8M | **0.642** | ✓ | 0.351 / 0.005 | 0.341 / 0.000 |
| d6 D256 ce1.0 ep50 | 6.1M | 0.738 | ✓ | 0.323 / 0.000 | 0.319 / 0.000 |
| d3 D128 ce1.0 ep150 | 1.0M | 0.859 | – | 0.349 / 0.009 | 0.348 / 0.000 |
| d6 D128 ce4.0 ep150 | 1.6M | 0.854 | – | 0.344 / 0.000 | 0.332 / 0.000 |
| d3 D256 ce4.0 ep150 | 3.8M | 0.639 | ✓ | 0.337 / 0.000 | 0.333 / 0.005 |
| d3 D128 ce1.0 ep50 `_disc` | 1.0M | 0.864 | – | 0.348 / 0.009 | 0.354 / 0.000 |
| d3 D128 ce4.0 ep50 `_disc` | 1.0M | 0.860 | – | 0.348 / 0.009 | 0.352 / 0.000 |
| d6 D128 ce1.0 ep50 `_disc` | 1.6M | 0.854 | – | 0.349 / 0.009 | 0.345 / 0.000 |
| d3 D256 ce1.0 ep150 `_disc` | 3.8M | 0.622 | ✓ | 0.341 / 0.005 | 0.336 / 0.000 |

**The curve is flat.** Findings:

1. **Scale is not a lever.** per-token recovery lives in [0.319, 0.358] for *every*
   cell; the *best* is the smallest/cheapest config (≈ the v35 baseline), and the
   6.1M-param cell is the *worst* (0.319). exact-seq never exceeds 0.9%.
2. **flow-MSE ⟂ coherence.** D=256 cells cut val flow-MSE to 0.62–0.74 (vs
   0.83–0.86) — markedly better flow-matching — with **no** change in token
   recovery. The model gets better at the continuous objective and no better at the
   discrete one. This is the mechanism behind the v35 "no-CE has lowest MSE yet 0%
   verify" observation, now confirmed across scale.
3. **The canonical fix fails too.** discrete-self-cond cells match continuous
   (per-token 0.34–0.35, exact 0) — training *and* decoding for coherence still
   does not cross the floor.
4. **ce_weight does not help;** higher CE (4.0) slightly *lowers* per-token.

---

## 4. §5 — Gate (not fired) → Lean skipped (`verified_best.json`)

Gate = `per_token_gold_recovery ≥ 0.60` **or** `exact_seq_recovery_rate ≥ 0.10`.
Best offline: per-token **0.358**, exact-seq **0.009** → **gate NOT fired**. The
Mathlib scratch env + `TrustedMathlibVerifier(confirm=True)` are available but the
verified run is intentionally skipped: with <1% exact-sequence recovery, a matched
pass@k cannot move off 0, and the offline result is already decisive. Recorded as
a negative confirmation rather than spending Lean to re-confirm 0.

---

## 5. Verdict

At CPU scale, the v35 embedded-flow's inter-token incoherence is **not closable**
by the levers v36 tested. The decode-side fix (iterative/discrete sampler with
remasking) holds per-token at ~0.36 and exact-seq at ~0; the train-side levers
(2×–6× params, 3× epochs, 20× CE weight, discrete self-conditioning) leave the
curve flat in [0.32, 0.36] per-token and <1% exact-seq, even as they cut the
training flow-MSE by ~25%. That decoupling — better flow-matching, identical
discrete coherence — is the crux: a non-autoregressive flow over token embeddings
has no mechanism coupling per-position predictions, and at this scale that
coupling does not emerge from capacity, training time, the CE anchor, discrete
self-conditioning, or iterative refinement. The gap is fundamental here — and the
v37 overfit control pins down *why*: it is a **sample-efficiency limit** (the flow
memorizes a few tactics coherently but cannot fit even its own training set beyond
~16 theorems), not a representational one. The token-AR engine (which gets
inter-token coherence for free) remains the right tool; the only remaining
unfalsified lever is a regime far outside CPU scale (orders of magnitude more
params/data, where flow LLMs begin to work) — out of scope for this project.

---

## 6. Reproduction

```bash
python scripts/v36_coherence_probe.py --mode baseline            # §2 v35 baseline
python scripts/v36_coherence_probe.py --mode compare             # §3 v35 vs v36 sampler
python scripts/v36_ladder.py --cell-seconds 900 --max-cells 13   # §4 ladder (offline, ~2.4h)
# §5 verified run only if the gate fires (it did not); see verified_best.json
```

Artifacts: `data/baselines/v36_coherence/{baseline_v35,sampler_compare,ladder,verified_best}.json`,
`run.log`. No model weights saved (the ladder trains in-memory and probes; v35/v24/v33 untouched).
