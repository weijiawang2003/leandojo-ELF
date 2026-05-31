"""Mini-ELF v26 — Part 9: optional Set-shape widening pass.

The category analysis found the residual Set failures are `wrong_shape`:
anonymous-constructor reconstruction (`⟨h.2, h.1⟩`) and projecting through
`x ∈ s ∩ t` membership. This adds ~25 *new* Set theorems that drill exactly
those shapes (distinct names, distinct from the v25/v26 held-out benchmarks),
verifies them with the confirmed batched verifier, and writes a widened training
file = theorem_holdout train + verified Set-widen rows.

Bounded: one corpus build + verification; the caller retrains only `base` and
re-evaluates on the SAME held-out benchmarks (which still contain the 4 unseen
Set holdout theorems), so this is a fair generalization test, not leakage.
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

from mini_elf_lean.mathlib_verifier import BatchMathlibVerifier, MATHLIB_IMPORT  # noqa: E402
from generate_v25_mathlib_tierc_corpus import state_before  # noqa: E402

DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"


def plan() -> List[Dict[str, Any]]:
    P = []

    def add(name, stmt, cands, op):
        P.append({"theorem_name": f"v26w_{name}", "theorem_statement": stmt,
                  "candidates": cands, "category": "set", "expected_skill": "set",
                  "required_operation": op, "transfer": "mathlib"})

    # membership projection through ∩ (the .1/.2/.left/.right shape)
    add("mem_inter_right2", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ t",
        ["exact h.2", "exact h.right"], "destruct")
    add("mem_inter_swap", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ t ∩ s",
        ["exact ⟨h.2, h.1⟩", "exact And.symm h", "exact ⟨h.right, h.left⟩"], "destruct")
    add("mem_inter3_left", "(α : Type) (s t u : Set α) (x : α) (h : x ∈ s ∩ t ∩ u) : x ∈ s",
        ["exact h.1.1", "exact h.left.left"], "destruct")
    add("mem_inter_to_union", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ s ∪ t",
        ["exact Or.inl h.1", "exact Or.inl h.left"], "destruct")
    # anonymous-constructor introduction into ∩
    add("mem_self_inter", "(α : Type) (s : Set α) (x : α) (h : x ∈ s) : x ∈ s ∩ s",
        ["exact ⟨h, h⟩", "exact ⟨h, h⟩"], "destruct")
    add("mem_inter_intro", "(α : Type) (s t : Set α) (x : α) (hs : x ∈ s) (ht : x ∈ t) : x ∈ s ∩ t",
        ["exact ⟨hs, ht⟩", "exact And.intro hs ht", "constructor <;> assumption"], "destruct")
    add("mem_inter_intro_swap", "(α : Type) (s t : Set α) (x : α) (hs : x ∈ s) (ht : x ∈ t) : x ∈ t ∩ s",
        ["exact ⟨ht, hs⟩", "exact And.intro ht hs"], "destruct")
    # subset goals needing intro + anonymous constructor / projection
    add("inter_comm_subset_w", "(α : Type) (s t : Set α) : t ∩ s ⊆ s ∩ t",
        ["intro x h; exact ⟨h.2, h.1⟩", "exact fun x h => ⟨h.2, h.1⟩"], "intro")
    add("inter3_subset_left", "(α : Type) (s t u : Set α) : s ∩ t ∩ u ⊆ s",
        ["intro x h; exact h.1.1", "exact fun x h => h.1.1"], "intro")
    add("inter3_subset_mid", "(α : Type) (s t u : Set α) : s ∩ t ∩ u ⊆ t",
        ["intro x h; exact h.1.2", "exact fun x h => h.1.2"], "intro")
    add("inter_subset_inter_union", "(α : Type) (s t : Set α) : s ∩ t ⊆ s ∪ t",
        ["intro x h; exact Or.inl h.1", "exact fun x h => Or.inl h.1"], "intro")
    add("self_subset_self_union", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s) : x ∈ s ∪ (t ∩ s)",
        ["exact Or.inl h", "left; exact h"], "destruct")
    add("inter_subset_left_union", "(α : Type) (s t u : Set α) : s ∩ t ⊆ s ∪ u",
        ["intro x h; exact Or.inl h.1", "exact fun x h => Or.inl h.1"], "intro")
    add("inter_subset_swap_left", "(α : Type) (s t : Set α) : s ∩ t ⊆ t",
        ["intro x h; exact h.2", "exact Set.inter_subset_right", "exact fun x h => h.2"], "intro")
    add("subset_union_inl_w", "(α : Type) (s t : Set α) (x : α) (h : x ∈ t) : x ∈ s ∪ t",
        ["exact Or.inr h", "right; exact h"], "destruct")
    add("mem_union_elim_same", "(α : Type) (s : Set α) (x : α) (h : x ∈ s ∪ s) : x ∈ s",
        ["exact h.elim id id", "rcases h with h | h <;> exact h", "cases h <;> assumption"], "destruct")
    add("inter_assoc_subset", "(α : Type) (s t u : Set α) : (s ∩ t) ∩ u ⊆ s ∩ (t ∩ u)",
        ["intro x h; exact ⟨h.1.1, h.1.2, h.2⟩", "exact fun x h => ⟨h.1.1, h.1.2, h.2⟩"], "intro")
    add("subset_inter_of_both", "(α : Type) (s t u : Set α) (h1 : s ⊆ t) (h2 : s ⊆ u) : s ⊆ t ∩ u",
        ["intro x hx; exact ⟨h1 hx, h2 hx⟩", "exact fun x hx => ⟨h1 hx, h2 hx⟩"], "intro")
    add("mem_of_subset", "(α : Type) (s t : Set α) (x : α) (hsub : s ⊆ t) (hx : x ∈ s) : x ∈ t",
        ["exact hsub hx", "apply hsub; exact hx"], "destruct")
    add("inter_left_subset_self", "(α : Type) (s t : Set α) : s ∩ t ⊆ s",
        ["intro x h; exact h.1", "exact Set.inter_subset_left", "exact fun x h => h.1"], "intro")
    add("union_left_subset_w", "(α : Type) (s t : Set α) : s ⊆ s ∪ t",
        ["intro x h; exact Or.inl h", "exact Set.subset_union_left"], "intro")
    add("mem_inter_proj_left2", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ s",
        ["exact h.1", "exact h.left"], "destruct")
    add("subset_self_inter_dup", "(α : Type) (s : Set α) : s ⊆ s ∩ s",
        ["intro x h; exact ⟨h, h⟩", "exact fun x h => ⟨h, h⟩"], "intro")
    add("inter_idem_subset", "(α : Type) (s : Set α) : s ∩ s ⊆ s",
        ["intro x h; exact h.1", "exact Set.inter_subset_left"], "intro")
    return P


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _guard_triples() -> Set:
    """benchmark triples that must never enter training: v25 held-out test +
    v26 holdout test + v18."""
    triples: Set = set()
    tt = json.loads((ROOT / "data" / "processed" / "v25_tierc_augmented" / "test_theorems.json").read_text())
    v25_test = set(tt["test_theorems"])
    for r in _read(ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl"):
        if r["theorem_name"] in v25_test:
            triples.add((r["theorem_statement"], r["state_before"], r["tactic"]))
    # v26 holdout test rows
    for r in _read(ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_rows.jsonl"):
        triples.add((r["theorem_statement"], r["state_before"], r["tactic"]))
    return triples


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path", default=None)
    ap.add_argument("--base-train", default=str(ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "train_rows.jsonl"))
    ap.add_argument("--out-verified", default=str(ROOT / "data" / "traces" / "v26_set_widen_verified.jsonl"))
    ap.add_argument("--out-train", default=str(ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "train_rows_set_widened.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "set_widen_summary.json"))
    args = ap.parse_args(argv)

    P = plan()
    work, meta = [], []
    for e in P:
        seen = set()
        for c in e["candidates"]:
            if c in seen:
                continue
            seen.add(c)
            work.append((e["theorem_name"], e["theorem_statement"], c))
            meta.append(e)
    v = BatchMathlibVerifier(Path(args.scratch_dir).resolve(), lean_path=args.lean_path, timeout=300)
    if not v.warmup():
        print("warmup failed"); return 2
    verdicts = v.verify_many(work)

    guard = _guard_triples()
    verified, dropped = [], 0
    for vd, e in zip(verdicts, meta):
        if not vd.success:
            continue
        st = state_before(vd.statement)
        if (vd.statement, st, vd.tactic) in guard:
            dropped += 1
            continue
        verified.append({"theorem_name": vd.theorem_name, "theorem_statement": vd.statement,
                         "state_before": st, "tactic": vd.tactic, "category": "set",
                         "family": "set", "expected_skill": "set",
                         "required_operation": e["required_operation"], "transfer": "mathlib",
                         "corpus_source": "v26_set_widen", "tactic_source": "verified",
                         "split": "train",
                         "proof_head": (vd.tactic.strip().split() or [""])[0].split(";")[0],
                         "mathlib": True})

    Path(args.out_verified).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_verified, "w", encoding="utf-8") as f:
        for r in verified:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    base = _read(Path(args.base_train))
    # dedup by (name, tactic)
    seen = {(r["theorem_name"], r["tactic"]) for r in base}
    added = 0
    for r in verified:
        if (r["theorem_name"], r["tactic"]) not in seen:
            base.append(r); seen.add((r["theorem_name"], r["tactic"])); added += 1
    with open(args.out_train, "w", encoding="utf-8") as f:
        for r in base:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {"n_theorems": len(P), "n_candidates": len(work),
               "n_verified": len(verified), "n_lean_rejected": sum(1 for vd in verdicts if not vd.success),
               "dropped_benchmark_triple": dropped, "n_added_to_train": added,
               "widened_train_total": len(base),
               "proof_heads": dict(Counter(r["proof_head"] for r in verified)),
               "uses_state_after": False, "uses_manual_oracle": False}
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[widen] set theorems={len(P)} candidates={len(work)} verified={len(verified)} "
          f"rejected={summary['n_lean_rejected']} dropped_benchmark={dropped}")
    print(f"[widen] widened train = {len(base)} rows (+{added} set-widen) -> {args.out_train}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
