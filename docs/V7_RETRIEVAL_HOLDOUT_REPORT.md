# Mini-ELF v7 — retrieval under donor scarcity (family / operation holdout)

> **Scope & honesty.** v6 reached pass@5 **1.00** on the planner-blind split, but
> that split is `family_interpolation`: every test family also has members in
> train. v7 asks the research question directly — *does structure-aware retrieval
> still help when the correct proof family is absent or scarce?* It measures the
> v6 retriever (unchanged) plus a template-free abstraction re-ranker across a
> graded set of donor-scarcity splits, with **real lean-cli** verification.
>
> The headline holdout numbers below are **not directly comparable** to v6's
> 1.00 on the interpolation split — they are a *different, harder* regime, built
> precisely to remove the same-family donors that interpolation provides.
> Retrieval here is **ranking + example reuse + light adaptation, never proof
> reasoning**; no `state_after` is read; **no new proof templates** are added as
> the solution (the one new mechanism, role re-concretisation, reuses a *verified
> donor proof* and only re-binds its hypothesis/literal slots).

## 1. The donor-scarcity gradient (pass@5, real lean-cli)

157 planner-blind theorems (61 theorems → up to 157 next-tactic rows), 10
families across 6 guessed required-operations. Retrieval-only (v3 off). `—` = not
run for that split.

| split | donor condition | v5_retrieval | v6_retrieval | v7_abstract |
| --- | --- | --- | --- | --- |
| `current` (interpolation) | abundant same-family donors | 0.595 | **1.000** | 1.000 |
| `kshot_2` | 2 same-family donors / family | — | **1.000** | 1.000 |
| `kshot_1` | 1 same-family donor / family | — | **0.908** | **0.939** |
| `literal_holdout` | schema in train, literal unseen | 1.000 | **1.000** | 1.000 |
| `family_holdout` | **no same-family donor** | 0.000 | **0.000** | 0.000 |
| `operation_holdout` | **no same-operation donor** | 0.000 | **0.000** | 0.000 |
| `kshot_0` | no donors at all (floor) | — | **0.000** | — |

pass@1 mirrors pass@5 except: `current` v5 0.357 → v6 1.000; `kshot_1` v6 0.832 →
v7_abstract **0.924**; `literal_holdout` v5 0.750 → v6 1.000.

**Reading.** The determinant of success is the **presence vs. absence of a
same-family donor, not its quantity.** With ≥1 same-family donor (`current`,
`kshot_2`, `kshot_1`, `literal_holdout`) retrieval scores 0.91–1.00; with **zero**
same-family donors (`family_holdout`, `operation_holdout`, `kshot_0`) every
configuration collapses to **0.00**. The cliff is at one donor, not at scarcity.

## 2. The current split is interpolation (retrieval-time forbids)

Run on the *same rich split*, forbidding donors at retrieval time:

| config (on `current`) | pass@1 | pass@5 | rank-0 donor same-family |
| --- | --- | --- | --- |
| v6_retrieval | 1.000 | 1.000 | 1.000 |
| v6 — forbid **same-family** donors | 0.000 | 0.000 | — |
| v6 — forbid **same-operation** donors | 0.107 | 0.107 | — |

v6's rank-0 donor is the **same family 100%** of the time, and removing same-family
donors zeroes it out. The 0.107 survivor under same-operation forbidding is
exactly the `exists_reconstruct` family, whose operation is guessed `unknown` so
the operation filter cannot catch it (9/84 rows). This is the same conclusion as
the Part-1 audit (`docs/V7_DONOR_AVAILABILITY_AUDIT.md`), reached independently
through the split builder.

## 3. Cross-family transfer is zero — and *why*

Across **every** split and config, `cross_family_verified = 0` and
`cross_operation_verified = 0`. Even where a held-out family has a **same-operation
sibling** in train (6 of 10 family folds — e.g. `neg_exfalso` ↔ `neg_or_cases`
both `contradiction`), the sibling's *concrete* tactic does not transfer:

- `neg_exfalso` target (`hp : p, hnp : ¬p ⊢ q`) gets the `neg_or_cases` donor
  `cases h with | inl … | inr …` → **`unknown identifier h`** (no disjunction `h`
  in the state).
- `exists_elim_conj` target (`h : ∃ _, p ∧ q ⊢ p`) gets the `exists_elim_prop`
  donor `rcases h with ⟨n, hp⟩; exact hp` → **type mismatch `hp : p ∧ q`** (the
  donor never takes the `.1` projection the target needs).

The `failure_taxonomy` quantifies it under `family_holdout`: **115/157** rows had
a cross-family same-operation donor available that still failed, and **42/157**
had no same-operation donor at all (the sole-family operations: `forall_inst` 7,
`rewrite_succ` 20, `exists_reconstruct` 15). Concrete transcripts:
`docs/V7_FAILURE_EXAMPLES.md`.

