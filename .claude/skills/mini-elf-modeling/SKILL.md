---
name: mini-elf-modeling
description: PLACEHOLDER for future Mini-ELF embedded-flow tactic-generation modeling. DO NOT USE YET. This stage of the project is dataset infrastructure only; there is no model to build, train, or evaluate.
---

# Mini-ELF Modeling Skill (DO NOT USE YET)

> **Status: deferred. Do not act on this skill.**
>
> The current project stage is a verifier-filtered Lean tactic **trace data
> factory** — not modeling. This file exists only to reserve the name and
> record intent. If you are tempted to start modeling, stop and finish the
> dataset audit first.

## Hard rules for now

- Do NOT implement Mini-ELF.
- Do NOT implement diffusion or flow-model training.
- Do NOT start model architecture work.
- Do NOT claim any model results.

## When this skill becomes active (future)

Only after the dataset is honest about success rate, automation ratio, and
duplication, and a split-by-`theorem_name` train/val/test exists. Even then,
the first model should be an autoregressive next-tactic baseline, with
verifier-aware metrics (Lean parse rate, Lean execution rate) reported next to
token-level loss — before any embedded-flow / ELF model is attempted.

See `lean-trace-collector` and `tactic-data-quality` for the active skills.
