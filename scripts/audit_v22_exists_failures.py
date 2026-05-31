"""Mini-ELF v22 — Part 3a: exists failure audit.

For each v18 broad-core `exists` theorem, dumps the v20/v21 candidate
beams, first-verified rank, verifier errors, the needed proof shape,
and whether that shape exists anywhere in the v21 broad-plus training
pool. Feeds the exists corpus design (Part 3b).

Read-only: no Lean, no model load.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit_v22_exists_failures")


def _load_preds(p: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s:
            r = json.loads(s)
            out[r["theorem_name"]] = r
    return out


def _first_rank(rec) -> Optional[int]:
    if not rec:
        return None
    for i, v in enumerate(rec.get("verifications", [])):
        if v.get("success"):
            return i
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v20", default="data/baselines/v20_broad_plus_eval_timeout_rerun/abstract/predictions.jsonl")
    ap.add_argument("--v21-routed", default="data/baselines/v21_routed_eval/abstract/predictions.jsonl")
    ap.add_argument("--seeds", default="data/seeds/v18_broad_core_seeds.jsonl")
    ap.add_argument("--train-pool", default="data/processed/v21_broad_plus_forall/train_rows.jsonl")
    ap.add_argument("--out-json", default="data/baselines/v22_exists_failure_audit.json")
    ap.add_argument("--out-md", default="docs/V22_EXISTS_FAILURE_AUDIT.md")
    args = ap.parse_args(argv)

    seeds = {r["theorem_name"]: r for r in
             (json.loads(l) for l in
              (ROOT / args.seeds).read_text(encoding="utf-8").splitlines()
              if l.strip())}
    exists_names = [nm for nm, s in seeds.items() if s.get("category") == "exists"]

    v20 = _load_preds(ROOT / args.v20)
    routed = _load_preds(ROOT / args.v21_routed)

    pool = [json.loads(l) for l in
            (ROOT / args.train_pool).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    # Probe whether anonymous-constructor / cases-elim exists shapes
    # are present in training.
    n_anon = sum(1 for r in pool if "⟨" in (r.get("tactic") or ""))
    n_cases_intro = sum(1 for r in pool
                        if re.search(r"cases .* with", r.get("tactic") or "")
                        and "intro" in (r.get("tactic") or ""))
    n_exists_cat = sum(1 for r in pool if r.get("category") == "exists"
                       or r.get("required_operation") in
                       ("destruct_exists", "exists_reconstruct"))

    rows: List[Dict[str, Any]] = []
    for nm in sorted(exists_names):
        seed = seeds[nm]
        r20, rr = v20.get(nm), routed.get(nm)
        rows.append({
            "theorem_name": nm,
            "split": seed.get("split"),
            "theorem_statement": seed["theorem_statement"],
            "expected_tactic_head": seed.get("expected_tactic_head"),
            "v20_first_rank": _first_rank(r20),
            "routed_first_rank": _first_rank(rr),
            "v20_top5": (r20 or {}).get("ordering", [])[:5],
            "v20_top3_errors": [
                ((v.get("error") or "").splitlines() or [""])[0][:130]
                for v in (r20 or {}).get("verifications", [])[:3]],
        })

    out = {
        "n_exists_theorems": len(rows),
        "training_pool_probes": {
            "rows_with_anonymous_constructor": n_anon,
            "rows_with_cases_with_intro": n_cases_intro,
            "rows_tagged_exists_category_or_op": n_exists_cat,
            "pool_total": len(pool),
        },
        "per_theorem": rows,
        "uses_state_after": False,
    }
    (ROOT / args.out_json).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    logger.info("wrote %s", args.out_json)

    L = ["# v22 exists failure audit\n\n",
         "Read-only audit of the v18 broad-core `exists` category "
         "(the most fragile: 0.250 baseline, 0.000 under both v21 "
         "single-retrain and capacity).\n\n",
         "## Training-pool probes (v21 broad-plus+forall pool)\n\n"]
    pp = out["training_pool_probes"]
    L.append(f"- rows with anonymous constructor `⟨...⟩`: "
             f"{pp['rows_with_anonymous_constructor']}\n")
    L.append(f"- rows with `cases ... with` + `intro`: "
             f"{pp['rows_with_cases_with_intro']}\n")
    L.append(f"- rows tagged exists category/operation: "
             f"{pp['rows_tagged_exists_category_or_op']}\n")
    L.append(f"- pool total: {pp['pool_total']}\n\n")
    L.append("## Per-theorem detail\n\n")
    for r in rows:
        L.append(f"### `{r['theorem_name']}` — {r['split']}\n\n")
        L.append(f"- statement: `{r['theorem_statement']}`\n")
        L.append(f"- expected head: `{r['expected_tactic_head']}`\n")
        L.append(f"- first-verified rank — v20: `{r['v20_first_rank']}`, "
                 f"routed: `{r['routed_first_rank']}`\n")
        L.append("- v20 top-3 candidates:\n")
        for c in r["v20_top5"][:3]:
            L.append(f"  - `{c!r}`\n")
        L.append("- v20 top-3 errors:\n")
        for e in r["v20_top3_errors"][:3]:
            L.append(f"  - `{(e or '').replace(chr(96), chr(39))}`\n")
        L.append("\n")
    L.append("## Needed proof shapes (core Lean)\n\n")
    L.append("- `∃ n, p n` from `h : p k` → `exact ⟨k, h⟩` "
             "(anonymous-constructor witness intro)\n")
    L.append("- `∃ m, n = m` → `exact ⟨n, rfl⟩` (reflexive witness)\n")
    L.append("- `∃ n, p n` from `h : ∃ n, p n` → "
             "`exact h` / `cases h with | intro n hn => exact ⟨n, hn⟩`\n")
    L.append("- compose: `cases h with | intro n hn => exact ⟨n, hpq n hn⟩`\n\n")
    L.append("## Read\n\n")
    L.append("The exists category needs **witness-introduction** shapes "
             "(`exact ⟨witness, proof⟩`) and **exists-elimination** "
             "(`cases h with | intro ...`). The v22 exists corpus (Part 3b) "
             "supplies these with varied witnesses and predicate names so a "
             "single model can learn witness-copy without overfitting to a "
             "fixed literal set (the v8-era `{0,1,2}`-only limitation).\n")
    (ROOT / args.out_md).write_text("".join(L), encoding="utf-8")
    logger.info("wrote %s", args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
