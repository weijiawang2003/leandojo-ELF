"""v35 dataset guardrails — theorem-level no-leakage + state_after never read.

Hermetic: builds a tiny synthetic verified-row corpus in ``tmp_path`` and runs
the real :mod:`build_v35_flow_dataset` over it, so the test does not depend on
the (gitignored, regenerable) ``data/processed`` corpora.

Two load-bearing invariants:

1. The train / val / test theorem-name sets are pairwise disjoint.
2. ``state_after`` is never read or propagated — even when present in the input
   rows, it must not appear in any emitted dataset row, and the condition tokens
   must be derivable from ``theorem_statement`` + ``state_before`` alone.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
import sys

for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_v35_flow_dataset as builder  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402


def _make_rows(n: int, tier: str):
    """Synthetic verified rows. A ``state_after`` field is deliberately included
    to prove the builder ignores it."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "theorem_name": f"{tier}_thm_{i}",
                "theorem_statement": f"(a b : Nat) : a + {i} = {i} + a",
                "state_before": f"a b : Nat\n⊢ a + {i} = {i} + a",
                "state_after": "THIS MUST NEVER BE READ",  # poison field
                "tactic": "rw [Nat.add_comm]" if i % 2 else "omega",
                "category": "nat",
                "family": "add_comm",
                "transfer": "mathlib" if tier == "mathlib" else "core",
                "mathlib": tier == "mathlib",
                "tactic_source": "verified",
            }
        )
    return rows


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _build(tmp_path: Path):
    ml = tmp_path / "mathlib_rows.jsonl"
    core = tmp_path / "core_rows.jsonl"
    _write_jsonl(ml, _make_rows(40, "mathlib"))
    _write_jsonl(core, _make_rows(40, "core"))
    out = tmp_path / "v35_out"
    rc = builder.main(
        [
            "--out-dir", str(out),
            "--mathlib-sources", str(ml),
            "--core-sources", str(core),
        ]
    )
    assert rc == 0
    return out


def _load(out: Path, split: str):
    return [json.loads(l) for l in (out / f"{split}.jsonl").read_text().splitlines() if l.strip()]


def test_splits_are_disjoint_by_theorem(tmp_path):
    out = _build(tmp_path)
    names = {}
    for split in ("train", "val", "test"):
        names[split] = {r["theorem_name"] for r in _load(out, split)}
    assert names["train"] & names["val"] == set()
    assert names["train"] & names["test"] == set()
    assert names["val"] & names["test"] == set()
    # And the split is non-degenerate (all three buckets populated for 80 thms).
    assert all(names[s] for s in ("train", "val", "test"))


def test_state_after_never_propagated(tmp_path):
    out = _build(tmp_path)
    for split in ("train", "val", "test"):
        for r in _load(out, split):
            assert "state_after" not in r, f"state_after leaked into {split} row"


def test_cond_ids_derive_from_statement_and_state_only(tmp_path):
    """cond_ids must equal encode_source(statement\\nstate_before) — i.e. the
    condition is a pure function of (statement, state_before), never state_after."""
    out = _build(tmp_path)
    vocab = TokenVocab.load(out / "vocab.json")
    for r in _load(out, "train"):
        expected = vocab.encode_source(build_input_text(r["theorem_statement"], r["state_before"]))
        assert r["cond_ids"] == expected[: len(r["cond_ids"])]


def test_vocab_built_from_train_only(tmp_path):
    """A token that appears ONLY in a held-out (val/test) tactic must not be in
    the vocabulary — otherwise the tokenizer leaks eval information."""
    out = _build(tmp_path)
    vocab = TokenVocab.load(out / "vocab.json")
    train = _load(out, "train")
    train_texts = [build_input_text(r["theorem_statement"], r["state_before"]) for r in train]
    train_tactics = [r["tactic"] for r in train]
    expected = TokenVocab.build(train_texts, train_tactics)
    assert vocab.itos == expected.itos


def test_manifest_records_no_state_after(tmp_path):
    out = _build(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["uses_state_after"] is False
    assert manifest["uses_manual_oracle"] is False
    assert manifest["n_rows"] == manifest["split_counts"]["train"] + manifest["split_counts"]["val"] + manifest["split_counts"]["test"]
