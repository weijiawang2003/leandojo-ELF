"""Mini-ELF v43 — A2 / D1: e2e union under the STRONG (retrieval) grounder, simp-inclusive base.

For each coarse plan source (flow/ar/mdlm × seed): generate K coarse plans/theorem (GPU,
deterministic), ground each with the BM25 RetrievalGrounder (premise selection), verify (bisect),
persist plans+proofs+vmap. Then the simp-inclusive union table:
    base = {direct-AR ∪ plan-AR(v42) ∪ simp ∪ aesop}
    flow union gain over base, per seed (pre-registered bar: ≥ +2 in ≥ 2/3 seeds).
A2 falsifier: flow's gain over the simp-inclusive strong-grounder base does NOT reach +2/2-of-3.
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
from mini_elf_lean.plan_coarse import parse_coarse_str
from mini_elf_lean.grounder_retrieval import RetrievalGrounder
from mini_elf_lean.verdict_cache import VerdictCache, cached_verify
from v38_matrix_eval import build_model


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def gen_kw(family, cfg_w=2.0):
    return {"cfg_weight": cfg_w, "self_cond": True} if family == "flow" else {}


@torch.no_grad()
def gen_and_ground(model, cfg, vocab, grounder, tier, dev, *, K, steps, family, cfg_w=2.0):
    """Return name -> (plans[str], proofs[str]). One grounded proof per generated plan (top fill)."""
    out_plans, out_proofs = {}, {}
    for t in tier:
        nm, stmt = t["full_name"], t["statement"]
        cids = vocab.encode_source(stmt)[:cfg.max_cond_len]
        cids = cids + [cfg.pad_id] * (cfg.max_cond_len - len(cids))
        cond = torch.tensor([cids], dtype=torch.long, device=dev)
        ids = model.generate(cond, n_samples=K, steps=steps, prompt=nm, device=dev, **gen_kw(family, cfg_w))
        plan_strs, proofs = [], []
        for k in range(ids.size(0)):
            ps = vocab.decode_target(ids[k].tolist())
            steps_parsed = parse_coarse_str(ps) or [("simp", ["NONE"])]
            # one proof per plan: the grounder's top-ranked fill
            cands = grounder.ground(stmt, t.get("state_before", ""), steps_parsed, K=1, exclude=[nm])
            plan_strs.append(ps)
            proofs.append(cands[0] if cands else "simp")
        out_plans[nm] = plan_strs
        out_proofs[nm] = proofs
    return out_plans, out_proofs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="tier_dev")
    ap.add_argument("--sources", required=True, help="label:family:snapshot:steps comma list")
    ap.add_argument("--plan-corpus", default=str(ROOT / "data/v43/corpora/coarseplan"))
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--topn", type=int, default=24)
    ap.add_argument("--cache", default=str(ROOT / "outputs/v43/union/vcache.jsonl"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    pvocab = TokenVocab.load(Path(args.plan_corpus) / "vocab.json")
    tier = [json.loads(l) for l in (ROOT / f"data/v40/tiers/{args.tier}.jsonl").read_text().splitlines() if l.strip()]
    name2stmt = {t["full_name"]: t["statement"] for t in tier}
    grounder = RetrievalGrounder(topn=args.topn)

    from v38_matrix_eval import get_verifier
    verifier = get_verifier()
    assert verifier is not None
    cache = VerdictCache(Path(args.cache), verifier.imports)

    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    per_source, solved_sets = [], {}
    for spec in args.sources.split(","):
        label, family, snap_path, steps = spec.split(":")[0], spec.split(":")[1], spec.split(":")[2], int(spec.split(":")[3])
        psnap = torch.load(snap_path, map_location="cpu", weights_only=False)
        pcfg = V38Config.from_dict(psnap["cfg"])
        pmodel = build_model(family, pcfg, **(psnap.get("family_kw") or {})).to(dev)
        pmodel.load_state_dict({k: v.to(dev) for k, v in psnap["state_dict"].items()}); pmodel.eval()
        t0 = time.time()
        plans, proofs = gen_and_ground(pmodel, pcfg, pvocab, grounder, tier, dev,
                                       K=args.K, steps=steps, family=family)
        # freq-rank proofs, verify top-10
        ranked = {nm: [c for c, _ in Counter(p for p in proofs[nm] if p.strip()).most_common(10)] for nm in proofs}
        items = [(nm, name2stmt[nm], c) for nm, cs in ranked.items() for c in cs]
        vmap = cached_verify(verifier, items, cache)
        solved = sorted(nm for nm, cs in ranked.items() if any(vmap.get((nm, c)) for c in cs))
        solved_sets[label] = solved
        # persist candidates
        (out_dir / f"{args.tier}_{label}.json").write_text(json.dumps({
            "label": label, "family": family, "tier": args.tier, "K": args.K, "git_sha": git_sha(),
            "verify_mode": getattr(verifier, "VERIFY_MODE", "bisect-batched"),
            "plans": plans, "proofs": proofs, "ranked": ranked,
            "vmap": {f"{n}\x1f{t}": bool(v) for (n, t), v in vmap.items()}}))
        per_source.append({"label": label, "family": family, "solved": len(solved),
                           "pass10": round(len(solved) / len(tier), 4), "wall_s": round(time.time() - t0, 1)})
        print(f"[{label}] solved {len(solved)}/{len(tier)}  ({time.time()-t0:.0f}s)")
        del pmodel
        if dev == "cuda":
            torch.cuda.empty_cache()

    out = {"verify_mode": "bisect-batched", "git_sha": git_sha(), "tier": args.tier, "n": len(tier),
           "per_source": per_source, "solved_sets": solved_sets,
           "lean_s": round(verifier.total_lean_seconds, 1)}
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
