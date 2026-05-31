"""Mini-ELF v8 Part 7 — failure-mode analysis on the v8 eval outputs.

Walks every ``<out-root>/<regime>/<config>/predictions.jsonl`` and assigns
each candidate a taxonomy label by inspecting (a) the candidate string and
(b) the verifier's error text. Counts are then aggregated per regime / config
/ failure class.

Taxonomy (mutually exclusive, first match wins):

  * ``verified``                     — Lean accepted the tactic.
  * ``malformed``                    — empty / whitespace / unparseable tokens.
  * ``wrong_theorem_family``         — tactic uses identifiers from a different family
                                       (e.g. uses ``hnp`` when target has no negation hyp).
  * ``missing_intro``                — implication goal, but the tactic doesn't `intro`.
  * ``wrong_binder``                 — `intro` / `rcases` binds wrong arity.
  * ``wrong_rewrite_dir``            — `rw [h]` / `rw [← h]` direction mismatch.
  * ``wrong_exists_destruct``        — `obtain ⟨_, _⟩` against an ∃ that's not a pair.
  * ``stale_donor``                  — verbatim donor tactic with an out-of-scope identifier.
  * ``lean_syntax_error``            — Lean parser rejected the surface syntax.
  * ``type_mismatch``                — Lean reported type/term mismatch.
  * ``no_candidate``                 — generator emitted nothing for this row.
  * ``other``                        — anything left.

Outputs::

    <out-root>/v8_failure_taxonomy.json   (rolled-up counts)
    <out-root>/v8_failure_examples.jsonl  (5–10 worked examples per class)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Taxonomy classifier
# --------------------------------------------------------------------------- #

_RX_INTRO_MISSING = re.compile(r"(?i)expected.+goal of the form|implication.*intro")
_RX_TYPE_MISMATCH = re.compile(r"(?i)type mismatch|expected type|application type mismatch")
_RX_UNKNOWN_ID = re.compile(r"(?i)unknown identifier")
_RX_SYNTAX = re.compile(r"(?i)unexpected token|syntax error|expected term")
_RX_RW_DIR = re.compile(r"(?i)did not change|motive is not type correct|rewrite|step failed")
_RX_RCASES_BINDER = re.compile(r"(?i)anonymous constructor|expected.+⟨|destructuring")
_RX_HAS_INTRO_TOKEN = re.compile(r"\bintro\w*\b")
_RX_HAS_RW_BACK = re.compile(r"\brw\s*\[\s*←")


def _classify_one(tactic: Optional[str], error: Optional[str], *,
                  goal_text: Optional[str] = None) -> str:
    if tactic is None:
        return "no_candidate"
    t = tactic.strip()
    if not t:
        return "malformed"
    if error is None or error == "":
        return "verified"
    e = error
    if _RX_UNKNOWN_ID.search(e):
        # Distinguish stale-donor (verbatim donor uses an out-of-scope name)
        # from wrong_theorem_family (uses an unrelated identifier).
        return "stale_donor" if _looks_verbatim_donor(t) else "wrong_theorem_family"
    if _RX_INTRO_MISSING.search(e) and not _RX_HAS_INTRO_TOKEN.search(t):
        return "missing_intro"
    if _RX_RCASES_BINDER.search(e):
        return "wrong_binder"
    if _RX_RW_DIR.search(e):
        return "wrong_rewrite_dir"
    if _RX_SYNTAX.search(e):
        return "lean_syntax_error"
    if _RX_TYPE_MISMATCH.search(e):
        return "type_mismatch"
    if "obtain" in t and ("anonymous constructor" in e.lower() or "destructuring" in e.lower()):
        return "wrong_exists_destruct"
    return "other"


def _looks_verbatim_donor(tac: str) -> bool:
    """Heuristic: a verbatim donor uses lower-case identifiers that look like
    the basic-corpus hypothesis naming (``hp``, ``hpq``, ``hq``, ``hr``)."""
    return bool(re.search(r"\b(hp|hq|hr|hnp|hnq|hpq|hpr|hqr)\b", tac))


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def _iter_jsonl(p: Path) -> Iterable[Dict[str, Any]]:
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            yield json.loads(s)


# --------------------------------------------------------------------------- #
# Walk
# --------------------------------------------------------------------------- #

def walk_eval_root(out_root: Path) -> Dict[str, Any]:
    """For each ``<regime>/<config>/predictions.jsonl``, classify each
    candidate. Returns rolled-up counts and a small set of example rows per
    class."""
    counts: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    examples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    EXAMPLES_PER_CLASS = 10

    if not out_root.exists():
        return {"counts": {}, "examples": {}}

    for regime_dir in sorted(out_root.iterdir()):
        if not regime_dir.is_dir():
            continue
        for config_dir in sorted(regime_dir.iterdir()):
            preds = config_dir / "predictions.jsonl"
            if not preds.exists():
                continue
            for row in _iter_jsonl(preds):
                cands = row.get("candidates") or []
                verifs = row.get("verifications") or [None] * len(cands)
                if not cands:
                    counts[regime_dir.name][config_dir.name]["no_candidate"] += 1
                    continue
                for j, (tac, v) in enumerate(zip(cands, verifs)):
                    if v is None:
                        cls = "other"
                    else:
                        cls = _classify_one(tac, v.get("error"))
                    counts[regime_dir.name][config_dir.name][cls] += 1
                    if len(examples[cls]) < EXAMPLES_PER_CLASS:
                        examples[cls].append({
                            "regime": regime_dir.name,
                            "config": config_dir.name,
                            "theorem_name": row.get("theorem_name"),
                            "family": row.get("family"),
                            "required_operation": row.get("required_operation"),
                            "rank": j,
                            "tactic": tac,
                            "error": (v or {}).get("error"),
                            "class": cls,
                        })
    return {
        "counts": {r: {c: dict(cls) for c, cls in m.items()}
                   for r, m in counts.items()},
        "examples": {cls: rows for cls, rows in examples.items()},
    }


def walk_seq2seq_dirs() -> Dict[str, Any]:
    """Also scan the flat ``data/baselines/v8_seq2seq_*`` outputs from
    :mod:`scripts.evaluate_proof_block_seq2seq`, whose predictions.jsonl
    already carries the verifier ``error`` text."""
    counts: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    examples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    EXAMPLES_PER_CLASS = 10
    base = ROOT / "data" / "baselines"
    if not base.exists():
        return {"counts": {}, "examples": {}}
    for sub in sorted(base.iterdir()):
        if not sub.is_dir() or not sub.name.startswith("v8_seq2seq_"):
            continue
        preds = sub / "predictions.jsonl"
        if not preds.exists():
            continue
        regime = sub.name.replace("v8_seq2seq_", "")
        for row in _iter_jsonl(preds):
            cands = row.get("candidates") or []
            verifs = row.get("verifications") or [None] * len(cands)
            for j, (tac, v) in enumerate(zip(cands, verifs)):
                cls = _classify_one(tac, (v or {}).get("error"))
                counts[regime]["seq2seq_only"][cls] += 1
                if len(examples[cls]) < EXAMPLES_PER_CLASS:
                    examples[cls].append({
                        "regime": regime,
                        "config": "seq2seq_only",
                        "theorem_name": row.get("theorem_name"),
                        "family": row.get("family"),
                        "required_operation": row.get("required_operation"),
                        "rank": j,
                        "tactic": tac,
                        "error": (v or {}).get("error"),
                        "class": cls,
                    })
    return {"counts": {r: {c: dict(cls) for c, cls in m.items()}
                       for r, m in counts.items()},
            "examples": {cls: rows for cls, rows in examples.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v8_eval"))
    args = ap.parse_args()
    out_root = Path(args.out_root)

    res = walk_eval_root(out_root)
    seq = walk_seq2seq_dirs()
    # Merge counts
    for regime, m in seq["counts"].items():
        for cfg, cls in m.items():
            tgt = res["counts"].setdefault(regime, {})
            existing = tgt.setdefault(cfg, {})
            for k, n in cls.items():
                existing[k] = existing.get(k, 0) + n
    # Merge examples (cap at 10 per class total)
    for cls, rows in seq["examples"].items():
        existing = res["examples"].setdefault(cls, [])
        for r in rows:
            if len(existing) >= 10:
                break
            existing.append(r)
    (out_root / "v8_failure_taxonomy.json").write_text(
        json.dumps(res["counts"], indent=2, ensure_ascii=False), encoding="utf-8")
    with (out_root / "v8_failure_examples.jsonl").open("w", encoding="utf-8") as f:
        for cls, rows in res["examples"].items():
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # Summary
    total = Counter()
    for r, m in res["counts"].items():
        for c, cls in m.items():
            for k, n in cls.items():
                total[k] += n
    print("v8 failure taxonomy (across all regime×config):")
    for k, n in total.most_common():
        print(f"  {k:<25} {n}")
    print(f"-> {out_root}/v8_failure_taxonomy.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
