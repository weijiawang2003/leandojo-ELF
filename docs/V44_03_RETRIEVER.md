# V44 Phase 2 — R1: dense premise retriever vs BM25

## Build
`src/mini_elf_lean/retriever_dense.py` + `scripts/v44_train_retriever.py`: a DPR-style dual encoder
over the shared V38 trunk (non-causal, mean-pooled → 256-d L2-normalized embedding), query =
`state_before`, premise = full-name string. Contrastive InfoNCE, in-batch + random-pool negatives
(the per-batch BM25 hard-negative variant was the CPU bottleneck — 96k pure-Python retrievals — and
was stealing cycles from the spine's Lean verification; dropped). Index = all **241,756** premises
encoded, flat cosine search. Trained 1500 steps (loss 5.42 → 2.79).

## R1 result — dense does NOT beat BM25 (falsifier met)
Recall on the **hard tier** (44 theorems with ≥1 gold premise; `outputs/v44/retriever/recall_eval.json`):

| retriever | recall@1 | recall@5 | recall@10 | recall@20 | MRR |
|---|---|---|---|---|---|
| BM25 | 0.015 | 0.082 | **0.101** | 0.109 | 0.085 |
| dense (from-scratch 10M) | 0.000 | 0.000 | **0.000** | 0.014 | 0.003 |

**R1 falsifier ("dense ≤ BM25") MET.** The from-scratch dual encoder is far *worse* than BM25 — it
barely retrieves any gold premise into the top-20. The brief anticipated this ("dense ≤ BM25 ⇒
data/training problem; fall back to BM25, report the gap"), and the cause is clear: a 10M encoder
trained from scratch on the project's tactic tokenizer (40k vocab), with premise text = bare name
strings, cannot learn the semantic state→lemma matching that a *pretrained-LM* dense retriever
(ReProver's ByT5, LeanSearch-v2) relies on. Lexical BM25's surface-token overlap is the stronger
signal at this scale.

## The honest bound this sets
**Both retrievers are weak on the hard tier: BM25 recall@10 = 0.10, dense ≈ 0.** The gold premises
of these non-simp-closable theorems share almost no surface tokens with the statement (e.g.
`sup_himp_self_left` needs `sup_himp_distrib`/`himp_self`/`top_inf_eq`), so lexical retrieval misses
them and the from-scratch dense model never learned to bridge the gap. This is exactly why the S2
*retrieved* arm (which uses BM25, the better of the two) will sit close to the *no-premise* baseline,
while the *gold* arm (retriever-independent) measures the headroom a real retriever could unlock.

**Consequence for R2 / V45:** realizing the retrieval-addressable fraction end-to-end requires a
*pretrained-LM* dense retriever (or LLM premise reranker), not a from-scratch one — named and bounded
as the V45 bottleneck. The retrieved arm of S2 uses BM25; the dense retriever is reported as a
negative.
