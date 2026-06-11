"""Mini-ELF v41 — LPSF end-to-end: plan-gen -> grounder -> Lean verify (pass@k + union).

For each plan source (plan-AR / plan-flow / plan-MDLM snapshot): K plans/theorem -> parse ->
GREEDY batched grounding (shared grounder) -> K proof candidates -> dedupe -> verify (freq-rank
top-10) -> pass@{1,5,10} + per-theorem detail. Greedy grounding keeps the budget = K (all diversity
attributable to plan space). Union analysis across sources for H13.
"""
from __future__ import annotations

import argparse
import json
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
from v38_matrix_eval import get_verifier, build_model
from v41_plan_factorize import plan_to_str, HEADS


def _san(s):
    cl, _ = sanitize_candidate_list([s]); return cl[0] if cl else ""


def step_str(step):
    h, a = step
    return f"{h} ( {' , '.join(a)} )"


def parse_plan_str(s, max_steps=8):
    steps = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if "(" in part and ")" in part:
            head = part[:part.index("(")].strip()
            inner = part[part.index("(") + 1:part.rindex(")")]
            types = [t.strip() for t in inner.split(",") if t.strip() in ("LEMMA", "HYP", "TERM", "NONE", "OTHER")]
        else:
            head = part.split()[0] if part.split() else ""
            types = ["NONE"]
        if head:
            steps.append((head, types or ["NONE"]))
        if len(steps) >= max_steps:
            break
    return steps


@torch.no_grad()
def batched_greedy(model, cond_batch, cfg, device):
    B, Sc, Tt = cond_batch.size(0), cfg.max_cond_len, cfg.max_tgt_len
    cond_pad = cond_batch == cfg.pad_id
    out = torch.full((B, Tt), cfg.pad_id, dtype=torch.long, device=device); out[:, 0] = cfg.bos_id
    fin = torch.zeros(B, dtype=torch.bool, device=device)
    for k in range(1, Tt):
        seq = torch.cat([cond_batch, out[:, :k]], 1)
        kpm = torch.cat([cond_pad, out[:, :k] == cfg.pad_id], 1); kpm[:, Sc] = False
        h = model.trunk(model.trunk.embed_tokens(seq), causal=True, key_padding_mask=kpm)
        nxt = model.trunk.readout_logits(h[:, -1, :]).argmax(-1)
        nxt = torch.where(fin, torch.full_like(nxt, cfg.pad_id), nxt)
        out[:, k] = nxt; fin |= (nxt == cfg.eos_id)
        if bool(fin.all()):
            break
    return out


@torch.no_grad()
def ground_plans_batched(grounder, statement, plans, vocab, gcfg, device):
    K = len(plans); plan_strs = [plan_to_str(p) for p in plans]; prev = [[] for _ in range(K)]
    Lmax = max((len(p) for p in plans), default=0)
    for i in range(Lmax):
        active = [k for k in range(K) if i < len(plans[k])]
        if not active:
            break
        conds = []
        for k in active:
            ct = f"{statement} PLAN: {plan_strs[k]} STEP: {step_str(plans[k][i])} PREV: {' ; '.join(prev[k])}"
            cids = vocab.encode_source(ct)[:gcfg.max_cond_len]
            cids = cids + [gcfg.pad_id] * (gcfg.max_cond_len - len(cids))
            conds.append(cids)
        ids = batched_greedy(grounder, torch.tensor(conds, dtype=torch.long, device=device), gcfg, device)
        for j, k in enumerate(active):
            prev[k].append(_san(vocab.decode_target(ids[j].tolist())) or "simp")
    return ["\n".join(prev[k]) for k in range(K)]


def gen_kw(family, cfg_w=2.0):
    return {"cfg_weight": cfg_w, "self_cond": True} if family == "flow" else {}


@torch.no_grad()
def source_candidates(plan_model, pcfg, pvocab, grounder, gcfg, gvocab, tier, dev, *, K, steps, family, cfg_w=2.0):
    """Return name -> list of (proof_candidate) (K grounded proofs, may dedupe later)."""
    out = {}
    for t in tier:
        name, stmt = t["full_name"], t["statement"]
        cids = pvocab.encode_source(stmt)[:pcfg.max_cond_len]
        cids = cids + [pcfg.pad_id] * (pcfg.max_cond_len - len(cids))
        cond = torch.tensor([cids], dtype=torch.long, device=dev)
        ids = plan_model.generate(cond, n_samples=K, steps=steps, prompt=name, device=dev, **gen_kw(family, cfg_w))
        plans = [parse_plan_str(pvocab.decode_target(ids[k].tolist())) for k in range(ids.size(0))]
        plans = [p for p in plans if p] or [[("simp", ["NONE"])]]
        proofs = ground_plans_batched(grounder, stmt, plans, gvocab, gcfg, dev)
        out[name] = proofs
    return out


