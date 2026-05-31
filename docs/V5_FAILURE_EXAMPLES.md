# Mini-ELF v5 — failure examples & taxonomy

Concrete, reproducible failures from the v5 proposer runs on the planner-blind
`family_interpolation` split. Verbatim from `predictions.jsonl` (inspect with
`scripts/_v5_inspect.py DIR thm_name`). Every line was checked by lean-cli.

The headline is positive — retrieval solves the template-less targets — so these
are the **honest limits**: where data-driven proposal still fails, and why.

## Taxonomy

| # | failure mode | families hit | root cause |
| --- | --- | --- | --- |
| F1 | verbatim donor out-ranks the correct adaptation | `forall_inst` (pass@1) | similarity ties; the un-adapted neighbour tactic is emitted first |
| F2 | left/right sibling confusion | `exists_elim_conj` | same-variable `_r` donor is more similar than the same-direction `_l` donor |
| F3 | cross-family confusion (missing step) | `neg_imp_exfalso`, `neg_exfalso`, `neg_or_cases` | nearest neighbour is a structurally-similar *different* family whose tactic omits a needed `intro` |
| F4 | char-n-gram picks the wrong negation family | `neg_exfalso` (pass@5 0.00) | shorter / letter-sharing neighbours score higher cosine than the correct same-family donor |
| F5 | LLM unavailable | all | no API key — skipped honestly, not faked |
| F6 | learned proposer deferred | all | see `docs/V5_LEARNED_PROPOSER.md` |

## F1 — adaptation ranked below the verbatim donor (`forall_inst`, pass@1)

`forall_inst_13_6` (goal `13 = 6`, needs `exact h 13`). Retrieval's nearest donor
is `forall_inst_3_0` (`exact h 3`); its verbatim copy is emitted **first**, the
correct numeric adaptation second:

```
THM forall_inst_13_6  GT: 'exact h 13'
  0 ok=False [retrieval]         from=forall_inst_3_0 :: 'exact h 3'
  1 ok=True  [retrieval_adapted] from=forall_inst_3_0 :: 'exact h 13'   <- correct, rank 1
  2 ok=False [retrieval_adapted] from=forall_inst_3_0 :: 'exact h 6'
  3 ok=False [retrieval]         from=forall_inst_5_2 :: 'exact h 5'
  4 ok=False [retrieval]         from=forall_inst_7_0 :: 'exact h 7'
```

Result: `forall_inst` pass@5 = **1.00** but pass@1 = **0.00** — the proposer finds
the answer but can't *rank* it first, because it has no signal that the adapted
literal beats the donor's original. Honest limitation of un-scored adaptation.

## F2 — left/right sibling confusion (`exists_elim_conj`, pass@5 0.25)

`exists_elim_conj_l_ab` needs the **left** projection (`exact hp` /`.1`). The most
similar donor is `exists_elim_conj_r_ab` — same variables `a b`, but the **right**
projection — so retrieval copies `exact hq` / `.2`, the wrong conjunct. The
same-direction donors (`_l_ps`, `_l_xy`) use different variable letters and score
lower:

```
THM exists_elim_conj_l_ab  GT: 'rcases h with ⟨n, hp, hq⟩\n  exact hp'
  0 ok=False [retrieval] from=exists_elim_conj_r_ab :: 'obtain ⟨n, hpq⟩ := h\n  exact hpq.2'
  1 ok=False [retrieval] from=exists_elim_conj_r_ab :: 'rcases h with ⟨n, hp, hq⟩\n  exact hq'
  2 ok=False [retrieval] from=exists_elim_prop_a   :: 'exact h.elim fun _ hp => hp'
  ...
```

This is the v1/v4 sibling-confusion problem (`and_elim_left` vs `_right`)
re-emerging: char similarity rewards *variable-letter* overlap over
*proof-direction* correctness.

## F3 — cross-family confusion: a missing `intro` (`neg_imp_exfalso`, pass@5 0.33)

`neg_imp_exfalso_ab` has goal `a → b`, so it must `intro hp` **then** derive
False. Its nearest neighbour is `neg_exfalso_ab` (goal `b`, hyp already in
context), whose tactics skip the `intro` and therefore don't typecheck here:

```
THM neg_imp_exfalso_ab  GT: 'intro hp\n  exact absurd hp hnp'
  0 ok=False [retrieval] from=neg_exfalso_ab :: 'contradiction'
  1 ok=False [retrieval] from=neg_exfalso_ab :: 'exact (hnp hp).elim'
  2 ok=False [retrieval] from=neg_exfalso_ab :: 'exact False.elim (hnp hp)'
  3 ok=False [retrieval] from=neg_exfalso_ab :: 'exact absurd hp hnp'
  4 ok=False [retrieval] from=neg_exfalso_arrow_ab :: 'exact (h hp).elim'
```

Retrieval has no notion that a `→`-goal needs an extra `intro` step; it copies a
proof for a subtly different goal shape.

## F4 — char-n-gram picks the wrong negation family (`neg_exfalso`, pass@5 0.00)

`neg_exfalso_pq` (`hp : p`, `hnp : ¬p ⊢ q`) is solved verbatim by
`exact absurd hp hnp`, which **is** in the train donors (`neg_exfalso_ab`/`_ac`).
But its top char-trigram neighbours are *other* negation families that happen to
share the letter `q` and are shorter (higher cosine):

```
THM neg_exfalso_pq  GT: 'exact absurd hp hnp'
  0 ok=False [retrieval] from=neg_double_intro_q :: 'exact fun hnp => hnp hp'
  1 ok=False [retrieval] from=neg_double_intro_q :: 'intro hnp\n  exact hnp hp'
  2 ok=False [retrieval] from=neg_or_cases_pq    :: 'cases h with ...'
  3 ok=False [retrieval] from=neg_or_cases_pq    :: 'rcases h with hp | hq ...'
  4 ok=False [retrieval] from=neg_imp_exfalso_ps :: 'exact fun hp => (hnp hp).elim'
```

The correct donor is ranked out of the top-5. This is why `v4 templates` (a
hand-written `absurd`/`contradiction` rule) still *beats* retrieval on the
negation families — and why the **fusion** `v3 + v4-tmpl ⊕ retrieval` reaches
1.00: the symbolic template covers exactly the families retrieval confuses, and
retrieval covers the template-less `forall_inst`/`rewrite_succ`.

## F5 — LLM proposer (skipped, not faked)

No `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` configured ⇒ the pilot wrote
`docs/V5_LLM_PILOT_SKIPPED.md` and produced **no** candidates (the `llm` config's
all-zero metrics reflect "no candidates", not a measured failure). See
`src/mini_elf_lean/llm_proposer.py` and `scripts/run_llm_proposer_pilot.py`.

## F6 — learned proof-block proposer (deferred)

A small seq2seq trained on the 29-theorem split train set cannot reliably learn
the literal-copying that `forall_inst` needs and would underperform retrieval; it
is deferred to a larger-corpus v6. Rationale + interface in
`docs/V5_LEARNED_PROPOSER.md`.

## What would fix F1–F4 (v6 directions)

- **A scorer for adapted candidates** (F1) — even a tiny "does the substituted
  literal appear on the goal LHS?" check would rank `exact h 13` first.
- **Structure-aware similarity** (F2–F4) — match on goal shape / projection
  direction / hypothesis types, not raw char-trigrams, so the donor with the
  right *proof structure* wins over the one with the right *variable letters*.
  This is the retrieval analogue of the v1 structure-aware reranker.
