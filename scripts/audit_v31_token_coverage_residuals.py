"""Mini-ELF v31 — Part 1: token-coverage residual audit.

For each v30 remaining failure, decide whether the miss is a **surface-token coverage**
problem (the proof *shape* exists in training, only the identifiers differ) or a genuine
vocabulary / API / missing-shape gap. This is what tells Part 2/4 whether identifier
normalization (or verified rename augmentation) can plausibly fix it. NO Lean run.

For each residual it records: family, expected proof, model top-10, error class, the
local identifiers + projection tokens the expected proof uses, and — the key signal —
whether a training row of the **same family** carries the **same identifier-free
pattern** (i.e., the shape is present under a different identifier surface).

Classification:
  identifier_surface_OOD | projection_token_OOD | lemma_namespace_OOD | api_arity |
  true_missing_shape
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_v29_family_density import family_of  # noqa: E402

V30_RESID = ROOT / "data" / "baselines" / "v30_remaining_failures" / "report.json"
V30_TRAIN = ROOT / "data" / "processed" / "v30_mathlib_specialist" / "configs" / "v30_general_targeted_train_rows.jsonl"
TRACES = ROOT / "data" / "traces"
VERIFIED = ["v25_mathlib_tierc_verified.jsonl", "v26_mathlib_specialist_verified.jsonl",
            "v27_mathlib_expanded_verified.jsonl", "v28_mathlib_expanded_verified.jsonl",
            "v29_mathlib_density_verified.jsonl", "v30_targeted_density_verified.jsonl"]

# Lean keywords / tactic words to keep when pattern-normalising
_KEEP = {"exact", "intro", "rintro", "simp", "rfl", "omega", "ring", "tauto", "aesop",
         "funext", "ext", "cases", "left", "right", "constructor", "exacts", "by",
         "Or", "And", "Iff", "Set", "Finset", "List", "Nat", "Function", "True", "False",
         "id", "min", "max", "inl", "inr", "mp", "mpr", "symm", "elim", "le_rfl",
         "le_refl", "le_antisymm", "le_trans", "le_of_eq", "empty_subset", "union_subset",
         "subset_inter", "mem_inter", "mem_union", "mem_inter_iff", "inter_subset_left",
         "inter_subset_right", "subset_union_left", "subset_union_right", "add_assoc",
         "mem_of_mem_inter_left", "mem_of_mem_inter_right", "mem_union_left",
         "mem_union_right", "subset_refl", "Subset", "refl", "univ", "trans"}
_IDENT = re.compile(r"[A-Za-z_α-ωΑ-Ω][A-Za-z0-9_'α-ωΑ-Ω]*")
_PROJ = re.compile(r"\.(1|2|left|right)\b|mem_inter_iff\.mp|mem_inter\.mp|Or\.in[lr]")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def tactic_pattern(tactic: str) -> str:
    """Identifier-free pattern: replace local identifiers (lowercase / h-prefixed,
    not Lean/Mathlib keywords or dotted/uppercase names) with `ID`. Keeps lemma names,
    operators, and projection tokens so two proofs that differ only by identifier
    naming collapse to the same pattern."""
    def repl(m):
        tok = m.group(0)
        if tok in _KEEP or tok[0].isupper():
            return tok
        return "ID"
    return _IDENT.sub(repl, tactic)


def local_identifiers(tactic: str) -> List[str]:
    out = []
    for m in _IDENT.finditer(tactic):
        tok = m.group(0)
        if tok not in _KEEP and not tok[0].isupper():
            out.append(tok)
    return sorted(set(out))


def classify(expected: List[str], errs: List[str], pattern_in_train: bool,
             beam: List[str]) -> str:
    cnt = Counter(errs)
    has_proj = any(_PROJ.search(e) for e in expected)
    if pattern_in_train:
        # the shape IS in train under a different identifier surface
        return "projection_token_OOD" if has_proj else "identifier_surface_OOD"
    if cnt.get("unknown_identifier", 0) >= 1 and any("." in c for c in beam):
        return "lemma_namespace_OOD"
    if cnt.get("type_mismatch", 0) >= 1:
        return "api_arity"
    return "true_missing_shape"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v31_token_coverage" / "report.json"))
    args = ap.parse_args(argv)

    # expected proofs from verified corpora
    proofs: Dict[str, List[str]] = defaultdict(list)
    for fn in VERIFIED:
        for r in _read(TRACES / fn):
            t = (r.get("tactic") or "").strip()
            if t and t not in proofs[r.get("theorem_name", "")]:
                proofs[r.get("theorem_name", "")].append(t)

    # train patterns per family
    fam_patterns: Dict[str, set] = defaultdict(set)
    fam_identifiers: Dict[str, set] = defaultdict(set)
    for r in _read(V30_TRAIN):
        fam = family_of(r)
        t = (r.get("tactic") or "").strip()
        fam_patterns[fam].add(tactic_pattern(t))
        for ident in local_identifiers(t):
            fam_identifiers[fam].add(ident)

    resid = json.loads(V30_RESID.read_text()) if V30_RESID.exists() else {"residuals": []}
    audits = []
    from evaluate_v25_tierc import v25_taxonomy
    for r in resid.get("residuals", []):
        nm = r["theorem"]
        fam = r.get("family", "?")
        expected = proofs.get(nm, []) or r.get("expected_proofs", [])
        errs = [k for k, _v in r.get("error_counts", {}).items()] or []
        beam = r.get("top10", [])
        # does the expected proof's pattern exist in train for this family?
        exp_patterns = {tactic_pattern(e) for e in expected}
        pattern_in_train = bool(exp_patterns & fam_patterns.get(fam, set()))
        exp_idents = sorted({i for e in expected for i in local_identifiers(e)})
        train_idents = sorted(fam_identifiers.get(fam, set()))
        missing_idents = [i for i in exp_idents if i not in train_idents]
        rec = {
            "theorem": nm, "family": fam, "category": r.get("category"),
            "expected_proofs": expected[:3], "top10": beam[:6],
            "error_classes": errs,
            "expected_identifiers": exp_idents,
            "train_identifiers_in_family": train_idents,
            "identifiers_missing_from_train": missing_idents,
            "uses_projection_tokens": any(_PROJ.search(e) for e in expected),
            "expected_patterns": sorted(exp_patterns),
            "pattern_present_in_train": pattern_in_train,
            "classification": classify(expected, errs, pattern_in_train, beam),
        }
        audits.append(rec)

    cls = Counter(a["classification"] for a in audits)
    report = {
        "config": "v31_token_coverage_audit",
        "source": "v30 remaining failures + v30 train patterns + verified corpora (no Lean run)",
        "n_residuals": len(audits),
        "classification_counts": dict(cls),
        "n_surface_token_fixable": sum(1 for a in audits
                                       if a["classification"] in ("identifier_surface_OOD", "projection_token_OOD")),
        "audits": audits,
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[token-coverage] residuals={len(audits)} classes={dict(cls)}")
    print(f"[token-coverage] surface-token-fixable: {report['n_surface_token_fixable']}/{len(audits)}")
    for a in audits:
        print(f"   {a['family']:26s} {a['classification']:22s} miss_idents={a['identifiers_missing_from_train']} {a['theorem']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
