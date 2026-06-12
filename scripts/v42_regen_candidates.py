"""Mini-ELF v42 — regenerate + PERSIST v41 e2e candidates (plans + grounded proofs).

v41's e2e never persisted its candidates (`--detail-dir` was dead code), so the v42
re-baseline regenerates them from the committed snapshots with the same per-theorem
deterministic seeding (`prompt=name`) and persists everything: plans, grounded
proofs, and the freq-ranked top-10 (both unfiltered and well_formed-filtered, so
the poison reproducer can use the raw set while metrics use the v41-canonical
filtered set). NO verification happens here — that is the re-baseline's job, with
mode provenance.
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

import torch as _torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from v38_matrix_eval import build_model
from v41_e2e import ground_plans_batched, parse_plan_str, well_formed, gen_kw
from v41_plan_factorize import plan_to_str


@_torch.no_grad()
def source_candidates_with_plans(plan_model, pcfg, pvocab, grounder, gcfg, gvocab, tier, dev,
                                 *, K, steps, family, cfg_w=2.0):
    """v41_e2e.source_candidates, but ALSO returns the decoded plans per proof
    (the uniques audit needs plan+proof pairs; v41 never persisted either)."""
    proofs_out, plans_out = {}, {}
    for t in tier:
        name, stmt = t["full_name"], t["statement"]
        cids = pvocab.encode_source(stmt)[:pcfg.max_cond_len]
        cids = cids + [pcfg.pad_id] * (pcfg.max_cond_len - len(cids))
        cond = _torch.tensor([cids], dtype=_torch.long, device=dev)
        ids = plan_model.generate(cond, n_samples=K, steps=steps, prompt=name, device=dev,
                                  **gen_kw(family, cfg_w))
        plans = [parse_plan_str(pvocab.decode_target(ids[k].tolist())) for k in range(ids.size(0))]
        plans = [p for p in plans if p] or [[("simp", ["NONE"])]]
        proofs = ground_plans_batched(grounder, stmt, plans, gvocab, gcfg, dev)
        proofs_out[name] = proofs
        plans_out[name] = [plan_to_str(p) for p in plans]
    return proofs_out, plans_out


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True)
    ap.add_argument("--grounder", default=str(ROOT / "outputs/v41/grounder/snapshots/scale_ar_30M_U79530.pt"))
    ap.add_argument("--sources", required=True, help="comma list label:family:snapshot:steps[:cfgw]")
    ap.add_argument("--plan-corpus", default=str(ROOT / "data/v41/corpora/plangen"))
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--out-dir", default=str(ROOT / "outputs/v42/candidates"))
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    pdir = Path(args.plan_corpus); pvocab = TokenVocab.load(pdir / "vocab.json")
    gvocab = TokenVocab.load(ROOT / "data/v41/corpora/grounder/vocab.json")
    tier = [json.loads(l) for l in Path(args.tier).read_text().splitlines() if l.strip()]
    gsnap = torch.load(args.grounder, map_location="cpu", weights_only=False)
    gcfg = V38Config.from_dict(gsnap["cfg"])
    grounder = build_model("ar", gcfg).to(dev)
    grounder.load_state_dict({k: v.to(dev) for k, v in gsnap["state_dict"].items()}); grounder.eval()

    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tier_stem = Path(args.tier).stem
    for spec in args.sources.split(","):
        parts = spec.split(":")
        label, family, snap_path, steps = parts[0], parts[1], parts[2], int(parts[3])
        cfg_w = float(parts[4]) if len(parts) > 4 else 2.0
        t0 = time.time()
        psnap = torch.load(snap_path, map_location="cpu", weights_only=False)
        pcfg = V38Config.from_dict(psnap["cfg"])
        pmodel = build_model(family, pcfg, **(psnap.get("family_kw") or {})).to(dev)
        pmodel.load_state_dict({k: v.to(dev) for k, v in psnap["state_dict"].items()}); pmodel.eval()
        cand, plans = source_candidates_with_plans(pmodel, pcfg, pvocab, grounder, gcfg, gvocab,
                                                   tier, dev, K=args.K, steps=steps,
                                                   family=family, cfg_w=cfg_w)
        rec = {"label": label, "family": family, "steps": steps, "cfg_w": cfg_w,
               "tier": tier_stem, "K": args.K, "git_sha": git_sha(),
               "grounder": args.grounder, "snapshot": snap_path,
               "plans": plans,
               "proofs": {nm: proofs for nm, proofs in cand.items()},
               "ranked_raw": {nm: [c for c, _ in Counter(p for p in proofs if p.strip()).most_common(10)]
                              for nm, proofs in cand.items()},
               "ranked_wf": {nm: [c for c, _ in Counter(p for p in proofs if well_formed(p)).most_common(10)]
                             for nm, proofs in cand.items()}}
        out = out_dir / f"{tier_stem}_{label}.json"
        out.write_text(json.dumps(rec))
        print(f"[{label}] {len(cand)} theorems, K={args.K}, {time.time()-t0:.0f}s -> {out}")
        del pmodel
        if dev == "cuda":
            torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
