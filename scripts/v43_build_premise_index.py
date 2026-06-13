"""Mini-ELF v43 — extract a Mathlib premise database + BM25 index from the LeanDojo corpus.

Each premise = (full_name, signature). The signature is the declaration `code` truncated at
`:=` (the type, not the body). We tokenize the full_name (camelCase / `.` / `_` split) and the
signature into an identifier bag, build document frequencies, and persist a compact JSON index
that `grounder_retrieval.py` loads for BM25 premise selection conditioned on a theorem statement.

This is the ReProver-style premise pool (LeanDojo, Yang et al. 2023) realized lexically — a
training-free, sound retrieval baseline; a dense retriever is the documented ceiling.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/v39/_raw/leandojo_benchmark_4/corpus.jsonl"
OUT = ROOT / "data/v43/premises"

_TOK = re.compile(r"[A-Za-z][A-Za-z0-9']*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def split_name(name: str) -> list[str]:
    """`Finset.sum_range_succ` -> finset sum range succ (+ camelCase split)."""
    out = []
    for part in re.split(r"[._]", name):
        for m in _CAMEL.findall(part):
            if m:
                out.append(m.lower())
    return out


def sig_tokens(code: str) -> list[str]:
    head = code.split(":=", 1)[0]
    head = re.sub(r"^@\[[^\]]*\]", " ", head)  # drop attributes
    return [t.lower() for t in _TOK.findall(head)][:80]


def main() -> int:
    seen: dict[str, str] = {}
    n_files = 0
    for line in CORPUS.read_text().splitlines():
        if not line.strip():
            continue
        n_files += 1
        r = json.loads(line)
        for p in r["premises"]:
            fn = p["full_name"]
            if fn in seen:
                continue
            seen[fn] = p.get("code", "") or ""

    # Keep premises that look usable as tactic arguments: drop obvious noise
    # (names with spaces, very long, or empty). Internal `_` -names kept (Mathlib uses them).
    docs: dict[str, list[str]] = {}
    for fn, code in seen.items():
        if not fn or " " in fn or len(fn) > 120:
            continue
        toks = split_name(fn) + sig_tokens(code)
        if toks:
            docs[fn] = toks

    # document frequency + idf
    df: Counter = Counter()
    for toks in docs.values():
        for t in set(toks):
            df[t] += 1
    N = len(docs)
    idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    OUT.mkdir(parents=True, exist_ok=True)
    # store: names (list), per-doc token-frequency (sparse), doc length, idf, avgdl
    names = list(docs.keys())
    name_idx = {fn: i for i, fn in enumerate(names)}
    postings: dict[str, list[list[float]]] = {}  # term -> [[doc_i, tf], ...]
    dl = []
    for i, fn in enumerate(names):
        toks = docs[fn]
        dl.append(len(toks))
        tf = Counter(toks)
        for t, c in tf.items():
            postings.setdefault(t, []).append([i, c])
    avgdl = sum(dl) / max(len(dl), 1)

    (OUT / "premises.json").write_text(json.dumps({"names": names}))
    (OUT / "bm25.json").write_text(json.dumps({
        "idf": idf, "postings": postings, "dl": dl, "avgdl": avgdl, "N": N}))
    (OUT / "manifest.json").write_text(json.dumps({
        "source": str(CORPUS), "n_files": n_files, "n_unique_premises": len(seen),
        "n_indexed": N, "avgdl": round(avgdl, 2), "vocab": len(idf)}, indent=1))
    print(f"indexed {N} premises from {n_files} files (vocab {len(idf)}, avgdl {avgdl:.1f}) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
