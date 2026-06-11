"""Mini-ELF v40 — whole-proof corpus tools.

Reconstruct verifiable `example <binders> : <goal> := by <proof>` from LeanDojo:
- statement := the FIRST tactic's `state_before` converted to example binders + goal;
- whole_proof := newline-join of the theorem's traced tactics (linear proofs only).

`state_to_example` is best-effort; the GOLD-COMPILE-RATE (does `example stmt := by gold`
compile) is the empirical quality measure and is itself a deliverable (Phase 1).
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

DAGGER = re.compile(r"[✝][¹²³⁰-⁹]*")  # ✝ with optional superscripts


def _strip_dagger(s: str) -> str:
    return DAGGER.sub("", s)


def state_to_example(state_before: str) -> Optional[str]:
    """Convert a single-goal proof state to the text after `example`, i.e.
    `<binders> : <goal>`. Returns None if not cleanly convertible."""
    if state_before.count("⊢") != 1:        # exactly one goal (skip case-split states)
        return None
    pre, goal = state_before.rsplit("⊢", 1)
    goal = goal.strip()
    if not goal:
        return None
    binders: List[str] = []
    auto = 0
    for ln in pre.strip().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("case "):
            continue
        if " : " not in ln and not ln.endswith(":"):
            return None
        names, typ = ln.split(":", 1)
        names, typ = names.strip(), typ.strip()
        if not typ:
            return None
        is_inst = names.replace("✝", "").rstrip("0123456789¹²³⁰-⁹").startswith("inst")
        if "✝" in typ:
            return None                          # inaccessible name in a type -> won't compile
        if is_inst:
            binders.append(f"[{typ}]")
        else:
            clean = []
            for nm in names.split():
                nm2 = _strip_dagger(nm)
                if not nm2 or "✝" in nm2:
                    nm2 = f"a{auto}"; auto += 1
                clean.append(nm2)
            binders.append(f"({' '.join(clean)} : {typ})")
    if "✝" in goal:
        return None
    return f"{' '.join(binders)} : {goal}".strip()


def whole_proof(traced_tactics: List[dict], *, linear_only: bool = True) -> Optional[str]:
    """Newline-join the tactic strings of a proof. If linear_only, reject proofs whose
    states ever branch (multiple goals) or use focus dots / case labels (don't linearize)."""
    tacs = []
    for st in traced_tactics:
        t = (st.get("tactic") or "").strip()
        if not t:
            return None
        if linear_only and (t.startswith("·") or t.startswith("case ") or t.startswith("· ")):
            return None
        tacs.append(t)
    if not tacs:
        return None
    return "\n".join(tacs)


if __name__ == "__main__":
    # --- gold-compile-rate probe on the LeanDojo test split ---
    import argparse, json, sys, time
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    for p in (str(ROOT / "src"), str(ROOT / "scripts")):
        sys.path.insert(0, p)
    from mini_elf_lean.tactic_tokenizer import tokenize
    from v38_matrix_eval import get_verifier

    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--n-try", type=int, default=150)
    ap.add_argument("--cond-cap", type=int, default=256)
    ap.add_argument("--proof-cap", type=int, default=48)
    args = ap.parse_args()
    RAW = ROOT / "data" / "v39" / "_raw" / "leandojo_benchmark_4" / "random" / f"{args.split}.json"
    data = json.load(open(RAW))
    print(f"{args.split}: {len(data)} theorems")

    def tlen(s):
        return sum(1 for _ in tokenize(s))

    cand = []
    for th in data:
        tt = th.get("traced_tactics", [])
        if not tt:
            continue
        sb = tt[0].get("state_before", "")
        stmt = state_to_example(sb)
        if stmt is None:
            continue
        wp = whole_proof(tt)
        if wp is None:
            continue
        if tlen(stmt) > args.cond_cap or tlen(wp) > args.proof_cap:
            continue
        cand.append((th["full_name"], stmt, wp, len(tt)))
    print(f"convertible+in-length: {len(cand)} / {len(data)}")
    import random
    random.seed(3407); random.shuffle(cand)
    probe = cand[: args.n_try]
    v = get_verifier()
    items = [(nm, stmt, wp) for (nm, stmt, wp, _) in probe]
    t = time.time()
    res = v.verify_many(items, confirm=True)
    ok = sum(1 for x in res if x.success)
    print(f"GOLD-COMPILE-RATE: {ok}/{len(items)} = {ok/max(len(items),1):.1%}  ({time.time()-t:.0f}s)")
    # length breakdown of successes
    by_len = {}
    smap = {(x.theorem_name, x.tactic): x.success for x in res}
    for (nm, stmt, wp, nt) in probe:
        b = "1" if nt == 1 else ("2-3" if nt <= 3 else "4+")
        by_len.setdefault(b, [0, 0])
        by_len[b][1] += 1
        if smap.get((nm, wp)):
            by_len[b][0] += 1
    print("by proof length (compiled/total):", {k: f"{v[0]}/{v[1]}" for k, v in by_len.items()})
    # show a few successes
    print("sample compiled whole-proofs:")
    shown = 0
    for x in res:
        if x.success and shown < 4:
            print(f"  [{x.theorem_name}]  example {x.statement[:60]}... := by {x.tactic!r}"); shown += 1