def passk_from(cand_by_name, vmap, train_proofs):
    pk, novel = {}, 0
    for kk in (1, 5, 10):
        npass = sum(1 for nm, ranked in cand_by_name.items() if any(vmap.get((nm, c)) for c, _ in ranked[:kk]))
        pk[str(kk)] = npass / max(len(cand_by_name), 1)
    for nm, ranked in cand_by_name.items():
        for c, _ in ranked[:10]:
            if vmap.get((nm, c)) and c not in train_proofs:
                novel += 1
    return pk, novel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default=str(ROOT / "data/v40/tiers/tier_dev.jsonl"))
    ap.add_argument("--grounder", default=str(ROOT / "outputs/v41/grounder/snapshots/scale_ar_30M_U79530.pt"))
    ap.add_argument("--sources", required=True, help="comma list label:family:snapshot:steps[:cfgw]")
    ap.add_argument("--plan-corpus", default=str(ROOT / "data/v41/corpora/plangen"))
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--out", required=True)
    ap.add_argument("--detail-dir", default=None)
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    pdir = Path(args.plan_corpus); pvocab = TokenVocab.load(pdir / "vocab.json")
    gvocab = TokenVocab.load(ROOT / "data/v41/corpora/grounder/vocab.json")
    train_proofs = {json.loads(l)["tactic"] for l in (ROOT / "data/v40/corpora/wholeproof/train.jsonl").read_text().splitlines() if l.strip()}
    tier = [json.loads(l) for l in Path(args.tier).read_text().splitlines() if l.strip()]
    gsnap = torch.load(args.grounder, map_location="cpu", weights_only=False)
    gcfg = V38Config.from_dict(gsnap["cfg"])
    grounder = build_model("ar", gcfg).to(dev)
    grounder.load_state_dict({k: v.to(dev) for k, v in gsnap["state_dict"].items()}); grounder.eval()

    verifier = get_verifier()
    results, detail_solved, t0 = [], {}, time.time()
    for spec in args.sources.split(","):
        parts = spec.split(":")
        label, family, snap_path, steps = parts[0], parts[1], parts[2], int(parts[3])
        cfg_w = float(parts[4]) if len(parts) > 4 else 2.0
        psnap = torch.load(snap_path, map_location="cpu", weights_only=False)
        pcfg = V38Config.from_dict(psnap["cfg"])
        pmodel = build_model(family, pcfg, **(psnap.get("family_kw") or {})).to(dev)
        pmodel.load_state_dict({k: v.to(dev) for k, v in psnap["state_dict"].items()}); pmodel.eval()
        cand = source_candidates(pmodel, pcfg, pvocab, grounder, gcfg, gvocab, tier, dev,
                                  K=args.K, steps=steps, family=family, cfg_w=cfg_w)
        # freq-rank deduped proofs per theorem, verify top-10
        cand_by_name, items = {}, set()
        name2stmt = {t["full_name"]: t["statement"] for t in tier}
        for nm, proofs in cand.items():
            ranked = Counter(p for p in proofs if p).most_common(10)
            cand_by_name[nm] = ranked
            for c, _ in ranked:
                items.add((nm, name2stmt[nm], c))
        vmap = {(x.theorem_name, x.tactic): x.success for x in verifier.verify_many(list(items), confirm=True)}
        pk, novel = passk_from(cand_by_name, vmap, train_proofs)
        solved = {nm for nm, ranked in cand_by_name.items() if any(vmap.get((nm, c)) for c, _ in ranked)}
        detail_solved[label] = sorted(solved)
        rec = {"label": label, "family": family, "steps": steps, "cfg_w": cfg_w, "tier": Path(args.tier).stem,
               "n_tier": len(tier), "pass_at_k": pk, "solved": len(solved), "novel": novel}
        results.append(rec)
        print(f"  [{label}] pass@1={pk['1']:.3f} pass@5={pk['5']:.3f} pass@10={pk['10']:.3f} solved={len(solved)}/{len(tier)} novel={novel}")
        del pmodel
        if dev == "cuda":
            torch.cuda.empty_cache()
    out = {"results": results, "solved_sets": detail_solved, "lean_s": round(verifier.total_lean_seconds, 0)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"lean {verifier.total_lean_seconds:.0f}s wall {time.time()-t0:.0f}s -> wrote {args.out}")


if __name__ == "__main__":
    main()
