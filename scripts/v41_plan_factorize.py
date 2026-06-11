"""Mini-ELF v41 — LPSF plan language: factorize a tactic into (head, arg-type signature).

A *plan* is a sequence of <=8 typed steps `head(T1,T2,..)` with T in {LEMMA, HYP, TERM, NONE},
dropping concrete identifiers (the abstraction). Heads cover ~89% of corpus tactics; the rest -> OTHER.
The plan string (e.g. `intro(HYP) ; simp(NONE) ; exact(TERM)`) is the flow/AR generation target; a
grounder later expands each step back to a concrete tactic conditioned on the statement.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# top heads (~89% coverage, measured on the v40 whole-proof corpus); rest -> OTHER
LEMMAS = {"rw", "simp", "simp_rw", "rwa", "dsimp", "erw", "rewrite", "simp_all", "simpa", "unfold"}
HYPS = {"intro", "rintro", "intros", "rintros"}
TERM = {"exact", "apply", "refine", "convert", "have", "exact?", "apply?", "calc", "show", "suffices"}
TARGET = {"cases", "rcases", "obtain", "induction", "subst", "by_cases", "induction'", "cases'"}
NONE = {"rfl", "ring", "omega", "constructor", "classical", "congr", "split_ifs", "aesop", "ext",
        "ext1", "norm_num", "norm_cast", "decide", "trivial", "assumption", "positivity", "linarith",
        "field_simp", "tauto", "aesop_cat", "infer_instance", "funext"}
HEADS = LEMMAS | HYPS | TERM | TARGET | NONE
TAGS = ("LEMMA", "HYP", "TERM", "NONE", "OTHER")
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9.']*")


def _head_of(line: str) -> str:
    line = line.strip()
    m = _WORD.match(line)
    h = m.group(0) if m else ""
    if line[:1] == "·" or line.startswith("case "):
        return ""
    return h if h in HEADS else ("OTHER" if h else "OTHER")


def _split_top_commas(s: str) -> List[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out if x.strip()]


def factorize_tactic(line: str) -> Optional[Tuple[str, List[str]]]:
    line = line.strip()
    if not line or line.startswith("·") or line.startswith("case "):
        return None
    head = _head_of(line)
    rest = line[len(_WORD.match(line).group(0)):].strip() if _WORD.match(line) else ""
    if head in LEMMAS:
        m = re.search(r"\[(.*)\]", line, re.DOTALL)
        if m:
            n = min(len(_split_top_commas(m.group(1))), 3) or 1
            args = ["LEMMA"] * n
        else:
            args = ["NONE"]
    elif head in HYPS:
        names = [t for t in _WORD.findall(rest)][:3]
        args = ["HYP"] * len(names) if names else ["NONE"]
    elif head in TERM:
        args = ["TERM"] if rest else ["NONE"]
    elif head in TARGET:
        args = ["HYP"] if rest else ["NONE"]
    elif head in NONE:
        # ext/funext may name vars -> HYP; else NONE
        if head in ("ext", "ext1", "funext") and _WORD.findall(rest):
            args = ["HYP"] * min(len(_WORD.findall(rest)), 2)
        else:
            args = ["NONE"]
    else:  # OTHER
        if "[" in line:
            args = ["LEMMA"]
        elif rest:
            args = ["TERM"]
        else:
            args = ["NONE"]
    return head, args


def factorize_proof(proof: str, max_steps: int = 8) -> Optional[List[Tuple[str, List[str]]]]:
    steps = []
    for line in proof.splitlines():
        f = factorize_tactic(line)
        if f is None:
            continue
        steps.append(f)
        if len(steps) >= max_steps:
            break
    return steps or None


def plan_to_str(steps: List[Tuple[str, List[str]]]) -> str:
    return " ; ".join(f"{h} ( {' , '.join(a)} )" for h, a in steps)


if __name__ == "__main__":
    import json, sys
    from pathlib import Path
    from collections import Counter
    ROOT = Path(__file__).resolve().parents[1]
    rows = [json.loads(l) for l in (ROOT / "data/v40/corpora/wholeproof/train.jsonl").read_text().splitlines() if l.strip()]
    n_tac = n_cov = 0
    lens, slots = Counter(), Counter()
    for r in rows:
        for line in r["tactic"].splitlines():
            f = factorize_tactic(line)
            if f is None:
                continue
            n_tac += 1
            if f[0] != "OTHER":
                n_cov += 1
        plan = factorize_proof(r["tactic"])
        if plan:
            lens[len(plan)] += 1
            for _, args in plan:
                for a in args:
                    slots[a] += 1
    print(f"head coverage (non-OTHER): {n_cov}/{n_tac} = {n_cov/max(n_tac,1):.1%}")
    print(f"plan-length dist: {dict(sorted(lens.items()))}")
    print(f"  L>=2 fraction: {sum(c for l,c in lens.items() if l>=2)/max(sum(lens.values()),1):.1%}")
    print(f"slot-type dist: {dict(slots.most_common())}")
    import random
    random.seed(3407)
    print("\n=== round-trip samples (proof -> plan) ===")
    for r in random.sample(rows, 12):
        plan = factorize_proof(r["tactic"])
        proof1 = r["tactic"].replace("\n", " ; ")
        print(f"  PROOF: {proof1[:70]}")
        print(f"  PLAN : {plan_to_str(plan) if plan else '<none>'}")
