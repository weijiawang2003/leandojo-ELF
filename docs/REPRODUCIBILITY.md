# Reproducibility — Mini-ELF-Lean (Mathlib specialist phase, v24 → v33)

Exact commands to reproduce the headline results, with the numbers you should
see. All paths are relative to the repo root `~/code/ELFMath` unless absolute.

> **Two interpreters.** ML / eval / audit scripts import the `mini_elf_lean`
> stack (pydantic + torch) and **must** run under `.venv/bin/python`. The Lean
> verifier alone works under plain `python3`. When in doubt, use `.venv/bin/python`.

## 0. Environment

| Component | Value |
|---|---|
| Python env | `.venv/` (created via `python -m venv .venv && .venv/bin/pip install -e .[dev,ar]`) |
| Lean toolchain | **v4.30.0**, direct binary `$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean` (never the elan `lean` shim — it hangs under sustained load) |
| External Mathlib scratch | `~/code/mini_elf_mathlib_probe` (~7.0 GB; its **own** project, outside this repo; built with `lake exe cache get` for Mathlib v4.30.0) |
| Cached Mathlib `LEAN_PATH` | `.tmp/v27_lean_path.txt` (passed to evals via `--lean-path-file`) |

The verifier uses a **precomputed `LEAN_PATH`** (one `lake env printenv` call) +
the direct binary, instead of `lake env lean` per candidate (which is ~60× slower
and prone to WSL2 hangs). See `src/mini_elf_lean/mathlib_verifier.py`.

## 1. Verify the Mathlib environment

```bash
# external scratch project present?
ls -d ~/code/mini_elf_mathlib_probe && du -sh ~/code/mini_elf_mathlib_probe   # ~7.0G

# Lean v4.30.0 binary present?
$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean --version          # Lean 4.30.0

# cached LEAN_PATH present? (regenerate if missing/stale — the ONLY `lake` call)
cat .tmp/v27_lean_path.txt
#   regenerate:
cd ~/code/mini_elf_mathlib_probe && lake env printenv LEAN_PATH \
    > ~/code/ELFMath/.tmp/v27_lean_path.txt
```

If the scratch project or binary is absent, the Mathlib-dependent tests
**auto-skip** (3 skipped) and the eval scripts below cannot run — but the rest of
the suite still passes.

## 2. Run the tests

```bash
.venv/bin/python -m pytest -q
```

**Expected: `1511 passed, 3 skipped`** (1514 collected). The 3 skips are the
LeanDojo `run_tac` / smoke tests that require an unblocked LeanDojo backend.

## 3. Reproduce the v33 routed-system eval (headline)

```bash
.venv/bin/python scripts/evaluate_v33_routed_system.py
# writes data/baselines/v33_routed_system/{comparison,broad_core_metrics,tierc_metrics}.json
```

**Expected (`comparison.json`):**

- routed **broad-core p@5 / p@10 = 0.9375 / 0.9583** (`preserves_v27_routed_bar:
  true`, `adopt_router: true`)
- routed **tier-C pass@10 = 0.992 over 244** held-outs (`tierc.n = 244`)
- `broad_core_preserved.no_regression: true` (vs v24 standalone 0.9167 / 0.9375)
- routing: `broad_to_core = 48/48`, `tierc_to_specialist = 244/244`

This is also the **broad-core preservation check**: the routed broad-core numbers
equal the v24 model routed bar exactly (v24 is never retrained; core theorems are
routed to it untouched).

## 4. Reproduce the v33 specialist eval (all six benches → 1.00)

```bash
.venv/bin/python scripts/evaluate_v33_mathlib_specialists.py
# writes data/baselines/v33_specialist_eval/
```

**Expected:** `v33_general_residual` = **pass@10 1.00 on all six benches**
(v25-heldout, v28-holdout, v29-holdout, token-diversity, adversarial-stress 46/46,
fresh-robustness 42/42), **0 no-verified**. ~5952 pairs, TrustedMathlibVerifier.

## 5. Reproduce the trusted-verifier gold sample (soundness & completeness)

```bash
.venv/bin/python scripts/audit_v27_verifier_soundness.py
# writes data/baselines/v27_verifier_soundness/report.json
```

**Expected: 0 mismatches** between `TrustedMathlibVerifier` (sentinel + confirm +
rescue, the batched headline verifier) and `GoldMathlibVerifier` (batch_size=1
ground truth). The naive batched verifier is **never** used for headline metrics.
Per-corpus gold re-checks also run inside `scripts/verify_v{27..30}_*_corpus.py`
(`GoldMathlibVerifier`), all reporting 0 false positives.

## 6. Reproduce the saturation analysis (the v34 stop-modeling decision)

```bash
.venv/bin/python scripts/analyze_v33_single_tactic_saturation.py
# writes data/baselines/v33_saturation/report.json
```

**Expected:** `saturation_strong: true`, `any_multi_step: false`,
`leandojo_next_state_relevant: false`, `n_remaining_failures: 0`,
`v34_decision` = "PACKAGING / paper-style report / git recovery".

## 7. Artifact inventory (no Mathlib needed)

```bash
python3 scripts/inventory_v34_artifacts.py
# writes data/baselines/v34_inventory/inventory.json ; see docs/V34_ARTIFACT_INVENTORY.md
```

## Expected-numbers cheat sheet

| Check | Command | Expected |
|---|---|---|
| Tests | `.venv/bin/python -m pytest -q` | **1511 passed, 3 skipped** |
| Routed broad-core | §3 | **0.9375 / 0.9583** (p@5 / p@10) |
| Routed tier-C | §3 | **0.992 over 244** |
| Specialist benches | §4 | **1.00** on all 6, 0 no-verified |
| Verifier soundness | §5 | **0 mismatches** |
| Saturation | §6 | `saturation_strong: true`, 0 multi-step |

## Notes & caveats

- The eval scripts (§3–§6) run **hundreds of real `import Mathlib` compilations**
  and take minutes (the v33 specialist eval ≈ 400 s). They require `.venv`, the
  external scratch, and the Lean binary.
- Results are **theorem-level / single-tactic**: a candidate is correct iff the
  whole `.lean` file typechecks. There is **no** `state_after` and **no** full
  multi-step proof search — see `docs/MINI_ELF_MATHLIB_FINAL_REPORT.md` §2, §7.
- The external Mathlib scratch is intentionally **not** part of this repo (it is a
  separate 7.0 GB Lake project); see `docs/V34_ARTIFACT_INVENTORY.md`.
