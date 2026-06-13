"""Mini-ELF v44 — S1: build a non-simp-closable hard tier with bisect-compiling gold + gold premises.

From the LeanDojo Benchmark 4 random/test pool: reconstruct each theorem as
`example <binders+goal> := by <newline gold tactics>` (v40 converter), extract the gold premise
names (union over annotated tactics), then keep a theorem iff:
  (a) its gold proof COMPILES under bisect, AND
  (b) the 15-tactic trivial sweep {simp,simp_all,aesop,...} FAILS (non-simp-closable).
Target n>=100. Emits the tier + a closability audit of the scanned pool (so hardness is auditable).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

from v40_wholeproof import state_to_example, whole_proof
from mini_elf_lean.verdict_cache import VerdictCache, cached_verify

POOL = ROOT / "data/v39/_raw/leandojo_benchmark_4/random/test.json"
TRAIN_POOL = ROOT / "data/v39/_raw/leandojo_benchmark_4/random/train.json"
WIDE = ["simp", "simp_all", "aesop", "norm_num", "omega", "rfl", "tauto", "decide",
        "simp_all [*]", "aesop?", "exact?", "norm_num [*]", "simp only []",
        "constructor <;> simp", "intro <;> simp"]


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def gold_premises(traced) -> list:
    names = []
    seen = set()
    for tt in traced:
        ann = tt.get("annotated_tactic")
        if ann and len(ann) > 1 and ann[1]:
            for p in ann[1]:
                fn = p.get("full_name")
                if fn and fn not in seen:
                    seen.add(fn); names.append(fn)
    return names


def candidate_rows(pool_path: Path, limit: int):
    """Yield (full_name, statement, gold_proof, premises, n_tactics) for convertible theorems."""
    data = json.loads(pool_path.read_text())
    out = []
    seen_names = set()
    for r in data:
        nm = r["full_name"]
        if nm in seen_names:
            continue
        traced = r.get("traced_tactics") or []
        if not traced:
            continue
        stmt = state_to_example(traced[0]["state_before"])
        if not stmt:
            continue
        proof = whole_proof(traced, linear_only=True)
        if not proof:
            continue
        seen_names.add(nm)
        out.append({"full_name": nm, "statement": stmt, "proof": proof,
                    "premises": gold_premises(traced), "n_tactics": len(proof.splitlines()),
                    "file_path": r.get("file_path", "")})
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", type=int, default=900, help="max theorems to convert+screen")
    ap.add_argument("--target", type=int, default=110)
    ap.add_argument("--cache", default=str(ROOT / "outputs/v44/hard_tier/vcache.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "outputs/v44/hard_tier"))
    args = ap.parse_args()

    from v38_matrix_eval import get_verifier
    verifier = get_verifier()
    assert verifier is not None
    cache = VerdictCache(Path(args.cache), verifier.imports)

    cands = candidate_rows(POOL, args.scan)
    print(f"convertible candidates from test pool: {len(cands)}")

    # Step 1: gold compiles? (bisect) — one candidate per theorem
    t0 = time.time()
    gold_items = [(c["full_name"], c["statement"], c["proof"]) for c in cands]
    gold_v = cached_verify(verifier, gold_items, cache)
    compiling = [c for c in cands if gold_v.get((c["full_name"], c["proof"]))]
    print(f"gold-compiling: {len(compiling)}/{len(cands)} = {len(compiling)/max(len(cands),1):.1%} "
          f"({time.time()-t0:.0f}s)")

    # Step 2: simp-closability of the compiling set (drop closable)
    t1 = time.time()
    simp_items = [(c["full_name"], c["statement"], tac) for c in compiling for tac in WIDE]
    simp_v = cached_verify(verifier, simp_items, cache)
    hard, closable = [], []
    for c in compiling:
        hits = [tac for tac in WIDE if simp_v.get((c["full_name"], tac))]
        c["simp_hits"] = hits
        (closable if hits else hard).append(c)
    print(f"non-simp-closable (HARD): {len(hard)}/{len(compiling)} "
          f"(closable {len(closable)}) ({time.time()-t1:.0f}s)")

    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    # split hard into dev/test (test touched once); keep premises + proof
    hard_sorted = sorted(hard, key=lambda c: c["full_name"])
    for c in hard_sorted:
        c.pop("simp_hits", None)
    n = len(hard_sorted)
    half = n // 2
    dev, test = hard_sorted[:half], hard_sorted[half:]
    with (out_dir / "hard_dev.jsonl").open("w") as f:
        for c in dev:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with (out_dir / "hard_test.jsonl").open("w") as f:
        for c in test:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    audit = {"verify_mode": "bisect-batched", "git_sha": git_sha(), "pool": str(POOL),
             "scanned": len(cands), "gold_compiling": len(compiling),
             "gold_compile_rate": round(len(compiling) / max(len(cands), 1), 4),
             "non_simp_closable": len(hard), "simp_closable": len(closable),
             "simp_closability_rate": round(len(closable) / max(len(compiling), 1), 4),
             "n_dev": len(dev), "n_test": len(test),
             "avg_premises_hard": round(sum(len(c["premises"]) for c in hard) / max(len(hard), 1), 2),
             "avg_n_tactics_hard": round(sum(c["n_tactics"] for c in hard) / max(len(hard), 1), 2),
             "lean_s": round(verifier.total_lean_seconds, 1)}
    (out_dir / "audit.json").write_text(json.dumps(audit, indent=1))
    print(f"HARD TIER: dev={len(dev)} test={len(test)} | gold-compile {audit['gold_compile_rate']:.1%} "
          f"| simp-closable {audit['simp_closability_rate']:.1%} | avg premises {audit['avg_premises_hard']}")
    print("->", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
