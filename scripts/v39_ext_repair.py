"""Mini-ELF v39 — E2: AR-drafts + flow-repair hybrid (H5, flagship).

Novel hybrid: AR drafts a tactic; if it fails Lean, embed the failed draft, push
it partway up the flow path (partial noise at t0), denoise with the trained flow
conditioned on the SAME theorem, decode, dedupe vs the draft, verify. Question:
can embedding-space flow repair recover AR failures that AR's own resampling does
not? Report % of AR-failed theorems rescued to a verified tactic, with examples.
Even 3-10% at ~zero extra training is a result; 0% is a clean negative for
embedding-space repair.

Budget: caps total verifier calls (default 150). Track-A v35 24-theorem tier.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.v38_data import load_dataset, mathlib_test_tier, gold_lookup, cond_ids_for
from mini_elf_lean.elf_v35_sample import decode_and_rank
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list
from v39_train import build_model
from v38_matrix_eval import get_verifier

OUT = ROOT / "outputs" / "v39"


@torch.no_grad()
def flow_repair(model, cond_ids, draft_ids, *, t0, steps, cfg_weight, K, device, seed=0, prompt=""):
    """Denoise K variants starting from a partially-noised AR draft embedding."""
    cfg = model.cfg
    Sc, Tt = cfg.max_cond_len, cfg.max_tgt_len
    cond = cond_ids.expand(K, -1).to(device)
    cond_pad = cond == cfg.pad_id
    cond_in = model._std(model.trunk.embed_tokens(cond))
    kpm_c = torch.cat([cond_pad, torch.zeros(K, Tt, dtype=torch.bool, device=device)], dim=1)
    kpm_u = torch.cat([torch.ones(K, Sc, dtype=torch.bool, device=device),
                       torch.zeros(K, Tt, dtype=torch.bool, device=device)], dim=1)
    d = (list(draft_ids)[:Tt] + [cfg.pad_id] * Tt)[:Tt]
    draft_t = torch.tensor([d] * K, dtype=torch.long, device=device)
    Z1 = model._std(model.trunk.embed_tokens(draft_t))
    g = torch.Generator(device=device); g.manual_seed((seed ^ zlib.crc32(prompt.encode())) & 0x7FFFFFFF)
    Z0 = torch.randn(K, Tt, cfg.d_model, generator=g, device=device) * model.noise_scale
    z = (1 - t0) * Z0 + t0 * Z1
    sc = torch.zeros_like(z)
    use_cfg = abs(cfg_weight - 1.0) > 1e-9
    k0 = round(t0 * steps)
    x_hat = z
    for i in range(k0, max(steps, 1)):
        t_val = i / max(steps, 1)
        t = torch.full((K,), t_val, device=device)
        out_c = model._core(cond_in, z, sc, t, kpm_c)
        x_c = out_c if model.predict == "x" else (z + (1 - t_val) * out_c)
        if use_cfg:
            out_u = model._core(cond_in, z, sc, t, kpm_u)
            x_u = out_u if model.predict == "x" else (z + (1 - t_val) * out_u)
            x_hat = x_u + cfg_weight * (x_c - x_u)
        else:
            x_hat = x_c
        v = (x_hat - z) / max(1 - t_val, 1e-3)
        sc = x_hat.detach()
        z = z + (1.0 / max(steps, 1)) * v
    return model.trunk.readout_ids(model._unstd(x_hat))


def sanitize(s):
    cl, _ = sanitize_candidate_list([s])
    return cl[0] if cl else ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default="trackA")
    ap.add_argument("--flow-snap", default="headline_flow_30M_U3689")
    ap.add_argument("--ar-snap", default="headline_ar_30M_U3689")
    ap.add_argument("--K-ar", type=int, default=16)
    ap.add_argument("--K-repair", type=int, default=6)
    ap.add_argument("--t0s", default="0.3,0.5")
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--cfg-weight", type=float, default=2.0)
    ap.add_argument("--verify-cap", type=int, default=160)
    args = ap.parse_args(argv)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    ds = load_dataset()
    vocab = ds["vocab"]
    tier = mathlib_test_tier(ds["test"], cap=24)
    name2stmt = {r["theorem_name"]: r["theorem_statement"] for r in tier}
    golds = gold_lookup(ds["train"] + ds["val"] + ds["test"])
    snap_dir = OUT / args.run / "snapshots"

    def load(family, name):
        sn = torch.load(snap_dir / f"{name}.pt", map_location="cpu", weights_only=False)
        cfg = V38Config.from_dict(sn["cfg"])
        m = build_model(family, cfg, **(sn.get("family_kw") or {})).to(dev)
        m.load_state_dict({k: v.to(dev) for k, v in sn["state_dict"].items()})
        m.eval()
        return m, cfg

    ar, acfg = load("ar", args.ar_snap)
    flow, fcfg = load("flow", args.flow_snap)
    verifier = get_verifier()
    if verifier is None:
        print("ERROR: verifier unavailable"); return 1
    t0s = [float(x) for x in args.t0s.split(",")]

    # ---- 1) AR drafts per theorem, find failures ----
    ar_cands = {}        # name -> ranked unique AR candidates
    verify_items = []    # (name, stmt, tac)
    for r in tier:
        cond = cond_ids_for(r, vocab, max_cond_len=acfg.max_cond_len, device=dev)
        ids = ar.generate(cond, n_samples=args.K_ar, prompt=r["theorem_name"], device=dev, temperature=1.0)
        ranked, _ = decode_and_rank(ids, vocab)
        cands = [t for t, _ in ranked][:8]
        ar_cands[r["theorem_name"]] = cands
        for t in cands:
            verify_items.append((r["theorem_name"], r["theorem_statement"], t))
    # verify AR candidates (cached, deduped by verifier)
    vmap = {}
    for x in verifier.verify_many(list({(n, s, t) for (n, s, t) in verify_items}), confirm=True):
        vmap[(x.theorem_name, x.tactic)] = x.success
    ar_solved = {n for n in ar_cands if any(vmap.get((n, t)) for t in ar_cands[n])}
    ar_failed = [n for n in ar_cands if n not in ar_solved]
    print(f"AR solves {len(ar_solved)}/{len(tier)}; failed theorems: {len(ar_failed)}")
    print("failed:", ar_failed)

    # ---- 2) flow-repair each failed theorem's top failed drafts ----
    repair_items = []       # (name, stmt, repaired_tac)
    repair_prov = {}        # (name, tac) -> {draft, t0}
    for n in ar_failed:
        stmt = name2stmt[n]
        r = next(x for x in tier if x["theorem_name"] == n)
        cond = cond_ids_for(r, vocab, max_cond_len=fcfg.max_cond_len, device=dev)
        drafts = [c for c in ar_cands[n] if c][:3]  # top-3 failed drafts
        for draft in drafts:
            draft_ids = vocab.encode_target(draft)
            for t0 in t0s:
                ids = flow_repair(flow, cond, draft_ids, t0=t0, steps=args.steps,
                                  cfg_weight=args.cfg_weight, K=args.K_repair, device=dev,
                                  prompt=f"{n}|{draft}|{t0}")
                for k in range(ids.size(0)):
                    cand = sanitize(vocab.decode_target(ids[k].tolist()))
                    if cand and cand not in ar_cands[n] and (n, cand) not in repair_prov:
                        repair_prov[(n, cand)] = {"draft": draft, "t0": t0}
                        repair_items.append((n, stmt, cand))
    # cap verifier calls
    repair_items = repair_items[: args.verify_cap]
    print(f"flow produced {len(repair_items)} unique repaired candidates (capped {args.verify_cap})")
    rmap = {}
    if repair_items:
        for x in verifier.verify_many(list({(n, s, t) for (n, s, t) in repair_items}), confirm=True):
            rmap[(x.theorem_name, x.tactic)] = x.success

    rescued = {}
    for (n, s, t) in repair_items:
        if rmap.get((n, t)):
            rescued.setdefault(n, []).append({"tactic": t, **repair_prov.get((n, t), {})})
    n_rescued = len(rescued)
    print(f"\nH5 RESULT: flow-repair rescued {n_rescued}/{len(ar_failed)} AR-failed theorems "
          f"= {100*n_rescued/max(len(ar_failed),1):.1f}% of failures")
    for n, exs in rescued.items():
        print(f"  RESCUED {n}: {exs[0]['tactic']!r} (from draft {exs[0].get('draft')!r}, t0={exs[0].get('t0')})")

    result = {
        "ar_solved": sorted(ar_solved), "ar_failed": ar_failed,
        "n_ar_failed": len(ar_failed), "n_rescued": n_rescued,
        "rescue_rate_of_failures": round(n_rescued / max(len(ar_failed), 1), 4),
        "rescued": rescued, "n_repair_candidates": len(repair_items),
        "params": {"K_ar": args.K_ar, "K_repair": args.K_repair, "t0s": t0s,
                   "steps": args.steps, "cfg_weight": args.cfg_weight},
        "verifier_lean_seconds": round(verifier.total_lean_seconds, 1),
    }
    out = OUT / args.run / "ext_repair.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
