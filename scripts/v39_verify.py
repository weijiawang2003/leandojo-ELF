"""Mini-ELF v39 — Phase 4 verified evaluation on the frozen 24-theorem tier.

Loads v39 snapshots (Track A) and runs TrustedMathlibVerifier(confirm=True) pass@k
via the validated v38 eval_checkpoint. Headline = AR/MDLM/FLOW at U=full. Also
reports novel-verified and distinct-verified per theorem at K. Budget-capped:
candidates are deduped + cached across models by the verifier.

Track A only: the 24-tier shares the v35 vocab/conditioning. (Track B / LeanDojo
is judged on its own dev exact-seq — distribution mismatch, no tier verification.)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.v38_data import load_dataset, mathlib_test_tier, gold_lookup
from v38_matrix_eval import eval_checkpoint, get_verifier, build_model

from v39_train import git_sha

OUT = ROOT / "outputs" / "v39"


def gen_kw_for(family, cfg_weight=2.0):
    return {"cfg_weight": cfg_weight, "self_cond": True} if family == "flow" else {}


def build_detail(raw, train_tactics, meta):
    """Assemble per-theorem detail from eval_checkpoint's raw pred_topk + vmap, and
    recompute pass@k / novel FROM the detail so they can be regression-checked against
    the aggregate path (which is never touched)."""
    vmap = raw["vmap"]                                # "name\x1ftactic" -> verified
    theorems = []
    for name, topk in raw["pred_topk"].items():
        cands = []
        for t in topk[:10]:
            ver = bool(vmap.get(f"{name}\x1f{t}", False))
            cands.append({"tactic": t, "verified": ver, "novel": ver and (t not in train_tactics)})
        theorems.append({"name": name, "solved": any(c["verified"] for c in cands),
                         "k_samples": raw["K"], "topk": cands})
    n = max(len(theorems), 1)
    agg = {f"pass@{kk}": sum(any(c["verified"] for c in th["topk"][:kk]) for th in theorems) / n
           for kk in (1, 5, 10)}
    agg["novel"] = sum(c["novel"] for th in theorems for c in th["topk"])
    return {**meta, "n_theorems": len(theorems), "aggregate_from_detail": agg, "theorems": theorems}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default="trackA")
    ap.add_argument("--pattern", default="headline_*", help="glob over snapshots/*.pt")
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--gen-steps", type=int, default=16)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--detail-dir", default=None, help="write per-theorem detail JSON per snapshot")
    args = ap.parse_args(argv)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    ds = load_dataset()
    vocab, man = ds["vocab"], ds["manifest"]
    test_tier = mathlib_test_tier(ds["test"], cap=24)
    golds = gold_lookup(ds["train"] + ds["val"] + ds["test"])
    train_tactics = {r["tactic"] for r in ds["train"]}

    snaps = sorted((OUT / args.run / "snapshots").glob(args.pattern.replace(".pt", "") + ".pt"))
    if not snaps:
        snaps = sorted((OUT / args.run / "snapshots").glob(args.pattern))
    print(f"verifying {len(snaps)} snapshots: {[s.stem for s in snaps]}")

    verifier = None if args.no_verify else get_verifier()
    if verifier is None and not args.no_verify:
        print("WARNING: verifier unavailable — running un-verified metrics only")

    results = []
    out_path = Path(args.out) if args.out else (OUT / args.run / "verified.json")
    t0 = time.perf_counter()
    for sp in snaps:
        snap = torch.load(sp, map_location="cpu", weights_only=False)
        cfg = V38Config.from_dict(snap["cfg"])
        family = snap["family"]
        model = build_model(family, cfg, **(snap.get("family_kw") or {})).to(dev)
        ec = eval_checkpoint(model, snap["state_dict"], test_tier, vocab, cfg, golds, train_tactics,
                             K=args.K, steps=args.gen_steps, device=dev, verifier=verifier,
                             gen_kw=gen_kw_for(family), return_detail=bool(args.detail_dir))
        m, raw = ec if args.detail_dir else (ec, None)
        rec = {"cell": sp.stem, "family": family, "params": sum(p.numel() for p in model.parameters()), **m}
        results.append(rec)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        if args.detail_dir and raw is not None:
            ddir = Path(args.detail_dir); ddir.mkdir(parents=True, exist_ok=True)
            gk = gen_kw_for(family)
            meta = {"model_id": sp.stem, "family": family, "steps": args.gen_steps,
                    "cfg_weight": gk.get("cfg_weight"), "gen_seed": 0, "K": args.K,
                    "git_sha": git_sha(), "snapshot": str(sp)}
            detail = build_detail(raw, train_tactics, meta)
            # regression gate: aggregates recomputed from detail must equal the aggregate path
            af = detail["aggregate_from_detail"]; pk = m.get("pass_at_k", {})
            mism = [f"pass@{k}: detail {af[f'pass@{k}']} vs agg {float(pk.get(str(k), 0)):.6f}"
                    for k in (1, 5, 10) if abs(af[f"pass@{k}"] - float(pk.get(str(k), 0))) > 1e-6]
            if af["novel"] != m.get("novel_verified_count", af["novel"]):
                mism.append(f"novel: detail {af['novel']} vs agg {m.get('novel_verified_count')}")
            detail["aggregate_matches_path"] = not mism
            if mism:
                print(f"  *** DETAIL MISMATCH {sp.stem}: {mism}")
            (ddir / f"{sp.stem}_s{args.gen_steps}.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")
        pk = m.get("pass_at_k", {})
        print(f"  [{sp.stem}] pass@1={pk.get('1')} pass@5={pk.get('5')} pass@10={pk.get('10')} "
              f"exact={m['exact_seq_recovery_rate']:.3f} pertok={m['per_token_gold_recovery']:.3f} "
              f"novel={m.get('novel_verified_count')} nverif={m.get('n_candidates_verified')}")
        del model
        if dev == "cuda":
            torch.cuda.empty_cache()
    if verifier is not None:
        print(f"total lean seconds: {verifier.total_lean_seconds:.1f}  wall: {time.perf_counter()-t0:.0f}s")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
