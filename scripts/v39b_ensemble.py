"""Mini-ELF v39b — ensemble / union analysis + novel-string audit.

Reads the per-theorem detail JSONs (scripts/v39_verify.py --detail-dir) and answers
the one remaining open question for continuous flow: does any flow/MDLM setting solve
theorems AR misses (ensemble value), at matched budget? Plus a verbatim novel-verified
tactic audit (truly novel vs trivial variant of a train tactic).

Writes outputs/v39/trackA/detail/ensemble.json. Pure read/analyze, no GPU/Lean.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mini_elf_lean.v38_data import load_dataset

DET = ROOT / "outputs" / "v39" / "trackA" / "detail"

# explicit file -> label map (avoids brittle filename parsing)
FILES = {
    "AR":       "headline_ar_30M_U3689_s16.json",
    "AR@K48":   "headline_ar_30M_U3689_K48.json",
    "MDLM":     "headline_mdlm_30M_U3689_s16.json",
    "FLOW@1":   "headline_flow_30M_U3689_s1.json",
    "FLOW@2":   "headline_flow_30M_U3689_s2.json",
    "FLOW@4":   "headline_flow_30M_U3689_s4.json",
    "FLOW@8":   "headline_flow_30M_U3689_s8.json",
    "FLOW@16":  "headline_flow_30M_U3689_s16.json",
}


def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def norm(s):
    return " ".join(s.split()).strip()


def simp_set(s):
    """If `s` is `simp [..]`/`simp only [..]`, return the lemma multiset for permutation-robust compare."""
    s = norm(s)
    if "[" in s and "]" in s and s.split()[0] in ("simp", "simp_all", "rw", "rfl?"):
        inner = s[s.index("[") + 1:s.rindex("]")]
        return frozenset(x.strip() for x in inner.replace(";", ",").split(",") if x.strip())
    return None


def main():
    ds = load_dataset()
    train_tactics = {r["tactic"] for r in ds["train"]}
    train_norm = {norm(t) for t in train_tactics}
    train_simp = [simp_set(t) for t in train_tactics if simp_set(t) is not None]

    detail = {}
    for label, fn in FILES.items():
        p = DET / fn
        if not p.exists():
            print(f"  missing {label}: {fn}"); continue
        detail[label] = json.load(open(p))

    # solved sets + verified tactics + novel tactics per model
    solved = {}      # label -> set(theorem names solved)
    novel = {}       # label -> list of (theorem, tactic)
    all_names = None
    for label, d in detail.items():
        s, nv = set(), []
        for th in d["theorems"]:
            if th["solved"]:
                s.add(th["name"])
            for c in th["topk"]:
                if c.get("novel"):
                    nv.append((th["name"], c["tactic"]))
        solved[label] = s
        novel[label] = nv
        names = {th["name"] for th in d["theorems"]}
        all_names = names if all_names is None else (all_names | names)
    N = len(all_names)

    # ---- solve matrix (24 x {AR, MDLM, FLOW@1, FLOW@2}) ----
    cols = ["AR", "MDLM", "FLOW@1", "FLOW@2"]
    matrix = []
    for nm in sorted(all_names):
        row = {"theorem": nm}
        for c in cols:
            row[c] = (nm in solved.get(c, set()))
        matrix.append(row)

    # ---- unions (pass@10 = |solved-union| / N) ----
    def union(*labels):
        u = set()
        for l in labels:
            u |= solved.get(l, set())
        return u
    unions = {
        "AR": len(solved["AR"]) / N,
        "AR@K48 (2x budget, AR-alone)": len(solved.get("AR@K48", set())) / N,
        "AR ∪ FLOW@1": len(union("AR", "FLOW@1")) / N,
        "AR ∪ FLOW@2": len(union("AR", "FLOW@2")) / N,
        "AR ∪ MDLM": len(union("AR", "MDLM")) / N,
        "AR ∪ MDLM ∪ FLOW@1": len(union("AR", "MDLM", "FLOW@1")) / N,
        "all-four (AR,MDLM,FLOW@1,FLOW@2)": len(union("AR", "MDLM", "FLOW@1", "FLOW@2")) / N,
    }

    # ---- AR's misses + who covers them ----
    ar_miss = sorted(all_names - solved["AR"])
    miss_coverage = {}
    for m in ar_miss:
        covered_by = [l for l in detail if l != "AR@K48" and m in solved.get(l, set())]
        miss_coverage[m] = covered_by

    # ---- unique solves (solved by exactly one model among AR/MDLM/FLOW@1/FLOW@2) ----
    cmp_labels = ["AR", "MDLM", "FLOW@1", "FLOW@2"]
    unique = {l: [] for l in cmp_labels}
    for nm in sorted(all_names):
        owners = [l for l in cmp_labels if nm in solved.get(l, set())]
        if len(owners) == 1:
            unique[owners[0]].append(nm)

    # ---- novel-string audit (dedup by (theorem,tactic)) ----
    seen, audit = set(), []
    for label, lst in novel.items():
        for (nm, tac) in lst:
            if (nm, tac) in seen:
                continue
            seen.add((nm, tac))
            ntac = norm(tac)
            ss = simp_set(tac)
            if ntac in train_norm:
                verdict = "trivial: normalized-equals a train tactic"
            elif ss is not None and ss in train_simp:
                verdict = "trivial: simp lemma-set permutation of a train tactic"
            else:
                dmin = min((levenshtein(ntac, t) for t in train_norm), default=999)
                verdict = (f"near-variant (min edit-distance {dmin} to train)" if dmin <= 3
                           else f"TRULY NOVEL (min edit-distance {dmin} to nearest train tactic)")
            audit.append({"theorem": nm, "tactic": tac, "found_by": [l for l in novel if (nm, tac) in novel[l]],
                          "verdict": verdict})

    result = {
        "n_theorems": N,
        "solved_counts": {l: len(s) for l, s in solved.items()},
        "solve_matrix": matrix,
        "unions_pass_at_10": unions,
        "ar_misses": ar_miss,
        "ar_miss_coverage": miss_coverage,
        "ar_K48_solves_misses": [m for m in ar_miss if m in solved.get("AR@K48", set())],
        "unique_solves": unique,
        "novel_audit": audit,
    }
    DET.mkdir(parents=True, exist_ok=True)
    (DET / "ensemble.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    # ---- console report ----
    print(f"\n=== ENSEMBLE (n={N} theorems) ===")
    print("solved/24:", {l: len(s) for l, s in solved.items()})
    print("\nunion pass@10:")
    for k, v in unions.items():
        print(f"  {k:<36} {v:.3f} ({round(v*N)}/{N})")
    print(f"\nAR misses ({len(ar_miss)}): {ar_miss}")
    for m, cov in miss_coverage.items():
        print(f"  {m}: covered by {cov if cov else 'NONE'}")
    print(f"AR@K48 (2x budget) solves of AR's misses: {result['ar_K48_solves_misses'] or 'NONE'}")
    print("\nunique solves (among AR/MDLM/FLOW@1/FLOW@2):")
    for l, lst in unique.items():
        print(f"  {l}: {lst if lst else '—'}")
    print(f"\nnovel-verified audit ({len(audit)} unique strings):")
    for a in audit:
        print(f"  [{a['theorem']}] {a['tactic']!r}  by {a['found_by']}\n      -> {a['verdict']}")
    print(f"\nwrote {DET/'ensemble.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
