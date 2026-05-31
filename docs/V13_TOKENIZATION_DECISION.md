# Mini-ELF v13 — Tokenization Decision

Companion to `V13_TIMEOUT_RERUN_REPORT.md`. Decision is made *after*
the warm-verifier rerun (Parts 1–3) so we only invest in tokenization
work for failures the rerun could not fix.

## TL;DR

* **Decision: PROCEED with a tactic-token tokenizer prototype.**
  Implemented as `src/mini_elf_lean/tactic_tokenizer.py` plus
  `tests/test_tactic_tokenizer.py` (Part 5). The token-level
  seq2seq comparison (Part 6) is **deferred to v14** because the
  scope of remaining truncation failures the prototype targets is
  small enough that we want to validate the tokenizer's *output*
  shape and unit-test it before re-spending compute on a retrain.

* **Why proceed rather than defer entirely:** the timeout rerun
  cleared 4 of 14 timeout slots but left **forall_inst_var_m**
  (the goal-literal-8, variable-`m` case) unfixed, and its beam is
  dominated by **char-truncation patterns the brief flagged
  explicitly** (`rcases h wi`, `rwexact h`, `refin rfl⟩`,
  `refintro hn`, `refintro hq`). These are mid-token splits the
  current char-level seq2seq produces because its decoder's character
  vocabulary lets it slice through identifier and keyword boundaries.

---

## 1. Classification of remaining failures (post-rerun)

We classify every row in the v11 family-LOFO test set that *still*
fails `pass@5` after the v13 warm-verifier rerun. "Truncation" means
mid-token decoder output; "schema gap" means literal-aware decode
could not fire because the beam contained no matching shape;
"shape/data gap" means the family doesn't appear in the training
distribution at all.

### 1.1 forall_inst (1 remaining failure of 7)

* **`forall_inst_var_m`** — beam shown in `V13_TIMEOUT_RERUN_REPORT.md`
  §3. Failure type = **char-truncation + schema gap**.
  Truncation candidates: `rcases h wi` (clipped `with`), `rwexact h`
  (fused `rw`+`exact`), `refin rfl⟩` (clipped `refine`), `refintro
  hn` / `refintro hq` (fused `refine`+`intro`), `refine ⟨m,`
  (unbalanced bracket). No candidate has the
  `exact <ident> <num>` shape, so literal-aware decode's gate stays
  closed.
  Tokenizer-fix viable: **YES** — a tactic-token tokenizer would
  prevent `rcases` from splitting before `with`, `rw` from fusing
  with `exact`, and `refine` from being truncated to `refin`.

### 1.2 rewrite_succ (0 remaining failures)

All 5 rows pass after warm rerun (5/5 = 1.000). No tokenizer-relevant
failures remain in this family.

### 1.3 exists_reconstruct (0 remaining failures)

All 5 rows pass (1.000 `literal_adapt_rerank`). The two timed-out
candidates were on already-passing rows; their underlying error
(unknown-identifier `m`) is a *witness-construction* bug, not a
tokenizer bug. Deferred — see §3.

### 1.4 neg_exfalso (3 remaining failures of 8)

These were already failing under v12, none touched timeouts. v11
family-LOFO test rows where the beam never produced `exact (h …)` or
`absurd … h₁ h₂`-style witnesses. Classification = **shape/data gap**
(model never learned the dual-hypothesis witness pattern for this
family because the holdout removes all examples). Tokenizer cannot
fix these — they need a generative proposer or richer training data.

### 1.5 neg_imp_exfalso (5 remaining failures of 5)

v10 corpus contains zero contrapositive shapes. Classification =
**pure data gap**. Tokenizer cannot fix; this is a corpus problem
to address in v14.

### 1.6 Counts

