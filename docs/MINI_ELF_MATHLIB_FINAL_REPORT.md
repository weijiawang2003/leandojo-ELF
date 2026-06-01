# Mini-ELF-Lean: A Routed Single-Tactic Mathlib Specialist with Theorem-Level Verification

_Final consolidated report for the Mathlib specialist phase (v24 → v33).
Packaging milestone: v34. All metrics are read from the recorded baseline JSONs
under `data/baselines/`; nothing here is re-derived or rounded up._

---

## 1. Abstract

Mini-ELF-Lean predicts a **single Lean 4 tactic** that closes a given proof goal,
and checks each prediction by **compiling it against real `import Mathlib`**
(Lean toolchain v4.30.0). Starting from a broad-core tactic model (v24) that does
**not** transfer to Mathlib (zero-shot tier-C pass@10 = 0.571), we show that
**co-training cannibalizes the broad-core model** (v25: Mathlib 0.556→0.786 but
broad-core 0.9375→0.833) and that a **specialist + router** architecture instead
preserves broad-core **bit-for-bit** while lifting the Mathlib tier. We then
characterize and remove the two ceilings on single-tactic Mathlib success: a
**within-family density law** (≈4–6 training siblings needed for reliable ≥0.9
held-out pass@10) and a **surface-token coverage ceiling**, the latter removed by
a **safe identifier canonicalization** (not generation-time placeholders). After
adversarial-identifier stress-testing and a final coverage pass, all six
single-tactic benchmarks reach **pass@10 = 1.00** with **0 residuals**, routed
broad-core stays at **0.9375/0.9583**, and routed tier-C reaches **0.992 over 244
held-outs**. Every remaining routed miss is a **single-tactic** data/API gap; **no
multi-step / proof-state residual exists**, so LeanDojo next-state work is not
yet justified. We make **no full-theorem-proving claim**: the system predicts one
verified tactic, not a complete multi-step proof search.

## 2. Problem setting

- **Task.** Given a Mathlib goal (theorem statement + `state_before`), generate a
  ranked list of candidate **single tactics**; score with pass@k.
- **Verification.** A candidate is *correct* iff it compiles: we build a `.lean`
  file with `import Mathlib`, the theorem, and the candidate tactic, and run the
  pinned Lean v4.30.0 toolchain binary. Verification is **theorem-level /
  tactic-closes-goal**, performed by `TrustedMathlibVerifier` (see §5).
- **No `state_after`.** Training and evaluation never use the post-tactic proof
  state. The model conditions only on the statement and the pre-state; we do not
  learn or exploit state transitions.
- **Not full theorem proving.** We do **not** perform multi-step proof search,
  backtracking, or proof-state-conditioned planning. "Solved" means a single
  predicted tactic closes the goal under real Mathlib. Multi-step proofs are out
  of scope for this phase (see §7, §8).

## 3. System evolution

1. **Broad-core model (v24).** A token-level seq2seq tactic predictor (bi-GRU +
   additive attention, ~0.5 M params) trained on the broad (non-Mathlib) tactic
   corpus. Strong on its own domain (0.9167/0.9375), but Mathlib zero-shot is only
   0.571 — it does not transfer.
2. **Mathlib tier-C probe (v25).** Confirmed the gap and tested co-training:
   augmenting the broad model with Mathlib rows lifted Mathlib (0.556→0.786) **but
   regressed broad-core to 0.833** — co-training cannibalizes the protected model.
3. **Specialist + router (v26).** Train a *separate* Mathlib specialist; route
   core theorems to the untouched v24 model and Mathlib theorems to the
   specialist. Routed broad-core returns to **0.9375/0.9583**; tier-C 0.917.
4. **Trusted verifier (v27).** Replace the unsafe naive batched verifier with
   `TrustedMathlibVerifier` (sentinel + confirm + rescue; sound & complete);
   scaled Set/order families (`set_heavy`).
5. **Finset + density scaling (v28).** Densifying sibling shapes broke the v27
   fresh-holdout plateau (0.714→0.857).
