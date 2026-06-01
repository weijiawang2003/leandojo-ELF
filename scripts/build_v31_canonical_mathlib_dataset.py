"""Mini-ELF v31 — Part 3: canonical dataset construction.

Canonicalizes the v30 training base (statement / state / tactic) with the v31
identifier normalizer so a model can be trained identifier-invariant. Builds four
configs and a token-diversity holdout (the 13 v30 residuals) for the eval.

Configs (configs/):
  A. canonical_general          every v30-base row canonicalized (c0,c1,… binders)
  B. raw_canonical_mixture      raw rows + canonical rows (union, dedup)
  C. raw_plus_canonical_aug     raw rows + ONLY the canonical rows that differ from raw
  D. (pattern-rerank baseline)  no new training — the v30 model + Approach-C reranker

Honesty / leakage:
  * RAW guard (standard): no held-out (statement, state, tactic) triple or (statement,
    state) pair in any RAW training row — inherited from the v30 base, which already
    excludes every v25–v30 held-out test statement.
  * Canonicalization **deliberately collapses identifier variants**, so a held-out
    identifier-variant (e.g. `…(w)(hw)…`) maps to a canonical shape the model trained on
    via a *different* raw theorem (`…(x)(h)…`). This is the generalization under test,
    NOT memorization of the held-out theorem: the held-out theorem's RAW statement is
    never in raw training, and the eval verifies the real (un-canonicalized) theorem
    with Lean — the canonical model must concretize correctly to pass.
  * No `state_after`; no unresolved canonical identifiers in any training target
    (asserted — every canonical tactic round-trips).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.v31_identifier_normalization import (  # noqa: E402
    build_canonical_map, canonicalize_text, concretize_or_reject,
)

P = ROOT / "data" / "processed"
V30CFG = P / "v30_mathlib_specialist" / "configs"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _dump(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def canonicalize_row(r: Dict[str, Any]) -> Dict[str, Any]:
    """Return a canonicalized copy of a training row. If the statement has no binders
    (cmap not ok) the row is returned unchanged (trains as raw)."""
    stmt, state, tac = r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")
    cmap = build_canonical_map(stmt, state)
    if not cmap.ok:
        return {**r, "canonicalized": False}
    cstmt = canonicalize_text(stmt, cmap)
    cstate = canonicalize_text(state, cmap)
    ctac = canonicalize_text(tac, cmap)
    return {**r, "theorem_statement": cstmt, "state_before": cstate, "tactic": ctac,
            "canonicalized": True, "raw_tactic": tac}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-train", default=str(V30CFG / "v30_general_targeted_train_rows.jsonl"))
    ap.add_argument("--base-val", default=str(V30CFG / "val_rows.jsonl"))
    ap.add_argument("--out-dir", default=str(P / "v31_canonical_mathlib"))
    ap.add_argument("--residual-report", default=str(ROOT / "data" / "baselines" / "v30_remaining_failures" / "report.json"))
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    cfg = out / "configs"
    raw_train = _read(Path(args.base_train))
    raw_val = _read(Path(args.base_val))

    canon_train = [canonicalize_row(r) for r in raw_train]
    canon_val = [canonicalize_row(r) for r in raw_val]
    n_canon = sum(1 for r in canon_train if r.get("canonicalized"))

    # round-trip check: re-derive the map from each ORIGINAL row, canonicalize its
    # tactic, and confirm concretize_or_reject recovers the raw tactic (no unresolved
    # canonical target can reach training).
    n_roundtrip_fail = 0
    for r in raw_train:
        cmap = build_canonical_map(r.get("theorem_statement", ""), r.get("state_before", ""))
        if not cmap.ok:
            continue
        ctac = canonicalize_text(r.get("tactic", ""), cmap)
        back = concretize_or_reject(ctac, cmap)
        if back != r.get("tactic", ""):
            n_roundtrip_fail += 1

    def key(r):
        return (r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", ""))

    # A. canonical_general
    _dump(cfg / "canonical_general_train_rows.jsonl", canon_train)
    _dump(cfg / "canonical_general_val_rows.jsonl", canon_val)
    # B. raw + canonical mixture (dedup)
    seen, mixture = set(), []
    for r in raw_train + canon_train:
        k = key(r)
        if k in seen:
            continue
        seen.add(k); mixture.append(r)
    _dump(cfg / "raw_canonical_mixture_train_rows.jsonl", mixture)
    _dump(cfg / "raw_canonical_mixture_val_rows.jsonl", raw_val + canon_val)
    # C. raw + ONLY canonical rows that differ from their raw (augmentation)
    raw_keys = {key(r) for r in raw_train}
    aug = list(raw_train) + [r for r in canon_train if key(r) not in raw_keys]
    _dump(cfg / "raw_plus_canonical_aug_train_rows.jsonl", aug)
    _dump(cfg / "raw_plus_canonical_aug_val_rows.jsonl", raw_val)
    # D pattern-rerank baseline uses the v30 model — no train file.

    # token-diversity holdout = the 13 v30 residual theorems' seeds (gather from existing)
    resid = json.loads(Path(args.residual_report).read_text()) if Path(args.residual_report).exists() else {"residuals": []}
    resid_names = {r["theorem"] for r in resid.get("residuals", [])}
    seed_files = [
        P / "v29_mathlib_specialist" / "family_density_holdout" / "test_seeds.jsonl",
        P / "v29_mathlib_specialist" / "low_density_holdout" / "test_seeds.jsonl",
        P / "v30_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
        P / "v30_mathlib_specialist" / "targeted_family_holdout" / "test_seeds.jsonl",
        P / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
    ]
    td_seeds, td_seen = [], set()
    for sp in seed_files:
        for s in _read(sp):
            if s["theorem_name"] in resid_names and s["theorem_name"] not in td_seen:
                td_seeds.append(s); td_seen.add(s["theorem_name"])
    _dump(out / "token_diversity_holdout" / "test_seeds.jsonl", td_seeds)

    # assertions
    assert n_roundtrip_fail == 0, f"{n_roundtrip_fail} canonical tactics did not round-trip"
    for r in (canon_train + mixture + aug):
        assert "state_after" not in r

    summary = {
        "config": "v31_canonical_mathlib_dataset",
        "base_train_rows": len(raw_train), "base_val_rows": len(raw_val),
        "n_canonicalized_rows": n_canon, "n_roundtrip_failures": n_roundtrip_fail,
        "configs": {"canonical_general": len(canon_train),
                    "raw_canonical_mixture": len(mixture),
                    "raw_plus_canonical_aug": len(aug),
                    "pattern_rerank_baseline": "v30_general_targeted (no new training)"},
        "token_diversity_holdout": {"n_theorems": len(td_seeds),
                                    "theorems": [s["theorem_name"] for s in td_seeds]},
        "leakage_guard": "RAW base already excludes all v25-v30 held-out statements; "
                         "canonicalization collapses identifier variants by design "
                         "(generalization under test, not memorization).",
        "uses_state_after": False, "uses_manual_oracle": False,
        "not_v19_placeholders": True,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[v31 canonical] base={len(raw_train)} canonicalized={n_canon} roundtrip_fail={n_roundtrip_fail}")
    print(f"[v31 canonical] configs: {summary['configs']}")
    print(f"[v31 canonical] token_diversity_holdout: {len(td_seeds)} theorems")
    print("[v31 canonical] assertions PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