**The wall is donor coverage, not ranking.** Retrieval can only return a proof
that already exists in the donor pool; when the family is held out, the needed
proof shape is simply absent, and no amount of re-ranking conjures it. This
corpus is adversarial to cross-family transfer by construction: each proof
operation's *flat* (single-step) tactic appears in exactly one family, so the
held-out family is always the unique source of its own operation's flat proof.

## 4. Where abstraction *does* help: same-family scarcity (kshot_1)

The v7 abstraction re-ranker (`AbstractionAwareRetrievalProposer`) adds **role-based
re-concretisation**: it abstracts a donor tactic to operation roles
(`exact absurd <prop_hyp> <neg_hyp>`) and re-binds each slot to the *target's* own
hypotheses of that role. This generalises v6's `hyp_remap` (which matched by exact
type) to matching by **proof role**, and it pays off in the 1-shot regime:

| metric (`kshot_1`, n=131) | v6_retrieval | v7_abstract |
| --- | --- | --- |
| pass@1 | 0.832 | **0.924** |
| pass@5 | 0.908 | **0.939** |
| adapted candidates verified | 17 | **29** |

The +12 rank-1 wins are all the same shape: a target whose negation hypothesis is
written as an **arrow** (`h : p → False`) rather than `¬p`. v6's type-exact
`hyp_remap` can't bind the donor's `hnp : ¬a` to it; v7 classifies `p → False` as
the `neg` role and re-concretises the *same-family* donor `exact absurd hp hnp`
into `exact absurd hp h`, which verifies (example in
`docs/V7_FAILURE_EXAMPLES.md` §4). Note this win is **same-family** — the donor
`neg_exfalso_ab` shares the target's family — so it does **not** contradict §3:
`cross_family_verified` stays 0 even for v7_abstract. Abstraction makes
*intra-family scarce* reuse more robust; it does not create cross-family transfer.

On the regimes where v6 is already saturated (`current`, `kshot_2`,
`literal_holdout`) v7_abstract ties at 1.00; on the absent-family regimes it stays
at 0.00.

## 5. Adaptation works when the schema is present (literal_holdout)

`literal_holdout` keeps each family's proof *schema* in train but makes every test
theorem's numeric literal globally unseen (held: `forall_inst` 9 & 13,
`exists_reconstruct` 11 & 20). pass@5 = **1.00** (v5/v6/v7): the forall theorems
are solved by **numeric adaptation** copying the goal literal (`exact h 9` from a
donor `exact h 8`), the exists theorems by their literal-free escape (`exact h` /
`rcases`). This isolates that v6's adaptation — not memorisation of the exact
tactic — is doing the work where a same-schema donor exists. (Honest caveat:
`exists_reconstruct` has a literal-free proof, so only `forall_inst` is a *clean*
forced-adaptation test here.)

## 6. What was intentionally **not** claimed

- **No** proof reasoning. v6/v7 re-rank and re-bind *verified donor proofs*; the
  one new mechanism (role re-concretisation) fills a donor proof's slots with the
  target's hypotheses — it does not synthesise a proof the donor pool lacks.
- **No** new hand-written templates as the solution (v4's whack-a-mole). The only
  additions are retrieval/scoring/abstraction over existing donor tactics.
- **No** `state_after` and **no** full ELF over proof states; theorem-level lean-cli
  verification only (`state_after_is_real=false`).
- Holdout numbers are **not** comparable to v6's interpolation 1.00 — different,
  harder regime by design.
- No LLM; no large model. (A tiny learned scorer was scoped in Part 5 and
  **skipped** — see `docs/NEXT_STEPS.md`: there is no learnable headroom, since
  positives are saturated where same-family donors exist and absent where they do
  not.)

## 7. Method notes (reproducibility)

- Splits: `scripts/build_planner_blind_retrieval_splits.py` →
  `data/processed/planner_blind_{family_holdout,operation_holdout,kshot_0,kshot_1,kshot_2,literal_holdout}/`
  (leave-one-out folds carry a `manifest.json`; pooled over folds for the
  aggregate). Strategy code + invariants: `src/mini_elf_lean/retrieval_splits.py`.
- Eval: `scripts/evaluate_retrieval_v7.py` (orchestrated by
  `scripts/run_mini_elf_v7_eval.sh`); summary `scripts/summarize_v7.py`. Lean
  results cached, keyed by `(theorem_name, tactic)`, shared across runs.
- Abstraction: `src/mini_elf_lean/retrieval_abstraction.py` (primitives) +
  `src/mini_elf_lean/retrieval_abstraction_proposer.py` (re-ranker). Donor filters
  (`forbid_same_family/operation`) are opt-in flags on the v6 proposer — default
  off, so v6 results are byte-for-byte unchanged.
