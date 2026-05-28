-- Reference Lean 4 source for the seeds in
-- data/seeds/toy_lean_cli_seeds.jsonl. Each `example` here corresponds to one
-- seed; the body shows a tactic that would close the goal. LeanCliRunner
-- builds files with the same shape, substituting an LLM-proposed tactic in
-- place of the placeholder.
--
-- None of these need Mathlib: a default `elan` toolchain with Lean 4 should
-- typecheck this file as-is via `lean examples/toy_lean_cli_theorems.lean`
-- (or `lake env lean ...` inside a Lake project).

example (n : Nat) : n + 0 = n := by
  rfl

example (p : Prop) (h : p) : p := by
  exact h

example (p q : Prop) (h : p) : p := by
  exact h

example : True := by
  trivial

example (n : Nat) : n = n := by
  rfl
