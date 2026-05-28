"""Per-theorem / per-tactic / per-error audit for a verified+failed trace pair.

``evaluate_traces`` summarizes a whole bag of records. This module slices that
bag along the axes a corpus reviewer actually wants when iterating on a manual
candidate file:

  - per-theorem success rate  -> which theorems are saturated vs starved
  - per-tactic success rate   -> which tactic heads consistently work / fail
  - zero-success theorems     -> theorems where every candidate was rejected
  - duplicate tactics         -> same (theorem_name, state_before, tactic)
                                 attempted more than once
  - top normalized Lean errors -> grouped after stripping the volatile temp
                                 file paths Lean prints (otherwise every
                                 message is "unique")

The module also accepts records pre-loaded as dicts so tests can feed synthetic
fixtures without round-tripping through JSONL.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .io_utils import read_jsonl
from .tactic_sanitizer import tactic_head

logger = logging.getLogger(__name__)


# Lean's whole-file CLI prefixes each error with the temp-file path it wrote,
# which makes raw error strings effectively unique per run. We strip:
#   /tmp/mini_elf_lean_abc123.lean:R:C:
#   C:\Users\...\mini_elf_lean_xyz.lean:R:C:
# and keep the rest (severity + kind + message) for grouping.
_PATH_PREFIX_RE = re.compile(
    r"^.*?mini_elf_lean[^:]+\.lean:\d+:\d+:\s*", re.MULTILINE
)


def normalize_error(err: Optional[str]) -> str:
    """Strip volatile path/line info from a Lean error message so equivalent
    errors group together. Returns the empty string when ``err`` is falsy."""
    if not err:
        return ""
    stripped = _PATH_PREFIX_RE.sub("", err).strip()
    # Take just the first line; subsequent lines are usually the "expected vs
    # got" detail, which is high-cardinality and hides the pattern.
    return stripped.splitlines()[0] if stripped else ""


@dataclass
class CorpusAudit:
    """Auditor output. Counts are over the full record stream (success + failed
    combined). Ratios are 0..1, never None — empty buckets are 0.0."""

    records_total: int = 0
    records_success: int = 0
    records_failed: int = 0
    by_theorem: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    by_tactic_head: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    zero_success_theorems: List[str] = field(default_factory=list)
    duplicate_tactic_attempts: List[Dict[str, Any]] = field(default_factory=list)
    top_errors: List[Dict[str, Any]] = field(default_factory=list)
    # Populated only when a theorem -> pattern_family map is supplied.
    by_pattern_family: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Populated only when both family + split maps are supplied.
    pattern_coverage_warnings: List[str] = field(default_factory=list)

    @property
    def overall_success_rate(self) -> float:
        return self.records_success / self.records_total if self.records_total else 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "records_total": self.records_total,
            "records_success": self.records_success,
            "records_failed": self.records_failed,
            "overall_success_rate": self.overall_success_rate,
            "by_theorem": self.by_theorem,
            "by_tactic_head": self.by_tactic_head,
            "zero_success_theorems": self.zero_success_theorems,
            "duplicate_tactic_attempts": self.duplicate_tactic_attempts,
            "top_errors": self.top_errors,
        }
        if self.by_pattern_family:
            d["by_pattern_family"] = self.by_pattern_family
        if self.pattern_coverage_warnings:
            d["pattern_coverage_warnings"] = self.pattern_coverage_warnings
        return d


def load_pattern_families(seeds_path: Path) -> Dict[str, str]:
    """Map ``theorem_name -> pattern_family`` from a seeds JSONL whose rows
    carry ``metadata.pattern_family`` (as written by generate_basic_corpus.py).
    Theorems without the key are simply omitted."""
    from .io_utils import read_jsonl as _read

    out: Dict[str, str] = {}
    for row in _read(seeds_path):
        fam = (row.get("metadata") or {}).get("pattern_family")
        name = row.get("theorem_name")
        if name and fam:
            out[name] = fam
    return out


def load_theorem_splits(splits_path: Path) -> Dict[str, str]:
    """Map ``theorem_name -> split`` from a ``theorem_splits.json`` produced by
    build_dataset.py (keys ``train``/``val``/``test`` -> lists of names)."""
    data = json.loads(Path(splits_path).read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    for split in ("train", "val", "test"):
        for name in data.get(split, []) or []:
            out[name] = split
    return out


def audit(
    records: Iterable[Dict[str, Any]],
    *,
    top_errors: int = 10,
    duplicate_top: int = 20,
    theorem_families: Optional[Dict[str, str]] = None,
    theorem_splits: Optional[Dict[str, str]] = None,
) -> CorpusAudit:
    """Build a ``CorpusAudit`` over an iterable of trace dicts.

    A record is considered a success iff ``record["success"]`` is truthy.
    ``record["theorem_name"]`` and ``record["tactic"]`` are required; missing
    fields are tolerated (treated as empty) so a partly-malformed feed doesn't
    abort the audit.

    When ``theorem_families`` (theorem_name -> pattern_family) is supplied, a
    ``by_pattern_family`` breakdown is added. When ``theorem_splits``
    (theorem_name -> "train"/"val"/"test") is *also* supplied, each family entry
    gains per-split theorem counts and ``pattern_coverage_warnings`` flags
    families that can't possibly transfer (only-in-train, only-in-eval, or an
    eval theorem whose family has no train representative).
    """
    records = list(records)
    result = CorpusAudit(records_total=len(records))

    # ---- per-theorem ----
    thm_succ: Dict[str, int] = defaultdict(int)
    thm_total: Dict[str, int] = defaultdict(int)
    for r in records:
        name = r.get("theorem_name") or "<unknown>"
        thm_total[name] += 1
        if r.get("success"):
            thm_succ[name] += 1
            result.records_success += 1
        else:
            result.records_failed += 1
    for name in sorted(thm_total):
        total = thm_total[name]
        succ = thm_succ.get(name, 0)
        result.by_theorem[name] = {
            "attempts": total,
            "successes": succ,
            "success_rate": succ / total if total else 0.0,
        }
        if succ == 0:
            result.zero_success_theorems.append(name)

    # ---- per-tactic-head ----
    head_total: Dict[str, int] = defaultdict(int)
    head_succ: Dict[str, int] = defaultdict(int)
    for r in records:
        h = tactic_head(r.get("tactic", "")) or "<empty>"
        head_total[h] += 1
        if r.get("success"):
            head_succ[h] += 1
    # Sort by attempts desc, then alphabetically — stable across runs.
    sorted_heads = sorted(head_total.items(), key=lambda kv: (-kv[1], kv[0]))
    for h, total in sorted_heads:
        succ = head_succ.get(h, 0)
        result.by_tactic_head[h] = {
            "attempts": total,
            "successes": succ,
            "success_rate": succ / total if total else 0.0,
        }

    # ---- duplicate tactics: same (theorem_name, state_before, tactic) seen >1 ----
    dup_counter: Counter[Tuple[str, str, str]] = Counter()
    for r in records:
        dup_counter[
            (r.get("theorem_name") or "", r.get("state_before") or "", r.get("tactic") or "")
        ] += 1
    dups: List[Dict[str, Any]] = []
    for (name, state, tac), count in dup_counter.most_common():
        if count <= 1:
            break
        dups.append(
            {
                "theorem_name": name,
                "state_before_preview": (state[:60] + "...") if len(state) > 60 else state,
                "tactic": tac,
                "count": count,
            }
        )
        if len(dups) >= duplicate_top:
            break
    result.duplicate_tactic_attempts = dups

    # ---- top errors (normalized) over failed records ----
    err_counter: Counter[str] = Counter()
    for r in records:
        if r.get("success"):
            continue
        key = normalize_error(r.get("error"))
        if key:
            err_counter[key] += 1
    result.top_errors = [
        {"error": err, "count": n} for err, n in err_counter.most_common(top_errors)
    ]

    # ---- pattern-family breakdown (optional) ----
    if theorem_families:
        _pattern_family_audit(records, result, theorem_families, theorem_splits)

    return result


def _pattern_family_audit(
    records: List[Dict[str, Any]],
    result: CorpusAudit,
    families: Dict[str, str],
    splits: Optional[Dict[str, str]],
) -> None:
    """Fill ``result.by_pattern_family`` (+ coverage warnings) in place.

    Success-rate is over attempt records; theorem counts are over distinct
    theorem names; per-split counts (if ``splits`` given) are theorem counts.
    """
    fam_attempts: Dict[str, int] = defaultdict(int)
    fam_succ: Dict[str, int] = defaultdict(int)
    fam_theorems: Dict[str, set] = defaultdict(set)
    for r in records:
        name = r.get("theorem_name") or ""
        fam = families.get(name)
        if fam is None:
            continue
        fam_attempts[fam] += 1
        fam_theorems[fam].add(name)
        if r.get("success"):
            fam_succ[fam] += 1

    # per-split theorem counts per family (only when splits provided)
    fam_split_thms: Dict[str, Dict[str, set]] = defaultdict(
        lambda: {"train": set(), "val": set(), "test": set()}
    )
    if splits:
        for name, fam in families.items():
            sp = splits.get(name)
            if sp in ("train", "val", "test"):
                fam_split_thms[fam][sp].add(name)

    for fam in sorted(fam_attempts):
        attempts = fam_attempts[fam]
        succ = fam_succ.get(fam, 0)
        entry: Dict[str, Any] = {
            "n_theorems": len(fam_theorems[fam]),
            "attempts": attempts,
            "successes": succ,
            "success_rate": succ / attempts if attempts else 0.0,
        }
        if splits:
            counts = {k: len(v) for k, v in fam_split_thms[fam].items()}
            entry["splits"] = counts
            entry["in_train"] = counts["train"] > 0
            entry["in_eval"] = (counts["val"] + counts["test"]) > 0
        result.by_pattern_family[fam] = entry

    if not splits:
        return

    warnings: List[str] = []
    for fam, entry in result.by_pattern_family.items():
        c = entry["splits"]
        if c["train"] > 0 and (c["val"] + c["test"]) == 0:
            warnings.append(f"family {fam!r} appears only in train ({c['train']} thms) — never evaluated")
        if c["train"] == 0 and (c["val"] + c["test"]) > 0:
            warnings.append(
                f"family {fam!r} appears only in eval (val+test={c['val'] + c['test']} thms, "
                "0 in train) — retrieval/majority cannot transfer to it"
            )
    # eval theorems whose family has no train representative
    train_families = {
        fam for fam, e in result.by_pattern_family.items() if e["splits"]["train"] > 0
    }
    for name, fam in sorted(families.items()):
        sp = splits.get(name)
        if sp in ("val", "test") and fam not in train_families:
            warnings.append(
                f"eval theorem {name!r} (family {fam!r}) has no train theorem of the same family"
            )
    result.pattern_coverage_warnings = warnings


def audit_files(paths: Sequence[Path], **kwargs: Any) -> CorpusAudit:
    """Convenience: load JSONL paths and call :func:`audit`. Missing files
    raise — silent skips would distort success rates."""
    records: List[Dict[str, Any]] = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            raise FileNotFoundError(f"trace file not found: {p}")
        records.extend(read_jsonl(p))
    return audit(records, **kwargs)


# ---------------- CLI ----------------


def _print_human(a: CorpusAudit, top_theorems: int = 10) -> None:
    print("=== Corpus audit ===")
    print(f"records_total          {a.records_total}")
    print(f"records_success        {a.records_success}")
    print(f"records_failed         {a.records_failed}")
    print(f"overall_success_rate   {a.overall_success_rate:.4f}")

    # Per-theorem: lowest success rate first (signals starved theorems).
    items = list(a.by_theorem.items())
    items.sort(key=lambda kv: (kv[1]["success_rate"], -kv[1]["attempts"]))
    print(f"\nBottom {top_theorems} theorems by success rate:")
    for name, stats in items[:top_theorems]:
        print(
            f"  {name:32s} {stats['successes']}/{stats['attempts']}  "
            f"rate={stats['success_rate']:.2f}"
        )

    # Per-tactic-head: most-attempted first.
    print("\nTactic heads (top 15 by attempts):")
    for i, (head, stats) in enumerate(a.by_tactic_head.items()):
        if i >= 15:
            break
        print(
            f"  {head:18s} {stats['successes']}/{stats['attempts']}  "
            f"rate={stats['success_rate']:.2f}"
        )

    if a.zero_success_theorems:
        print(f"\nTheorems with ZERO successes ({len(a.zero_success_theorems)}):")
        for name in a.zero_success_theorems:
            print(f"  - {name}")
    else:
        print("\nZero-success theorems: none.")

    if a.duplicate_tactic_attempts:
        print(f"\nDuplicate (theorem, state_before, tactic) attempts:")
        for d in a.duplicate_tactic_attempts:
            print(f"  {d['theorem_name']:30s} x{d['count']}  TAC {d['tactic']!r}")
    else:
        print("\nDuplicate tactic attempts: none.")

    if a.top_errors:
        print("\nTop normalized Lean errors (failed-out):")
        for e in a.top_errors:
            print(f"  ({e['count']:3d}) {e['error'][:120]}")

    if a.by_pattern_family:
        print("\nBy pattern family (success rate; split theorem counts when available):")
        for fam, e in sorted(a.by_pattern_family.items()):
            sp = e.get("splits")
            sp_str = f"  splits(tr/va/te)={sp['train']}/{sp['val']}/{sp['test']}" if sp else ""
            print(
                f"  {fam:18s} {e['successes']:3d}/{e['attempts']:<3d} "
                f"rate={e['success_rate']:.2f}  thms={e['n_theorems']}{sp_str}"
            )

    if a.pattern_coverage_warnings:
        print("\n!!! Pattern coverage warnings:")
        for w in a.pattern_coverage_warnings:
            print(f"  - {w}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Per-theorem / per-tactic / error audit over verified + failed trace JSONL."
    )
    p.add_argument(
        "--verified", action="append", default=[], type=Path,
        help="Path to verified trace JSONL. Repeatable.",
    )
    p.add_argument(
        "--failed", action="append", default=[], type=Path,
        help="Path to failed trace JSONL. Repeatable.",
    )
    p.add_argument(
        "inputs", nargs="*", type=Path,
        help="Additional trace JSONL paths (success and failure can be mixed; the audit "
             "uses each record's `success` field).",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of a human report.")
    p.add_argument("--top-errors", type=int, default=10)
    p.add_argument("--duplicate-top", type=int, default=20)
    p.add_argument("--top-theorems", type=int, default=10,
                   help="Number of worst-performing theorems to show in human output.")
    p.add_argument("--seeds", type=Path, default=None,
                   help="Seeds JSONL with metadata.pattern_family; enables the by-pattern-family "
                        "breakdown (theorem_name -> pattern_family).")
    p.add_argument("--splits", type=Path, default=None,
                   help="theorem_splits.json from build_dataset.py; enables per-family split "
                        "coverage + transfer warnings (requires --seeds too).")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    paths: List[Path] = list(args.verified) + list(args.failed) + list(args.inputs)
    if not paths:
        print("error: no trace files given (use --verified, --failed, or positional args)",
              file=sys.stderr)
        return 2

    families = load_pattern_families(args.seeds) if args.seeds else None
    splits = load_theorem_splits(args.splits) if args.splits else None
    if splits and not families:
        print("error: --splits requires --seeds (need theorem -> pattern_family too)",
              file=sys.stderr)
        return 2

    try:
        a = audit_files(
            paths, top_errors=args.top_errors, duplicate_top=args.duplicate_top,
            theorem_families=families, theorem_splits=splits,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(a.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_human(a, top_theorems=args.top_theorems)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
