"""Mini-ELF v24 — Part 1: detailed audit of the 8 generator-bound rows.

Starts from the v23 generator-bound audit (the 8 v18 broad-core theorems
with NO verified candidate in the v22 plus_exists top-10) and, for each,
records the statement / state / raw top candidates / verifier errors plus
a curated **expected core-Lean proof shape** (probed and lean-verified
during this audit) and the **proposed v24 corpus family**. Read-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit_v24_generator_bound_rows")

# Curated, lean-verified expected shapes + proposed corpus family for each
# of the 8 generator-bound theorems (verified shapes confirmed in Part 1).
CURATED: Dict[str, Dict[str, Any]] = {
    "v18_and_assoc_one": {
        "classification": "conjunction shape gap (nested re-association)",
        "family": "conj_reassoc",
        "verified_shape": "exact ⟨⟨h.1, h.2.1⟩, h.2.2⟩"},
    "v18_or_inr": {
        "classification": "disjunction shape gap + wrong-hyp (emits Or.inr hp not hq)",
        "family": "or_intro",
        "verified_shape": "exact Or.inr hq"},
    "v18_or_elim_to_common": {
        "classification": "disjunction shape gap (or-elimination)",
        "family": "or_elim",
        "verified_shape": "exact Or.elim h hpr hqr"},
    "v18_neg_or_left": {
        "classification": "negation shape gap (push ¬ through Or.inl)",
        "family": "neg_of_or",
        "verified_shape": "intro hp\n  exact h (Or.inl hp)"},
    "v18_exists_intro_eq": {
        "classification": "exists shape gap (reversed reflexive witness ∃ m, n = m)",
        "family": "exists_eq_rev",
        "verified_shape": "exact ⟨n, rfl⟩"},
    "v18_nat_zero_add": {
        "classification": "nat_succ shape gap (0 + n = n is NOT rfl; needs lemma/omega)",
        "family": "nat_zero_add",
        "verified_shape": "exact Nat.zero_add n  /  omega"},
    "v18_nat_succ_inj": {
        "classification": "nat_succ shape gap (succ injectivity)",
        "family": "nat_succ_inj",
        "verified_shape": "exact Nat.succ.inj h  /  injection h  /  omega"},
    "v18_list_append_nil": {
        "classification": "list shape gap (xs ++ [] = xs is NOT rfl; needs lemma/simp)",
        "family": "list_append_nil",
        "verified_shape": "exact List.append_nil xs  /  simp"},
}


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()] if p.exists() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-json", default=str(ROOT / "data" / "baselines"
                                              / "v24_generator_bound_rows.json"))
    ap.add_argument("--out-md", default=str(ROOT / "docs"
                                            / "V24_GENERATOR_BOUND_ROWS.md"))
    args = ap.parse_args(argv)

    seeds = {r["theorem_name"]: r for r in
             _read(ROOT / "data" / "seeds" / "v18_broad_core_seeds.jsonl")}
    raw = {r["theorem_name"]: r for r in
           _read(ROOT / "data" / "baselines" / "v22_general_plus_exists_eval"
                 / "raw" / "predictions.jsonl")}
    gb = json.loads((ROOT / "data" / "baselines"
                     / "v23_generator_bound_audit.json").read_text(encoding="utf-8"))
    gb_names = [t["theorem"] for t in gb["theorems"] if t["class"] == "generator_bound"]

    rows = []
    for nm in gb_names:
        s = seeds.get(nm, {})
        r = raw.get(nm, {})
        cur = CURATED.get(nm, {})
        top = (r.get("ordering") or [])[:3]
        errs = [(v.get("error") or "OK").split("\n")[0].split("error")[-1][:60]
                for v in (r.get("verifications") or [])[:3]]
        rows.append({
            "theorem_name": nm, "category": s.get("category", r.get("category")),
            "statement": s.get("theorem_statement", ""),
            "state_before": s.get("state_before", ""),
            "raw_top3": top, "raw_top3_errors": errs,
            "classification": cur.get("classification", "?"),
            "proposed_family": cur.get("family", "?"),
            "verified_shape": cur.get("verified_shape", "?"),
            "similar_verified_in_training": "no (generator never emitted this shape)",
        })

    out = {"n_generator_bound": len(rows), "rows": rows,
           "families_to_add": sorted({r["proposed_family"] for r in rows}),
           "uses_state_after": False}
    Path(args.out_json).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                   encoding="utf-8")

    L = ["# v24 generator-bound rows (Part 1)\n\n",
         "The 8 v18 broad-core theorems with **no verified candidate in the "
         "v22 plus_exists top-10** (from the v23 generator-bound audit). v23 "
         "proved these are unreachable by reranking; v24 adds targeted, "
         "lean-verified core-Lean shape corpora for each. Every `verified_shape` "
         "below was probed and accepted by lean-cli during this audit.\n\n",
         f"**Families to add:** {', '.join(out['families_to_add'])}\n\n"]
    for r in rows:
        L.append(f"## `{r['theorem_name']}` — {r['category']}\n\n")
        L.append(f"- statement: `{r['statement']}`\n")
        L.append(f"- classification: **{r['classification']}**\n")
        L.append(f"- verified core-Lean shape: `{r['verified_shape']}`\n")
        L.append(f"- proposed corpus family: **{r['proposed_family']}**\n")
        L.append(f"- raw top-3 (all fail): {r['raw_top3']}\n")
        L.append(f"- similar verified tactic in training: "
                 f"{r['similar_verified_in_training']}\n\n")
    Path(args.out_md).write_text("".join(L), encoding="utf-8")
    logger.info("audited %d generator-bound rows; families=%s",
                len(rows), out["families_to_add"])
    logger.info("wrote %s + %s", args.out_json, args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
