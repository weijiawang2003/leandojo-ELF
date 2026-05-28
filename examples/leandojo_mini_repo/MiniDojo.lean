/-
Smallest possible LeanDojo-traceable library: a couple of *named* theorems with
no Mathlib dependency, so `lake build` + LeanDojo tracing are fast.

NOTE: LeanDojo locates a theorem by its fully-qualified name, so these must be
`theorem`s (an anonymous `example` cannot be targeted). The corresponding seed
in data/seeds/leandojo_seeds.jsonl uses `full_name = "id_of_p"` etc.
-/

theorem id_of_p (p : Prop) (h : p) : p := by
  exact h

theorem and_comm_toy (p q : Prop) (h : p ∧ q) : q ∧ p := by
  exact ⟨h.2, h.1⟩

theorem nat_refl (n : Nat) : n = n := by
  rfl