6. **Density law (v29).** Quantified it: held-out pass@10 rises ≈0.68→0.83→0.94
   as training siblings go 0→1–3→4–6; reliable ≥0.9 at ≈4 siblings. The effect is
   **within-family density**, not whole-category transfer.
7. **Targeted repair (v30).** Used the law as a construction rule to recover the
   v25 micro-regression (0.857→1.000) by densifying only sparse families.
8. **Identifier canonicalization (v31).** Removed the surface-token ceiling by
   mapping binder identifiers to valid Lean names (`c0,c1,…`), decoding, then
   **concretizing-or-rejecting** before the verifier, **unioned** with the raw
   v30 fallback. Residuals 13→1; tier-C 0.985. **Not** v19 generation-time
   placeholders.
9. **Adversarial robustness (v32).** Stress-tested with never-seen identifiers
   (`h_left`, `φψχ`, subscripts): raw 0.26 vs canonical 0.89 vs augmentation-only
   0.28 — canonicalization *generalizes*, memorization does not.
10. **Saturation (v33).** Diagnosed the residual 0.89 as a **parser-coverage bug**
    (subscript `proof₁` not recognized as a binder); a one-line decode fix lifted
    adversarial stress 0.891→1.00 for **every** canonical model with **zero
    retraining**. A small residual-coverage corpus closed the fresh shapes. All
    six benches → 1.00, 0 residuals.

## 4. Main results table

