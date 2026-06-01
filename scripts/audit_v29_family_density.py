"""Mini-ELF v29 — Part 1: sibling-density audit.

v28 established that improvement on fresh Mathlib held-outs comes from **within-family
sibling density**, not generic category transfer. v29's central hypothesis is that
*held-out success is a function of how many training siblings a family has*. This
script measures that relationship from existing artifacts (NO Lean run):

For every theorem family across the v26 / v27 / v28 Mathlib verified corpora it
records:
  * verified candidate rows in the family;
  * distinct theorem statements (siblings) in the family;
  * distinct proof heads (first tactic token) in the family;
  * variable-name variants (distinct alpha-skeletons -> how much the family varies
    surface identifiers vs pure shape);
  * held-out members of the family and their best-config pass@1/5/10 (from the v28
    specialist eval + category-holdout transfer cells).

It then bins families by sibling count (1-3 / 4-6 / 7-10 / 10+), computes mean
held-out pass@10 per bin (the density law), tallies residual failures per bin, and
flags the sparse families v29 should densify (Finset projection direction,
le_antisymm, comp_assoc, union_subset, mem_inter_iff variants, Set/Finset inter/union
projection, Nat/List name variants).

theorem_family is taken verbatim where the corpus carries it (v27/v28); for the
older v25/v26 rows that predate the field, a family stem is derived from the theorem
name (version prefix + trailing index stripped). Reads only existing artifacts;
expected proofs are Lean-verified references, never predictions; no state_after.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

TRACES = ROOT / "data" / "traces"
V28_SPEC = ROOT / "data" / "baselines" / "v28_specialist_eval"
PROC = ROOT / "data" / "processed"

# model label -> its training-rows file (used to compute *effective* training
# density: how many family siblings actually remained in the train set of the model
# that evaluated a held-out theorem). Transfer-cell models have their whole category
# removed, so their effective in-category density is ~0 — this is exactly the signal
# that distinguishes the within-family-density regime from whole-category transfer.
MODEL_TRAIN = {
    "v26_base": PROC / "v26_mathlib_specialist" / "train_rows.jsonl",
    "v26_widened": PROC / "v26_mathlib_specialist" / "train_rows.jsonl",
    "v27_widened": PROC / "v27_mathlib_specialist" / "configs" / "v27_widened_train_rows.jsonl",
    "v27_set_heavy": PROC / "v27_mathlib_specialist" / "configs" / "v27_set_heavy_train_rows.jsonl",
    "v28_general": PROC / "v28_mathlib_specialist" / "configs" / "v28_general_train_rows.jsonl",
    "v28_set_order_heavy": PROC / "v28_mathlib_specialist" / "configs" / "v28_set_order_heavy_train_rows.jsonl",
    "v28_category_balanced": PROC / "v28_mathlib_specialist" / "configs" / "v28_category_balanced_train_rows.jsonl",
    "v28_finset_specialist": PROC / "v28_mathlib_specialist" / "configs" / "v28_finset_specialist_train_rows.jsonl",
    "v28_set_holdout": PROC / "v28_mathlib_specialist" / "category_holdout_set" / "train_rows.jsonl",
    "v28_order_holdout": PROC / "v28_mathlib_specialist" / "category_holdout_order" / "train_rows.jsonl",
    "v28_finset_holdout": PROC / "v28_mathlib_specialist" / "category_holdout_finset" / "train_rows.jsonl",
}

# Mathlib verified corpora (v26 .. v28). v25 is included for completeness of the
# family census but predates theorem_family.
CORPORA = [
    ("v26", TRACES / "v26_mathlib_specialist_verified.jsonl"),
    ("v26_set", TRACES / "v26_set_widen_verified.jsonl"),
    ("v27", TRACES / "v27_mathlib_expanded_verified.jsonl"),
    ("v28", TRACES / "v28_mathlib_expanded_verified.jsonl"),
]

_VER_PREFIX = re.compile(r"^v\d+_")
_TAIL_IDX = re.compile(r"_\d+$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def name_stem(name: str) -> str:
    """Derive a family stem from a theorem name: drop version prefix + trailing
    numeric index (alpha-rename siblings share a stem)."""
    s = _VER_PREFIX.sub("", name)
    s = _TAIL_IDX.sub("", s)
    return s or name


def family_of(row: Dict[str, Any]) -> str:
    """Explicit theorem_family when present (v27/v28); else derived name stem
    namespaced by category so unrelated stems don't collide across categories."""
    fam = (row.get("theorem_family") or "").strip()
    if fam:
        return f"{row.get('category','?')}::{fam}"
    return f"{row.get('category','?')}::{name_stem(row.get('theorem_name',''))}"


