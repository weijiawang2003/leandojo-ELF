"""Mini-ELF v43 — A3: gold-plan ceiling under the premise-selection (retrieval) grounder.

Factorize each tier-dev gold proof into a plan (v41 factorizer), ground it with the BM25
retrieval grounder (K fills from retrieved premises, ranked), verify (bisect). Report:
  - retrieval ceiling pass@1 (top-ranked fill) and pass@K
  - causality control: corrupted plan (random heads) must be much lower
vs V42's neural greedy 0.267 / beam-2 0.311. Pre-registered A3 falsifier: ceiling stays < 0.35.
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

from mini_elf_lean.grounder_retrieval import RetrievalGrounder  # noqa: E402
from mini_elf_lean.verdict_cache import VerdictCache, cached_verify  # noqa: E402
from v41_plan_factorize import factorize_proof, HEADS  # noqa: E402


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def corrupt(plan, rng):
    heads = [h for h in HEADS if h != "OTHER"]
    return [(rng.choice(heads), a) for (_h, a) in plan]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="tier_dev")
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--topn", type=int, default=24)
    ap.add_argument("--cache", default=str(ROOT / "outputs/v43/grounder/vcache.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "outputs/v43/grounder/ceiling_retrieval.json"))
    args = ap.parse_args()

    from v38_matrix_eval import get_verifier
    verifier = get_verifier()
    assert verifier is not None
    cache = VerdictCache(Path(args.cache), verifier.imports)
    g = RetrievalGrounder(topn=args.topn)

    rows = [json.loads(l) for l in (ROOT / f"data/v40/tiers/{args.tier}.jsonl").read_text().splitlines() if l.strip()]
    rng = random.Random(3407)
    gold_cands, corr_cands, planned = {}, {}, []
    for r in rows:
        plan = factorize_proof(r["proof"])
        if not plan:
            continue
        planned.append(r["full_name"])
        nm, stmt = r["full_name"], r["statement"]
        sb = r.get("state_before", "")
        gc = g.ground(stmt, sb, plan, K=args.K, exclude=[nm])
        cc = g.ground(stmt, sb, corrupt(plan, rng), K=args.K, exclude=[nm])
        gold_cands[nm] = gc
        corr_cands[nm] = cc

    # verify all (deduped via cache)
    name2stmt = {r["full_name"]: r["statement"] for r in rows}
    items = [(nm, name2stmt[nm], c) for nm, cs in gold_cands.items() for c in cs]
    items += [(nm, name2stmt[nm], c) for nm, cs in corr_cands.items() for c in cs]
    t0 = time.time()
    vmap = cached_verify(verifier, items, cache)

    def passk(cands, k):
        return sum(1 for nm, cs in cands.items() if any(vmap.get((nm, c)) for c in cs[:k]))

    n = len(planned)
    res = {"verify_mode": "bisect-batched", "git_sha": git_sha(), "tier": args.tier,
           "n_planned": n, "K": args.K, "topn": args.topn,
           "retrieval_ceiling_pass1": round(passk(gold_cands, 1) / max(n, 1), 4),
           "retrieval_ceiling_passK": round(passk(gold_cands, args.K) / max(n, 1), 4),
           "ceiling_pass1_hits": passk(gold_cands, 1), "ceiling_passK_hits": passk(gold_cands, args.K),
           "corrupted_pass1": round(passk(corr_cands, 1) / max(n, 1), 4),
           "corrupted_passK": round(passk(corr_cands, args.K) / max(n, 1), 4),
           "v42_reference": {"neural_greedy": 0.267, "neural_beam2": 0.311},
           "lean_s": round(verifier.total_lean_seconds, 1), "wall_s": round(time.time() - t0, 1),
           "solved_names_passK": sorted(nm for nm, cs in gold_cands.items() if any(vmap.get((nm, c)) for c in cs))}
    op = Path(args.out); op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(res, indent=1))
    print(f"[{args.tier}] retrieval ceiling pass@1={res['retrieval_ceiling_pass1']} "
          f"pass@{args.K}={res['retrieval_ceiling_passK']} (neural greedy 0.267 / beam2 0.311) | "
          f"corrupted pass@1={res['corrupted_pass1']} pass@{args.K}={res['corrupted_passK']}")
    print("->", op)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
