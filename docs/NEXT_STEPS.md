# Next Steps

Ordered by dependency. Status as of the Mini-ELF v0 milestone.

## Near-term engineering

1. **Grow the corpus.** Add more variants per family and more families via
   `scripts/generate_basic_corpus.py` (the generator + `audit_corpus.py` catch
   typos and drift). Target enough eval theorems per family that `pass@k` is
   statistically meaningful (current: 16 eval theorems/split → diagnostic only).
2. **Collect real LLM proposals.** Wire `--llm-backend anthropic|openai` into
   `collect_traces.py` runs (keys via env), compare prompt styles, and grow the
   verified corpus beyond hand-written templates.
3. **Robust lean-cli invocation.** Keep `MINI_ELF_LEAN_COMMAND` pointed at the
   concrete toolchain binary (not the elan shim) to avoid the WSL2 network-stall
   timeouts; consider documenting this in the runner's default resolution.
4. **Install numpy/sklearn (optional).** Would enable a real TF-IDF retrieval
   point of comparison and a less hand-rolled classifier without changing the
   evaluation harness.

## Research extensions

1. ~~Generative (open-vocabulary) decoding.~~ **Done**: the char-level GRU
   seq2seq (`src/mini_elf_lean/ar_model.py`) generates tactic strings character
   by character — it beats the classifier on every `pass@k` and produces *novel*
   verified tactics (composing `exact ⟨N, rfl⟩` for seen witnesses).
2. ~~A first embedded-flow generator.~~ **Done — Mini-ELF v0**
   (`src/mini_elf_lean/elf_{embed,flow,train,sample}.py`): a tactic-autoencoder
   latent + conditional rectified-flow model. Beats AR on `pass@5` (test 0.90 vs
   0.82) via ~20 stochastic candidates/row.
   ~~Mini-ELF v1: raise `pass@1` precision and make novel generations verify.~~
   **Done — Mini-ELF v1** (`elf_{structure,rerank,witness,v1_train,v1_sample}.py`):
   a verifier-aware reranker (trained on past Lean outcomes + self-training hard
   negatives) raises test `pass@1` 0.61→**0.89**; witness-copy makes
   `∃`-generations verify (`novel_verified` 0→**10/2**); structure-aware features
   crack the siblings. Open items → Mini-ELF v2 below.
3. ~~**Structure-aware model.** `and_elim` left vs right top-1 family accuracy
   0.00 for every model.~~ **Done in v1**: the reranker's conjunct/disjunct
   consistency features take `and_elim` and `or_intro` top-1 family accuracy
   0.00→**1.00**. Remaining: families needing multi-step tactics
   (`or_self_elim`), and lifting `exists_witness` from `pass@5` to `pass@1`.
4. **Real next-state supervision.** Unblock LeanDojo `run_tac` (fix the
   elaboration-stdin path, pin a working Lean version, or add an interactive
   REPL backend) so `state_after_is_real=true` data can be collected and a
   genuine `state_before → tactic → state_after` model trained.

## Mini-ELF roadmap

**Mini-ELF v0 (a small prototype of the *generation loop*) is implemented** — a
tactic autoencoder latent + conditional rectified-flow generator + Lean
verification, comparable to the baselines via the same `pass@k` harness. The
**full ELF method** (continuous embedded-flow over *proof states*) remains the
eventual research target and still needs:

1. A larger, real-LLM-augmented verified corpus.
2. ~~A strong autoregressive baseline to beat.~~ **Done**: AR seq2seq (test
   pass@5 0.82) and Mini-ELF v0 (test pass@5 0.90).
3. ~~**Mini-ELF v1**: precision + verifiable novel generation; structure-aware
   encoder for `and_elim`.~~ **Done** (test pass@1 0.89, pass@5 0.95; siblings
   1.00; `novel_verified` 10/2). See §9b of the project report.
4. **Mini-ELF v2** (open):
   - Lift `exists_witness` from `pass@5` to `pass@1` (rank the witness #1) and
     handle multi-step families like `or_self_elim` (a `cases`/`rcases` block).
   - Make the **generator itself** (not just the reranker) precise — e.g. fold
     the reranker signal back into flow sampling, or a likelihood-based decoder.
   - Validate the reranker on a **larger, less templated** corpus + real LLM
     candidates (the current clean verified/failed separation partly reflects the
     small templated corpus and the self-training loop).
5. Real next-state supervision (depends on the LeanDojo unblock) — the
   prerequisite for modeling actual proof-state flow rather than tactic strings.

## What NOT to claim yet

- ❌ "Real proof-state transition modeling" — all verification is theorem-level;
  `state_after_is_real=false` everywhere, AR and Mini-ELF v0 included.
- ❌ "Mini-ELF / ELF solved" or "real embedded proof-state flow" — Mini-ELF v0/v1
  are small **prototypes of the generation loop**, not the full method; they
  operate on tactic-string latents, not proof states.
- ❌ "Mini-ELF v1's witness-copy is neural open-vocabulary generation" — it is an
  explicit **symbolic** augmentation (copy a literal into `exact ⟨N, rfl⟩`),
  evaluated honestly by the same Lean verifier but not learned generation.
- ❌ "v1's reranker is well-calibrated in general" — its clean verified/failed
  separation is on a small, templated corpus and uses self-training on v1's own
  train-split candidates; it is **not** validated on a large or real-LLM corpus.
- ❌ "`exists_witness` solved" — solved at `pass@5`, **not** `pass@1`;
  `or_self_elim` (multi-step) still fails at every k.
- ❌ "LeanDojo works end-to-end" — tracing + initial state work; `run_tac` is
  blocked and `xfail`'d.
- ❌ "A large / pretrained / transformer model" — AR (410K) and Mini-ELF v0
  (343K) are small char-level CPU models; PyTorch is an optional extra.
- ❌ "Solved open-vocabulary generation" — AR's is **partial** (template
  composition over `{0,1,2}`); Mini-ELF's novel generations don't verify.
- ❌ "Statistically significant" gaps — 16 eval theorems/split; directional.
- ❌ Any metric not backed by a generated `metrics.json` file.