def alpha_skeleton(stmt: str) -> str:
    """Replace identifiers with a positional placeholder so two statements that
    differ only by variable renaming collapse to one skeleton. Keeps operators,
    keywords, and structure; this lets us count true *shape* siblings vs pure
    surface-token (variable-name) variants."""
    # keep Lean/Mathlib keywords & type names; rename lower-case single/short binders
    KEEP = {"Type", "Set", "Finset", "List", "Nat", "Prop", "Preorder", "PartialOrder",
            "LinearOrder", "Lattice", "DecidableEq", "id", "min", "max", "True", "False"}
    def repl(m):
        tok = m.group(0)
        if tok in KEEP or tok[0].isupper():
            return tok
        return "_v"
    return _IDENT.sub(repl, stmt)


def bin_of(n_siblings: int) -> str:
    if n_siblings <= 3:
        return "1-3"
    if n_siblings <= 6:
        return "4-6"
    if n_siblings <= 10:
        return "7-10"
    return "10+"


def best_pred_file(run_dir: Path) -> Optional[Path]:
    best = None
    for mf in run_dir.glob("*/metrics.json"):
        m = json.loads(mf.read_text())
        key = (m.get("pass@5", 0), m.get("pass@1", 0))
        if best is None or key > best[0]:
            best = (key, mf.parent / "predictions.jsonl")
    return best[1] if best else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v29_family_density" / "report.json"))
    ap.add_argument("--out-families", default=str(ROOT / "data" / "baselines" / "v29_family_density" / "families.jsonl"))
    args = ap.parse_args(argv)

    # ---- census: family -> stats over the combined verified corpora ----
    fam_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    fam_thms: Dict[str, set] = defaultdict(set)
    fam_stmts: Dict[str, set] = defaultdict(set)
    fam_heads: Dict[str, set] = defaultdict(set)
    fam_skels: Dict[str, set] = defaultdict(set)
    fam_cat: Dict[str, str] = {}
    thm_family: Dict[str, str] = {}
    thm_stmt: Dict[str, str] = {}
    for _ver, path in CORPORA:
        for r in _read(path):
            fam = family_of(r)
            nm = r.get("theorem_name", "")
            fam_rows[fam].append(r)
            fam_thms[fam].add(nm)
            fam_stmts[fam].add(r.get("theorem_statement", ""))
            head = (r.get("proof_head") or (r.get("tactic", "").split() or [""])[0]).strip()
            fam_heads[fam].add(head)
            fam_skels[fam].add(alpha_skeleton(r.get("theorem_statement", "")))
            fam_cat.setdefault(fam, r.get("category", "?"))
            thm_family[nm] = fam
            thm_stmt[nm] = r.get("theorem_statement", "")

    # ---- per-model training family census (for effective density) ----
    train_fam_names: Dict[str, Dict[str, set]] = {}
    for model, tf in MODEL_TRAIN.items():
        fam_names: Dict[str, set] = defaultdict(set)
        for r in _read(tf):
            fam_names[family_of(r)].add(r.get("theorem_name", ""))
        train_fam_names[model] = fam_names

    def effective_density(nm: str, model: str, fam: str) -> Optional[int]:
        """# distinct sibling theorems of `fam` present in `model`'s training set,
        excluding the held-out theorem itself. None if the model's train file is
        unknown."""
        fam_names = train_fam_names.get(model)
        if fam_names is None:
            return None
        return len(fam_names.get(fam, set()) - {nm})

    # ---- held-out outcomes: collect EVERY (theorem, model, bench) eval point with
    # its effective training density, plus the per-theorem *realised* best outcome
    # (for the per-family summary). Using all points is what separates the
    # full-family condition from the category-removed condition for the same theorem.
    eval_points: List[Dict[str, Any]] = []  # one per (theorem, model, bench) best-config
    thm_outcome: Dict[str, Dict[str, Any]] = {}
    if V28_SPEC.exists():
        for run_dir in sorted(V28_SPEC.iterdir()):
            if not run_dir.is_dir():
                continue
            pf = best_pred_file(run_dir)
            if not pf:
                continue
            model = run_dir.name.split("__")[0]
            is_transfer = model in ("v28_set_holdout", "v28_order_holdout", "v28_finset_holdout")
            for r in _read(pf):
                nm = r["theorem_name"]
                p10, p5, p1 = int(bool(r.get("pass@10"))), int(bool(r.get("pass@5"))), int(bool(r.get("pass@1")))
                fam = thm_family.get(nm)
                ed = effective_density(nm, model, fam) if fam else None
                eval_points.append({"theorem": nm, "model": model, "cell": run_dir.name,
                                    "family": fam, "effective_density": ed,
                                    "pass@1": p1, "pass@5": p5, "pass@10": p10,
                                    "transfer_cell": is_transfer})
                cur = thm_outcome.get(nm)
                cand = {"pass@1": p1, "pass@5": p5, "pass@10": p10,
                        "first_rank": r.get("first_verified_rank"),
                        "category": r.get("category"), "transfer_cell": is_transfer,
                        "cell": run_dir.name}
                if cur is None or (cand["pass@10"], cand["pass@5"]) > (cur["pass@10"], cur["pass@5"]):
                    thm_outcome[nm] = cand

    # ---- assemble per-family record ----
    families = []
    for fam in sorted(fam_rows):
        n_sib = len(fam_thms[fam])           # distinct theorem siblings
        held = [(nm, thm_outcome[nm]) for nm in fam_thms[fam] if nm in thm_outcome]
        ho_p10 = [o["pass@10"] for _nm, o in held]
        ho_p5 = [o["pass@5"] for _nm, o in held]
        ho_p1 = [o["pass@1"] for _nm, o in held]
        rec = {
            "family": fam, "category": fam_cat[fam],
            "n_verified_rows": len(fam_rows[fam]),
            "n_sibling_theorems": n_sib,
            "n_distinct_statements": len(fam_stmts[fam]),
            "n_distinct_proof_heads": len(fam_heads[fam]),
            "n_alpha_skeletons": len(fam_skels[fam]),
            "n_varname_variants": max(0, len(fam_stmts[fam]) - len(fam_skels[fam])),
            "density_bin": bin_of(n_sib),
            "n_heldout_members": len(held),
            "heldout_pass@1": round(sum(ho_p1) / len(ho_p1), 4) if ho_p1 else None,
            "heldout_pass@5": round(sum(ho_p5) / len(ho_p5), 4) if ho_p5 else None,
            "heldout_pass@10": round(sum(ho_p10) / len(ho_p10), 4) if ho_p10 else None,
            "heldout_success": sum(ho_p10), "heldout_fail": len(ho_p10) - sum(ho_p10),
            "heldout_theorems": [nm for nm, _o in held],
        }
        families.append(rec)

    # ---- effective-density law: bin each held-out *evaluation* by the number of
    # training siblings actually available to the model that produced its outcome.
    # This is the honest density signal — transfer cells (whole category removed)
    # land at density 0, theorem-holdouts keep their family, so the law separates
    # the two regimes v28 conflated.
    EBINS = ["0", "1-3", "4-6", "7-10", "10+"]

    def ebin_of(n: int) -> str:
        if n == 0:
            return "0"
        return bin_of(n)

    eff_points: List[Tuple[int, int, str, str]] = [  # (eff_density, pass@10, theorem, family)
        (pt["effective_density"], pt["pass@10"], pt["theorem"], pt["family"])
        for pt in eval_points if pt["effective_density"] is not None]

    by_ebin: Dict[str, Dict[str, Any]] = {b: {"n_heldout": 0, "heldout_success": 0} for b in EBINS}
    for ed, p10, _nm, _fam in eff_points:
        d = by_ebin[ebin_of(ed)]
        d["n_heldout"] += 1
        d["heldout_success"] += p10
    for b in EBINS:
        d = by_ebin[b]
        d["pass@10"] = round(d["heldout_success"] / d["n_heldout"], 4) if d["n_heldout"] else None

    # corpus-wide family-size bins (descriptive only; not the law)
    bins = ["1-3", "4-6", "7-10", "10+"]
    by_bin: Dict[str, Dict[str, Any]] = {b: {"n_families": 0, "n_heldout": 0,
                                             "heldout_success": 0, "heldout_fail": 0} for b in bins}
    for rec in families:
        b = rec["density_bin"]
        by_bin[b]["n_families"] += 1
        if rec["n_heldout_members"]:
            by_bin[b]["n_heldout"] += rec["n_heldout_members"]
            by_bin[b]["heldout_success"] += rec["heldout_success"]
            by_bin[b]["heldout_fail"] += rec["heldout_fail"]
    for b in bins:
        d = by_bin[b]
        d["pass@10"] = round(d["heldout_success"] / d["n_heldout"], 4) if d["n_heldout"] else None

    # ---- density by category (avg family density + held-out pass@10) ----
    by_cat: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"families": 0, "sib_total": 0,
                                                             "ho_n": 0, "ho_succ": 0})
    for rec in families:
        c = by_cat[rec["category"]]
        c["families"] += 1
        c["sib_total"] += rec["n_sibling_theorems"]
        c["ho_n"] += rec["n_heldout_members"]
        c["ho_succ"] += rec["heldout_success"]
    cat_density = {}
    for cat, c in sorted(by_cat.items()):
        cat_density[cat] = {
            "n_families": c["families"],
            "avg_family_density": round(c["sib_total"] / c["families"], 2) if c["families"] else 0,
            "n_heldout": c["ho_n"],
            "heldout_pass@10": round(c["ho_succ"] / c["ho_n"], 4) if c["ho_n"] else None,
        }

    # ---- sparse families to densify (1-3 siblings) + the named v29 targets ----
    TARGET_HINTS = ["mem_of_mem_inter", "inter_proj", "antisymm", "comp_assoc", "union_subset",
                    "mem_inter", "inter_subset", "subset_union", "mem_union", "le_trans",
                    "le_of_eq", "append", "reverse", "map_"]
    sparse = sorted([r for r in families if r["n_sibling_theorems"] <= 3],
                    key=lambda r: (r["category"], r["family"]))
    flagged = sorted([r for r in families
                      if any(h in r["family"] for h in TARGET_HINTS)],
                     key=lambda r: r["n_sibling_theorems"])

    # ---- correlation: does *effective* training density predict success? ----
    xs = [ed for ed, _p, _n, _f in eff_points]
    ys = [p for _ed, p, _n, _f in eff_points]
    # binary form too: any siblings (density>0) vs none
    has_sib = [(1 if ed > 0 else 0, p) for ed, p, _n, _f in eff_points]
    corr = None
    if len(xs) >= 3 and len(set(xs)) > 1 and len(set(ys)) > 1:
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs)
        vy = sum((y - my) ** 2 for y in ys)
        corr = round(cov / (vx ** 0.5 * vy ** 0.5), 4) if vx and vy else None
    p10_no_sib = ([p for s, p in has_sib if s == 0])
    p10_sib = ([p for s, p in has_sib if s == 1])
    density_gate = {
        "pass@10_density_0": round(sum(p10_no_sib) / len(p10_no_sib), 4) if p10_no_sib else None,
        "n_density_0": len(p10_no_sib),
        "pass@10_density_ge1": round(sum(p10_sib) / len(p10_sib), 4) if p10_sib else None,
        "n_density_ge1": len(p10_sib),
    }

    report = {
        "config": "v29_family_density_audit",
        "source": "v26/v27/v28 verified corpora + v28 specialist eval (no Lean run)",
        "n_families": len(families),
        "n_families_with_heldout": sum(1 for r in families if r["n_heldout_members"]),
        "effective_density_law": by_ebin,
        "effective_density_gate": density_gate,
        "corpus_family_size_bins_descriptive": by_bin,
        "density_by_category": cat_density,
        "pointwise_effdensity_vs_pass10_pearson": corr,
        "n_effective_density_points": len(eff_points),
        "n_sparse_families_1_3": len(sparse),
        "sparse_families_to_densify": [
            {"family": r["family"], "category": r["category"],
             "n_siblings": r["n_sibling_theorems"], "n_heads": r["n_distinct_proof_heads"],
             "heldout_pass@10": r["heldout_pass@10"], "n_heldout": r["n_heldout_members"]}
            for r in sparse],
        "named_target_families": [
            {"family": r["family"], "category": r["category"],
             "n_siblings": r["n_sibling_theorems"], "density_bin": r["density_bin"],
             "heldout_pass@10": r["heldout_pass@10"], "n_heldout": r["n_heldout_members"]}
            for r in flagged],
        "uses_state_after": False, "uses_manual_oracle": False,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with Path(args.out_families).open("w", encoding="utf-8") as f:
        for rec in sorted(families, key=lambda r: (-r["n_sibling_theorems"], r["family"])):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[density] families={len(families)} with_heldout={report['n_families_with_heldout']} "
          f"pearson(eff_density,pass@10)={corr} (n={len(eff_points)})")
    print(f"[density] GATE: density=0 pass@10={density_gate['pass@10_density_0']} "
          f"(n={density_gate['n_density_0']}) | density>=1 pass@10={density_gate['pass@10_density_ge1']} "
          f"(n={density_gate['n_density_ge1']})")
    print("[density] effective-density law (training siblings available):")
    for b in EBINS:
        d = by_ebin[b]
        print(f"   eff={b:5s} heldout={d['n_heldout']:3d} pass@10={d['pass@10']}")
    print("[density] by category (avg_family_density | heldout pass@10):")
    for cat, d in cat_density.items():
        print(f"   {cat:9s} fams={d['n_families']:3d} avg_density={d['avg_family_density']:5.2f} "
              f"ho_n={d['n_heldout']:3d} pass@10={d['heldout_pass@10']}")
    print(f"[density] sparse (1-3 sib) families: {len(sparse)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
