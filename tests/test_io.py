"""Tests for io_utils: JSONL round-trip, comment skipping, JsonCache."""

from __future__ import annotations

from pathlib import Path

from mini_elf_lean.io_utils import JsonCache, append_jsonl, hash_key, read_jsonl, write_jsonl
from mini_elf_lean.schemas import TheoremSeed


def test_jsonl_roundtrip_with_pydantic_models(tmp_path: Path) -> None:
    p = tmp_path / "seeds.jsonl"
    seeds = [
        TheoremSeed(theorem_name="a", theorem_statement="1=1"),
        TheoremSeed(theorem_name="b", theorem_statement="2=2", initial_state="⊢ 2=2"),
    ]
    n = write_jsonl(p, seeds)
    assert n == 2
    rows = list(read_jsonl(p))
    assert [r["theorem_name"] for r in rows] == ["a", "b"]
    assert rows[1]["initial_state"] == "⊢ 2=2"


def test_jsonl_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "data.jsonl"
    p.write_text(
        "# header comment\n"
        "\n"
        '{"x": 1}\n'
        "   \n"
        '{"x": 2}\n',
        encoding="utf-8",
    )
    rows = list(read_jsonl(p))
    assert rows == [{"x": 1}, {"x": 2}]


def test_append_jsonl_is_additive(tmp_path: Path) -> None:
    p = tmp_path / "out.jsonl"
    append_jsonl(p, [{"a": 1}])
    append_jsonl(p, [{"a": 2}, {"a": 3}])
    rows = list(read_jsonl(p))
    assert [r["a"] for r in rows] == [1, 2, 3]


def test_hash_key_is_stable_and_order_sensitive() -> None:
    assert hash_key("a", "b") == hash_key("a", "b")
    assert hash_key("a", "b") != hash_key("b", "a")


def test_json_cache_roundtrip(tmp_path: Path) -> None:
    cache = JsonCache(tmp_path / "cache")
    assert cache.get("missing") is None
    cache.put("k1", {"value": 42, "list": [1, 2, 3]})
    assert cache.get("k1") == {"value": 42, "list": [1, 2, 3]}


def test_read_jsonl_returns_empty_on_missing_file(tmp_path: Path) -> None:
    assert list(read_jsonl(tmp_path / "nope.jsonl")) == []
