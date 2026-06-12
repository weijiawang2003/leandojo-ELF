"""Mini-ELF v42 — persistent verification-verdict cache.

Re-baselining v39–v41 re-verifies thousands of (statement, tactic) candidates,
many shared across sources/tiers/phases. This append-only JSONL cache makes
repeats free. Keys include the verifier's import header so core-Lean and
Mathlib verdicts never collide; only TRUSTED verdicts (bisect-batched or
isolated — both provably equal isolation) may be stored.

Honesty: the cache stores Lean's verdict verbatim; it never synthesises one.
A cache hit is exactly the verdict Lean produced earlier for the identical
(imports, statement, tactic) triple under the same pinned toolchain.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

Item = Tuple[str, str, str]  # (theorem_name, statement, tactic)


class VerdictCache:
    def __init__(self, path: Path, imports: Sequence[str]) -> None:
        self.path = Path(path)
        self.header = "\x1f".join(imports)
        self._map: Dict[str, Tuple[bool, Optional[str]]] = {}
        self.hits = 0
        self.misses = 0
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                self._map[r["h"]] = (bool(r["ok"]), r.get("err"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def _key(self, statement: str, tactic: str) -> str:
        return hashlib.sha256(
            f"{self.header}\x1e{statement}\x1e{tactic}".encode()).hexdigest()

    def get(self, statement: str, tactic: str) -> Optional[Tuple[bool, Optional[str]]]:
        return self._map.get(self._key(statement, tactic))

    def put(self, statement: str, tactic: str, ok: bool, err: Optional[str]) -> None:
        h = self._key(statement, tactic)
        if h in self._map:
            return
        self._map[h] = (ok, err)
        self._fh.write(json.dumps({"h": h, "ok": ok, "err": err}) + "\n")
        self._fh.flush()


def cached_verify(verifier, items: Sequence[Item], cache: Optional[VerdictCache],
                  *, isolated: bool = False) -> Dict[Tuple[str, str], bool]:
    """Verify ``items`` (deduped) through the cache; misses go to the verifier's
    trusted path (``verify_many_bisect``, or one-per-file when ``isolated``).
    Returns ``(theorem_name, tactic) -> verified``."""
    vmap: Dict[Tuple[str, str], bool] = {}
    todo: List[Item] = []
    seen = set()
    for nm, stmt, tac in items:
        if (nm, tac) in seen:
            continue
        seen.add((nm, tac))
        hit = cache.get(stmt, tac) if cache else None
        if hit is not None:
            cache.hits += 1
            vmap[(nm, tac)] = hit[0]
        else:
            if cache:
                cache.misses += 1
            todo.append((nm, stmt, tac))
    if todo:
        if isolated:
            verdicts = []
            for it in todo:
                verdicts.extend(verifier.verify_many_bisect([it]))
        else:
            verdicts = verifier.verify_many_bisect(todo)
        for (nm, stmt, tac), v in zip(todo, verdicts):
            vmap[(nm, tac)] = v.success
            if cache:
                cache.put(stmt, tac, v.success, v.error)
    return vmap


__all__ = ["VerdictCache", "cached_verify", "Item"]
