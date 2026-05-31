"""Mini-ELF v14 — char-vs-token comparison report.

Aggregates four configurations on the same v11 family-LOFO test rows:

  1. v13 char-level + literal_adapt + rerank, **warm-verified**
     (the fair char baseline per the v14 brief).
  2. v14 token-level **raw beam**.
  3. v14 token-level + literal_adapt + rerank.
  4. (Optional) Ensemble: dedup(char raw beam ∪ token raw beam),
     re-verify, then literal_adapt + rerank.

For each (family, config) we report pass@1/5/10, malformed/fused
rates, schema rates, error taxonomy, and the
``forall_inst_var_m_pass@5`` indicator. No v12/v13 files are
overwritten — comparison results go to
``data/baselines/v14_token_seq2seq/comparison.json`` and
``docs/V14_CHAR_VS_TOKEN_REPORT.md``.

The ensemble step requires re-verifying any candidate that isn't in
either source's cache, so it shares the v14 cache for speed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)
from mini_elf_lean.literal_aware_decode import (  # noqa: E402
    SOURCE_SEQ2SEQ, compose_candidates,
)
from mini_elf_lean.proof_block_reranker import rerank  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("compare_v13_v14")


# ---------------- IO ----------------


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _pass_at(verifs: Sequence[Dict[str, Any]], k: int) -> bool:
    for v in verifs[:k]:
        if v.get("success"):
            return True
    return False


# ---------------- v13 warm metrics ----------------


def load_v13_warm(v13_root: Path) -> Dict[str, Dict[str, float]]:
    """Read the v13 warm-rerun corrected metrics. Returns
    ``{fam: {pass@k: value}}`` for the ``literal_adapt_rerank`` config."""
    p = v13_root / "metrics_rerun.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, float]] = {}
    for fam, cfgs in data.items():
        cfg = cfgs.get("literal_adapt_rerank") or {}
        out[fam] = {
            "pass@1": cfg.get("pass@1_warm_rerun"),
            "pass@5": cfg.get("pass@5_warm_rerun"),
            "pass@10": cfg.get("pass@10_warm_rerun"),
            "n": cfg.get("n"),
            "source": "v13_char_literal_adapt_rerank_warm",
        }
    return out


# ---------------- v14 raw/literal-rerank metrics ----------------


def load_v14(v14_root: Path, families: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for fam in families:
        per_cfg: Dict[str, Any] = {}
        for cfg in ("raw", "literal_adapt_rerank"):
            mp = v14_root / fam / cfg / "metrics.json"
            if mp.exists():
                per_cfg[cfg] = json.loads(mp.read_text(encoding="utf-8"))
        out[fam] = per_cfg
    return out


# ---------------- ensemble ----------------


def _load_v12_raw_predictions(v12_root: Path, fam: str) -> Dict[str, List[str]]:
    """theorem_name -> char-level v11 raw beam (the v12 ``raw`` config
    is exactly the v11 candidates, untouched)."""
    p = v12_root / fam / "raw" / "predictions.jsonl"
    by_name: Dict[str, List[str]] = {}
    for r in _read_jsonl(p):
        by_name[r["theorem_name"]] = list(r.get("candidates", []))
    return by_name


def _load_v14_raw_predictions(v14_root: Path, fam: str) -> Dict[str, List[str]]:
    p = v14_root / fam / "raw" / "predictions.jsonl"
    by_name: Dict[str, List[str]] = {}
    for r in _read_jsonl(p):
        by_name[r["theorem_name"]] = list(r.get("candidates", []))
    return by_name


def _load_test_index(fold_root: Path, fam: str) -> Dict[str, Dict[str, Any]]:
    rows = _read_jsonl(fold_root / fam / "test.jsonl")
    by_name: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        nm = r.get("theorem_name")
        if nm and nm not in by_name:
            by_name[nm] = r
    return by_name


def evaluate_ensemble(
    *, fam: str, v12_root: Path, v14_root: Path, fold_root: Path,
    cache: VerificationCache, verifier, k_max: int,
) -> Dict[str, Any]:
    """Dedup char raw beam ∪ token raw beam, then literal_adapt +
    rerank, then re-verify."""
    char_pred = _load_v12_raw_predictions(v12_root, fam)
    tok_pred = _load_v14_raw_predictions(v14_root, fam)
    tests = _load_test_index(fold_root, fam)

    pass_k = {1: 0, 5: 0, 10: 0}
    per_row: List[Dict[str, Any]] = []
    n = 0
    for nm, tr in tests.items():
        char_cands = list(char_pred.get(nm, []))
        tok_cands = list(tok_pred.get(nm, []))
        # Dedup preserving precedence: char first (the calibrated baseline),
        # then token; otherwise the token model could displace verified
        # char candidates from the top-k.
        seen, merged = set(), []
        for c in char_cands + tok_cands:
            cs = c.strip()
            if cs in seen:
                continue
            seen.add(cs); merged.append(c)
        # literal_adapt + rerank
        composed = compose_candidates(
            merged, state_before=tr.get("state_before", ""),
            theorem_statement=tr.get("theorem_statement", ""),
        )
        items = [(t, s) for (t, s, _) in composed]
        items = [(c.tactic, c.source) for c in rerank(
            items, state_before=tr.get("state_before", ""),
            required_operation=tr.get("required_operation"),
        )]
        items = items[: k_max]

        verifs: List[Dict[str, Any]] = []
        for t, _src in items:
            hit = cache.get(nm, t)
            if hit is not None:
                res = hit
            else:
                res = verifier(nm, tr.get("theorem_statement", ""), t)
                cache.put(nm, t, res)
            verifs.append({"success": bool(res.get("success")),
                           "error": res.get("error")})
        p1, p5, p10 = (_pass_at(verifs, k) for k in (1, 5, 10))
        pass_k[1] += int(p1); pass_k[5] += int(p5); pass_k[10] += int(p10)
        per_row.append({
            "theorem_name": nm,
            "merged_candidates": [t for t, _ in items],
            "sources": [s for _, s in items],
            "verifications": verifs,
            "pass@1": p1, "pass@5": p5, "pass@10": p10,
        })
        n += 1
    return {
        "fam": fam,
        "n_test_theorems": n,
        "pass@1": pass_k[1] / n if n else 0.0,
        "pass@5": pass_k[5] / n if n else 0.0,
        "pass@10": pass_k[10] / n if n else 0.0,
        "per_row": per_row,
    }


# ---------------- main ----------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v12-root",
                    default=str(ROOT / "data" / "baselines" / "v12_eval"))
    ap.add_argument("--v13-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v13_timeout_rerun"))
    ap.add_argument("--v14-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_token_seq2seq"))
    ap.add_argument("--fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--out",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_token_seq2seq" / "comparison.json"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ", "neg_exfalso",
                             "exists_reconstruct", "neg_imp_exfalso"])
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache"
                                / "v14_token_cache.json"))
    ap.add_argument("--ensemble", action="store_true",
                    help="Also compute the (char ∪ token) ensemble — requires "
                         "re-verifying any new merged candidates.")
    ap.add_argument("--verifier-timeout", type=float, default=120.0)
    args = ap.parse_args(argv)

    v13 = load_v13_warm(Path(args.v13_root))
    v14 = load_v14(Path(args.v14_root), args.families)

    # v14 warm-rerun corrections (parallel to v13's metrics_rerun.json).
    v14_warm_p = (ROOT / "data" / "baselines" / "v14_timeout_rerun"
                  / "metrics_rerun.json")
    v14_warm = (json.loads(v14_warm_p.read_text(encoding="utf-8"))
                if v14_warm_p.exists() else {})

    rows: Dict[str, Any] = {}
    for fam in args.families:
        warm = v14_warm.get(fam, {}).get("literal_adapt_rerank", {})
        warm_raw = v14_warm.get(fam, {}).get("raw", {})
        rows[fam] = {
            "v13_char_warm": v13.get(fam, {}),
            "v14_raw_lower_bound": v14.get(fam, {}).get("raw", {}),
            "v14_literal_adapt_rerank_lower_bound":
                v14.get(fam, {}).get("literal_adapt_rerank", {}),
            "v14_raw_warm_corrected": {
                "pass@1": warm_raw.get("pass@1_warm_rerun"),
                "pass@5": warm_raw.get("pass@5_warm_rerun"),
                "pass@10": warm_raw.get("pass@10_warm_rerun"),
                "n": warm_raw.get("n"),
                "row_flips": warm_raw.get("row_flips"),
            },
            "v14_literal_adapt_rerank_warm_corrected": {
                "pass@1": warm.get("pass@1_warm_rerun"),
                "pass@5": warm.get("pass@5_warm_rerun"),
                "pass@10": warm.get("pass@10_warm_rerun"),
                "n": warm.get("n"),
                "row_flips": warm.get("row_flips"),
            },
        }

    if args.ensemble:
        cache = VerificationCache.load(Path(args.cache), enabled=True)
        verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)
        for fam in args.families:
            logger.info("ensemble: %s", fam)
            ens = evaluate_ensemble(
                fam=fam, v12_root=Path(args.v12_root),
                v14_root=Path(args.v14_root), fold_root=Path(args.fold_root),
                cache=cache, verifier=verifier, k_max=10,
            )
            rows[fam]["ensemble_char_union_token"] = {
                k: v for k, v in ens.items() if k != "per_row"}
            # also persist per-row ensemble predictions for the report
            ens_out = (Path(args.v14_root) / fam / "ensemble"
                       / "predictions.jsonl")
            ens_out.parent.mkdir(parents=True, exist_ok=True)
            with ens_out.open("w", encoding="utf-8") as f:
                for r in ens["per_row"]:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            cache.save()

    out = {
        "families": list(args.families),
        "rows": rows,
        "v13_corrected_metrics_path": args.v13_root,
        "v14_metrics_path": args.v14_root,
        "v14_warm_corrections_path": str(v14_warm_p),
        "v12_metrics_path_referenced_but_not_modified": args.v12_root,
        "uses_state_after": False,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    logger.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
