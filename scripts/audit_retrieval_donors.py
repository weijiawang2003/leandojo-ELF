"""V7 Part 1 — donor-availability audit of the planner-blind retrieval split.

v6 reached pass@5 1.00 on the planner-blind `family_interpolation` split, but that
split keeps **same-family donors in train** (a held-out sibling's verified tactic
is one numeric/identifier edit away). This script makes the donor structure
explicit: for every test row it records whether a same-family / same-operation
donor exists in train, whether the proof *schema* is represented in train, whether
a numeric adaptation is required, and whether the v6 retriever's candidates verify
at rank 1/5 — both normally and when **same-family donors are forbidden at
retrieval time** (a clean preview of the family-holdout regime on the rich split).

Verification is real lean-cli (cache-backed; keyed by `(theorem_name, tactic)` so
prior runs are reused). The donor-condition computation itself
(:func:`compute_donor_conditions`) is pure / lean-free and unit-tested.

Outputs:
  * data/baselines/v7_donor_audit/donor_audit.json   (machine-readable)
  * docs/V7_DONOR_AVAILABILITY_AUDIT.md               (the report)

No `state_after`; no new templates; example reuse, not reasoning.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baseline_eval import VerificationCache, _verify_tactic, make_lean_cli_verifier  # noqa: E402
from mini_elf_lean.baselines import Example, load_dataset, oracle_verified_lookup  # noqa: E402
from mini_elf_lean.io_utils import read_jsonl  # noqa: E402
from mini_elf_lean.retrieval_abstraction import operation_signature  # noqa: E402
from mini_elf_lean.retrieval_features import OP_UNKNOWN, extract_features  # noqa: E402
from mini_elf_lean.retrieval_proposer import StructureAwareRetrievalProposer, load_v6_weights  # noqa: E402

import re
_NUM_RE = re.compile(r"(?<![\w.])\d+(?!\w)")


# ---------------- pure donor-condition analysis (no Lean) ----------------


def family_map_from_seeds(seeds_path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in read_jsonl(seeds_path):
        m = row.get("metadata") or {}
        if row.get("theorem_name") and m.get("pattern_family"):
            out[row["theorem_name"]] = m["pattern_family"]
    return out


def operation_map(rows: Sequence[Example]) -> Dict[str, str]:
    """theorem_name -> guessed required_operation (from its first row)."""
    out: Dict[str, str] = {}
    for r in rows:
        if r.theorem_name not in out:
            out[r.theorem_name] = extract_features(r.theorem_statement, r.state_before).required_operation
    return out


@dataclass
class TrainFacts:
    families: frozenset
    operations: frozenset
    schema_keys: frozenset           # operation-signature keys present in train
    tactics: frozenset               # literal train tactic strings


def train_facts(train: Sequence[Example], thm2fam: Dict[str, str], thm2op: Dict[str, str]) -> TrainFacts:
    fams = {thm2fam.get(e.theorem_name) for e in train} - {None}
    ops = {thm2op.get(e.theorem_name) for e in train} - {None, OP_UNKNOWN}
    keys = {operation_signature(e.tactic, e.state_before).key() for e in train}
    tacs = {e.tactic for e in train}
    return TrainFacts(frozenset(fams), frozenset(ops), frozenset(keys), frozenset(tacs))


def compute_donor_conditions(
    train: Sequence[Example],
    test: Sequence[Example],
    thm2fam: Dict[str, str],
    thm2op: Dict[str, str],
    oracle: Dict[Tuple[str, str], frozenset],
) -> List[Dict[str, Any]]:
    """Per test row: corpus donor-availability conditions (lean-free)."""
    tf = train_facts(train, thm2fam, thm2op)
    out: List[Dict[str, Any]] = []
    for e in test:
        fam = thm2fam.get(e.theorem_name)
        op = thm2op.get(e.theorem_name)
        verified = oracle.get((e.theorem_name, e.state_before), frozenset())
        verified_schemas = {operation_signature(vt, e.state_before).key() for vt in verified}
        # proof schema represented in train?
        schema_in_train = bool(verified_schemas & tf.schema_keys)
        # numeric adaptation needed: a correct proof carries a literal, that exact
        # tactic is absent from train, yet its schema IS in train (so only the
        # literal differs -> adaptation rather than verbatim reuse).
        adapt_needed = False
        for vt in verified:
            if _NUM_RE.search(vt) and vt not in tf.tactics:
                if operation_signature(vt, e.state_before).key() in tf.schema_keys:
                    adapt_needed = True
                    break
        out.append({
            "theorem_name": e.theorem_name,
            "family": fam,
            "operation": op,
            "goal_literals": list(extract_features(e.theorem_statement, e.state_before).goal_literals),
            "same_family_donor_in_train": (fam in tf.families) if fam else False,
            "same_operation_donor_in_train": (op in tf.operations) if (op and op != OP_UNKNOWN) else False,
            "schema_in_train": schema_in_train,
            "numeric_adaptation_needed": adapt_needed,
            "n_known_verified": len(verified),
        })
    return out


# ---------------- lean-backed verification of proposer candidates ----------------


def _verify_topk(proposer, e: Example, k: int, cache, verifier) -> Dict[str, Any]:
    cands = proposer.propose(e.theorem_statement, e.state_before,
                             theorem_name=e.theorem_name, max_candidates=k)
    results: List[Tuple[Any, bool]] = []
    for c in cands[:k]:
        res = _verify_tactic(theorem_name=e.theorem_name, theorem_statement=e.theorem_statement,
                             tactic=c.tactic, verifier=verifier, cache=cache)
        results.append((c, bool(res.get("success"))))
    top = cands[0] if cands else None
    first_ok = next((c for c, ok in results if ok), None)
    return {
        "top_donor_theorem": (top.metadata.get("neighbor_theorem") if top else None),
        "top_donor_family": (top.metadata.get("donor_family") if top else None),
        "top_donor_operation": (top.metadata.get("donor_operation") if top else None),
        "rank1_tactic": (top.tactic if top else None),
        "rank1_source": (top.source if top else None),
        "verified@1": (results[0][1] if results else False),
        "verified@5": any(ok for _c, ok in results),
        "verified_tactic": (first_ok.tactic if first_ok else None),
        "verified_donor_family": (first_ok.metadata.get("donor_family") if first_ok else None),
        "verified_adapted": (bool(first_ok.metadata.get("adapted")) if first_ok else False),
        "n_candidates": len(cands),
    }


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _agg_by(rows: List[Dict[str, Any]], keyfn, passkey: str) -> Dict[str, Any]:
    by: Dict[str, Dict[str, int]] = defaultdict(lambda: {"n": 0, "p1": 0, "p5": 0})
    for r in rows:
        kb = keyfn(r)
        by[kb]["n"] += 1
        by[kb]["p1"] += int(r[passkey]["verified@1"])
        by[kb]["p5"] += int(r[passkey]["verified@5"])
    return {k: {"n": v["n"], "pass@1": _rate(v["p1"], v["n"]), "pass@5": _rate(v["p5"], v["n"])}
            for k, v in sorted(by.items(), key=lambda kv: str(kv[0]))}


def build_audit(dataset: Path, seeds: Path, weights_path: Path, output_dir: Path,
                k: int = 5, verify: bool = True) -> Dict[str, Any]:
    rows = load_dataset(dataset)
    train = [e for e in rows if e.split == "train"]
    test = [e for e in rows if e.split == "test"]
    thm2fam = family_map_from_seeds(seeds)
    thm2op = operation_map(rows)
    oracle = oracle_verified_lookup(rows)

    conditions = compute_donor_conditions(train, test, thm2fam, thm2op, oracle)
    cond_by_thm = {c["theorem_name"]: c for c in conditions}

    weights = load_v6_weights(weights_path)
    v6 = StructureAwareRetrievalProposer(weights=weights, family_map=thm2fam).fit(train)
    xfam = StructureAwareRetrievalProposer(weights=weights, family_map=thm2fam,
                                           forbid_same_family=True).fit(train)

    cache = None
    verifier = None
    if verify:
        output_dir.mkdir(parents=True, exist_ok=True)
        cache = VerificationCache.load(output_dir / "verification_cache.json", enabled=True)
        verifier = make_lean_cli_verifier(timeout=60.0)

    per_row: List[Dict[str, Any]] = []
    for e in test:
        rec = dict(cond_by_thm[e.theorem_name])
        rec["state_before"] = e.state_before
        if verify:
            rec["v6"] = _verify_topk(v6, e, k, cache, verifier)
            rec["cross_family_only"] = _verify_topk(xfam, e, k, cache, verifier)
            rec["v6"]["top_donor_same_family"] = (rec["v6"]["top_donor_family"] == rec["family"])
        per_row.append(rec)
    if verify and cache is not None:
        cache.save()

    n = len(per_row)
    summary: Dict[str, Any] = {
        "split": "family_interpolation (current planner-blind)",
        "n_test_rows": n,
        "n_test_theorems": len({r["theorem_name"] for r in per_row}),
        "same_family_donor_available": sum(r["same_family_donor_in_train"] for r in per_row),
        "same_operation_donor_available": sum(r["same_operation_donor_in_train"] for r in per_row),
        "schema_in_train": sum(r["schema_in_train"] for r in per_row),
        "numeric_adaptation_needed": sum(r["numeric_adaptation_needed"] for r in per_row),
    }
    if verify:
        summary["v6"] = {
            "pass@1": _rate(sum(r["v6"]["verified@1"] for r in per_row), n),
            "pass@5": _rate(sum(r["v6"]["verified@5"] for r in per_row), n),
            "donor_family_match_rate": _rate(sum(r["v6"]["top_donor_same_family"] for r in per_row), n),
        }
        summary["cross_family_only"] = {
            "pass@1": _rate(sum(r["cross_family_only"]["verified@1"] for r in per_row), n),
            "pass@5": _rate(sum(r["cross_family_only"]["verified@5"] for r in per_row), n),
            "cross_family_verified_rows": sum(r["cross_family_only"]["verified@5"] for r in per_row),
        }
        summary["pass_at_k_by_family_v6"] = _agg_by(per_row, lambda r: r["family"], "v6")
        summary["pass_at_k_by_family_cross_family_only"] = _agg_by(per_row, lambda r: r["family"], "cross_family_only")
        summary["pass_at_k_by_operation_v6"] = _agg_by(per_row, lambda r: r["operation"], "v6")
        summary["pass_at_k_by_operation_cross_family_only"] = _agg_by(per_row, lambda r: r["operation"], "cross_family_only")
        summary["pass_at_k_by_same_family_available_v6"] = _agg_by(
            per_row, lambda r: "available" if r["same_family_donor_in_train"] else "absent", "v6")
    return {"summary": summary, "rows": per_row}


# ---------------- report rendering ----------------


def render_markdown(audit: Dict[str, Any]) -> str:
    s = audit["summary"]
    rows = audit["rows"]
    L: List[str] = []
    L.append("# Mini-ELF v7 — donor-availability audit (planner-blind, current split)\n")
    L.append("> **Scope.** Documents the donor structure behind v6's pass@5 1.00. The current "
             "split is `family_interpolation`: every test family also has members in train, so "
             "the retriever can reuse a *same-family* donor (one numeric/identifier edit from the "
             "answer). This audit measures how much of v6's success rides on that, by also "
             "verifying candidates when **same-family donors are forbidden at retrieval time** "
             "(`forbid_same_family`) — a preview of the Part-3 family-holdout regime on the rich "
             "split. Real lean-cli verification; no `state_after`; no new templates; example "
             "reuse, not reasoning.\n")
    L.append("## 1. Corpus donor conditions\n")
    L.append(f"- test rows: **{s['n_test_rows']}** ({s['n_test_theorems']} theorems)")
    L.append(f"- rows with a **same-family** donor in train: **{s['same_family_donor_available']}/{s['n_test_rows']}**")
    L.append(f"- rows with a **same-operation** donor in train: **{s['same_operation_donor_available']}/{s['n_test_rows']}**")
    L.append(f"- rows whose **proof schema** is present in train: **{s['schema_in_train']}/{s['n_test_rows']}**")
    L.append(f"- rows that **require numeric adaptation** (literal absent from a same-schema train donor): **{s['numeric_adaptation_needed']}/{s['n_test_rows']}**\n")
    if "v6" in s:
        L.append("## 2. Verified pass@k — full retriever vs cross-family-only\n")
        L.append("| condition | pass@1 | pass@5 |")
        L.append("| --- | --- | --- |")
        L.append(f"| v6 (same-family donors allowed) | {s['v6']['pass@1']:.3f} | {s['v6']['pass@5']:.3f} |")
        L.append(f"| v6 — same-family donors **forbidden** | {s['cross_family_only']['pass@1']:.3f} | {s['cross_family_only']['pass@5']:.3f} |")
        L.append("")
        L.append(f"- v6 rank-0 donor is **same-family** in **{s['v6']['donor_family_match_rate']:.3f}** of test rows "
                 "(retrieval prefers the same-family donor when it exists).")
        L.append(f"- with same-family donors forbidden, **{s['cross_family_only']['cross_family_verified_rows']}/{s['n_test_rows']}** "
                 "rows still find a verifying candidate from a *cross-family* donor.\n")
        L.append("## 3. pass@k by family (v6 vs cross-family-only)\n")
        L.append("| family | n | v6 @1 | v6 @5 | xfam @1 | xfam @5 |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        fv = s["pass_at_k_by_family_v6"]
        fx = s["pass_at_k_by_family_cross_family_only"]
        for fam in sorted(fv):
            a, b = fv[fam], fx.get(fam, {"pass@1": 0, "pass@5": 0})
            L.append(f"| {fam} | {a['n']} | {a['pass@1']:.3f} | {a['pass@5']:.3f} | {b['pass@1']:.3f} | {b['pass@5']:.3f} |")
        L.append("")
        L.append("## 4. pass@k by required operation (v6 vs cross-family-only)\n")
        L.append("| operation | n | v6 @1 | v6 @5 | xfam @1 | xfam @5 |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        ov = s["pass_at_k_by_operation_v6"]
        ox = s["pass_at_k_by_operation_cross_family_only"]
        for op in sorted(ov):
            a, b = ov[op], ox.get(op, {"pass@1": 0, "pass@5": 0})
            L.append(f"| {op} | {a['n']} | {a['pass@1']:.3f} | {a['pass@5']:.3f} | {b['pass@1']:.3f} | {b['pass@5']:.3f} |")
        L.append("")
    L.append("## 5. Per-theorem donor table\n")
    L.append("| theorem | family | operation | same-fam | same-op | schema∈train | adapt? | v6@5 | xfam@5 | v6 top-donor (fam) |")
    L.append("| --- | --- | --- | :--: | :--: | :--: | :--: | :--: | :--: | --- |")
    for r in sorted(rows, key=lambda x: (x["family"] or "", x["theorem_name"])):
        v6 = r.get("v6", {})
        xf = r.get("cross_family_only", {})
        def tick(b):
            return "✓" if b else "·"
        td = v6.get("top_donor_theorem") or "—"
        tdf = v6.get("top_donor_family") or "?"
        L.append(f"| {r['theorem_name']} | {r['family']} | {r['operation']} | "
                 f"{tick(r['same_family_donor_in_train'])} | {tick(r['same_operation_donor_in_train'])} | "
                 f"{tick(r['schema_in_train'])} | {tick(r['numeric_adaptation_needed'])} | "
                 f"{tick(v6.get('verified@5'))} | {tick(xf.get('verified@5'))} | {td} ({tdf}) |")
    L.append("")
    L.append("## 6. Reading\n")
    L.append("- The current split is **interpolation**: a same-family donor is available for "
             "essentially every test row, and v6 reuses it.")
    L.append("- Forbidding same-family donors is a retrieval-time preview of family holdout; the "
             "gap between the two rows in §2 is the share of v6's success attributable to "
             "same-family interpolation rather than transferable proof structure.")
    L.append("- This audit motivates Part 2/3: genuinely hold the family (and the whole "
             "operation) out of **train** and re-measure. Retrieval is ranking + reuse, never "
             "reasoning; no `state_after`; no new templates.")
    return "\n".join(L) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dataset", type=Path,
                   default=ROOT / "data/processed/planner_blind_split_lean_cli/next_tactic.jsonl")
    p.add_argument("--seeds", type=Path, default=ROOT / "data/seeds/planner_blind_seeds.jsonl")
    p.add_argument("--weights", type=Path, default=ROOT / "data/configs/v6_retrieval.json")
    p.add_argument("--output-dir", type=Path, default=ROOT / "data/baselines/v7_donor_audit")
    p.add_argument("--doc", type=Path, default=ROOT / "docs/V7_DONOR_AVAILABILITY_AUDIT.md")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--no-verify", dest="verify", action="store_false")
    p.set_defaults(verify=True)
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    os.environ.setdefault(
        "MINI_ELF_LEAN_COMMAND",
        os.path.expanduser("~/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"))
    audit = build_audit(args.dataset, args.seeds, args.weights, args.output_dir,
                        k=args.top_k, verify=args.verify)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "donor_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    args.doc.write_text(render_markdown(audit), encoding="utf-8")
    s = audit["summary"]
    print(json.dumps(s, indent=2, sort_keys=True))
    print(f"\nwrote {args.output_dir/'donor_audit.json'} and {args.doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
