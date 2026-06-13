"""Mini-ELF v44 — train the dense premise retriever (R1) + build the premise index.

Contrastive InfoNCE on (state_before → gold-used premise) pairs from the LeanDojo train pool,
in-batch negatives + BM25 hard negatives. Then encode the 241k-premise pool → index. Uses the
shared V43 premise DB for signatures + BM25 hard negatives. Vocab = the premcond corpus vocab
(covers states + premise names). Runs on .venv-gpu.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

import torch
import torch.nn.functional as F

from mini_elf_lean.v38_backbone import V38Config, SCALE_PRESETS
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from mini_elf_lean.retriever_dense import DualEncoder
from mini_elf_lean.grounder_retrieval import BM25Retriever

RAW = ROOT / "data/v39/_raw/leandojo_benchmark_4/random"
PREM = ROOT / "data/v43/premises"


def build_pairs(split, max_pairs):
    data = json.load(open(RAW / f"{split}.json"))
    pairs = []
    for th in data:
        for tt in th.get("traced_tactics", []):
            sb = tt.get("state_before", "")
            ann = tt.get("annotated_tactic")
            if not sb or not ann or len(ann) < 2 or not ann[1]:
                continue
            for pr in ann[1]:
                fn = pr.get("full_name")
                if fn:
                    pairs.append((sb, fn))
        if len(pairs) >= max_pairs:
            break
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(ROOT / "data/v44/corpora/premcond"))
    ap.add_argument("--scale", default="10M")
    ap.add_argument("--proj", type=int, default=256)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-pairs", type=int, default=120000)
    ap.add_argument("--hard-neg", type=int, default=2)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--out", default=str(ROOT / "outputs/v44/retriever"))
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(args.seed); random.seed(args.seed)

    vocab = TokenVocab.load(Path(args.corpus) / "vocab.json")
    preset = SCALE_PRESETS[args.scale]
    cfg = V38Config(vocab_size=len(vocab), max_cond_len=256, max_tgt_len=64,
                    pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id, **preset)
    model = DualEncoder(cfg, proj_dim=args.proj).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)

    # premise text for the encoder = the premise name string (the camelCase-aware vocab covers it);
    # BM25 supplies hard negatives.
    bm25 = BM25Retriever()

    pairs = build_pairs("train", args.max_pairs)
    print(f"train pairs: {len(pairs)} | vocab {len(vocab)} | scale {args.scale}")

    def enc_ids(text, cap):
        c = vocab.encode_source(text)[:cap]
        return c + [cfg.pad_id] * (cap - len(c))

    QCAP, PCAP = 256, 24

    def batch(bs):
        idx = [random.randrange(len(pairs)) for _ in range(bs)]
        states = [pairs[i][0] for i in idx]
        prems = [pairs[i][1] for i in idx]
        # hard negatives: BM25 top premises for each state that are not the gold
        neg = []
        for st, gp in zip(states, prems):
            cands = [c for c in bm25.retrieve(st, topn=args.hard_neg + 3) if c != gp][:args.hard_neg]
            neg.extend(cands)
        q = torch.tensor([enc_ids(s, QCAP) for s in states], dtype=torch.long, device=dev)
        allp = prems + neg
        p = torch.tensor([enc_ids(x, PCAP) for x in allp], dtype=torch.long, device=dev)
        return q, p, len(prems)

    model.train()
    t0 = time.time()
    for step in range(1, args.steps + 1):
        q, p, npos = batch(args.bs)
        qe = model.encode_query(q)            # (B, proj)
        pe = model.encode_premise(p)          # (B+neg, proj)
        logits = (qe @ pe.t()) / 0.05         # temperature
        target = torch.arange(npos, device=dev)  # positives are the first npos columns, aligned
        loss = F.cross_entropy(logits, target)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % 200 == 0 or step == 1:
            print(f"step {step}/{args.steps} loss {loss.item():.4f} ({time.time()-t0:.0f}s)")

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    torch.save({"cfg": cfg.to_dict(), "state_dict": {k: v.cpu() for k, v in model.state_dict().items()},
                "proj_dim": args.proj, "shared": False, "vocab_dir": str(Path(args.corpus))},
               out / "dual_encoder.pt")

    # build the premise index: encode all 241k premise names
    names = json.loads((PREM / "premises.json").read_text())["names"]
    model.eval()
    embs = []
    with torch.no_grad():
        for s in range(0, len(names), 1024):
            chunk = names[s:s + 1024]
            p = torch.tensor([enc_ids(x, PCAP) for x in chunk], dtype=torch.long, device=dev)
            embs.append(model.encode_premise(p).cpu())
    emb = torch.cat(embs, 0)
    torch.save({"names": names, "emb": emb}, out / "prem_index.pt")
    print(f"WROTE dual_encoder + index ({emb.shape[0]} premises) -> {out}")


if __name__ == "__main__":
    raise SystemExit(main())
