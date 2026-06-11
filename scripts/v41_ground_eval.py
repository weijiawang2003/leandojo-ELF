"""Mini-ELF v41 — grounder: greedy plan→proof expansion + ceiling + causality control.

ground_plan(grounder, statement, plan_steps) greedily expands each typed step to a concrete
tactic (conditioned on statement + plan + step + previously-grounded tactics), assembles a proof.
Ceiling = ground the GOLD plans of tier-dev → verify (pipeline upper bound). Causality control =
ground CORRUPTED plans (random head swaps); if pass ≈ gold, the plan is ignored (logic breaks).
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

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list
from v38_matrix_eval import get_verifier, build_model
from v41_plan_factorize import factorize_proof, plan_to_str, HEADS

GND_DIR = ROOT / "data/v41/corpora/grounder"


def _san(s):
    cl, _ = sanitize_candidate_list([s]); return cl[0] if cl else ""


def step_str(step):
    h, a = step
    return f"{h} ( {' , '.join(a)} )"


@torch.no_grad()
def ground_plan(grounder, statement, plan_steps, vocab, cfg, device, *, temperature=0.05, seed=0, prompt=""):
    """Greedy expand each plan step -> tactic; return assembled newline proof."""
    plan_s = plan_to_str(plan_steps)
    prev = []
    for i, step in enumerate(plan_steps):
        cond_text = f"{statement} PLAN: {plan_s} STEP: {step_str(step)} PREV: {' ; '.join(prev)}"
        cids = vocab.encode_source(cond_text)[:cfg.max_cond_len]
        cids = cids + [cfg.pad_id] * (cfg.max_cond_len - len(cids))
        cond = torch.tensor([cids], dtype=torch.long, device=device)
        ids = grounder.generate(cond, n_samples=1, temperature=temperature, prompt=f"{prompt}|{i}", seed=seed, device=device)
        tac = _san(vocab.decode_target(ids[0].tolist()))
        if not tac:
            tac = step[0] if step[0] in HEADS and step[0] != "OTHER" else "simp"
        prev.append(tac)
    return "\n".join(prev)


def corrupt_plan(plan_steps, rng):
    heads = [h for h in HEADS if h != "OTHER"]
    return [(rng.choice(heads), a) for (h, a) in plan_steps]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grounder", default=str(ROOT / "outputs/v41/grounder/snapshots/scale_ar_30M_U79530.pt"))
    ap.add_argument("--tier", default=str(ROOT / "data/v40/tiers/tier_dev.jsonl"))
    ap.add_argument("--temperature", type=float, default=0.05)
    ap.add_argument("--out", default=str(ROOT / "outputs/v41/ceiling.json"))
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    vocab = TokenVocab.load(GND_DIR / "vocab.json")
    snap = torch.load(args.grounder, map_location="cpu", weights_only=False)
    cfg = V38Config.from_dict(snap["cfg"])
    g = build_model("ar", cfg).to(dev)
    g.load_state_dict({k: v.to(dev) for k, v in snap["state_dict"].items()}); g.eval()

    tier = [json.loads(l) for l in Path(args.tier).read_text().splitlines() if l.strip()]
    rng = random.Random(3407)
    gold_items, corr_items, n_planned = [], [], 0
    for t in tier:
        plan = factorize_proof(t["proof"])
        if not plan:
            continue
        n_planned += 1
        gp = ground_plan(g, t["statement"], plan, vocab, cfg, dev, temperature=args.temperature, prompt=t["full_name"])
        gold_items.append((t["full_name"], t["statement"], gp))
        cp = ground_plan(g, t["statement"], corrupt_plan(plan, rng), vocab, cfg, dev, temperature=args.temperature, prompt=t["full_name"] + "_c")
        corr_items.append((t["full_name"], t["statement"], cp))

    v = get_verifier()
    t0 = time.time()
    gres = {(x.theorem_name): x.success for x in v.verify_many(gold_items, confirm=True)}
    cres = {(x.theorem_name): x.success for x in v.verify_many(corr_items, confirm=True)}
    n = len(gold_items)
    ceil_pass = sum(gres.values()) / max(n, 1)
    corr_pass = sum(cres.values()) / max(n, 1)
    print(f"CEILING (gold-plan + grounder, greedy pass@1): {sum(gres.values())}/{n} = {ceil_pass:.3f}")
    print(f"CAUSALITY (corrupted-plan pass@1): {sum(cres.values())}/{n} = {corr_pass:.3f}")
    print(f"  plan IS causally used: {'YES' if ceil_pass > corr_pass + 0.05 else 'WEAK/NO — investigate'}")
    print(f"  (direct-AR tier-dev pass@10 was 0.422; ceiling/{ceil_pass:.2f} bounds the pipeline)")
    print(f"  lean {v.total_lean_seconds:.0f}s wall {time.time()-t0:.0f}s")
    # sample grounded gold proofs
    samples = [{"name": nm, "grounded": pf, "verified": gres.get(nm)} for (nm, st, pf) in gold_items[:8]]
    result = {"ceiling_pass1": ceil_pass, "ceiling_hits": sum(gres.values()), "n": n,
              "corrupted_pass1": corr_pass, "corrupted_hits": sum(cres.values()),
              "plan_causal": bool(ceil_pass > corr_pass + 0.05), "temperature": args.temperature,
              "samples": samples}
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
