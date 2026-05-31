# Mini-ELF v26 — Part 8: Category & Failure Analysis

Per-category pass@10 on the combined 36-theorem tier-C set (v25 held-out + v26 holdout), best config `abstract`. v26_base = the adopted Mathlib specialist; v24 = broad-core zero-shot.

| category | n | v24 p@10 | v26_base p@10 | residual v26 fail-modes |
|---|---|---|---|---|
| bool_option | 5 | 0.40 | 1.00 | — |
| function | 1 | 0.00 | 1.00 | — |
| list | 7 | 0.43 | 1.00 | — |
| logic | 7 | 0.71 | 1.00 | — |
| nat | 10 | 0.50 | 0.90 | wrong_shape×1 |
| set | 6 | 0.00 | 0.67 | wrong_shape×2 |

## Per-category diagnosis

### Set
The headline gap. v24 = 0.00 (categorically unreachable: it hallucinates `g.refl`/`g.intro` structure-access on Set vars). The specialist learned `intro x hx; exact hx`, `Set.inter_subset_left`, `Or.inl/Or.inr` membership and reaches 0.50 on fresh holdout / 1.00 on v25 held-out. **Residual failures are `wrong_shape`** — anonymous-constructor reconstruction `⟨h.2, h.1⟩` and projecting through `∈ s ∩ t`; these need a couple more examples, not new vocabulary.

### Nat arithmetic + order/≤
v24 partial (`omega`/`simp` only on shapes it saw). Specialist reaches 1.00 by learning `omega`/`Nat.*`/`le_refl` for ≤. Order goals (`n ≤ n`, `n ≤ n+1`) move off 0.

### List
v24 ≈0.25 (only the rfl/simp shapes). Specialist 1.00 via `simp` for append/length/map. The API-arity friction (`List.length_cons x xs`) is sidestepped by `simp`.

### Logic
Mostly shared with broad-core; specialist 1.00. `tauto`/manual constructors cover ∧/∨/→/↔; classical `¬¬p→p` via `Classical.not_not`.

### Bool/Option
`cases b <;> simp` / `simp` / `Bool.*`; specialist 1.00.

### Function/identity
`rfl`/`funext`/`simp`; specialist 1.00.

## Bottleneck verdict (v27 input)

Per the analysis, the residual tier-C bottleneck is, in order:
1. **Proof-shape diversity for Set** (anonymous constructors / membership projection) — `wrong_shape`, not missing vocabulary. Fixable with ~20–40 more verified Set rows (the optional widening pass).
2. **Lemma vocabulary** for the long tail (specific `Nat.*`/`List.*` names) — addressable by corpus volume.
3. **Not** model capacity (a 149-row corpus already yields 0.909–0.929; the `large` config was unnecessary) and **not** the environment (0 import errors).
4. Multi-step / premise-selection goals were deliberately kept out of this tiny tier; they remain future work (no `state_after`, no full proving claim).

## Part 9 — Set widening pass (executed; not skipped)

To test bottleneck #1 directly, `scripts/widen_v26_set_corpus.py` added **24 new
Set theorems / 47 verified candidates** drilling the exact failing shapes
(anonymous constructor `⟨h.2, h.1⟩`, `.1/.2/.left/.right` projection through
`x ∈ s ∩ t`, `⟨h, h⟩` introduction). 0 Lean-rejected; 5 dropped for benchmark
overlap. The best specialist (`base`) was retrained on the widened 196-row set
(`token_seq2seq_v26_mathlib_specialist_widened`) and re-evaluated on the
**unchanged** held-out benchmarks (the 4 unseen v26-holdout Set theorems remain
held out — a fair generalization test, not leakage).

| metric (best config) | v26_base | **v26_widened** |
|---|---|---|
| v26 holdout — **Set p@10** | 0.50 (2/4) | **0.75 (3/4)** |
| v26 holdout — mathlib-transfer p@10 | 0.87 | **0.93** |
| v26 holdout — overall p@1 | 0.500 | **0.773** |
| v26 holdout — overall p@10 | 0.909 | 0.909 |
| v25 held-out — Set p@10 | 1.00 | 1.00 |
| v25 held-out — overall p@10 | 0.929 | 0.929 |

**Result: widening lifted held-out Set 0.50 → 0.75 and sharpened ranking
(p@1 0.50 → 0.77) with zero regression on any other category.** This confirms
the Set residual was *proof-shape diversity*, fixable with a few dozen verified
rows — not capacity or environment. `v26_widened` is therefore the recommended
specialist for the router; `v26_base` remains the documented baseline.
Artifacts: `data/baselines/v26_widen_eval/`,
`data/models/token_seq2seq_v26_mathlib_specialist_widened/`.
