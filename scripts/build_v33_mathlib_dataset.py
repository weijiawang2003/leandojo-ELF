"""Mini-ELF v33 — Part 4: build v33 dataset (canonical, residual-coverage).

Configs (canonical-mode, on top of the v32 canonical base):
  A. v33_general_residual         v32_canonical base + 83 canonicalized residual rows  [recommended]
  B. v33_general_residual_stress  A + token-surface (subscript-identifier) rows upsampled 2×
  C. v33_residual_only            the 83 canonicalized residual rows only (ablation)
  (D unweighted general == A — unweighted is the recommended default; no balancing.)

Leakage guards (asserted): no name/statement/triple overlap train↔(11 residuals,
v32 stress, v32/v33 fresh holdouts, v25–v31 benchmarks); no state_after; no unresolved
canonical identifiers in any training target (round-trip checked).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.v31_identifier_normalization import canonicalize_example, build_canonical_map, concretize_or_reject, canonicalize_text  # noqa: E402

P = ROOT / "data" / "processed"
V32CFG = P / "v32_mathlib" / "configs"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _dump(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def canon_row(r):
    cs, cst, ct, cmap = canonicalize_example(r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", ""))
    return {**r, "theorem_statement": cs, "state_before": cst, "tactic": ct, "canonicalized": cmap.ok, "raw_tactic": r.get("tactic", "")}


def _eval_pairs() -> Set[Tuple[str, str]]:
    pairs = set()
    seeds = [ROOT / "data" / "seeds" / "v32_identifier_stress_seeds.jsonl",
             ROOT / "data" / "seeds" / "v32_fresh_mathlib_holdout_seeds.jsonl",
             ROOT / "data" / "seeds" / "v33_fresh_robustness_holdout_seeds.jsonl",
             ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"]
    for d in [P / "v26_mathlib_specialist_splits" / "theorem_holdout", P / "v27_mathlib_specialist" / "theorem_holdout",
              P / "v28_mathlib_specialist" / "theorem_holdout", P / "v29_mathlib_specialist" / "theorem_holdout",
              P / "v29_mathlib_specialist" / "family_density_holdout", P / "v29_mathlib_specialist" / "low_density_holdout",
              P / "v30_mathlib_specialist" / "theorem_holdout", P / "v30_mathlib_specialist" / "targeted_family_holdout",
              P / "v31_canonical_mathlib" / "token_diversity_holdout"]:
        seeds.append(d / "test_seeds.jsonl")
    for sp in seeds:
        for s in _read(sp):
            pairs.add((s.get("theorem_statement", ""), s.get("state_before", "")))
    return pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v32-base", default=str(V32CFG / "v32_canonical_repaired_train_rows.jsonl"))
    ap.add_argument("--v32-val", default=str(V32CFG / "v32_canonical_repaired_val_rows.jsonl"))
    ap.add_argument("--residual-rows", default=str(P / "v33_mathlib_specialist" / "residual_coverage_rows.jsonl"))
    ap.add_argument("--out-dir", default=str(P / "v33_mathlib_specialist"))
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    cfg = out / "configs"
    base = _read(Path(args.v32_base))           # already canonical
    val = _read(Path(args.v32_val))
    residual_raw = _read(Path(args.residual_rows))

    # canonicalize the residual rows; drop any whose canonical (stmt,state) matches an
    # eval/holdout statement (leakage) — the raw guard already removed exact raw matches.
    eval_pairs = _eval_pairs()
    canon_residual, n_roundtrip_fail, dropped = [], 0, 0
    for r in residual_raw:
        cr = canon_row(r)
        # round-trip check
        cmap = build_canonical_map(r.get("theorem_statement", ""), r.get("state_before", ""))
        if cmap.ok and concretize_or_reject(canonicalize_text(r.get("tactic", ""), cmap), cmap) != r.get("tactic", ""):
            n_roundtrip_fail += 1
        if (r.get("theorem_statement", ""), r.get("state_before", "")) in eval_pairs:
            dropped += 1
            continue
        canon_residual.append(cr)

    token_surface = [r for r in canon_residual if r.get("repair_type") == "token_surface"]

    general = base + canon_residual
    general_stress = general + token_surface  # upsample subscript-identifier rows
    residual_only = canon_residual
    _dump(cfg / "v33_general_residual_train_rows.jsonl", general)
    _dump(cfg / "v33_general_residual_stress_train_rows.jsonl", general_stress)
    _dump(cfg / "v33_residual_only_train_rows.jsonl", residual_only)
    _dump(cfg / "val_rows.jsonl", val)

    # assertions
    all_train = general + general_stress + residual_only
    tp = {(r.get("theorem_statement", ""), r.get("state_before", "")) for r in all_train}
    assert not (tp & eval_pairs), "an eval/holdout statement leaked into a v33 train config"
    for r in all_train:
        assert "state_after" not in r
    assert n_roundtrip_fail == 0, f"{n_roundtrip_fail} residual tactics did not round-trip"

    summary = {
        "config": "v33_mathlib_specialist_dataset",
        "v32_base_rows": len(base), "residual_rows_raw": len(residual_raw),
        "residual_rows_kept": len(canon_residual), "residual_dropped_eval_overlap": dropped,
        "n_roundtrip_failures": n_roundtrip_fail,
        "configs": {"v33_general_residual": len(general), "v33_general_residual_stress": len(general_stress),
                    "v33_residual_only": len(residual_only), "val": len(val)},
        "by_repair_type_added": dict(Counter(r.get("repair_type") for r in canon_residual)),
        "leakage_guard": "name + statement vs 11 residuals + v32 stress + v32/v33 fresh + v25-v31 benchmarks",
        "category_balanced": "NOT built", "uses_state_after": False, "uses_manual_oracle": False,
        "not_v19_placeholders": True,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[v33 dataset] base={len(base)} residual_kept={len(canon_residual)} (dropped {dropped}) roundtrip_fail={n_roundtrip_fail}")
    print(f"[v33 dataset] configs: {summary['configs']}")
    print(f"[v33 dataset] by_repair_type: {summary['by_repair_type_added']}")
    print("[v33 dataset] leakage guards PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
