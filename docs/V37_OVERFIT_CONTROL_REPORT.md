# Mini-ELF v37 — Overfit control: architecture limit, or sample-efficiency limit?

**Verdict (sharper than "fundamental"): a sample-efficiency / capacity-per-example
limit — NOT a hard architecture limit, NOT a pure generalization limit.**

The non-AR embedded flow **can** represent and *exactly reproduce* coherent,
Lean-valid multi-token tactics — but only by **memorizing a handful**. At **M=4**
theorems / 800 epochs it reaches **train exact-sequence recovery 0.55** and
**per-token 0.67** on its own rows (Lean-confirmed: 5/5 sampled exact
reproductions verify). But coherence **collapses as data grows**: at 800 epochs,
train exact-seq goes **M=4: 0.55 → M=16: 0.14 → M=64: 0.00**. By the time the
training set is 64 theorems (154 rows) the flow can no longer fit even its *own*
training tactics. More capacity (width 256) does not rescue it.

So v35/v36's "fundamental at CPU scale" is real but its *cause* is now precise: the
architecture is not incapable of coherence — it is **catastrophically sample-
inefficient at discrete coherence**. With few examples, flow-MSE and coherence are
coupled (it memorizes); as examples grow, the average-L2-optimal solution becomes
the **incoherent ~0.34 "salad" hedge**, which is exactly the v35/v36 held-out
floor. This explains the earlier "MSE↓ but coherence flat" decoupling: the
decoupling *emerges with data scale*.

Scope unchanged: CPU-scale, ELF-*style*, single-tactic. No full-theorem-proving /
proof-state / ELF-at-scale claim. v37 wrote only `v37_*` artifacts; v24/v33/v35/v36
weights/configs untouched.

---

## 1. Design (train == probe, by design)

This is an **overfit control**, so there is **no held-out set and no early
stopping** — we *want* the model to memorize if it can. We train the v35 flow on a
tiny fixed subset of M Mathlib-tier **train** theorems (nested by `md5(name)`, so
M=4 ⊂ M=16 ⊂ M=64), `val == train`, then run the §2 coherence metric
(`v36_coherence_probe`, **integrate-from-noise** — true generation, not teacher
forcing) on **those same training rows**. "train coherence" below means: does the
flow reproduce the gold token sequence of an example it was trained on? Each cell
is probed at CFG weight 1.0 and 2.0; the table reports the better (CFG 2.0
concentrated best on the memorized tactic). Per-train hard cap 25 min; CPU;
deterministic (seed 0); offline except §5.

---

## 2. Overfit table (`data/baselines/v37_overfit/overfit.json`)

| cell | rows | params | train flow-MSE | epochs | train per-token | **train exact-seq** | head-body |
|---|---|---|---|---|---|---|---|
| M=4  D128 | 8 | 1.0M | 1.215 | 200 | 0.454 | 0.164 | 0.40 |
| **M=4  D128** | 8 | 1.0M | **0.350** | **800** | **0.672** | **0.555** | 0.48 |
| M=16 D128 | 36 | 1.0M | 1.119 | 200 | 0.432 | 0.076 | 0.64 |
| M=16 D128 | 36 | 1.0M | 0.539 | 800 | 0.558 | 0.141 | 0.79 |
| M=64 D128 | 154 | 1.0M | 0.896 | 200 | 0.395 | 0.009 | 0.65 |
| M=64 D128 | 154 | 1.0M | 0.464 | 800 | 0.412 | **0.000** | 0.71 |
| M=16 **D256** (capacity) | 36 | 3.8M | 0.428 | 800 | 0.527 | 0.071 | 0.72 |

(v35/v36 **held-out** reference: per-token 0.356, exact-seq 0.003.)

---

## 3. Two curves

**train exact-seq vs epochs** (memorization needs training time):
```
M=4 :  200ep 0.164  →  800ep 0.555     (steeply rising — it is memorizing)
M=16:  200ep 0.076  →  800ep 0.141     (rising slowly)
M=64:  200ep 0.009  →  800ep 0.000     (flat at zero — cannot memorize)
```

**train exact-seq vs M** (at 800 epochs — the collapse with data):
```
M=4  0.555  ████████████████████
M=16 0.141  █████
M=64 0.000
```

The flow memorizes 4 theorems coherently, struggles with 16, and fails entirely at
64 — all on its *own* training data, with identical architecture and epochs.

---

## 4. flow-MSE ↓ vs coherence — coupled then decoupled

* **M=4 / 800ep:** train flow-MSE **0.350**, train exact-seq **0.555** → *coupled*
  (driving MSE down = memorizing the exact latent sequence).
* **M=64 / 800ep:** train flow-MSE **0.464**, train exact-seq **0.000** →
  *decoupled* (the L2-optimal map averages over examples into the incoherent hedge).
* **Capacity (M=16, D256):** lowest MSE of the M=16 cells (0.428) yet exact-seq
  0.071 ≤ the D128 M=16 value (0.141) — **more parameters did not buy memorization**.

This is the mechanism behind v36's "MSE decoupled from coherence": it is not a
constant property of the architecture; the decoupling *emerges* as data outstrips
the flow's (very low) sample efficiency for discrete coherence.

---

## 5. §5 Lean sanity (`lean_sanity.json`)

Train exact-seq > 0, so we verified that exact-sequence hits are genuinely valid:
the reproduced M=4 model's 5 distinct exact-gold reproductions were checked with
`TrustedMathlibVerifier(confirm=True)` — **5/5 verify**, including a non-trivial
multi-token tactic `intro x hx; exact absurd (Finset.mem_inter.mp hx).1 (by simp)`.
So exact-seq recovery corresponds to real, Lean-valid tactics, not a metric
artifact — the architecture demonstrably *can* emit coherent verified tactics.

---

## 6. Verdict

The discriminating control resolves the v35/v36 question. The flow's incoherence is
**not** an inability to represent coherent tactics (refuted: M=4/800ep memorizes
them exactly and they verify in Lean), and **not** a pure generalization gap
(refuted: it fails to fit even its own 64-theorem training set). It is a
**sample-efficiency limit** — the non-autoregressive token-embedding flow needs an
impractical amount of capacity-per-example to commit to a coherent discrete
sequence, so beyond a few memorized theorems the minimum-average-L2 solution is the
incoherent ~0.34 hedge that v35/v36 measured on held-out data. At the ~400-theorem
Mathlib tier this floor governs both train and held-out, so verified pass@k is 0.
For CPU-scale verified single-tactic generation the flow remains dominated by
token-AR; the only unfalsified lever is an off-CPU-scale regime (orders of
magnitude more capacity/data), out of scope. A clean, sharpened negative.

---

## 7. Reproduction

```bash
python scripts/v37_overfit_control.py --m-values 4,16,64 --epochs-values 200,800 --capacity-arm
python scripts/v37_lean_sanity.py     # §5, gated on train exact-seq > 0
```
Artifacts: `data/baselines/v37_overfit/{overfit,lean_sanity}.json`, `run.log`.
No model weights saved (trains in-memory; v35/v24/v33/v36 untouched).
