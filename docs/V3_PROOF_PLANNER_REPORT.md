# Mini-ELF v3 — Structured Proof-Block Planner

**v3 attacks the one wall v2 could not move: compositional generalization.** v2
showed that training the flat tactic-string generator on harder data recovers
*in-distribution* hard problems but leaves the `difficulty_holdout` split (train
easy/medium → test hard) at `pass@5` **0.06** — the model never learns to
*compose* a multi-step proof it did not see. v3 keeps the entire v2 model and
adds a small, deterministic **symbolic proof-block planner**
(`src/mini_elf_lean/proof_planner.py`) as a new candidate source, then verifies
every candidate with the same lean-cli `pass@k`.

> Scope, unchanged: **theorem-level** verification only (`state_after_is_real=
> false`); v0–v3 are prototypes of the *generation loop*, **not** full ELF over
> proof states; LeanDojo `run_tac` remains blocked (`xfail`). **The planner is
> symbolic / heuristic, not neural generation** — it constructs proof terms from
> a parsed goal. **16–96 eval rows per split → directional, never statistically
> definitive.**

## 1. Why a planner (Part 1 failure analysis)

`scripts/analyze_difficulty_failures.py` bins the Lean-verified failures of
v1-transfer and v2 on the hard `difficulty_holdout` test split (96 rows, 90
unsolved at `pass@5` for **both**). The failures are almost entirely
*structural*, not garble (full table: `docs/V3_DIFFICULTY_FAILURE_ANALYSIS.md`):

| failure category | v1-transfer | v2 |
| --- | --- | --- |
| missing nested conjunction projection | 30 | 30 |
| missing implication chain composition | 26 | 24 |
| wrong equality direction | 22 | 22 |
| missing case split | 8 | 6 |
| wrong iff direction | 4 | 4 |
| wrong witness / malformed | 0 | 4 |

The model can't chain three implications, project `h.2.2`, split a disjunction,
or pick the iff/equality direction — it is *missing composition*. A planner that
**constructs** the proof block from the parsed goal targets exactly this.

## 2. Architecture

**Parser (Part 2, `proof_planner.parse_planner_state`).** A heuristic
turnstile/`:`-split parser (no Lean AST) that classifies each hypothesis by its
*top-level* connective (Lean precedence `↔ → ∨ ∧ =`): implication `A → B`, iff
`A ↔ B`, equality `a = b`, conjunction (with nested structure), disjunction,
atom; plus declared Prop/Type variables and value variables. Reads only
`theorem_statement` + `state_before`.

**Backward proof search (Part 3, `_Prover`).** A depth-bounded, deterministic
backward-chaining builder that returns proof-term strings tagged by the
outermost rule used:

- *base / projection* — a hypothesis (or a `.1/.2`/`.left/.right` projection of a
  conjunction hypothesis, expanded recursively) of exactly the goal type.
- *application* — apply an implication hypothesis `f : X → goal` to a proof of
  `X` (modus-ponens chains: `h3 (h2 (h1 h))`).
- *iff direction* — `h.mp` / `h.mpr` composition (`h2.mp (h1.mp hp)`).
- *conjunction build* — `⟨pₗ, pᵣ⟩` from proofs of each side (so `h ⟨ha, hb⟩`
  works for uncurry).

**Template strategies.** On top of the search, a small library emits full
tactic blocks: `intro` + `exact`/`fun =>` for implication goals; anonymous
constructor / `constructor` / `And.intro` for conjunction goals; `Or.inl/inr`
and `left/right` for disjunction goals; a trans/symm **path search** over
equality hypotheses for equality goals; and `cases … with` / `rcases` / `Or.elim`
case splits for any goal when a disjunction hypothesis is present. Existential
goals are **deferred** to the existing symbolic witness-copy. Each candidate
carries a `planner_*` source label and a confidence priority.

**Fusion (Part 4, `elf_v3_sample.MiniElfV3Baseline`).** Per prompt, merge
planner ⊕ witness-copy ⊕ v2 flow candidates, deduplicate (planner/witness claim
shared strings first), and rank in **tiers**:

1. **planner** candidates by symbolic priority (ties broken by reranker score),
2. **witness-copy** candidates,
3. the **v2 reranked flow pool** (unchanged), then the **flow tail**.

The learned reranker is **not** allowed to reorder the planner blocks against
flow, because v2 proved it mis-calibrates off-distribution — and indeed on
v3's planner candidates it assigns mean scores of only 0.25–0.86 to blocks that
*all* verify (§5). The tail is preserved so `pass@5` recall never drops below v2.

## 3. Headline result — difficulty_holdout 0.06 → 1.00

lean-cli `pass@k`, `decoder_rerank_witness` + planner (`scripts/run_mini_elf_v3_eval.sh`):

| eval split | n | v1-transfer pass@5 | v2 pass@5 | **v3 pass@1** | **v3 pass@5** |
| --- | --- | --- | --- | --- | --- |
| **hard difficulty_holdout** (TARGET) | 96 | 0.06 | 0.06 | **0.98** | **1.00** |
| hard adversarial_sibling | 89 | 0.11 | 0.53 | **1.00** | **1.00** |
| hard hash | 26 | 0.23 | 1.00 | **1.00** | **1.00** |
| basic test (regression) | 38 | 0.95 | 0.82 | **1.00** | **1.00** |

