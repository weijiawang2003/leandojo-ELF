"""V4 Part 1 — audit what the Mini-ELF v3 symbolic planner does and does not cover.

Three views, all from existing artifacts (no Lean, no new corpus):

  1. **Shape catalog** — run the planner on a fixed probe of proof shapes
     (supported *and* deliberately-unsupported) and report how many candidates it
     emits for each. Shapes with 0 planner candidates are the planner-blind
     frontier the v4 corpus targets (negation/contradiction, contrapositive,
     ∃-elimination, ∀-instantiation, rewrite/substitution).
  2. **Empirical family coverage** — run the planner on every basic + hard seed
     and report, per pattern family, the fraction of theorems for which it emits
     ≥1 candidate.
  3. **v3 source attribution** — from the Lean-verified v3 predictions, which
     source actually solved each family, which theorems are solved *only* by the
     symbolic planner (not the learned flow generator), and concrete cases where
     the v2 reranker scores a Lean-verified planner candidate low (i.e. would
     mis-rank it below flow garble if the tier policy did not bypass it).

Reads `proof_planner.py` behavior + seeds + `data/baselines/mini_elf_v3_*`
predictions. Theorem-level only; never reads `state_after`. Writes
`docs/V4_PLANNER_COVERAGE_AUDIT.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.io_utils import read_jsonl  # noqa: E402
from mini_elf_lean.proof_planner import PLANNER_SOURCES, plan_candidates  # noqa: E402

# A fixed catalog: (shape_name, supported?, theorem_statement, state_before).
_S = "\n".join
SHAPE_PROBES: List[Tuple[str, bool, str, str]] = [
    ("conjunction projection (nested)", True,
     "(p q r : Prop) (h : p ∧ q ∧ r) : r", _S(["p q r : Prop", "h : p ∧ q ∧ r", "⊢ r"])),
    ("implication chain", True,
     "(p q r s : Prop) (h1 : p → q) (h2 : q → r) (h3 : r → s) : p → s",
     _S(["p q r s : Prop", "h1 : p → q", "h2 : q → r", "h3 : r → s", "⊢ p → s"])),
    ("iff direction composition", True,
     "(p q r : Prop) (h1 : p ↔ q) (h2 : q ↔ r) : p → r",
     _S(["p q r : Prop", "h1 : p ↔ q", "h2 : q ↔ r", "⊢ p → r"])),
    ("equality trans/symm chain", True,
     "(a b c d : Nat) (h1 : a = b) (h2 : b = c) (h3 : c = d) : a = d",
     _S(["a b c d : Nat", "h1 : a = b", "h2 : b = c", "h3 : c = d", "⊢ a = d"])),
    ("∨-elimination case split", True,
     "(p q r : Prop) (h : p ∨ q) (hp : p → r) (hq : q → r) : r",
     _S(["p q r : Prop", "h : p ∨ q", "hp : p → r", "hq : q → r", "⊢ r"])),
    ("∧/∨ introduction", True,
     "(p q : Prop) (hp : p) (hq : q) : p ∧ q", _S(["p q : Prop", "hp : p", "hq : q", "⊢ p ∧ q"])),
    ("∃-witness (deferred to witness-copy)", False,
     ": ∃ n : Nat, n = 6", _S(["⊢ ∃ n : Nat, n = 6"])),
    ("negation: ¬p + p ⊢ q (ex falso)", False,
     "(p q : Prop) (hp : p) (hnp : ¬p) : q",
     _S(["p q : Prop", "hp : p", "hnp : ¬p", "⊢ q"])),
    ("contrapositive ⊢ ¬p", False,
     "(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p",
     _S(["p q : Prop", "h : p → q", "hnq : ¬q", "⊢ ¬p"])),
    ("∃-elimination (h : ∃ _, p ⊢ p)", False,
     "(p : Prop) (h : ∃ _ : Nat, p) : p",
     _S(["p : Prop", "h : ∃ _ : Nat, p", "⊢ p"])),
    ("∀-instantiation (h : ∀ x, x = 0 ⊢ 7 = 0)", False,
     "(h : ∀ x : Nat, x = 0) : 7 = 0",
     _S(["h : ∀ x : Nat, x = 0", "⊢ 7 = 0"])),
    ("rewrite/substitution (h : n = m ⊢ n.succ = m.succ)", False,
     "(n m : Nat) (h : n = m) : n.succ = m.succ",
     _S(["n m : Nat", "h : n = m", "⊢ n.succ = m.succ"])),
    ("negation inside cases (h : p ∨ q, ¬p ⊢ q)", False,
     "(p q : Prop) (h : p ∨ q) (hnp : ¬p) : q",
     _S(["p q : Prop", "h : p ∨ q", "hnp : ¬p", "⊢ q"])),
]

V3_SPLITS = [
    ("hard difficulty_holdout", "mini_elf_v3_hard_difficulty_test"),
    ("hard adversarial_sibling", "mini_elf_v3_hard_adversarial_test"),
    ("hard hash", "mini_elf_v3_hard_hash_test"),
    ("basic", "mini_elf_v3_basic_test"),
]
_PLANNER = set(PLANNER_SOURCES)


def _shape_catalog() -> List[Dict[str, Any]]:
    out = []
    for name, supported, stmt, state in SHAPE_PROBES:
        cands = plan_candidates(stmt, state)
        out.append({
            "shape": name, "expected_supported": supported,
            "planner_candidates": len(cands),
            "sample": cands[0].tactic.replace("\n", "\\n") if cands else None,
            "sample_source": cands[0].source if cands else None,
        })
    return out


def _family_coverage(seed_paths: List[Path]) -> Dict[str, Dict[str, int]]:
    cov: Dict[str, Dict[str, int]] = defaultdict(lambda: {"covered": 0, "total": 0})
    for sp in seed_paths:
        for row in read_jsonl(sp):
            meta = row.get("metadata") or {}
            fam = meta.get("pattern_family")
            if not fam:
                continue
            cands = plan_candidates(row["theorem_statement"], row["initial_state"], pattern_family=fam)
            cov[fam]["total"] += 1
            cov[fam]["covered"] += int(bool(cands))
    return {k: v for k, v in sorted(cov.items())}


def _v3_attribution(pred_path: Path, thm2fam: Dict[str, str]) -> Dict[str, Any]:
    rows = list(read_jsonl(pred_path))
    fam_src: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    planner_only: List[str] = []
    misrank: List[Dict[str, Any]] = []
    for row in rows:
        fam = thm2fam.get(row.get("theorem_name", ""), "?")
        preds = row.get("predictions") or []
        prov = row.get("prediction_provenance") or []
        lean = row.get("lean_results") or {}
        planner_ok = flow_ok = False
        for i, tac in enumerate(preds):
            p = prov[i] if i < len(prov) else {}
            src = p.get("source")
            ok = bool(lean.get(tac, {}).get("success"))
            if ok:
                fam_src[fam][src or "?"] += 1
            if src in _PLANNER:
                if ok:
                    planner_ok = True
                    sc = p.get("reranker_score")
                    if sc is not None and sc < 0.5:
                        misrank.append({"theorem": row.get("theorem_name"), "family": fam,
                                        "tactic": tac.replace("\n", "\\n"), "reranker_score": round(sc, 3)})
            elif src == "flow_decoder" and ok:
                flow_ok = True
        if planner_ok and not flow_ok:
            planner_only.append(row.get("theorem_name", ""))
    return {
        "verified_by_source_by_family": {k: dict(v) for k, v in sorted(fam_src.items())},
        "n_planner_only_theorems": len(set(planner_only)),
        "planner_only_examples": sorted(set(planner_only))[:12],
        "reranker_misrank_examples": misrank[:12],
    }


def _load_fam_map(paths: List[Path]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in paths:
        for row in read_jsonl(p):
            fam = (row.get("metadata") or {}).get("pattern_family")
            if row.get("theorem_name") and fam:
                out[row["theorem_name"]] = fam
    return out


def render(catalog, coverage, attribution) -> str:
    L: List[str] = ["# Mini-ELF v3 planner — coverage audit (V4 Part 1)\n"]
    L.append(
        "Generated by `scripts/audit_planner_coverage.py`. Establishes the "
        "*frontier* of the symbolic planner (`src/mini_elf_lean/proof_planner.py`) "
        "so the v4 planner-blind corpus targets shapes it genuinely cannot "
        "construct. Theorem-level only; never reads `state_after`.\n")

    L.append("\n## 1. Proof-shape catalog (planner candidates emitted)\n")
    L.append("| proof shape | supported | planner candidates | sample |\n| --- | --- | --- | --- |")
    for c in catalog:
        mark = "✅" if c["planner_candidates"] else "❌ **blind**"
        samp = f"`{c['sample']}` ({c['sample_source']})" if c["sample"] else "—"
        L.append(f"| {c['shape']} | {mark} | {c['planner_candidates']} | {samp} |")
    blind = [c["shape"] for c in catalog if c["planner_candidates"] == 0]
    L.append(f"\n**Planner-blind shapes** ({len(blind)}): " + "; ".join(blind) + ".")
    L.append(
        "\nNote: `∃`-witness shows 0 planner candidates **by design** — it is "
        "delegated to the symbolic witness-copy, a separate source. The remaining "
        "blind shapes have *no* source in the v3 system that constructs them, "
        "which is exactly what the v4 corpus probes.\n")

    L.append("\n## 2. Empirical family coverage (basic + hard seeds)\n")
    L.append("Fraction of each family's theorems for which the planner emits ≥1 candidate.\n")
    L.append("| pattern family | planner-covered / total |\n| --- | --- |")
    for fam, v in coverage.items():
        L.append(f"| {fam} | {v['covered']}/{v['total']} |")

    L.append("\n## 3. v3 source attribution (who solved what)\n")
    for title, attr in attribution:
        L.append(f"\n### {title}")
        L.append(f"- theorems solved **only** by the symbolic planner (flow did not verify): "
                 f"**{attr['n_planner_only_theorems']}** "
                 f"{attr['planner_only_examples'][:8]}")
        fs = attr["verified_by_source_by_family"]
        if fs:
            L.append("- verified-by-source per family (top-5):")
            for fam, srcs in fs.items():
                pretty = ", ".join(f"{k}={v}" for k, v in sorted(srcs.items()))
                L.append(f"  - `{fam}`: {pretty}")
        if attr["reranker_misrank_examples"]:
            L.append("- **reranker would mis-rank these Lean-verified planner candidates** "
                     "(score < 0.5, only ranked by the tier-policy bypass):")
            for m in attr["reranker_misrank_examples"][:6]:
                L.append(f"  - `{m['theorem']}` [{m['family']}] `{m['tactic']}` "
                         f"reranker={m['reranker_score']}")
    L.append(
        "\n## Takeaway\n\nThe planner covers a **closed catalog** of proof shapes "
        "(projection, chains, case splits, iff/eq composition, ∃-witness via "
        "witness-copy). It is *blind* to negation/contradiction, contrapositive "
        "`¬`-goals, ∃-elimination, ∀-instantiation, and rewrite/substitution — and "
        "no other v3 source constructs these either. The v4 planner-blind corpus "
        "(`scripts/generate_planner_blind_corpus.py`) is built from exactly these "
        "shapes; see `docs/V4_PLANNER_BLIND_REPORT.md`.\n")
    return "\n".join(L)


def _parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--seeds", type=Path, nargs="+",
                   default=[ROOT / "data/seeds/basic_lean_seeds.jsonl",
                            ROOT / "data/seeds/hard_lean_seeds.jsonl"])
    p.add_argument("--out", type=Path, default=ROOT / "docs/V4_PLANNER_COVERAGE_AUDIT.md")
    p.add_argument("--json-out", type=Path, default=ROOT / "data/baselines/v4_planner_coverage_audit.json")
    return p


def main(argv=None) -> int:
    args = _parse().parse_args(argv)
    catalog = _shape_catalog()
    coverage = _family_coverage([p for p in args.seeds if p.exists()])
    thm2fam = _load_fam_map([p for p in args.seeds if p.exists()])
    attribution = []
    for title, d in V3_SPLITS:
        pred = ROOT / "data/baselines" / d / "predictions.jsonl"
        if pred.exists():
            attribution.append((title, _v3_attribution(pred, thm2fam)))
    args.out.write_text(render(catalog, coverage, attribution), encoding="utf-8")
    print(f"wrote {args.out}")
    if args.json_out:
        args.json_out.write_text(json.dumps(
            {"shape_catalog": catalog, "family_coverage": coverage,
             "v3_attribution": {t: a for t, a in attribution}},
            indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json_out}")
    blind = [c["shape"] for c in catalog if c["planner_candidates"] == 0]
    print(f"planner-blind shapes ({len(blind)}): {blind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
