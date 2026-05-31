"""Compile the Mini-ELF v2 generalization comparison tables from generated
metrics.json files. Prints pass@k / invalid@1 / novelty / source / per-difficulty
/ sibling rows for any set of baseline dirs. Read-only; no Lean, no torch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

B = Path("data/baselines")


def load(name: str):
    p = B / name / "metrics.json"
    if not p.exists():
        return None
    return json.load(open(p, encoding="utf-8"))


def pk(d, k):
    try:
        return d["lean_verification"]["pass_at_k"][str(k)]["rate"]
    except Exception:
        return float("nan")


def fmt_row(label, d):
    if not d:
        return f"{label:40s}  (missing)"
    g = d.get("elf_v1_generation") or d.get("elf_generation") or {}
    inv = g.get("invalid_rate_top1", g.get("candidate_invalid_rate", float("nan")))
    nv = g.get("novel_candidates_verified", "-")
    src = g.get("candidate_source_breakdown", {})
    wit = src.get("witness_copy", {})
    wv = f"{wit.get('verified', 0)}/{wit.get('attempted', 0)}" if wit else "-"
    n = d.get("n_examples", "?")
    return (f"{label:40s} n={str(n):>3s}  p@1={pk(d,1):.2f} p@3={pk(d,3):.2f} p@5={pk(d,5):.2f}  "
            f"inv@1={inv if isinstance(inv,str) else f'{inv:.2f}'}  novelV={nv}  witness={wv}")


def main(argv=None) -> int:
    # label -> baseline dir name
    rows = [
        ("--- BASIC corpus (in-distribution) ---", None),
        ("v1 rerank+witness  basic val", "basic_lean_cli_mini_elf_v1_rerank_witness_val"),
        ("v1 rerank+witness  basic test", "basic_lean_cli_mini_elf_v1_rerank_witness_test"),
        ("v2 rerank+witness  basic test", "combined_lean_cli_mini_elf_v2_basic_test"),
        ("--- HARD corpus: v1 TRANSFER (no retrain) ---", None),
        ("v1 transfer  hard hash", "hard_lean_cli_transfer_v1_hash_test"),
        ("v1 transfer  hard hash (no rerank)", "hard_lean_cli_transfer_v1_hash_test_norerank"),
        ("v1 transfer  hard family_holdout", "hard_lean_cli_transfer_v1_family_holdout_test"),
        ("v1 transfer  hard difficulty_holdout", "hard_lean_cli_transfer_v1_difficulty_holdout_test"),
        ("v1 transfer  hard adversarial_sibling", "hard_lean_cli_transfer_v1_adversarial_sibling_test"),
        ("--- HARD corpus: v2 (trained on combined) ---", None),
        ("v2  hard hash", "combined_lean_cli_mini_elf_v2_hard_hash_test"),
        ("v2  hard difficulty_holdout", "combined_lean_cli_mini_elf_v2_hard_difficulty_test"),
        ("v2  hard adversarial_sibling", "combined_lean_cli_mini_elf_v2_hard_adversarial_test"),
        ("v2  hard family_holdout", "combined_lean_cli_mini_elf_v2_hard_family_test"),
    ]
    for label, name in rows:
        if name is None:
            print("\n" + label)
            continue
        print("  " + fmt_row(label, load(name)))

    # per-difficulty + sibling detail for the transfer + v2 hash dirs
    print("\n=== per-difficulty pass@5 + sibling top-1 family acc ===")
    detail = [
        ("v1 transfer hash", "hard_lean_cli_transfer_v1_hash_test"),
        ("v1 transfer difficulty", "hard_lean_cli_transfer_v1_difficulty_holdout_test"),
        ("v1 transfer adversarial", "hard_lean_cli_transfer_v1_adversarial_sibling_test"),
        ("v2 hard hash", "combined_lean_cli_mini_elf_v2_hard_hash_test"),
        ("v2 hard difficulty", "combined_lean_cli_mini_elf_v2_hard_difficulty_test"),
        ("v2 hard adversarial", "combined_lean_cli_mini_elf_v2_hard_adversarial_test"),
    ]
    for label, name in detail:
        d = load(name)
        if not d:
            continue
        pd = d.get("per_difficulty_pass_at_k", {})
        pd_s = " ".join(f"{k}:p5={v['pass_at_k']['5']['rate']:.2f}(n{v['n_rows']})" for k, v in pd.items())
        sc = d.get("sibling_confusion", {})
        sib = " ".join(f"{g}:{sc[g]['top1_family_accuracy']:.2f}" for g in sc if "n_rows" in sc[g])
        print(f"  {label:26s} diff[{pd_s}]  sibling[{sib}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
