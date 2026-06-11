"""Mini-ELF v40 — verify whole-proof snapshots on a real-Mathlib tier.

Loads a v40 snapshot + corpus vocab, encodes a tier (tier_dev/tier_final) under that
vocab, and runs TrustedMathlibVerifier pass@k via the v39 eval_checkpoint (return_detail
on). Statement is the `example` body; generated proof is a newline-joined tactic block
(verifier compiles `example stmt := by <proof>`). Per-theorem detail persisted.

Tier-final must be touched exactly once (Phase 7).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from mini_elf_lean.baselines import Example, oracle_verified_lookup
from v38_matrix_eval import eval_checkpoint, get_verifier, build_model
from v39_verify import build_detail, git_sha


def gen_kw_for(family, cfg_weight=2.0, self_cond=True):
    return {"cfg_weight": cfg_weight, "self_cond": self_cond} if family == "flow" else {}


def load_tier(path, vocab, cfg):
    rows = []
    for ln in Path(path).read_text().splitlines():
        if not ln.strip():
            continue
        c = json.loads(ln)
        rows.append({"theorem_name": c["full_name"], "theorem_statement": c["statement"],
                     "state_before": "", "tactic": c["proof"],
                     "cond_ids": vocab.encode_source(c["statement"])[:cfg.max_cond_len],
                     "tgt_ids": vocab.encode_target(c["proof"]), "n_tactics": c.get("n_tactics", 1)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", required=True, help="path to .pt (or glob)")
    ap.add_argument("--corpus-dir", default=str(ROOT / "data" / "v40" / "corpora" / "wholeproof"))
    ap.add_argument("--tier", default=str(ROOT / "data" / "v40" / "tiers" / "tier_dev.jsonl"))
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--gen-steps", type=int, default=16)
    ap.add_argument("--cfg-weight", type=float, default=2.0)
    ap.add_argument("--self-cond", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--detail-dir", default=None)
    ap.add_argument("--label", default=None)
    args = ap.parse_args(argv)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    cdir = Path(args.corpus_dir)
    vocab = TokenVocab.load(cdir / "vocab.json")
    train_rows = [json.loads(l) for l in (cdir / "train.jsonl").read_text().splitlines() if l.strip()]
    train_tactics = {r["tactic"] for r in train_rows}

    snaps = sorted(Path().glob(args.snapshot)) if any(c in args.snapshot for c in "*?[") else [Path(args.snapshot)]
    verifier = get_verifier()
    results, t0 = [], time.perf_counter()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    if args.detail_dir:
        Path(args.detail_dir).mkdir(parents=True, exist_ok=True)

    for sp in snaps:
        snap = torch.load(sp, map_location="cpu", weights_only=False)
        cfg = V38Config.from_dict(snap["cfg"]); family = snap["family"]
        tier_rows = load_tier(args.tier, vocab, cfg)
        ex = [Example(r["theorem_name"], r["theorem_statement"], r["state_before"], r["tactic"], "test") for r in tier_rows]
        golds = oracle_verified_lookup(ex)
        model = build_model(family, cfg, **(snap.get("family_kw") or {})).to(dev)
        ec = eval_checkpoint(model, snap["state_dict"], tier_rows, vocab, cfg, golds, train_tactics,
                             K=args.K, steps=args.gen_steps, device=dev, verifier=verifier,
                             gen_kw=gen_kw_for(family, args.cfg_weight, bool(args.self_cond)),
                             return_detail=bool(args.detail_dir))
        m, raw = ec if args.detail_dir else (ec, None)
        label = args.label or sp.stem
        # multi-tactic verified count
        mt_verified = 0
        if raw is not None:
            vmap = raw["vmap"]
            nt = {r["theorem_name"]: r["n_tactics"] for r in tier_rows}
            for th_name, topk in raw["pred_topk"].items():
                if nt.get(th_name, 1) >= 2 and any(vmap.get(f"{th_name}\x1f{t}") for t in topk):
                    mt_verified += 1
        rec = {"label": label, "cell": sp.stem, "family": family, "tier": Path(args.tier).stem,
               "steps": args.gen_steps, "cfg_weight": args.cfg_weight, "n_tier": len(tier_rows),
               "multi_tactic_verified": mt_verified, **m}
        results.append(rec)
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        if args.detail_dir and raw is not None:
            meta = {"model_id": label, "family": family, "steps": args.gen_steps,
                    "cfg_weight": args.cfg_weight, "tier": Path(args.tier).stem, "K": args.K,
                    "git_sha": git_sha(), "snapshot": str(sp)}
            detail = build_detail(raw, train_tactics, meta)
            af, pk = detail["aggregate_from_detail"], m.get("pass_at_k", {})
            detail["aggregate_matches_path"] = all(abs(af[f"pass@{k}"] - float(pk.get(str(k), 0))) < 1e-6 for k in (1, 5, 10))
            (Path(args.detail_dir) / f"{label}.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")
        pk = m.get("pass_at_k", {})
        print(f"  [{label}] tier={Path(args.tier).stem} steps={args.gen_steps} "
              f"pass@1={pk.get('1')} pass@5={pk.get('5')} pass@10={pk.get('10')} "
              f"exact={m['exact_seq_recovery_rate']:.3f} mt_verified={mt_verified} novel={m.get('novel_verified_count')}")
        del model
        if dev == "cuda":
            torch.cuda.empty_cache()
    if verifier is not None:
        print(f"lean seconds: {verifier.total_lean_seconds:.0f} wall {time.perf_counter()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