All numbers recorded in `data/baselines/`. Routed broad-core is the **same
48-theorem** held-out set every version. Routed tier-C `n` **grows** as each
version contributes held-outs, so tier-C pass@10 is comparable only at fixed `n`
(v33's 0.992 is over the largest, hardest set).

| Ver | Milestone | Broad-core (own domain / routed) | Mathlib tier-C pass@10 (n) |
|---|---|---|---|
| v24 | broad-core, protected | 0.9167 / 0.9375 (standalone) | zero-shot **0.571** |
| v25 | probe + co-train | co-trained broad-core **0.833** (regressed) | zero-shot 0.556 → augmented **0.786** |
| v26 | specialist + router | routed **0.9375 / 0.9583** | **0.917** (36) |
| v27 | trusted verifier + Set/order | routed **0.9375 / 0.9583** | **0.907** (43) |
| v28 | Finset + density | routed **0.9375 / 0.9583** | **0.918** (73) |
| v29 | density law | routed **0.9375 / 0.9583** | **0.921** (140) |
| v30 | targeted repair | routed **0.9375 / 0.9583** | **0.921** (165) |
| v31 | canonicalization | routed **0.9375 / 0.9583** | **0.985** (131) |
| v32 | stress | routed **0.9375 / 0.9583** | **0.950** (202) |
| v33 | saturation | routed **0.9375 / 0.9583** | **0.992** (244) |

**v33 single-tactic benches (all pass@10 = 1.00, model `v33_general_residual`):**
v25-heldout · v28-holdout · v29-holdout · token-diversity · adversarial-stress
(46/46) · fresh-robustness (42/42). 0 no-verified, 0 residuals.

**v33 routed tier-C per category (n=244):** nat 1.00, logic 1.00, function 1.00,
order 1.00, finset 1.00, bool/option 1.00, set 0.987 (78), list 0.941 (17).

**The single parser-coverage fix (v33):** re-evaluating the *unchanged*
`v31_canonical_general` weights with the hardened decode lifts adversarial-stress
**0.891 → 1.00** — evidence the 0.89 was a decode bug, not a model-capacity limit.

## 5. Scientific conclusions

1. **Co-training cannibalizes broad-core.** A single shared model cannot serve
   both domains without regression (v25: broad-core 0.9375→0.833).
2. **Specialist + router works.** Isolating the Mathlib specialist behind a router
   preserves broad-core **bit-for-bit** (0.9375/0.9583 unchanged v26→v33) while
   the specialist tier improves independently. The router is an engineering
   switch, not a learned classifier on the headline path.
3. **A trusted verifier is essential.** Headline metrics require a sound &
   complete verifier (`TrustedMathlibVerifier`); the naive batched verifier is
   used only for internal speed tests, never for reported numbers. 0 gold
   mismatches maintained project-long.
4. **Within-family density beats whole-category transfer.** Held-out success is
   driven by how many *sibling shapes of the same family* appear in training, not
   by category-level volume. Cross-category transfer does **not** scale (v29).
5. **The density threshold is ≈4–6 siblings** for reliable ≥0.9 held-out pass@10
   (law: ≈0.68 → 0.83 → 0.94 for 0 → 1–3 → 4–6 siblings).
6. **Surface-token canonicalization removes the OOD-identifier ceiling.** Mapping
   binders to canonical names + concretize-or-reject + raw-fallback union makes
   generation identifier-invariant **and generalizes** to never-seen identifiers
   (v32: 0.26→0.89; v33 parser fix →1.00) — without v19's failed
   generation-time placeholders.
7. **The remaining residuals are single-tactic data/API, not proof-state.** Every
   characterized failure is an unknown identifier, wrong namespace/API choice,
   parser coverage, or a sparse sibling family — all fixable with data/coverage.
   **No multi-step / proof-state wall was found.**

## 6. Failure modes

| Class | Example | Status at v33 |
|---|---|---|
| Unknown identifier (OOD binder) | `proof₁`, `φ`, `h_left` not seen in training | **closed** by canonicalization + hardened decode |
| Wrong namespace / API | `Set.empty_inter` vs `Set.inter_empty` etc. | reduced by residual-coverage corpus; minor residual |
| Parser / canonicalization coverage | subscript `₁` outside the identifier regex | **closed** by the v33 `_IDENT` fix (additive) |
| Sparse sibling family | a shape with <4 training siblings | **closed** by density-targeted construction |
| Multi-step / proof-state | a goal needing ≥2 chained tactics | **none observed** in any benchmark |

The ~2/244 routed tier-C misses (list/set) are sparse single-tactic shapes —
density/coverage gaps, addressable with more verified siblings, not architecture.

## 7. Limitations

- **Theorem-level verification only.** Correctness = "a single tactic compiles and
  closes the goal," not a verified multi-step proof.
- **No true proof-state transition.** We never condition on or predict
  `state_after`; the system has no proof-state model.
- **No LeanDojo next-state work.** Deliberately deferred — no multi-step residual
  exists to justify it (§5.7, §8).
- **A curated Mathlib tier, not all of Mathlib.** The benchmark is a curated
  single-tactic tier-C across a fixed set of categories (nat/list/set/finset/
  order/function/logic/bool-option), not the full Mathlib distribution.
- **Single-tactic focus.** Multi-tactic proofs are out of scope for this phase.
- **External Mathlib scratch.** Mathlib v4.30.0 lives in an external 7.0 GB
  project (`~/code/mini_elf_mathlib_probe`) outside the repo; reproduction
  requires that environment (see `docs/REPRODUCIBILITY.md`).

## 8. Future work

- **Build a genuine multi-step Mathlib benchmark.** The current tier is
  single-tactic-saturated; the next scientific frontier is goals requiring chained
  tactics — which would be a **new corpus**, not a fix to this one.
- **Revisit LeanDojo next-state only when multi-step residuals exist.** With a
  real proof-state transition signal, next-state conditioning becomes meaningful;
  until then it adds machinery without a failure to address.
- **Larger / more Mathlib categories.** Extend beyond the curated tier toward the
  full Mathlib identifier and lemma distribution.
- **Automated family discovery.** The density law is currently applied with
  hand-identified families; learn family membership to target densification
  automatically.
- **Release engineering.** Git cleanup (done in v34), artifact-size policy for the
  large `data/models`/`data/baselines`/`data/processed` trees, and CI that runs
  the verifier smoke test (see `docs/V34_COMMIT_PLAN.md`,
  `docs/REPRODUCIBILITY.md`).

---

_Constraints honored throughout: real `import Mathlib`; `TrustedMathlibVerifier`
only for headline metrics; no `state_after`; no manual-oracle candidates as model
predictions; no revived v10 leakage; v24 broad-core never overwritten; no category
balancing; no full-theorem-proving claim; no v19 placeholder decoding._
