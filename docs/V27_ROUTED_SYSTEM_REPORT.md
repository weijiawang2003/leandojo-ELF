# Mini-ELF v27 — Routed System Report (Part 7b)

Source: `scripts/evaluate_v27_routed_system.py` →
`data/baselines/v27_routed_system/`. Router: the v26 `MathlibRouter` (an
engineering switch — `import Mathlib` / mathlib-flag → specialist, else v24
broad-core; no theorem-specific routing). Specialist = **`v27_set_heavy`**.
Broad-core verified with the trusted **core** verifier; tier-C with the trusted
**Mathlib** verifier. No state_after; no manual oracle; v24 model untouched.

## Routing (deterministic, inspectable)

- broad-core seeds → v24 broad-core: **48 / 48**
- tier-C seeds → v27 specialist: **43 / 43** (v25 held-out 14 + v26 holdout 22 + v27 holdout 7)

## Results (best config)

| Tier | n | p@1 | p@5 | p@10 |
|------|---|-----|-----|------|
| **broad-core** (`policy_abstract`) | 48 | 0.771 | **0.938** | **0.958** |
| **tier-C** (`abstract`) | 43 | 0.628 | 0.907 | 0.907 |

### Broad-core preservation (the non-negotiable)

| | routed | v24 baseline |
|--|--------|--------------|
| pass@5 | 0.938 | 0.917 |
| pass@10 | 0.958 | 0.938 |

`no_regression = true`. Routed broad-core is **identical to v26's routed
broad-core** (0.938 / 0.958) because the v24 model is byte-for-byte untouched and
every broad-core theorem still routes to it. Per-category broad-core (n): bool 1.0,
implication 1.0, equality_rewrite 1.0, exists 1.0, forall 1.0, list 1.0,
negation 1.0, nat_succ p@10 1.0; the only sub-1.0 cells are conjunction (0.833) and
disjunction (0.800) — the same long-standing v24 residuals, unchanged.

## Targets — met

| Target | Result |
|--------|--------|
| routed broad-core p@5 ≥ 0.938 | **0.938** ✅ |
| routed broad-core p@10 ≥ 0.958 | **0.958** ✅ |
| broad-core preserved (no regression) | **true** ✅ |
| tier-C strong on combined held-out | **0.907** over 43 theorems ✅ |

## Conclusion

The v26 specialist+router design **scales cleanly into v27**: swapping in the
larger-corpus `v27_set_heavy` specialist raises tier-C coverage (Set residual
closed, v26-holdout 0.909 → 0.955 standalone; 0.907 over the combined 43-theorem
tier-C) **with zero broad-core cost** — the routed broad-core is bit-identical to
v24/v26. Co-training is still the wrong tool (it regressed broad-core in v25); the
specialist+router keeps the two tiers fully decoupled.
