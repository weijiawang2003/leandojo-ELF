---
name: tactic-data-quality
description: Use when cleaning, evaluating, filtering, or splitting Lean tactic trace datasets. Audits traces instead of blindly training on garbage.
---

# Tactic Data Quality Skill

Use this skill when cleaning, evaluating, filtering, or splitting Lean tactic trace datasets.

## Goal

Produce a clean verifier-filtered dataset suitable for next-tactic prediction, tactic-block generation, and later Mini-ELF embedded-flow modeling.

## Required Checks

For every trace file, report:

- total records
- successful transitions
- failed attempts, if present
- success rate
- unique theorem names
- unique states
- unique tactics
- top 20 tactics
- proof_finished count AND ratio
- average goals before
- average goals after
- goal reduction rate
- state_changed rate
- automation tactic ratio
- duplicate transition ratio
- backend distribution
- model / source distribution
- prompt_style distribution

Never claim a dataset is good from record count alone. `scripts/evaluate_traces.py` computes all of the above plus honesty warnings (all-mock data, high automation, high duplication, lean-cli placeholder states).

## Automation Tactics

Track tactics such as:

- simp
- simp_all
- aesop
- omega
- linarith
- nlinarith
- ring
- norm_num
- exact?
- apply?
- grind

Do not automatically delete them. Mark them and allow filtering/ablation.

## Dataset Split Rule

Split train/val/test by `theorem_name`, not by individual transition, whenever `theorem_name` is available. This prevents transitions from the same proof from leaking across splits.

## Filtering Options

Support filters for:

- exclude automation tactics
- include only `proof_finished`
- include only goal-reducing transitions
- max tactic length
- max state length
- remove duplicate `state_before` + `tactic` pairs
- remove forbidden tactics: `sorry`, `admit`, `unsafe`

## Reporting Rule

Never claim dataset quality based only on record count. Always discuss:

- success rate
- automation ratio
- duplication
- theorem-level coverage

## Do Not

- Do not train on failed attempts as positive labels.
- Do not delete failed attempts; they are useful for analysis.
- Do not split by transition when theorem_name is known.
- Do not silently drop forbidden tactics without logging counts.
