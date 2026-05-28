# leandojo_mini_repo

The smallest possible Lean 4 library for a **real LeanDojo smoke test**: a few
named theorems, no Mathlib, so `lake build` and LeanDojo tracing are fast.

This directory is a self-contained Lean package. To use it with LeanDojo you
push it to a git host (or trace a local clone) and point a seed at it. Full
walkthrough: [`../../docs/LEANDOJO_SETUP.md`](../../docs/LEANDOJO_SETUP.md).

```bash
lake build          # sanity-check it compiles (works on any OS, incl. Windows)
```

Theorems (all in `MiniDojo.lean`, so `file_path = "MiniDojo.lean"`):

| full_name      | statement                              |
| -------------- | -------------------------------------- |
| `id_of_p`      | `(p : Prop) (h : p) : p`               |
| `and_comm_toy` | `(p q : Prop) (h : p ∧ q) : q ∧ p`     |
| `nat_refl`     | `(n : Nat) : n = n`                    |

> LeanDojo itself does **not** run on native Windows (it needs a Unix PTY).
> Build/trace this on Linux, macOS, or WSL.
