"""V5 Part 6/8 — summarize the proposer-configuration metrics into
`docs/V5_RESULTS_SUMMARY.md` (and stdout). Reads the generated metrics.json
files only — no metric is invented here.

Usage: python scripts/summarize_v5.py [--output docs/V5_RESULTS_SUMMARY.md]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "baselines"

# (label, baseline-dir) on the within-family SPLIT test set (32 theorems).
SPLIT_CONFIGS: List[Tuple[str, str]] = [
    ("v3 (unchanged)", "planner_blind_split_v3_test"),
    ("v4 templates (both, labelled)", "planner_blind_split_v4templates_test"),
    ("retrieval (alone)", "planner_blind_retrieval_proposer_test"),
    ("retrieval-verbatim (no adapt)", "planner_blind_retrieval_verbatim_test"),
    ("v3 ⊕ retrieval", "planner_blind_v5_retrieval_fusion_test"),
    ("v3 + v4-tmpl ⊕ retrieval", "planner_blind_v5_retrieval_fusion_v4templates_test"),
    ("LLM (alone)", "planner_blind_v5_llm_test"),
]

# All-test (61-theorem) v4 numbers, kept as the separate off-library headline.
ALLTEST_CONFIGS: List[Tuple[str, str]] = [
    ("v3 unchanged [all-test, n=61]", "planner_blind_v3_test"),
    ("v3 + v4 both [all-test, n=61]", "planner_blind_v4_template_both_test"),
]

FOCUS = ("forall_inst", "rewrite_succ")
FAMILY_ORDER = (
    "neg_exfalso", "neg_contrapositive", "neg_imp_exfalso", "neg_double_intro",
    "neg_or_cases", "exists_elim_prop", "exists_elim_conj", "exists_reconstruct",
    "forall_inst", "rewrite_succ",
)


def _load(suffix: str) -> Optional[Dict[str, Any]]:
    p = BASE / suffix / "metrics.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _g(m: Dict[str, Any], k: str) -> Optional[float]:
    pk = m.get("lean_verification", {}).get("pass_at_k", {}).get(k)
    return pk.get("rate") if pk else None


def _fam5(m: Dict[str, Any], fam: str) -> Optional[float]:
    e = (m.get("per_family_pass_at_k") or {}).get(fam)
    return e["pass_at_k"]["5"]["rate"] if e else None


def _v5(m: Dict[str, Any], key: str) -> Any:
    return (m.get("mini_elf_v5") or {}).get(key)


def _novel(m: Dict[str, Any]) -> Any:
    v = _v5(m, "novel_verified")
    if v is not None:
        return v
    return (m.get("elf_v1_generation") or {}).get("novel_candidates_verified")


def _invalid1(m: Dict[str, Any]) -> Optional[float]:
    v = _v5(m, "invalid_rate_top1")
    if v is not None:
        return v
    return (m.get("elf_v1_generation") or {}).get("invalid_rate_top1")


def _fmt(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.3f}"


def _table(configs: List[Tuple[str, str]]) -> List[str]:
    rows = ["| config | n | pass@1 | pass@3 | pass@5 | forall_inst@5 | rewrite_succ@5 | invalid@1 | novel_verified | rows_only_proposer |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for label, suffix in configs:
        m = _load(suffix)
        if m is None:
            rows.append(f"| {label} | — | _(not run)_ | | | | | | | |")
            continue
        n = m.get("n_theorems", "—")
        rop = _v5(m, "rows_solved_only_by_proposer")
        rows.append(
            f"| {label} | {n} | {_fmt(_g(m,'1'))} | {_fmt(_g(m,'3'))} | {_fmt(_g(m,'5'))} "
            f"| {_fmt(_fam5(m,'forall_inst'))} | {_fmt(_fam5(m,'rewrite_succ'))} "
            f"| {_fmt(_invalid1(m))} | {_novel(m) if _novel(m) is not None else '—'} "
            f"| {rop if rop is not None else '—'} |"
        )
    return rows


def _family_table(configs: List[Tuple[str, str]]) -> List[str]:
    loaded = [(label, _load(suffix)) for label, suffix in configs]
    loaded = [(l, m) for l, m in loaded if m is not None]
    header = "| family | " + " | ".join(l for l, _ in loaded) + " |"
    sep = "| --- | " + " | ".join("---" for _ in loaded) + " |"
    rows = [header, sep]
    for fam in FAMILY_ORDER:
        cells = [_fmt(_fam5(m, fam)) for _, m in loaded]
        tag = " **(target)**" if fam in FOCUS else ""
        rows.append(f"| {fam}{tag} | " + " | ".join(cells) + " |")
    return rows


def build_doc() -> str:
    out: List[str] = []
    out.append("# Mini-ELF v5 — results summary\n")
    out.append(
        "> **Scope.** Theorem-level lean-cli verification only "
        "(`state_after_is_real=false`); these are prototypes of the *generation "
        "loop*, not full ELF over proof states. The v5 split test set is **32 "
        "theorems** (the `family_interpolation` within-family split, so each "
        "family has held-out test theorems **and** same-family train donors, with "
        "no theorem in both). It is therefore **not** the same set as the v4 "
        "all-test 61-theorem corpus — the all-test v4 numbers are kept separately "
        "below as the off-library headline. n is small ⇒ directional, not "
        "statistically definitive. Manual-oracle candidates are **never** counted "
        "as a model result.\n"
    )
    out.append("## 1. Primary question: the template-less targets\n")
    ret = _load("planner_blind_retrieval_proposer_test")
    if ret is not None:
        out.append(
            f"On the split test set, the **retrieval** proposer takes the two "
            f"families no v4 template ever recovered to "
            f"`forall_inst` pass@5 = **{_fmt(_fam5(ret,'forall_inst'))}** "
            f"(via numeric-literal adaptation; `verified_by_adaptation = "
            f"{_v5(ret,'verified_by_adaptation')}`) and "
            f"`rewrite_succ` pass@5 = **{_fmt(_fam5(ret,'rewrite_succ'))}** "
            f"(verbatim reuse) — with **no hand-written template**. This is the v5 "
            f"result: a data-driven proposer escapes the per-shape whack-a-mole on "
            f"the targets.\n"
        )
    out.append("## 2. Configuration comparison (split test, n=32)\n")
    out.extend(_table(SPLIT_CONFIGS))
    out.append("")
    out.append("## 3. Per-family pass@5 (split test)\n")
    out.extend(_family_table(SPLIT_CONFIGS))
    out.append("")
    out.append("## 4. Off-library headline (v4 all-test, n=61) — unchanged, for context\n")
    out.extend(_table(ALLTEST_CONFIGS))
    out.append("")
    out.append(
        "## 5. Honest reading\n\n"
        "- **Retrieval is example reuse + light adaptation, not reasoning.** It "
        "works on the targets only because the corpus uses consistent hypothesis "
        "names within a family (verbatim transfer) and because the ∀-witness is a "
        "literal copyable from the goal (numeric adaptation). Given same-family "
        "donors, it generalizes *within* a family; it does not compose new proof "
        "shapes.\n"
        "- **Char-n-gram similarity confuses the negation siblings.** `neg_exfalso` "
        "stays at pass@5 0.00 for retrieval: its nearest neighbours by char-trigram "
        "cosine are *other* negation families (`neg_double_intro`, `neg_or_cases`), "
        "whose tactics do not transfer, so the correct same-family donor "
        "(`exact absurd hp hnp`, which is in train) is ranked out of the top-5. "
        "This is the v1 sibling-confusion problem resurfacing at the retrieval "
        "layer — reported, not hidden.\n"
        "- **Adaptation matters:** compare `retrieval` vs `retrieval-verbatim` — "
        "numeric substitution is what lifts `forall_inst` off 0.00.\n"
        "- **v4 templates remain separate from v3 and v5.** The `v4_templates` and "
        "`v3 + v4-tmpl ⊕ retrieval` rows are explicitly labelled ablations, never "
        "folded into the v3 planner.\n"
        "- **LLM pilot:** see `docs/V5_LLM_PILOT_*.md` — gated on an API key.\n"
    )
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=ROOT / "docs" / "V5_RESULTS_SUMMARY.md")
    args = ap.parse_args(argv)
    doc = build_doc()
    args.output.write_text(doc, encoding="utf-8")
    print(doc)
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
