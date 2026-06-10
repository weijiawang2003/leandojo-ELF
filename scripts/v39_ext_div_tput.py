"""Mini-ELF v39 — E-extras: H3 distinct-verified diversity + E4 throughput.

H3: at matched K, does FLOW (CFG ladder) yield more *distinct verified* tactics per
theorem than AR (temperature ladder)? AR temps {0.7,1.0,1.3} vs FLOW cfg {1,1.5,2},
K each on the 24-tier; dedupe, verify (budget-capped), count distinct-verified/theorem.

E4: tactics/sec at batch 256 (bf16, GPU) — FLOW@8 steps vs AR sampling. One row each.
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
    if p not in sys.path:
        sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.v38_data import load_dataset, mathlib_test_tier, cond_ids_for
from mini_elf_lean.elf_v35_sample import decode_and_rank
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list
from v39_train import build_model
from v38_matrix_eval import get_verifier

OUT = ROOT / "outputs" / "v39"


def load(family, name, dev):
    sn = torch.load(OUT / "trackA" / "snapshots" / f"{name}.pt", map_location="cpu", weights_only=False)
    cfg = V38Config.from_dict(sn["cfg"])
    m = build_model(family, cfg, **(sn.get("family_kw") or {})).to(dev)
    m.load_state_dict({k: v.to(dev) for k, v in sn["state_dict"].items()})
    m.eval()
    return m, cfg


def san(s):
    cl, _ = sanitize_candidate_list([s]); return cl[0] if cl else ""


def h3_diversity(ar, acfg, flow, fcfg, tier, vocab, dev, *, K, top_per_thm, verify_cap):
    verifier = get_verifier()
    if verifier is None:
        print("H3: verifier unavailable, skipping"); return None
    pools = {"ar": {}, "flow": {}}  # model -> name -> Counter(cand)
    for r in tier:
        n = r["theorem_name"]
        cond_a = cond_ids_for(r, vocab, max_cond_len=acfg.max_cond_len, device=dev)
        ca = Counter()
        for temp in (0.7, 1.0, 1.3):
            ids = ar.generate(cond_a, n_samples=K, prompt=n, device=dev, temperature=temp)
            for k in range(ids.size(0)):
                c = san(vocab.decode_target(ids[k].tolist()))
                if c: ca[c] += 1
        pools["ar"][n] = ca
        cond_f = cond_ids_for(r, vocab, max_cond_len=fcfg.max_cond_len, device=dev)
        cf = Counter()
        for cw in (1.0, 1.5, 2.0):
            ids = flow.generate(cond_f, n_samples=K, steps=16, cfg_weight=cw, self_cond=True, prompt=n, device=dev)
            for k in range(ids.size(0)):
                c = san(vocab.decode_target(ids[k].tolist()))
                if c: cf[c] += 1
        pools["flow"][n] = cf
    # build capped verify set: top_per_thm most frequent per (model,theorem)
    items, stmt = set(), {r["theorem_name"]: r["theorem_statement"] for r in tier}
    for mdl in ("ar", "flow"):
        for n, cnt in pools[mdl].items():
            for c, _ in cnt.most_common(top_per_thm):
                items.add((n, stmt[n], c))
    items = list(items)[:verify_cap]
    vmap = {}
    for x in verifier.verify_many(items, confirm=True):
        vmap[(x.theorem_name, x.tactic)] = x.success
    res = {}
    for mdl in ("ar", "flow"):
        per = []
        for n, cnt in pools[mdl].items():
            dv = len({c for c, _ in cnt.most_common(top_per_thm) if vmap.get((n, c))})
            per.append(dv)
        res[mdl] = {"distinct_verified_per_theorem": round(sum(per) / len(per), 3),
                    "total_distinct_candidates": round(sum(len(p) for p in pools[mdl].values()) / len(pools[mdl]), 2)}
    flow_dv = res["flow"]["distinct_verified_per_theorem"]; ar_dv = res["ar"]["distinct_verified_per_theorem"]
    res["H3_supported"] = bool(flow_dv > ar_dv)
    res["lean_seconds"] = round(verifier.total_lean_seconds, 1)
    print(f"H3: distinct-verified/thm  AR={ar_dv}  FLOW={flow_dv}  -> "
          f"{'SUPPORTED' if res['H3_supported'] else 'REFUTED'}")
    return res


def e4_throughput(ar, acfg, flow, fcfg, tier, vocab, dev, *, bs=256, reps=5):
    r = tier[0]
    out = {}
    cond_f = cond_ids_for(r, vocab, max_cond_len=fcfg.max_cond_len, device=dev)
    cond_a = cond_ids_for(r, vocab, max_cond_len=acfg.max_cond_len, device=dev)
    for name, fn in [("flow@8", lambda: flow.generate(cond_f, n_samples=bs, steps=8, cfg_weight=2.0, self_cond=True, prompt="t", device=dev)),
                     ("flow@16", lambda: flow.generate(cond_f, n_samples=bs, steps=16, cfg_weight=2.0, self_cond=True, prompt="t", device=dev)),
                     ("ar", lambda: ar.generate(cond_a, n_samples=bs, prompt="t", device=dev, temperature=1.0))]:
        fn()  # warm
        if dev == "cuda": torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(reps): fn()
        if dev == "cuda": torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        out[name] = round(bs * reps / dt, 1)
        print(f"E4 {name}: {out[name]:,.0f} tactics/s (batch {bs})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flow-snap", default="headline_flow_30M_U3689")
    ap.add_argument("--ar-snap", default="headline_ar_30M_U3689")
    ap.add_argument("--K", type=int, default=32)
    ap.add_argument("--top-per-thm", type=int, default=5)
    ap.add_argument("--verify-cap", type=int, default=220)
    ap.add_argument("--skip-h3", action="store_true")
    args = ap.parse_args(argv)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    ds = load_dataset(); vocab = ds["vocab"]
    tier = mathlib_test_tier(ds["test"], cap=24)
    ar, acfg = load("ar", args.ar_snap, dev)
    flow, fcfg = load("flow", args.flow_snap, dev)

    result = {}
    if not args.skip_h3:
        result["H3"] = h3_diversity(ar, acfg, flow, fcfg, tier, vocab, dev,
                                    K=args.K, top_per_thm=args.top_per_thm, verify_cap=args.verify_cap)
    result["E4_throughput_tactics_per_s"] = e4_throughput(ar, acfg, flow, fcfg, tier, vocab, dev)
    out = OUT / "trackA" / "ext_div_tput.json"
    out.write_text(json.dumps(result, indent=2)); print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
