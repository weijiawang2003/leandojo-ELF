# V32 — Failure Examples

_From `data/baselines/v32_saturation/report.json` (best model
`v32_canonical_repaired`, across the adversarial-stress, fresh-shape, and
token-diversity benches). No Lean run._

## 11 remaining failures — all single-tactic, 0 multi-step

| class | count | what they are |
|---|---:|---|
| `api_vocabulary` | 9 | hardest adversarial identifiers (Greek/subscript `proof₁`, `hα`) + unseen lemma-shape (`min_comm`, `inf_comm`, `inter_assoc`, `le_of_lt`) |
| `token_or_shape` | 1 | a fresh shape the model never saw |
| `sparse_shape_single_tactic` | 1 | the lingering `∅∩s⊆t` (sparse `∅∩` shape) |
| **multi_step / proof_state** | **0** | — |

By category: set 5, order 4, finset 2. By bench: identifier-stress 5, fresh-shape 5,
token-diversity 1.

## Two residual mechanisms (both single-tactic, neither multi-step)

1. **Extreme adversarial identifiers** (e.g. an order theorem with `proof₁`/`hα`):
   the canonical decode occasionally desyncs on Greek/subscript tokens (these are
   2.8–8.5 % of canonical candidates, all **dropped before the verifier** by the v19
   guard), and the raw v30 fallback can't bind the unusual name either. Fix: harden the
   canonical alphabet / also canonicalize element tokens (v33).

2. **Unseen shapes** (e.g. `min a b = min b a`, `a ⊓ b = b ⊓ a`, `s∩t∩u = s∩(t∩u)`):
   a **density / shape-coverage** gap (axis 1), not token coverage — the family simply
   has no sibling of that shape. Fix: a few verified siblings (the v29/v30 density
   recipe).

## LeanDojo relevance — still no

**0 of 11 residuals are multi-step**; each has a single verifying tactic the model did
not reach. LeanDojo next-state supervision is **not** justified by any current failure.
The remaining work is single-tactic coverage/robustness (v33), after which the
single-tactic Mathlib tier is saturated and the project is ready to package.

Trusted verifier only; no `state_after`; no manual oracle as predictions; v24 untouched.
