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
   0.82) via ~20 stochastic candidates/row. **Mini-ELF v1** must: (a) raise
   `pass@1` precision — better latent→string fidelity and a likelihood-based
   ranking instead of sample frequency; (b) make novel generations verify
   (currently `novel_verified=0`) — e.g. a copy/pointer decoder or a
   VAE-regularized latent so off-distribution samples still decode validly.
3. **Structure-aware model.** `and_elim` left vs right is still top-1 family
   accuracy 0.00 for *every* model. Distinguishing "the goal is the first vs the
   second conjunct" needs explicit positional/relational features (or a small
   transformer with structural encodings) — the clearest open empirical gap.
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
3. **Mini-ELF v1**: precision + verifiable novel generation (see Research
   extensions #2); a structure-aware condition encoder for `and_elim`.
4. Real next-state supervision (depends on the LeanDojo unblock) — the
   prerequisite for modeling actual proof-state flow rather than tactic strings.

## What NOT to claim yet

- ❌ "Real proof-state transition modeling" — all verification is theorem-level;
  `state_after_is_real=false` everywhere, AR and Mini-ELF v0 included.
- ❌ "Mini-ELF / ELF solved" or "real embedded proof-state flow" — Mini-ELF v0 is
  a small **prototype of the generation loop**, not the full method; it operates
  on tactic-string latents, not proof states.
- ❌ "Mini-ELF beats AR outright" — it beats AR on `pass@5` (recall) but **trails
  on `pass@1`** (precision); its generative decoder's novel candidates don't yet
  verify (`novel_verified=0`). The nn-decode variant that tops `pass@k` is
  latent-space retrieval, not open-vocabulary generation.
- ❌ "LeanDojo works end-to-end" — tracing + initial state work; `run_tac` is
  blocked and `xfail`'d.
- ❌ "A large / pretrained / transformer model" — AR (410K) and Mini-ELF v0
  (343K) are small char-level CPU models; PyTorch is an optional extra.
- ❌ "Solved open-vocabulary generation" — AR's is **partial** (template
  composition over `{0,1,2}`); Mini-ELF's novel generations don't verify.
- ❌ "Statistically significant" gaps — 16 eval theorems/split; directional.
- ❌ Any metric not backed by a generated `metrics.json` file.
