# Mini-ELF v12 — tokenization note (char-level truncation analysis)

## Scope

This is an *analysis* note, not a v12 deliverable. The v12 brief
explicitly defers tokenizer changes to v13 ("Do not rewrite the whole
model unless quick"). The literal-adapt module
(`literal_aware_decode.py`) and the rule-based reranker
(`proof_block_reranker.py`) attack the *literal-extrapolation* and
*beam-ranking* failure modes; this note documents the third v11
failure mode — **char-level mid-token truncation** — and sketches what
would be needed to address it.

## Concrete v11 truncation cases (from `predictions.jsonl`)

Failure mode 1 (char-level mid-token cut) shows up across every v11
family:

| family / theorem | top-k beam output (truncated) | likely intended |
|---|---|---|
| `forall_inst_5_2` v11 [0] | `exact h` | `exact h 5` |
| `forall_inst_var_m` v11 [0] | `exact h` | `exact h 8` |
| `forall_inst_var_k` v11 [0] | `rcases h with ⟨n, hn⟩\n  exact ` | (Mathlib transplant; tail dropped) |
| `rewrite_succ_xy` v11 [3] | `rw Eq.symm h` | `rw [Eq.symm h]` (mis-formed) |
| `rewrite_succ_ij` v11 [3] | `rw [hns` | `rw [h]` |
| `rewrite_succ_ij` v11 [4] | `rw [h2` | `rw [h]` |
| `forall_inst_3_0` v11 [1] | `rcases h w` | (Mathlib transplant tail-cut) |
| `forall_inst_*` v11 [4] | `exact h 4` (well-formed but stale) | n/a |

## Why these happen

The seq2seq decoder is char-level (`mini_elf_lean.ar_train`) with
``max_output_len = 80`` and ``length_penalty = 0.7``. The
length-penalty term in the beam scoring rewards shorter sequences,
which combined with the model's per-character softmax produces:

* **Premature end-of-sequence tokens**. A high-prob `<eos>` after
  `exact h` outranks the continuation `exact h 5` for some test rows.
* **Length-truncation at `max_output_len`**. The 80-char cap clips
  long Mathlib-transplant attempts (`rcases h with ⟨n, hn⟩\n  exact …`)
  exactly at the position where the tail tactic would be.
* **Character drift inside multi-char identifiers**. The model emits
  `[hns` for `[h]` because it picked the wrong character at position 4,
  then can't recover — char-level beams cannot back-track at the
  *token* level.

## What v12 ships against this failure mode

1. **The reranker's `_is_malformed` detector** in
   `proof_block_reranker.py` matches:
   * trailing punctuation: `[`, `⟨`, `,`, `.`,
   * unclosed brackets: `[…<no ]>`, `⟨…<no ⟩>`,
   * trailing `with` with no body,
   * dotted suffix with 0–3 trailing chars (`exact h.`, `rw [h.s`),
     while whitelisting known fields (`.left`, `.right`, `.elim`,
     `.mp`, `.mpr`, `.symm`, `.trans`).
   Malformed candidates get a `-2.0` penalty in the score sum — enough
   to drop them below any well-formed candidate that doesn't carry a
   stale-literal penalty.

2. **No new model.** v12 leaves the char-level seq2seq and the
   `ar_train` decoding loop untouched.

3. **No new beam decoder.** The candidates v12 reranks are exactly the
   v11 model's beam output, plus the literal-adapt augmentation.

## Sketch: a token-level tactic tokenizer (deferred to v13)

If v13 attacks this failure mode, a minimal tactic-tokenizer should:

1. Tokenise on a small grammar:
   * **identifiers**: `[A-Za-z_][A-Za-z0-9_]*`,
   * **numbers**: `\d+`,
   * **dotted fields**: `\.[A-Za-z_][A-Za-z0-9_]*` (`.left`, `.symm`),
   * **lean symbols**: `=>`, `↦`, `∀`, `∃`, `⟨`, `⟩`, `▸`, `↔`, `¬`,
     `→`,
   * **punctuation**: `(`, `)`, `[`, `]`, `{`, `}`, `,`, `;`, `:`,
     `:=`,
   * **whitespace**: `\n`, indent runs.
2. Train the same v8/v10/v11 seq2seq with this tokenizer applied to
   `tactic`. The encoder side can stay char-level (matching state-before
   conventions) or also switch.
3. The decoder's `<eos>` token then fires on a *tactic boundary*, not a
   character boundary — eliminating the `exact h` / `rw [hns` failure
   mode.

Estimated cost: ~3–6 hours engineering + ~2 hr re-training (CPU). Not
in v12 scope.

## Sketch: BPE alternative

BPE would also address the failure mode by learning multi-char
sub-tokens (`exact_h_`, `rw_`, `_with_`, `⟨n,_hn⟩`). It's more general
than a hand-rolled tactic tokenizer but introduces a tokenizer-training
step and may merge unexpected sub-tokens. For v13 the hand-rolled
tactic tokenizer is recommended first.

## What v12 *does not claim* about tokenization

- It does **not** claim to fix mid-token truncation. The reranker
  attenuates it (malformed candidates fall to last place) but does not
  recover the truncated content.
- It does **not** propose a v12 model retrain. Same v11 checkpoints
  are reused under post-processing.
- The 2 of 7 `forall_inst` rows whose top-5 contains no `exact h <num>`
  schema at all (`forall_inst_var_m`, `forall_inst_var_k`) are
  primarily a *tokenization / max-len / Mathlib-transplant* problem,
  not a literal-substitution problem. v12 cannot unblock them; v13
  with the tokenizer above plausibly can.
