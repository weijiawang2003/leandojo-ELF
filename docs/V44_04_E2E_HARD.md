# V44 Phase 3 — R2 (retrieval-augmented e2e) + E1 (ensemble), hard tier

These are read from the S2 oracle arms (`outputs/v44/oracle/cand_*.json`) — the retrieved arm IS the
retrieval-augmented e2e, and the per-arm solved sets give the ensemble. No extra Lean.

## R2 — does realistic retrieval move end-to-end proving on hard theorems?
| source | none | retrieved (BM25) | gold (oracle) |
|---|---|---|---|
| AR | 0/26 | **0/26** | 1/26 |
| MDLM | 0/26 | **0/26** | 1/26 |

**R2 falsifier ("retrieved ≈ none") MET.** BM25-retrieved premises give **0 gain** over no premises
on the hard tier — because BM25 recall@10 is only 0.10 (`V44_03`), so it almost never surfaces the
gold premise into the conditioning. Retrieval is not realizable end-to-end here with a lexical
retriever. Per the close-out tree this is the *"retrieval-addressable but current retrieval can't
reach it"* leg — except S2 shows the deeper problem: even the gold oracle (perfect retrieval) only
reaches 1/26, so the binding constraint is generation, not retrieval (see `V44_02`).

## E1 — discrete ensemble on the hard tier, simp-controlled
The hard tier is **non-simp-closable by construction**, so the `simp`/`aesop` baseline solves **0/26**
— the "over simp" credit is automatic but the absolute numbers are what matter:

| ensemble (best arm = gold) | solved |
|---|---|
| AR alone | 1/26 |
| MDLM alone | 1/26 |
| AR ∪ MDLM | **1/26** (same theorem) |
| + simp/aesop | +0 (tier is non-simp-closable) |

**E1 falsifier ("union ≈ max component") MET on the hard tier.** AR and MDLM solve the *same* single
theorem, so there is no plan-/whole-proof-level ensemble complementarity here. This does **not**
contradict v40's whole-proof H10 (AR∪MDLM 27/44) — that complementarity lived on the *mixed*
(mostly simp-closable) tier, where the two discrete models pick up different *easy* theorems. On
genuinely *hard* theorems, both solve ~nothing, so there is nothing to union. The discrete ensemble's
value is real but concentrated on the trivial majority a `simp` sweep also gets.

## Net (R2 + E1)
On non-simp-closable theorems, neither retrieval-augmentation (BM25) nor the AR∪MDLM ensemble moves
the needle: the system solves 1/26 at best, only with a gold-premise oracle. The honest e2e headline
is sobering and matches the S2 decomposition — **a 30M discrete generative prover, even with perfect
premises and an ensemble, barely touches the hard tier; the value seen in prior nights was on the
simp-closable majority.**
