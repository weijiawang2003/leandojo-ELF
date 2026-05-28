"""JSONL I/O and a tiny on-disk JSON cache.

The cache is intentionally trivial: it maps a SHA-256 hash of a key string to a
JSON value on disk. We use it both for LLM proposals (so re-running collection
doesn't burn tokens) and for Lean tactic results (so debugging a single seed
doesn't re-spawn LeanDojo for already-verified tactics).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------- JSONL ----------------


def read_jsonl(path: str | os.PathLike[str]) -> Iterator[dict[str, Any]]:
    """Yield records from a JSONL file. Blank lines and lines starting with
    '#' are ignored, which lets seed files carry comments."""

    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSONL line %s:%d (%s)", p, lineno, exc)


def append_jsonl(path: str | os.PathLike[str], records: Iterable[BaseModel | dict[str, Any]]) -> int:
    """Append records to a JSONL file. Returns the number of lines written."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a", encoding="utf-8") as fh:
        for rec in records:
            if isinstance(rec, BaseModel):
                payload = rec.model_dump()
            else:
                payload = rec
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            fh.write("\n")
            n += 1
    return n


def write_jsonl(path: str | os.PathLike[str], records: Iterable[BaseModel | dict[str, Any]]) -> int:
    """Overwrite a JSONL file with the given records."""

    p = Path(path)
    if p.exists():
        p.unlink()
    return append_jsonl(p, records)


# ---------------- Cache ----------------


def hash_key(*parts: str) -> str:
    """Stable hash over an ordered tuple of strings."""

    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class JsonCache:
    """Persistent hash -> JSON cache.

    Each entry lives in its own file under `root/<first 2 chars>/<hash>.json`,
    which keeps directory listings reasonable as the cache grows.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Optional[Any]:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Cache read failed for %s: %s", key, exc)
            return None

    def put(self, key: str, value: Any) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, sort_keys=True)
        tmp.replace(path)
