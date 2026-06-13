"""Mini-ELF v44 — S2: gold-premise oracle decomposition (the headline).

For each hard-tier theorem, a premise-conditioned generator (AR or MDLM) produces K whole-proof
candidates under three premise-conditioning arms:
  none      — empty premise set
  retrieved — premises from a retriever (BM25 by default; dense via --retriever)
  gold      — the premise NAMES used in the gold proof (retriever-independent; never the gold tactic)
Verify (bisect). The **(gold − none) pass@k gap = the retrieval-addressable fraction of the wall**.

Generation on .venv-gpu (deterministic). Verify via verify_many_bisect. Persists all candidates +
the premise sets + vmap.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list
from mini_elf_lean.verdict_cache import VerdictCache, cached_verify
from v38_matrix_eval import build_model

MAX_PREM = 12


def git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def cond_text(premises, stmt):
    return f"PREM: {' '.join(premises[:MAX_PREM]) if premises else ''} STMT: {stmt}"


def _san(s):
    cl, _ = sanitize_candidate_list([s]); return cl[0] if cl else ""


def get_retriever(kind):
    if kind == "bm25":
        from mini_elf_lean.grounder_retrieval import BM25Retriever
        r = BM25Retriever()
        return lambda stmt, nm: r.retrieve(stmt, topn=MAX_PREM, exclude=[nm])
    if kind == "dense":
        from mini_elf_lean.retriever_dense import DenseRetriever
        r = DenseRetriever()
        return lambda stmt, nm: r.retrieve(stmt, topn=MAX_PREM, exclude=[nm])
    return None


@torch.no_grad()
def gen_arm(model, cfg, vocab, tier, dev, premise_fn, *, K, steps, family):
    """premise_fn(theorem)->list[str]; returns name->[proof candidates]."""
    out = {}
    kw = {"cfg_weight": 2.0, "self_cond": True} if family == "flow" else {}
    for t in tier:
        nm, stmt = t["full_name"], t["statement"]
        prem = premise_fn(t)
        cids = vocab.encode_source(cond_text(prem, stmt))[:cfg.max_cond_len]
        cids = cids + [cfg.pad_id] * (cfg.max_cond_len - len(cids))
        cond = torch.tensor([cids], dtype=torch.long, device=dev)
        ids = model.generate(cond, n_samples=K, steps=steps, prompt=nm, device=dev, **kw)
        out[nm] = [_san(vocab.decode_target(ids[k].tolist())) for k in range(ids.size(0))]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default=str(ROOT / "outputs/v44/hard_tier/hard_dev.jsonl"))
    ap.add_argument("--corpus", default=str(ROOT / "data/v44/corpora/premcond"))
    ap.add_argument("--sources", required=True, help="label:family:snapshot:steps comma list")
    ap.add_argument("--retriever", default="bm25", choices=["bm25", "dense", "none"])
    ap.add_argument("--K", type=int, default=12)
    ap.add_argument("--cache", default=str(ROOT / "outputs/v44/oracle/vcache.jsonl"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    vocab = TokenVocab.load(Path(args.corpus) / "vocab.json")
    tier = [json.loads(l) for l in Path(args.tier).read_text().splitlines() if l.strip()]
    name2stmt = {t["full_name"]: t["statement"] for t in tier}

    from v38_matrix_eval import get_verifier
    verifier = get_verifier(); assert verifier is not None
    cache = VerdictCache(Path(args.cache), verifier.imports)
    retr = get_retriever(args.retriever)

    arms = {
        "none": lambda t: [],
        "gold": lambda t: t.get("premises", []),
    }
    if retr is not None:
        arms["retrieved"] = lambda t: retr(t["statement"], t["full_name"])

    out_dir = Path(args.out).parent; out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in args.sources.split(","):
        label, family, snap_path, steps = spec.split(":")[0], spec.split(":")[1], spec.split(":")[2], int(spec.split(":")[3])
        snap = torch.load(snap_path, map_location="cpu", weights_only=False)
        cfg = V38Config.from_dict(snap["cfg"])
        model = build_model(family, cfg, **(snap.get("family_kw") or {})).to(dev)
        model.load_state_dict({k: v.to(dev) for k, v in snap["state_dict"].items()}); model.eval()
        for arm, pfn in arms.items():
            t0 = time.time()
            cand = gen_arm(model, cfg, vocab, tier, dev, pfn, K=args.K, steps=steps, family=family)
            ranked = {nm: [c for c, _ in Counter(p for p in cs if p.strip()).most_common(10)] for nm, cs in cand.items()}
            items = [(nm, name2stmt[nm], c) for nm, cs in ranked.items() for c in cs]
            vmap = cached_verify(verifier, items, cache)
            solved = sorted(nm for nm, cs in ranked.items() if any(vmap.get((nm, c)) for c in cs))
            pk = {}
            for kk in (1, 5, 10):
                pk[str(kk)] = round(sum(1 for nm, cs in ranked.items() if any(vmap.get((nm, c)) for c in cs[:kk])) / max(len(tier), 1), 4)
            rec = {"label": label, "family": family, "arm": arm, "n": len(tier),
                   "solved": len(solved), "pass_at_k": pk, "solved_names": solved,
                   "wall_s": round(time.time() - t0, 1)}
            results.append(rec)
            (out_dir / f"cand_{label}_{arm}.json").write_text(json.dumps({
                "label": label, "arm": arm, "retriever": args.retriever, "ranked": ranked,
                "premises": {nm: pfn(t) for nm, t in zip([x["full_name"] for x in tier], tier)},
                "vmap": {f"{n}\x1f{tc}": bool(v) for (n, tc), v in vmap.items()}}))
            print(f"[{label}/{arm}] solved {len(solved)}/{len(tier)} pass@10={pk['10']} ({time.time()-t0:.0f}s)")
        del model
        if dev == "cuda":
            torch.cuda.empty_cache()

    out = {"verify_mode": "bisect-batched", "git_sha": git_sha(), "retriever": args.retriever,
           "tier": Path(args.tier).stem, "n": len(tier), "K": args.K, "results": results}
    Path(args.out).write_text(json.dumps(out, indent=1))
    # decomposition summary
    by = {}
    for r in results:
        by.setdefault(r["label"], {})[r["arm"]] = r["pass_at_k"]["10"]
    print("\n=== S2 decomposition (pass@10) ===")
    for label, arms_pk in by.items():
        none, gold = arms_pk.get("none", 0), arms_pk.get("gold", 0)
        retr_pk = arms_pk.get("retrieved")
        print(f"{label}: none={none} retrieved={retr_pk} gold={gold} | (gold-none)={round(gold-none,4)}")
    print("->", args.out)


if __name__ == "__main__":
    main()
