# V44 Phase 0 — S1: the non-simp-closable hard tier (and what building it already revealed)

**Tier: n=52** (26 dev / 26 test), every theorem gold-compiling under bisect and **not closable by
`{simp, simp_all, aesop}`**. Source: LeanDojo Benchmark 4 random/**test** split (decontaminated from
the generator training data by construction — generators train on the train split).
Artifacts: `outputs/v44/hard_tier/{hard_dev,hard_test,audit}.json`.

## How rare "hard" theorems are (the constraint, and a finding)
Scanning the test pool (`outputs/v44/hard_tier/audit.json`):
- **1035** of 2000 test theorems convert to a compiling-shaped `example … := by …`.
- **gold-compile-rate 9.9%** (102/1035) — most gold proofs fail under version skew (LeanDojo B4 was
  traced against an older Mathlib; our pinned toolchain is v4.30). This is the dominant filter.
- of the 102 compiling, **91% are closable by `{simp,simp_all,aesop}`** — confirming V43's finding
  that these tiers are overwhelmingly trivial — leaving **52 hard** (49% non-core-closable).

So **n≥100 (the brief's target) is infeasible for a *clean* hard tier**: the intersection
{non-trivial ∧ gold-compiling ∧ convertible} is ~5% of the test pool, and the test split is only
2000 theorems. We report **n=52** and the rates; the rarity is itself the result — *non-trivial,
cleanly-formalizable theorems are a sliver of this benchmark slice.*

## The pre-S2 retrieval signal (the headline finding before any model runs)
On the 102 compiling theorems, the closer-tactic counts (`audit.json:closer_counts`):

| tactic | closes |
|---|---|
| `simp` | 40/102 |
| `aesop` | 50/102 |
| `simp_all` | 48/102 |
| `norm_num` | 40/102 |
| `omega` | 2/102 |
| `decide` | 1/102 |
| **`exact?`** | **84/102** |

`exact?` — Lean's *premise-search* tactic (find a single library lemma that closes the goal) —
solves **84/102**, far more than `simp` (40). On the **hard** tier specifically (simp/aesop fail),
**43/52 (83%) are still closed by `exact?` alone.** That is the retrieval-vs-generation thesis
visible in the raw data **before training anything**: most "hard" theorems here are not hard for
*reasoning* — they are hard for *automation that doesn't know the right lemma*. A single retrieved
premise + `exact` closes 5 in 6 of them.

This is why "hard" is defined as **non-`{simp,simp_all,aesop}`-closable** and *not* the V43
15-tactic wide sweep: the wide sweep included `exact?`, which would have discarded exactly the
premise-retrieval-addressable theorems that are the point of V44. (We still record wide-closability
for audit: 93/102 wide-closable, dominated by `exact?`.)

## Tier composition
avg gold premises **2.2**, avg gold tactics **2.2** per hard theorem — short, premise-bearing
proofs (not deep multi-step search). Examples: `IsUnit.isUnit_iff_mulRight_bijective` (`simp
[mul_assoc]`), `IsPRadical.injective_comp_of_pNilradical_eq_bot` (4-tactic, 3 premises). The tier is
committed as a reusable benchmark; the S2 oracle decomposition (next) measures whether a *trained
generator* can convert known premises into verified proofs — quantifying the retrieval-addressable
fraction the `exact?` signal upper-bounds at ~83%.
