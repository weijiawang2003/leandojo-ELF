-- Toy Lean 4 theorems used as seeds for sanity tests against the
-- MockLeanRunner. None of these need a real Lean toolchain to drive the
-- pipeline -- the mock backend has hand-written rules for `rfl`, `intro`,
-- `simp`, etc. When the LeanDojo backend is wired up, the same theorem
-- declarations can be re-used directly.

theorem refl_nat : 1 + 1 = 2 := by
  rfl

theorem id_implication (p : Prop) : p -> p := by
  intro hp
  exact hp

theorem and_comm_toy (p q : Prop) : p /\ q -> q /\ p := by
  intro h
  exact ⟨h.2, h.1⟩

theorem trivial_true : True := by
  trivial
