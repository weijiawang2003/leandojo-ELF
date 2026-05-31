# Mini-ELF v5 — learned proof-block proposer (design + deferral)

**Status: deferred to v6, documented — not implemented, repo not half-broken.**

Part 5 of the v5 brief ("a small learned proof-block proposer") is explicitly
optional ("If too much work: skip and document, do not half-break repo"). After
the retrieval and LLM-pilot work, a small learned proposer was deferred for the
reasons below. The `evaluate_mini_elf_v5.py` `learned` / `v3_retrieval_learned`
configs already **degrade gracefully**: they look for
`mini_elf_lean.proof_block_model.LearnedProofBlockProposer`, and when it is
absent they emit a clear note and produce no learned candidates (rather than
crashing). No stub model file is shipped.

## Intended design (for v6)

- **Module** `src/mini_elf_lean/proof_block_model.py`: a `LearnedProofBlockProposer`
  reusing the existing char-level GRU seq2seq (`ar_model.py` / `ar_decode.py`):
  input `theorem_statement + "\n" + state_before`, output a full tactic block,
  beam-search top-k, wrapped in the `CandidateProposer` interface. Theorem-level;
  **no** `state_after` (same constraint as every model here).
- **Train** `scripts/train_proof_block_proposer.py`: train on verified blocks from
  `basic` + `hard` + `combined` + the `planner_blind` **train** split (clearly
  labelled by `corpus_source`), CPU, small, deterministic.
- **Eval** `scripts/evaluate_proof_block_proposer.py`: planner-blind split test,
  with the `forall_inst` / `rewrite_succ` focus, compared to retrieval and LLM.

## Why it is deferred (honest assessment)

1. **Too few same-shape examples.** The `family_interpolation` split gives only
   ~29 train theorems (≈73 rows), and `forall_inst` has just 4 train instances.
   A char-level seq2seq cannot reliably learn the key behaviour — *copy the
   goal's LHS literal into `exact h _`* — from four examples; it would memorise
   the training literals (`exact h 3` / `exact h 7`) and fail to instantiate at a
   held-out literal. The v0–v2 study already showed this exact model class does
   **not** compositionally generalise on this corpus.
2. **Retrieval already establishes the result.** The v5 research question — can a
   *data-driven* proposer beat per-shape templates on `forall_inst`/`rewrite_succ`
   without hand-authoring a rule? — is answered **yes** by retrieval + numeric
   adaptation (pass@5 1.00 on both), with an explicit, auditable mechanism. A
   weak learned model would add a (predictable) negative point, not change the
   conclusion.
3. **Scope / not half-breaking the repo.** Training a new model + two scripts is
   meaningful surface area; a rushed, underperforming model risks an unstable
   artifact. The brief sanctions a documented skip, which keeps every shipped
   component working and tested.

## Predicted outcome if implemented now

`forall_inst` / `rewrite_succ` pass@5 ≈ **0.0–low** (literal-copying not learnable
from 4 examples; rewrite blocks possibly memorised verbatim), i.e. **below
retrieval**. The honest takeaway would be: *with this little same-shape data, a
learned char model underperforms train-free retrieval* — which is itself a useful
v6 signal (collect a larger, real-LLM-augmented verified corpus first; see
`docs/NEXT_STEPS.md`).
