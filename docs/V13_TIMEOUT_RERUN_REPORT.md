# Mini-ELF v13 — Warm Verifier Rerun Report

**Status:** complete (warm-verifier rerun only — no model retraining).
**Scope:** revisit every v12 timeout candidate with a higher per-tactic
lean-cli timeout (`120 s`) and a one-shot warm-up theorem to pay the
lean cold-start / JIT cost up front.

**v13 brief, verbatim:** *"Resolve verification-timeout uncertainty
first, then evaluate whether tokenizer/BPE is needed. Do not change
model architecture before rechecking the timeout cases. Do not retcon
previous metrics silently."*

This is a pure **evaluation-reliability fix** — the model is byte-for-byte
identical to v12. Headline gains on forall_inst and rewrite_succ come
from removing the 20-second wall-clock noise floor, not from new candidate
synthesis.

---

## 0. TL;DR

| metric | v12 original lower bound | v13 warm-verifier corrected | Δ |
|---|---:|---:|---:|
| forall_inst pass@5 (`literal_adapt_rerank`) | **3 / 7 = 0.429** | **6 / 7 = 0.857** | **+0.428** |
| forall_inst pass@1 (`literal_adapt_rerank`) | 3 / 7 = 0.429 | 6 / 7 = 0.857 | +0.428 |
| forall_inst pass@10 (`literal_adapt_rerank`) | 3 / 7 = 0.429 | 6 / 7 = 0.857 | +0.428 |
| rewrite_succ pass@5 (every config) | **4 / 5 = 0.800** | **5 / 5 = 1.000** | **+0.200** |
| rewrite_succ pass@1 (every config) | 3 / 5 = 0.600 | 4 / 5 = 0.800 | +0.200 |
| exists_reconstruct (every config) | unchanged | unchanged | 0.000 |
| neg_exfalso / neg_imp_exfalso | unchanged | unchanged | 0.000 |

**Honesty note.** The v12 metrics on disk under `data/baselines/v12_eval/`
are NOT overwritten. The corrected numbers live at
`data/baselines/v13_timeout_rerun/metrics_rerun.json` alongside an
untouched copy of the v12 metrics in `metrics_original.json`. The
`test_v12_eval.py` pins are still valid against v12's lower-bound disk
state.

---

## 1. Rerun mechanics

Script: `scripts/rerun_v12_timeouts.py`.

* **Input:** v12 predictions under
  `data/baselines/v12_eval/<fam>/literal_adapt_rerank/predictions.jsonl`
  (carries the superset of candidates across the four configs).