| failure category | count | tokenizer-fixable? |
|---|---:|:---:|
| char-truncation + schema gap (forall_inst_var_m) | 1 | **YES** |
| witness-construction (already-passing exists rows showed this in non-top ranks) | 2 (latent) | partial |
| shape/data gap (neg_exfalso ranks) | 3 | NO |
| pure data gap (neg_imp_exfalso) | 5 | NO |
| **timeout-only (fixed by warm rerun in Part 1–3)** | **4** | n/a |
| (clean wins) | 16 | — |

The **4 timeout-only failures** are precisely the ones the v13 brief
predicted (`exact h 5`, `exact h 13`, `exact h 8`, `rw [h]`). They
flipped, and the brief's "If remaining failures are mostly timeout-
fixed: defer tokenizer" branch *partially* applies.

We do **not** defer wholesale because of the brief's second branch:
*"If remaining failures include `exact h.` / `rw [hns` / `cases h
wi`: proceed with tokenizer prototype."* — and the
forall_inst_var_m beam contains `rcases h wi` and `refintro hn`, both
matching that pattern.

---

## 2. Brief alignment

The v13 brief's decision rule, verbatim:

> **If remaining failures are mostly timeout-fixed: defer tokenizer.**
> **If remaining failures include `exact h.` / `rw [hns` / `cases h wi`: proceed with tokenizer prototype.**

After the rerun, 9 of 13 cleared targets fell into "mostly timeout-
fixed" (false timeouts revealing real elaboration errors that the
warm rerun let lean report properly) — but the residual
`forall_inst_var_m` beam contains both `rcases h wi` and the related
`refintro hn` truncation pattern. The brief's "AND" reading is
unambiguous: **proceed with the prototype.**

We **bound the scope:**

* implement the tokenizer module + unit tests (Part 5);
* write a migration note describing how a future token-level seq2seq
  would consume it (Part 6, *deferred to v14*);
* do **NOT** retrain the full model in v13 — first the prototype
  needs to demonstrably solve the truncation patterns in offline
  tokenize/detokenize tests.

---

## 3. Deferred to v14

* Train a token-level seq2seq on the same v11 family-LOFO folds and
  compare offline on forall_inst + rewrite_succ. (The brief marks
  Part 6 as "Optional, if time remains.")
* Tackle the `exists_reconstruct` witness-construction subtlety
  (`⟨m, hn⟩` with the introduced witness from `cases`). This is a
  candidate-generation question, not a tokenization question.
* Address the neg_imp_exfalso / neg_exfalso shape/data gaps by
  augmenting v10 with contrapositive and dual-hypothesis families.

---

## 4. What the prototype gives us today

`src/mini_elf_lean/tactic_tokenizer.py`:

* `TacticTokenizer.tokenize(s)` and `.detokenize(tokens)` round-trip
  Lean 4 tactic strings without splitting inside identifiers,
  numeric literals, or Lean symbol clusters (`⟨⟩`, `∧∨→↔¬`, `≤≥≠`).
* `KEYWORDS` covers the Mini-ELF v0–v12 tactic surface (`exact`,
  `intro`, `intros`, `apply`, `rw`, `rcases`, `cases`, `refine`,
  `with`, `rfl`, `by`, `simp`, `omega`, `decide`, `trivial`,
  `constructor`, `exists`).
* Token classes are tagged: `IDENT`, `NUMBER`, `KEYWORD`, `SYMBOL`,
  `PUNCT`, `WS`. The future trainer can choose whether to keep
  whitespace tokens (Mini-ELF v13's char-level model effectively
  ignores them; a token model can simply elide `WS` from the input
  stream).
* Unit tests (`tests/test_tactic_tokenizer.py`) pin the round-trip
  property and explicitly verify the truncation patterns the v13
  brief calls out: `exact h.` → `[exact][WS][h][.]` (no
  `exact h.` collapse), `rw [hns` → `[rw][WS][[][hns]` (the bracket
  prevents the identifier from leaking past the `[`),
  `cases h wi` → `[cases][WS][h][WS][wi]` (the `wi` identifier
  cannot be confused with the keyword `with`).

The tokenizer never invokes lean. It is a pure-Python module suitable
for use in a future v14 token-level seq2seq.
