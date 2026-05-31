"""Mini-ELF v8 helper — back-fill verifier ``error`` text into
``predictions.jsonl`` rows that pre-date the
``evaluate_mini_elf_v8.py`` schema fix.

Reads ``data/lean_cache/<cache>.json`` (the shared lean-cli verification
cache) and walks ``data/baselines/v8_eval/**/predictions.jsonl``; for each
row that has ``candidates`` but no ``verifications`` (or whose
``verifications`` only has ``success`` flags), looks up the cache by
``sha256(theorem_name||tactic)`` and writes the enriched row back.

Idempotent — running twice is a no-op.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]


def _cache_key(thm: str, tactic: str) -> str:
    """Matches ``mini_elf_lean.baseline_eval._cache_key`` exactly: sha256 of
    the concatenation of theorem_name + tactic, with no separator."""
    h = hashlib.sha256()
    h.update(thm.encode("utf-8"))
    h.update(tactic.encode("utf-8"))
    return h.hexdigest()


def enrich(cache_path: Path, eval_root: Path) -> Dict[str, int]:
    if not cache_path.exists():
        return {"cache_missing": 1}
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    n_files = 0
    n_rows_changed = 0
    n_errors_added = 0
    for preds in eval_root.rglob("predictions.jsonl"):
        rows = []
        with preds.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                rows.append(json.loads(s))
        if not rows:
            continue
        changed = False
        for r in rows:
            cands = r.get("candidates") or []
            verifs = r.get("verifications") or []
            new_verifs = list(verifs)
            while len(new_verifs) < len(cands):
                new_verifs.append({})
            row_changed = False
            for j, tac in enumerate(cands):
                v = new_verifs[j] if j < len(new_verifs) else {}
                if v.get("error") not in (None, ""):
                    continue  # already enriched
                hit = cache.get(_cache_key(r["theorem_name"], tac))
                if hit is not None:
                    new_verifs[j] = {
                        "success": bool(hit.get("success")),
                        "error": hit.get("error"),
                    }
                    n_errors_added += 1
                    row_changed = True
            if row_changed:
                r["verifications"] = new_verifs
                changed = True
                n_rows_changed += 1
        if changed:
            with preds.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n_files += 1
    return {"files_updated": n_files,
            "rows_updated": n_rows_changed,
            "errors_added": n_errors_added}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache" / "v8_fusion_cache.json"))
    ap.add_argument("--eval-root", default=str(ROOT / "data" / "baselines" / "v8_eval"))
    args = ap.parse_args()

    # The v8 fusion + seq2seq caches both store the same key shape; try both.
    eval_root = Path(args.eval_root)
    total = {"files_updated": 0, "rows_updated": 0, "errors_added": 0}
    for c in [args.cache,
              str(ROOT / "data" / "lean_cache" / "v8_seq2seq_cache.json"),
              str(ROOT / "data" / "lean_cache" / "v7_eval_cache.json"),
              str(ROOT / "data" / "lean_cache" / "v6_retrieval_cache.json")]:
        cp = Path(c)
        if not cp.exists():
            continue
        out = enrich(cp, eval_root)
        for k in total:
            total[k] += out.get(k, 0)
        print(f"{c} -> {out}")
    print(f"TOTAL {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
