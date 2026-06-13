# V43 Phase 0 — A1: the simp/aesop baseline (the cheapest falsifier fires)

**Verdict: A1 FALSIFIER MET. The flow-unique verified solves are simp-bias. LPSF's H13 "diversity"
value dissolves under a trivial baseline — the flow thread closes as a mechanism result.**

All verification: `verify_many_bisect` (V42 sound path, == isolation). The 6 decisive solves were
additionally **isolation-ground-truthed** one-declaration-per-file (V42 protocol).

## 1. The result

A training-free sweep of trivial closers on both tiers vs the V42 flow-unique theorems (the ones
v41/v42 credited to plan-flow's "strategic diversity" over `{direct-AR ∪ plan-AR}`):

| flow-unique theorem | tier | solved by bare `simp`? | solved by `{simp,simp_all,aesop}`? | isolation-confirmed |
|---|---|---|---|---|
| `MulRingNorm.isPowMul` | dev | ✅ | ✅ | ✅ |
| `sup_himp_self_left` | dev | ✅ | ✅ | ✅ |
| `sdiff_le_iff'` | dev | ❌ (only `exact?`) | ❌ | ✅ (`exact?`) |
| `Rep.ρ_inv_self_apply` | final | ✅ | ✅ | ✅ |
| `codisjoint_inf_right` | final | ✅ | ✅ | ✅ |
| `upperBounds_closure` | final | ✅ | ✅ | ✅ |

**Bare `simp` alone catches 5 of 6 flow uniques; the pre-registered `{simp,simp_all,aesop}` set
catches the same 5; the 6th (`sdiff_le_iff'`) falls to `exact?`.** Every flow "unique" verified
solve is captured by a one-line trivial tactic. Pre-registered falsifier ("simp-sweep ≥ flow∪AR
uniques on dev") is **met** (and on tier-final too).

## 2. The bigger picture — the tiers are mostly simp-closable

| set | tier-dev (n=45) | tier-final (n=44) |
|---|---|---|
| `{simp, simp_all, aesop}` (simp3) | 24 | 24 |
| wide trivial sweep (15 tactics) | **42** | **40** |
| direct-AR ∪ plan-AR (base, V42) | 25 | 25 |
| base ∪ simp3 | 27 | 29 |
| base ∪ wide | **42** | **41** |

A 15-tactic trivial sweep (`simp/simp_all/aesop/norm_num/omega/rfl/tauto/decide/exact?/aesop?/…`)
solves **42/45 dev and 40/44 final** — these LeanDojo-derived tiers (gold-compile-rate 13.7% under
version skew, so they skew single-tactic) are **overwhelmingly closable by trivial automation**.
This recontextualizes the whole v40–v42 "competitive pass@k" framing: plan-AR 0.44 / direct-AR 0.42
were competing on the handful of theorems the trivial sweep *doesn't* get, and flow's "unique"
contributions sat entirely inside the simp-closable majority.

The wide sweep adds **+17 dev / +16 final** theorems over the learned base — i.e. the trained
generators (direct-AR, plan-AR, plan-flow) were *missing* most of the simp-closable theorems that a
zero-training baseline gets for free. The verified-generation story on these tiers is dominated by
automation the models never learned to call.

## 3. Close-out (pre-registered decision tree)

> *A1 simp ≥ flow∪AR uniques → LPSF closes; deliverable = the mechanism result ("flow's verified
> value was diversity-toward-simplicity under a weak grounder") + MDLM as the productionizable
> discrete substrate (v40 H10 AR∪MDLM 27/44 stands). This is a strong negative, not a failure.*

**This leg fires.** The V42 prediction is confirmed at the cheapest possible cost: flow's H13
verified value was diversity *toward simplicity* — the diverse plans that "uniquely" verified did
so by grounding to `simp`, which a trivial baseline already supplies. The LPSF diversity mechanism
is **not real** in the sense that matters (gains a strong baseline doesn't already have).

The remaining V43 phases (A2 confirmation under the strong grounder; B1/B2 continuous-vs-discrete;
C1/C2 granularity frontier) still run — they are publishable mechanism science *regardless* of A,
and A2 will make the closure airtight by showing flow adds nothing over `{simp ∪ aesop ∪ direct-AR
∪ plan-AR}` even with premise selection.

Artifacts: `outputs/v43/simp/simp_baseline.json` (`verify_mode=bisect-batched`, per-theorem hits).
