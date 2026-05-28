#!/usr/bin/env bash
# Does disabling async elaboration restore elaboration-time stdin for a tactic?
set -uo pipefail
cd "$HOME/code/ELFMath/scripts"

mkdir -p /tmp/leanprobe
cat > /tmp/leanprobe/probe_async_setopt.lean <<'LEAN'
import Lean
open Lean Lean.Elab Lean.Elab.Tactic

elab "probe_repl" : tactic => do
  let line ← (← IO.getStdin).getLine
  IO.println s!"PROBE_GOT[{line.trim}] len={line.length}"
  (← IO.getStdout).flush

set_option maxHeartbeats 0 in
set_option Elab.async false in
theorem probe_thm (p : Prop) (h : p) : p := by
  probe_repl
  exact h
LEAN

cat > /tmp/leanprobe/probe_async_cli.lean <<'LEAN'
import Lean
open Lean Lean.Elab Lean.Elab.Tactic

elab "probe_repl" : tactic => do
  let line ← (← IO.getStdin).getLine
  IO.println s!"PROBE_GOT[{line.trim}] len={line.length}"
  (← IO.getStdout).flush

set_option maxHeartbeats 0 in
theorem probe_thm (p : Prop) (h : p) : p := by
  probe_repl
  exact h
LEAN

echo "=== (1) set_option Elab.async false in  [lean 4.20.0] ==="
echo "HELLO_SETOPT" | elan run leanprover/lean4:v4.20.0 lean /tmp/leanprobe/probe_async_setopt.lean 2>&1 | grep -E "PROBE_GOT|error" | head -5

echo "=== (2) CLI -D Elab.async=false  [lean 4.20.0] ==="
echo "HELLO_CLI" | elan run leanprover/lean4:v4.20.0 lean -D Elab.async=false /tmp/leanprobe/probe_async_cli.lean 2>&1 | grep -E "PROBE_GOT|error" | head -5

echo "=== (3) baseline (async on)  [lean 4.20.0] ==="
echo "HELLO_BASE" | elan run leanprover/lean4:v4.20.0 lean /tmp/leanprobe/probe_async_cli.lean 2>&1 | grep -E "PROBE_GOT|error" | head -5

rm -rf /tmp/leanprobe
echo "DONE"
