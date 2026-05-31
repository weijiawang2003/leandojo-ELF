# V25 Mathlib environment report (Part 1)

Probe driver: [`scripts/probe_v25_mathlib_env.py`](../scripts/probe_v25_mathlib_env.py).
Machine-readable result: `data/baselines/v25_mathlib_env_probe.json`.

## Result: **Mathlib is available.** ✅

Mathlib **v4.30.0** (commit `c5ea00351c28e24afc9f0f84379aa41082b1188f`) imports
and typechecks against our installed Lean **4.30.0** toolchain. v25 therefore
proceeds down the **real-Mathlib** path (Part 2A), **not** the core-Lean
surrogate fallback.

## Paths tested, in order

### A. Existing repo Mathlib — **not available** (expected)

- The only in-repo Lean project, `examples/leandojo_mini_repo`, is a minimal
  standalone lib with **no** Mathlib dependency.
- `lake env lean --version` there → Lean 4.30.0 (rc 0).
- Compiling `import Mathlib` there → **rc 1**, verbatim:
  `unknown module prefix 'Mathlib' … No directory 'Mathlib' or file
  'Mathlib.olean' in the search path`.
- So the repo gives no Mathlib, as designed. **The main repo's lake setup was
  not modified** to obtain Mathlib.

### B. Scratch project outside the repo — **available** ✅

Created at `../mini_elf_mathlib_probe` (i.e. `/home/wangw/code/mini_elf_mathlib_probe`,
**outside** `ELFMath`), via `--init-scratch`:

- `lean-toolchain` → `leanprover/lean4:v4.30.0` (matches the installed toolchain;
  no new toolchain download).
- `lakefile.toml` requires `mathlib` from
  `https://github.com/leanprover-community/mathlib4` at **`rev = "v4.30.0"`** —
  the Mathlib tag pinned to exactly `leanprover/lean4:v4.30.0`.
- A trivial root module `MiniElfMathlibProbe.lean`.

The first `lake env` invocation in that directory **auto-resolved the manifest,
cloned Mathlib + transitive deps, and fetched the prebuilt olean cache from the
Azure mirror** — `Attempting to download 8459 file(s) from
leanprover-community/mathlib4 cache … Decompressed 8459 file(s)` (~107 s, no
from-source build). Resolved package revs (`lake-manifest.json`):

| package | rev (12) |
|---|---|
| mathlib | `c5ea00351c28` |
| batteries | `32dc18cde368` |
| aesop | `558915ae105b` |
| Qq | `a6e6c34c4ef1` |
| proofwidgets | `a84b3e2475d5` |
| importGraph | `515cf9d0c00e` |
| plausible | `a456461b368b` |
| LeanSearchClient | `c5d5b8fe6e51` |
| Cli | `6b907cf12b2e` |

On-disk olean cache: **7.4 G** under `.lake/`.

Verified imports (all rc 0):

- `import Mathlib` + `example (n : Nat) : n + 0 = n := by simp` — full umbrella
  import, ~13.7 s cold / **5.5 s warm**.
- `import Mathlib.Logic.Basic` + `example (p : Prop) (h : p) : p := h` — single
  leaf module, **1.2 s**.
- Independent re-confirmation (outside the probe script):
  `example (a b : Nat) : a + b = b + a := by exact Nat.add_comm a b` and
  `example (xs : List Nat) : xs ++ [] = xs := by simp` both typecheck.

### C. Failure path — **not taken**

No install failure occurred, so the Part 2B core-Lean surrogate fallback is not
used. (Had it failed, the exact stderr would have been recorded here and the
surrogate run instead — nothing would have been faked.)

## How v25 verifies Mathlib-tier candidates

Mathlib candidates are verified with `LeanCliRunner(command="lake env lean",
working_dir=<scratch>)` + a `TheoremSeed` carrying the needed `import …` lines —
i.e. whole-file typecheck inside the scratch project so Mathlib oleans resolve.
This is the same coarse-grained "the file typechecks ⇒ the tactic is accepted"
contract used since the basic corpus; **no state_after, no manual oracle, no
mock verification.**

Note: the scratch project lives **outside** the ELFMath repo and its 7.4 G
`.lake/` cache is **not** committed or added to the repo. The repo only stores
the resulting seeds / candidates / verified traces (text JSONL).

## Confirmation

- ✅ Mathlib genuinely imports and typechecks; result is **not** mocked.
- ✅ main repo lake setup untouched; scratch project is external.
- ✅ pinned toolchain binary used for non-lake probes; `lake env lean` used for
  Mathlib (it must, to resolve the Mathlib search path).
- ✅ no state_after, no manual-oracle-as-prediction, no v10 leakage.