* **Discovery:** every (theorem, candidate) pair whose v12 verifier
  result has `error == "timeout"` is a candidate target. A small
  syntactic pre-filter rejects `refintro*` (a clearly mid-token
  truncation we'd otherwise burn a 120 s subprocess on); everything
  else is sent to lean.
* **Verifier:** fresh `make_lean_cli_verifier(timeout=120.0)` —
  separate from the v12 cache so cached `timeout` records cannot leak
  back as hits. Backend = `lean-cli` against the elan toolchain
  (`~/.elan/bin/lean`, Lean `4.30.0`).
* **Warm-up:** one trivial theorem (`example (x : Nat) : x = x := by rfl`)
  runs first so the lean process pays imports / elaborator JIT cost
  once. Warm-up wall-clock was **~2.4 s**; subsequent reruns finished
  in **0.4–0.5 s each**. The whole 13-candidate rerun completed in
  **< 10 s wall-clock**.

| Discovery cell | count |
|---|---:|
| total v12 timeout slots across forall_inst / rewrite_succ / exists_reconstruct | **14** |
| syntactic pre-filter rejections (`refintro hn`) | 1 |
| rerun targets actually invoked | **13** |

* **Output:** `data/baselines/v13_timeout_rerun/{metrics_original.json,
  metrics_rerun.json, changed_results.jsonl, rerun_log.jsonl,
  rerun_plan.jsonl, rerun_summary.json}`.

---

## 2. Per-candidate outcomes (all 13)

| family | theorem | rank | source | candidate | v12 result | v13 result | timeout → verified? |
|---|---|---:|---|---|---|---|:---:|
| forall_inst | forall_inst_7_0 | 1 | seq2seq | `exact h` | timeout | type-mismatch fail | — (already row-pass) |
| forall_inst | forall_inst_7_0 | 6 | seq2seq | `rcases h with \|` | timeout | parse fail | — (truncation; row already passes) |
| forall_inst | forall_inst_3_0 | 6 | seq2seq | `exact h 4` | timeout | type-mismatch fail | — (wrong literal; row already passes) |
| **forall_inst** | **forall_inst_5_2** | **0** | **seq2seq_literal_adapt** | **`exact h 5`** | **timeout** | **VERIFIED** | **YES** |
| forall_inst | forall_inst_9_4 | 3 | seq2seq | `exact h (h` | timeout | parse fail | — (truncation; row already passes) |
| **forall_inst** | **forall_inst_13_6** | **0** | **seq2seq_literal_adapt** | **`exact h 13`** | **timeout** | **VERIFIED** | **YES** |
| forall_inst | forall_inst_13_6 | 4 | seq2seq | `exact h` | timeout | type-mismatch fail | no |
| forall_inst | forall_inst_13_6 | 7 | seq2seq | `exact h 4` | timeout | type-mismatch fail | no |
| **forall_inst** | **forall_inst_var_k** | **0** | **seq2seq_literal_adapt** | **`exact h 8`** | **timeout** | **VERIFIED** | **YES** |
| forall_inst | forall_inst_var_k | 7 | seq2seq | `rcases h with hn => exact h` | timeout | unsolved-goals fail | no |
| **rewrite_succ** | **rewrite_succ_ij** | **0** | **seq2seq** | **`rw [h]`** | **timeout** | **VERIFIED** | **YES** |
| exists_reconstruct | exists_reconstruct_3 | 5 | seq2seq | `cases h with \| intro n hn => exact ⟨m, hn⟩` | timeout | unknown-identifier `m` | no (row already passes) |
| exists_reconstruct | exists_reconstruct_20 | 1 | seq2seq | `cases h with \| intro n hn => exact ⟨m, rfl⟩` | timeout | unknown-identifier `m` | no (row already passes) |

**Summary:** 4 of 13 candidates flipped `timeout → VERIFIED`. The other
9 had genuine elaboration errors that v12's 20-second subprocess cap
was clipping before lean could report them. None of the 9 ever could
have verified; their being marked `timeout` in v12 was a noise mode.

**Reproduce:** `./.venv/bin/python scripts/rerun_v12_timeouts.py
--include-completeness --timeout 120`.

---

## 3. Part 2 — forall_inst row-by-row table

This is the focused table the v13 brief asks for. "Goal literal" is the
first integer in the conclusion (`8 = m` → `8`); "adapted rank" is
where the `seq2seq_literal_adapt` candidate appears in v12's composed
beam (`-1` if none was emitted).

| theorem | goal lit | raw top candidate | adapted candidate | adapted rank | v12 result | v13 result | final status | failure type |
|---|---:|---|---|---:|:---:|:---:|---|---|
| forall_inst_7_0 | 7 | `exact h 7` | — | — | pass@5 ✓ | pass@5 ✓ | UNCHANGED (raw already wins) | — |
| forall_inst_3_0 | 3 | `exact h 3` | `exact h 3` (dedup of raw) | 0 | pass@5 ✓ | pass@5 ✓ | UNCHANGED (raw + adapt agree) | — |
| **forall_inst_5_2** | 5 | `exact h 5` | `exact h 5` | 0 | pass@5 ✗ (timeout) | pass@5 ✓ | **FLIPPED → win** | timeout-only |
| forall_inst_9_4 | 9 | `exact h 9` | `exact h 9` | 0 | pass@5 ✓ | pass@5 ✓ | UNCHANGED (raw wins; adapt confirms) | — |
| **forall_inst_13_6** | 13 | `exact h 13` | `exact h 13` | 0 | pass@5 ✗ (timeout) | pass@5 ✓ | **FLIPPED → win** | timeout-only |
| forall_inst_var_m | 8 | `exact h` | — *(no schema match in beam)* | — | pass@5 ✗ | pass@5 ✗ | STILL FAIL | char-truncation + schema gate |
| **forall_inst_var_k** | 8 | `exact h 8` | `exact h 8` | 0 | pass@5 ✗ (timeout) | pass@5 ✓ | **FLIPPED → win** | timeout-only |

**Headline:** forall_inst pass@5 corrects from **3 / 7 = 0.429** to
**6 / 7 = 0.857** under warm verification.

**Residual failure (forall_inst_var_m):** the beam for `(m : Nat) (h : ∀
x : Nat, x = m) : 8 = m` contains only:

```
rank 0: 'exact h'           — type-mismatch (no literal supplied)
rank 1: 'refine hq ='       — parse fail
rank 2: 'rcases h wi'       — parse fail (char-truncation: 'with' clipped)
rank 3: 'refine hq'         — unknown-identifier 'hq'
rank 4: 'refine hq⟩'        — unknown-identifier 'hq'
rank 5: 'refin rfl⟩'        — unknown-tactic 'refin'  (char-truncation of 'refine')
rank 6: 'refintro hn'       — unknown-tactic 'refintro'  (fused 'refine' + 'intro')
rank 7: 'rwexact h'         — unknown-tactic 'rwexact'  (fused 'rw' + 'exact')
rank 8: 'refintro hq'       — same as rank 6
rank 9: 'refine ⟨m,'        — parse fail
```

None of these is a valid `exact <ident> <num>` schema, so v12's
literal-aware decode could not fire (`compose_candidates` requires a
candidate with the schema *shape* — it doesn't synthesize the head
from scratch). The dominant failure mode here is **char-level
truncation** (`rcases h wi`, `rwexact h`, `refin rfl⟩`, `refintro …`),
which is exactly the failure family the v13 brief flags for tokenizer
work. Conclusion → see `docs/V13_TOKENIZATION_DECISION.md`.

---

## 4. Part 3 — rewrite_succ timeout rerun

The only rewrite_succ timeout was `rewrite_succ_ij` rank-0 `rw [h]`
(source=seq2seq, NOT literal_adapt — so this is genuinely a v12 false
timeout on a stock seq2seq candidate, not a literal-adapt artefact).

| theorem | top candidate | v12 result | v13 result | row pass@5 v12 → v13 |
|---|---|:---:|:---:|---|
| rewrite_succ_nm | `rw [h]` | ✓ | (cached ✓) | ✓ → ✓ |
| rewrite_succ_ab | `rw [h]` | ✓ | (cached ✓) | ✓ → ✓ |
| rewrite_succ_xy | `rw [h]` | ✓ | (cached ✓) | ✓ → ✓ |
| **rewrite_succ_ij** | **`rw [h]`** | **✗ timeout** | **VERIFIED** | **✗ → ✓** |
| rewrite_succ_kl | `rw [h]` | ✓ | (cached ✓) | ✓ → ✓ |

**Headline:** rewrite_succ pass@5 corrects from **4 / 5 = 0.800** to
**5 / 5 = 1.000** across ALL FOUR configs (raw, literal_adapt, rerank,
literal_adapt_rerank) under warm verification — because `rw [h]` is the
literal raw seq2seq beam-rank-0 candidate and lives in every config's
candidate list.

Recall the v12 brief floor: *"rewrite_succ pass@5 ≥ 0.800."* It was
already met at the lower bound; warm verification merely tightens it
from a floor to the actual value `1.000`.

---

## 5. exists_reconstruct, neg_exfalso, neg_imp_exfalso

* **exists_reconstruct (n=5).** Two timeouts (`cases h with | intro n
  hn => exact ⟨m, hn⟩` and `cases h with | intro n hn => exact ⟨m,
  rfl⟩`) were on rows that already passed via other beam entries. v13
  reveals both as **unknown-identifier `m`** errors (the candidate
  references a witness `m` that was never introduced — a real semantic
  bug, not a timeout). Headline metrics unchanged from v12 (1.000 in
  `literal_adapt_rerank`).
* **neg_exfalso (n=8).** No timeouts. v13 = v12 = **5 / 8 = 0.625**.
* **neg_imp_exfalso (n=5).** No timeouts. v13 = v12 = **0 / 5 = 0.000**.
  (v10 corpus lacks the contrapositive shape; this is a data-gap, not
  a verifier issue.)

---

## 6. Corrected aggregate

| family (n) | v12 lower-bound pass@5 (`literal_adapt_rerank`) | v13 warm pass@5 | Δ |
|---|---:|---:|---:|
| forall_inst (7) | 0.429 | **0.857** | +0.428 |
| exists_reconstruct (5) | 1.000 | 1.000 | 0.000 |
| rewrite_succ (5) | 0.800 | **1.000** | +0.200 |
| neg_exfalso (8) | 0.625 | 0.625 | 0.000 |
| neg_imp_exfalso (5) | 0.000 | 0.000 | 0.000 |
| **mean** | **0.571** | **0.696** | **+0.126** |

> *This is an evaluation-reliability gain (verifier-timeout noise
> removed), **not** a model improvement. The seq2seq weights and the
> v12 literal-adapt + reranker code are unchanged.*

---

## 7. Claims avoided

* **Not a model improvement.** No retraining, no architecture change,
  no new candidate sources. v12 weights, v12 literal-adapt module, v12
  reranker — all bit-identical.
* **Not retconning v12.** `test_v12_eval.py` PINNED tuples still hold
  against the on-disk v12 metrics — those files are untouched. v13
  publishes corrected numbers at a parallel path.
* **Not state_after.** Same template-substitution lean-cli backend.
* **Not manual oracle.** Every candidate came from v12's recorded
  beams — no candidate was inserted by hand for the rerun.
* **Not v10-leakage revival.** Eval rows are still the clean v11
  family-LOFO test rows.
* **Not full forall_inst unblock.** forall_inst_var_m remains a
  failure; it's a char-truncation + schema-gate problem the warm
  rerun cannot fix. The tokenizer prototype (Part 5) targets it.

---

## 8. Where the numbers live

* `data/baselines/v12_eval/<fam>/<config>/metrics.json` — **v12
  on-disk lower-bound metrics** (unchanged; pinned by tests).
* `data/baselines/v13_timeout_rerun/metrics_original.json` — exact
  snapshot of v12 metrics at the time of v13 rerun (for audit).
* `data/baselines/v13_timeout_rerun/metrics_rerun.json` — corrected
  pass@1/5/10 with rerun outcomes substituted into the timed-out
  verification slots.
* `data/baselines/v13_timeout_rerun/changed_results.jsonl` — one row
  per timeout candidate with original vs rerun outcome.
* `data/baselines/v13_timeout_rerun/rerun_log.jsonl` — verbatim
  subprocess outcome for every candidate (incl. warm-up).
* `data/baselines/v13_timeout_rerun/rerun_summary.json` — counts.
