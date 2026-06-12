"""Mini-ELF v42 — P4.2 grounder upgrade pass: beam-2 grounding, ceiling re-measured.

Replaces the grounder's near-greedy per-step decode (temperature 0.05, 1 sample) with
true beam search (width B, sum-of-logprob scoring, deterministic). The ceiling metric
stays pass@1-comparable: one grounded proof per gold plan. Verification is the v42
trusted path. Pre-registered consequence: ceiling ≥ 0.35 lifts v41's "weak grounder"
conditionality on H12/H13.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

import torch
import torch.nn.functional as F

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from v38_matrix_eval import get_verifier, build_model
from v41_plan_factorize import factorize_proof, plan_to_str, HEADS
from v41_ground_eval import _san, step_str, corrupt_plan, GND_DIR


@torch.no_grad()
def beam_decode(model, cond_ids, cfg, device, *, width=2, max_len=None):
    """Deterministic beam search; returns the highest-logprob target id sequence."""
    Tt = max_len or cfg.max_tgt_len
    cond = cond_ids.to(device)                       # (1, Sc)
    cond_pad = cond == cfg.pad_id
    beams = [([cfg.bos_id], 0.0, False)]             # (ids, logprob, finished)
    for _ in range(1, Tt):
        if all(f for (_i, _lp, f) in beams):
            break
        cand = []
        for ids, lp, fin in beams:
            if fin:
                cand.append((ids, lp, True))
                continue
            out = torch.tensor([ids], dtype=torch.long, device=device)
            seq = torch.cat([cond, out], 1)
            kpm = torch.cat([cond_pad, out == cfg.pad_id], 1); kpm[:, cfg.max_cond_len] = False
            h = model.trunk(model.trunk.embed_tokens(seq), causal=True, key_padding_mask=kpm)
            logp = F.log_softmax(model.trunk.readout_logits(h[:, -1, :]).float(), dim=-1)[0]
            top = torch.topk(logp, width)
            for tok, tlp in zip(top.indices.tolist(), top.values.tolist()):
                cand.append((ids + [tok], lp + tlp, tok == cfg.eos_id))
        cand.sort(key=lambda x: x[1], reverse=True)
        beams = cand[:width]
    return beams[0][0]


@torch.no_grad()
def ground_plan_beam(grounder, statement, plan_steps, vocab, cfg, device, *, width=2):
    plan_s = plan_to_str(plan_steps)
    prev = []
    for step in plan_steps:
        cond_text = f"{statement} PLAN: {plan_s} STEP: {step_str(step)} PREV: {' ; '.join(prev)}"
        cids = vocab.encode_source(cond_text)[:cfg.max_cond_len]
        cids = cids + [cfg.pad_id] * (cfg.max_cond_len - len(cids))
        ids = beam_decode(grounder, torch.tensor([cids], dtype=torch.long), cfg, device, width=width)
        tac = _san(vocab.decode_target(ids))
        if not tac:
            tac = step[0] if step[0] in HEADS and step[0] != "OTHER" else "simp"
        prev.append(tac)
    return "\n".join(prev)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grounder", default=str(ROOT / "outputs/v41/grounder/snapshots/scale_ar_30M_U79530.pt"))
    ap.add_argument("--tier", default=str(ROOT / "data/v40/tiers/tier_dev.jsonl"))
    ap.add_argument("--width", type=int, default=2)
    ap.add_argument("--out", default=str(ROOT / "outputs/v42/rebase/ceiling_beam2_v42iso.json"))
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    vocab = TokenVocab.load(GND_DIR / "vocab.json")
    snap = torch.load(args.grounder, map_location="cpu", weights_only=False)
    cfg = V38Config.from_dict(snap["cfg"])
    g = build_model("ar", cfg).to(dev)
    g.load_state_dict({k: v.to(dev) for k, v in snap["state_dict"].items()}); g.eval()

    tier = [json.loads(l) for l in Path(args.tier).read_text().splitlines() if l.strip()]
    rng = random.Random(3407)
    gold_items, corr_items = [], []
    for t in tier:
        plan = factorize_proof(t["proof"])
        if not plan:
            continue
        gold_items.append((t["full_name"], t["statement"],
                           ground_plan_beam(g, t["statement"], plan, vocab, cfg, dev, width=args.width)))
        corr_items.append((t["full_name"], t["statement"],
                           ground_plan_beam(g, t["statement"], corrupt_plan(plan, rng), vocab, cfg, dev,
                                            width=args.width)))

    v = get_verifier()
    t0 = time.time()
    gres = {x.theorem_name: x.success for x in v.verify_many(gold_items, confirm=True)}
    cres = {x.theorem_name: x.success for x in v.verify_many(corr_items, confirm=True)}
    n = len(gold_items)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    res = {"verify_mode": "bisect-batched", "git_sha": sha, "beam_width": args.width,
           "ceiling_pass1": sum(gres.values()) / max(n, 1), "ceiling_hits": sum(gres.values()), "n": n,
           "corrupted_pass1": sum(cres.values()) / max(n, 1), "corrupted_hits": sum(cres.values()),
           "lean_s": round(v.total_lean_seconds, 1), "wall_s": round(time.time() - t0, 1),
           "samples": [{"name": nm, "grounded": pf, "verified": gres.get(nm)}
                       for (nm, _st, pf) in gold_items[:8]]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=1))
    print(f"BEAM-{args.width} CEILING: {res['ceiling_hits']}/{n} = {res['ceiling_pass1']:.3f} "
          f"(greedy was 0.267) | corrupted {res['corrupted_pass1']:.3f} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
