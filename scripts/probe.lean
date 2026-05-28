import Lean
open Lean Lean.Elab Lean.Elab.Tactic

elab "probe_repl" : tactic => do
  let stdin ← IO.getStdin
  let line ← stdin.getLine
  IO.println s!"PROBE_TACTIC_GOT[{line.trim}] len={line.length}"
  (← IO.getStdout).flush

set_option maxHeartbeats 0 in
theorem probe_thm (p : Prop) (h : p) : p := by
  probe_repl
  exact h
