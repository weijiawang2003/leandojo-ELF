# V28 Part 0 — Repo / Environment Status

_Date: 2026-05-31. Branch: `v27-mathlib-specialist`._

This is the v28 baseline snapshot: the trusted-verifier toolchain, the external
Mathlib project, and the v27 results we must preserve or beat. v28 changes **no
git history** and makes **no commits** — it only adds scripts, data, docs, tests.

## Git state (left untouched on purpose)

```
$ git status -sb
## v27-mathlib-specialist
(many ?? untracked data/baselines/* and docs — pre-existing)
```

**Pre-existing stale rebase.** `.git/rebase-merge/` exists, dated **2026-05-28**
(three days before this session). `git status` reports *"currently editing a
commit while rebasing branch 'main' on '6852545'"*. This was **not** created by
v28 and is **left exactly as found**: the v28 task constraints explicitly forbid
abort/reset/rebase/commit and changing git history. None of the v28 work touches
git — all outputs are new files under `scripts/`, `data/`, `docs/`, `tests/`.
The interrupted rebase is a repo-hygiene item for the human to resolve; it does
not block v28 (the working tree is intact and all v27 artifacts are present).

## Toolchains

| Tool | Version |
|------|---------|
| `lean` (elan shim) | 4.30.0 (commit `d024af0`) |
| `lake` | 5.0.0-src+d024af0 (Lean 4.30.0) |
| Direct ELF binary | `~/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean` |

Verification always uses the **direct toolchain binary** with a precomputed
`LEAN_PATH` (cached at `.tmp/v27_lean_path.txt`), never the elan `lean` shim
(hang risk under sustained load — see project memory).

## External Mathlib project

`~/code/mini_elf_mathlib_probe` — a real, external Lake project pinning
`mathlib4 @ v4.30.0` (`lean-toolchain = leanprover/lean4:v4.30.0`). Mathlib is
**real and external**, not vendored or mocked. `LEAN_PATH` was resolved once via
`lake env printenv LEAN_PATH` and cached.

### Key lemmas confirmed present (for v28 categories)

```
@Set.mem_inter_iff   : x ∈ a ∩ b ↔ x ∈ a ∧ x ∈ b
@Set.union_subset    : s ⊆ r → t ⊆ r → s ∪ t ⊆ r
@Set.subset_inter    : r ⊆ s → r ⊆ t → r ⊆ s ∩ t
@Finset.mem_union    : a ∈ s ∪ t ↔ a ∈ s ∨ a ∈ t        [DecidableEq α]
@Finset.mem_inter    : a ∈ s₁ ∩ s₂ ↔ a ∈ s₁ ∧ a ∈ s₂    [DecidableEq α]
@Finset.subset_union_left : s₁ ⊆ s₁ ∪ s₂                [DecidableEq α]
@le_trans  / @le_refl : Preorder α
@min_le_left / @le_max_right : LinearOrder α
@Function.const
```

Design consequences for v28:
* **Finset** (new category C) theorems must carry a `[DecidableEq α]` binder.
* **General order/lattice** theorems need `[Preorder α]` / `[LinearOrder α]` /
  `[Lattice α]` binders (the v27 order category was Nat-only).

## Trusted verifier (canonical, unchanged from v27)

`mini_elf_lean.mathlib_batched_verifier.TrustedMathlibVerifier` — sentinel render
+ `confirm=True` success re-batching + lexer-poison rescue pass. **Sound and
complete**, gold-audited with zero mismatches in v27. `confirm=False` raises
(`UnsafeVerifierError`), so the unsound path is unreachable by accident. The
`NaiveBatchMathlibVerifier` exists only for the soundness regression test and
**must never** be used for headline metrics.

End-to-end smoke test run this session (real `import Mathlib` typecheck):

| theorem | tactic | verdict |
|---------|--------|---------|
| `x ∈ s ∩ t ↔ x ∈ s ∧ x ∈ t` | `exact Set.mem_inter_iff x s t` | ✅ verified |
| `s ⊆ u → t ⊆ u → s ∪ t ⊆ u` | `exact Set.union_subset h1 h2` | ✅ verified |
| `n + 1 = n` | `rfl` | ❌ rejected (correct) |

The verifier accepts the two known-good Mathlib proofs and correctly rejects the
false goal — sound and live.

## v27 baseline to preserve / beat

| Metric | v27 value | v28 target |
|--------|-----------|------------|
| Routed broad-core p@5 / p@10 | **0.9375 / 0.9583** | preserve (else don't adopt router) |
| v25 held-out pass@10 | **1.000** (`v27_category_balanced`) | preserve if possible |
| v26 holdout pass@10 | **0.955** (`v27_set_heavy`) | improve or preserve |
| v27 fresh holdout pass@10 | **0.714** (5/7 theorems) | **improve above 0.714** |

The v27 fresh-holdout plateau (0.714) is driven by exactly **2 of 7** theorems:

| theorem | family | v27 failure class |
|---------|--------|-------------------|
| `v27_set_mem_inter_iff` (`x ∈ s∩t ↔ x∈s ∧ x∈t`) | set / mem_iff | `unknown_identifier` (lemma vocabulary) |
| `v27_set_union_subset` (`s⊆u→t⊆u→s∪t⊆u`) | set / union_subset | `type_mismatch` (proof-shape / API arity) |

Both proofs exist and verify (smoke test above) — the model simply does not
**generate** a verifying candidate for these held-out shapes. v28's hypothesis:
more sibling shapes per family → better generalization to fresh holdouts.

## What v28 will NOT do (carried-forward invariants)

* No `state_after`. No manual oracle as model predictions. No v10 leakage.
* No claim of full theorem proving (single-tactic, tiny goals only).
* No naive batched verifier for headline metrics.
* No overwrite of the v24 broad-core model; no adoption of a router that
  regresses routed broad-core.
* No retcon of v24/v25/v26/v27 metrics.
