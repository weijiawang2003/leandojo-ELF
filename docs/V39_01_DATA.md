# V39 Phase 1 — Data

Two corpora drive the night. **Track A** reuses the frozen v35 corpus (same vocab,
same 24-theorem verified tier) so the verified pass@k comparison and extensions are
apples-to-apples with v35–v37. **Track B** is a fresh LeanDojo scale corpus in its
own vocab/dev space for the scale arm (H1) and a wide data-constrained crossover (H2),
judged on a held-out LeanDojo dev set.

## Track A — existing v35 corpus (the U-floor)
- `data/processed/v35_elf_flow/`: **3689 train** rows (1567 unique theorem-states, 891
  unique tactics), 456 val, 497 test. vocab 377; `max_cond_len 96`, `max_tgt_len 32`.
- U-ladder = nested random subsets (seed 3407): **{461, 922, 1844, 3689}** (8× span).
- Dev = the val split (456, theorem-disjoint from train; **empirically 0 overlap** with
  the 24-tier — confirmed by the code review). Verified eval = the 24-theorem Mathlib tier.

## Track B — LeanDojo Benchmark 4 (scale corpus)
**Source (acquired, MD5-verified):** LeanDojo Benchmark 4, Zenodo record 15382959,
`leandojo_benchmark_4.tar.gz` (85.7 MB, md5 `1c7c4727…`), **random split** (theorem-disjoint
train/val/test). Mathlib4 v4.19.0. `random/train.json` = 145,520 theorems, 76,343 with
proofs, **321,554 traced tactic steps**.

**Field mapping → v38_data format** (documented deviation): LeanDojo entries have no clean
statement string, so `theorem_statement := full_name` and `state_before := step.state_before`,
i.e. `build_input_text = "{full_name}\n{state_before}"`, target = `step.tactic`. This is
standard proof-state→tactic prediction (the state carries the goal). `state_after` never read.

**Cleaning (builder `scripts/v39_build_leandojo.py`, seed 3407):**
| stage | train | dev (val split) |
|-------|-------|-----|
| raw tactic steps | 321,554 | (val) |
| drop `sorry`/`admit`/empty | included below | |
| drop cond > 128 tok (filter, not truncate) | −190,877 | −2,514 |
| drop tactic > 38 tok | −8,769 | −118 |
| dedup exact (state_before, tactic) | −563 | |
| decontaminate vs 24-tier (full_name OR state) | **−0** | |
| **kept (MAX)** | **121,345** | **1,599** |

- Cond ≤128 / tac ≤38 keeps 41% of steps — the long-state tail (median cond-len 151 tok) is
  excluded rather than truncated, so nothing is silently cut. Track B therefore uses its own
  cfg (`max_cond_len 128`, `max_tgt_len 40`, seq 168 vs Track A's 128).
- **Vocabulary (train-only, freq-capped min_count=2):** 55,303 tokens (full unique-token vocab
  would be larger; rare hapax identifiers → `<unk>`). **OOV(unk) token rate: train 0.21%,
  dev 1.06%** — clean.
- **Decontamination: 0 dropped** — the 24-tier uses synthetic theorem names (`v26_…`) that do
  not collide with real Mathlib `full_name`s; guardrail 5 satisfied with zero loss.
- U-ladder = nested subsets **{4000, 16000, 64000, 121345}** (30× span). Dev = the 1,599
  held-out LeanDojo theorems (disjoint from train).

**Fingerprints** (`data/v39/corpora/leandojo/fingerprints.json`):
train sha256 `caaf2e31…`, dev sha256 `954670b6…`, n_train 121,345, n_dev 1,599, vocab 55,303.

**Honesty note:** Track B is **not** verified on the 24-tier (different vocab + conditioning
distribution); H1 is judged on Track B dev exact-seq, exactly the brief's H1 criterion. The
corpus jsonl + vocab are gitignored (large); the builder, manifest, and fingerprints are committed.
