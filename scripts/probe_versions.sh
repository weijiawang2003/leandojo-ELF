#!/usr/bin/env bash
# Test whether an elab-tactic's IO.getStdin.getLine reads piped stdin, across
# Lean toolchains. Run: bash scripts/probe_versions.sh
set -uo pipefail
cd "$HOME/code/ELFMath/scripts"

echo "=== default lean (PATH) version ==="
lean --version || true

echo
echo "=== default lean: echo HELLO | lean probe.lean ==="
echo "HELLO_DEFAULT" | lean probe.lean 2>&1 | head -20

echo
echo "=== try elan toolchains available ==="
elan toolchain list 2>&1 | head -20

for TC in leanprover/lean4:v4.20.0 leanprover/lean4:v4.30.0; do
  echo
  echo "=== $TC: echo HELLO | lean probe.lean ==="
  if elan run "$TC" lean --version >/dev/null 2>&1; then
    echo "HELLO_$TC" | elan run "$TC" lean probe.lean 2>&1 | head -20
  else
    echo "(toolchain $TC not installed)"
  fi
done
echo "DONE"
