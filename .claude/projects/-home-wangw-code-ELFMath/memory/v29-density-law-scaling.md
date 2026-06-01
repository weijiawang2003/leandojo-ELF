---
name: v29-density-law-scaling
description: v29 derived the within-family sibling "density law" (pass@10 0.68→0.83→0.94 by training siblings) and scaled along it; fixed v28 residuals, lifted fresh holdout 0.867→0.933, broad-core preserved; cross-category transfer does NOT scale.
metadata:
  type: project
---

Mini-ELF v29 (completed 2026-05-31) turned the [[v28-data-scaling-breaks-plateau]]
hypothesis — improvement = **within-family sibling density**, not category transfer —
into a measured **density law**, then scaled along it.

**The density law (headline, two independent measurements):**
- cross-family (Part 1, 507 held-out evals binned by *effective* training density —
  siblings actually in the evaluating model's train set): pass@10 **0.684 (0) → 0.829
  (1–3) → 0.944 (4–6)**, monotone, reliable (≥0.9) at **~4 siblings**.
- causal (same hard lemma-binding families): **0.16–0.26 at density 0**
  (whole-category transfer) → **0.70 at density ~6** (family-density holdout).

**Corpus:** densified every sparse residual family to 7–16 verified siblings via
var-set × proof-head menus — **229 theorems → 492 verified rows, 0 coverage gaps**;
TrustedMathlibVerifier only; integrity **492/492**; gold sample **32/all-7-cats, 0
mismatches / 0 false positives** (0-mismatch invariant held v27→v28→v29).

**Results (`token_seq2seq_v29_general` recommended; `v29_set_finset_order_heavy`
strongest on structured benches):**
- **fresh v28 holdout 0.867 → 0.933** (heavy **0.967**); new **v29 holdout 1.000**;
  **v26 → 1.000**; v28 residuals `comp_assoc`/`antisymm` **FIXED**.
- routed broad-core **bit-for-bit 0.9375/0.9583** (v24 untouched, adopt_router=True);
  routed Mathlib tier-C **0.921** over **140** held-outs (up from v28's 0.918 on 73).
- **HONEST COST: v25 regressed 1.000 → 0.857** (2/14: `nat_add_assoc` needs
  `omega`, `set_empty_subset` needs `Set.empty_subset s` — correct tactics still
  verify but fell out of the top-10 beam under distribution shift; recoverable in v30).

**Key levers / gotchas for v30:**
- **Cross-category transfer does NOT scale** (set 0.237→0.292, finset 0.333→0.136,
  order 0.778→0.556) → spend density *within* each family; a new category needs its
  own ≥4–6 siblings before its held-out members work.
- **Balancing (capping) still ≤ general** everywhere; targeted **upsampling** (not
  capping) of weak structured cats helps → `set_finset_order_heavy` is a safe strict
  add. Unweighted `general` is the default. (built `v29_category_balanced` only as a
  labelled negative control.)
- **family_density-vs-low_density raw contrast is CONFOUNDED**: low_density families
  (`add_zero`/`append_nil`/`and_symm`) close by a universal tactic (simp/omega/rfl/
  tauto) at any density → they hit 1.0 even at density 0. Density matters only for
  **lemma-binding** families. Use the clean same-hard-family comparison.
- Remaining residuals (8) are **single-tactic data-bound** (6 vocab, 2 API, **0
  multi-step**) → LeanDojo next-state STILL premature. Hardest = the `_3`
  surface-token variants (`u,v` sets, element `w`/`hw`) of projection/membership
  families — density lifted them 0.25→0.70 but the last-mile binding under unusual
  identifiers still slips.
- A capacity probe (embed 128/hidden 192) was deemed unnecessary: the ~0.5M-param
  model still improved under data scaling → bottleneck is data, not capacity.

New code: `scripts/{audit_v29_family_density,audit_v29_sparse_residuals,
generate_v29_mathlib_density_corpus,verify_v29_mathlib_density_corpus,
build_v29_mathlib_dataset,train_v29_mathlib_specialist,
evaluate_v29_mathlib_specialists,evaluate_v29_routed_system,analyze_v29_density_law,
analyze_v29_remaining_failures}.py`, `src/mini_elf_lean/v29_mathlib_router.py`
(core→v24, mathlib→v29 specialist; no per-category route). 10 V29 docs; 7 v29 test
files (33 tests); full suite **1425 passed**. Git history untouched; stale
`.git/rebase-merge/` from 2026-05-28 still present and untouched (constraints forbid
abort/reset/rebase/commit). Builds on [[v28-data-scaling-breaks-plateau]],
[[v27-scaled-mathlib-specialist]], [[lean-verifier-use-direct-toolchain-binary]].