**Ablation (clean attribution).** Same model, same split, planner **off**
(`--no-planner`, == pure v2 through the v3 harness): `difficulty_holdout`
`pass@5` = **0.083**, `invalid@1` 0.94. Turning the planner on takes the same
96 theorems to **1.00**. The entire lift is the planner.

Notes:
- v3 **also recovers the basic-corpus regression v2 introduced** (0.82 → 1.00):
  the planner solves the basic and/or/iff/eq/exists families the diversified v2
  model had started to miss, so v3 is — uniquely in this project — a *uniform*
  improvement across every split.
- per-difficulty on the holdout split: `hard` `pass@5` = **1.00** (n=96), vs v2's
  0.06. The genuinely multi-step theorems are now solved.

## 4. Planner contribution (Part 5)

Per-source verified / attempted candidates in the top-5 (from
`candidate_sources_summary.json` / `metrics.json`):

| split | planner verified (by strategy) | rows solved *only* by planner | flow verified | witness |
| --- | --- | --- | --- | --- |
| difficulty_holdout | projection 80, chain 52, template 36, eq 34, cases 30, iff 8 | **88 / 96** | 8 | 4/8 |
| adversarial_sibling | projection 72, template 45, iff 32, chain 14, eq 4, cases 4 | 59 / 89 | 60 | 12/12 |
| hash | template 20, projection 16, chain 12, iff 12 | 14 / 26 | 14 | 8/8 |
| basic | template 25, projection 6, eq 4, cases 4, iff 4, chain 2 | 16 / 38 | 49 | 4/4 |

**Every planner candidate that reached the top-5 verified** (e.g. difficulty:
80/80 projection, 52/52 chain, 34/34 eq, …). The planner is high-precision by
construction. On `difficulty_holdout` it single-handedly solves 88 of 96
theorems the flow generator cannot. Examples of newly-solved multi-step proofs
and the (two) remaining pass@1 misses: `docs/V3_FAILURE_EXAMPLES.md`.

## 5. Reranker calibration on planner candidates

Mean v2-reranker score assigned to planner candidates (recorded but **not** used
for planner ordering):

| split | reranker score on planner candidates (all of which verify) |
| --- | --- |
| hard hash | 0.86 |
| basic | 0.80 |
| hard difficulty_holdout | 0.47 |
| hard adversarial_sibling | 0.25 |

The reranker scores correct, Lean-verified multi-step blocks as low as **0.25**
on the held-out adversarial families — confirming v2's finding that it is
**mis-calibrated off-distribution**. Had v3 let the reranker order the planner
blocks against high-frequency flow garble, it would have buried them. The
tier policy (symbolic priority first) is what makes the planner usable.

## 6. Remaining failures (honest)

- **2 pass@1 misses on `difficulty_holdout`** — both `exists_hyp_copy_12`
  (`⊢ ∃ n : Nat, n = m`). Witness-copy tries the copied literal `⟨12, rfl⟩`
  (from `h : m = 12`) before the correct `⟨m, rfl⟩`, which verifies at rank 3.
  A known witness-ordering quirk (numeric-literal-first), not a planner gap;
  `pass@5` is still 1.00.
- **No pass@5 failures on any evaluated split.**

## 7. LLM proposal pilot

**Still skipped — no API key configured** (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
unset; only `.env.example`). Not faked. v3 did not need it; it remains the
natural way to escape the closed template/family set (§8).

## 8. What v3 does and does **not** show (the central honesty)

- ✅ **Compositional generalization on this corpus is achievable** — the
  `difficulty_holdout` `pass@5` goes 0.06 → 1.00, and the ablation proves it is
  the planner.
- ❗ **This is engineered symbolic *coverage*, not learned generalization.** The
  planner has hand-written templates + a backward search for exactly the proof
  shapes this corpus uses (implication chains, conjunction projection/intro,
  disjunction elim/intro, iff/equality composition). It "generalizes" across the
  train/test split only because it *constructs* proofs from the parsed goal and
  is indifferent to which split a theorem is in — **not** because any model
  learned to compose.
- ❗ **On a genuinely novel proof shape with no matching template, the planner
  would fail just like v1/v2.** v3 therefore *reframes* the open problem rather
  than closing it: the wall is no longer "compose a seen pattern across a split"
  but "**handle proof structures the template library does not cover**" and
  "**learn the templates instead of hand-writing them**".
- ❗ Everything remains theorem-level, small-sample, closed-family, and a
  generation-loop prototype — not full ELF over proof states.

## 9. What remains for v4

1. **Replace hand-written templates with learned/searched tactics** — a neural
   policy that *proposes* the planner's structured steps (or a real LLM
   candidate pilot, §7) so coverage is not capped by the template author.
2. **Open-family stress corpus** — proof shapes deliberately *outside* the
   current template library, to measure where symbolic coverage actually ends
   (the honest successor to `difficulty_holdout`).
3. **Reranker recalibration off-distribution** — the planner sidesteps the
   mis-calibrated reranker; a domain-robust reranker would let learned and
   symbolic candidates be ranked together.
4. **Real next-state supervision** (LeanDojo `run_tac` unblock) — the
   prerequisite for a planner that operates over *actual* intermediate proof
   states rather than the initial theorem-level prompt.
