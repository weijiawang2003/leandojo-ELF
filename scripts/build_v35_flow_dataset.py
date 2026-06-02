"""Mini-ELF v35 — Part 0: build the embedded-flow dataset (core + Mathlib tier-C).

Assembles **Lean-verified** ``(condition, tactic)`` rows into a theorem-level
split for the v35 ELF-style flow generator AND its matched token-AR baseline.
The two models must see *identical* tokens, so this builder owns the single
shared :class:`~mini_elf_lean.token_seq2seq_dataset.TokenVocab` (built from the
train split only) and emits pre-tokenized ``cond_ids`` / ``tgt_ids`` alongside
the raw ``theorem_statement`` / ``state_before`` (the Lean eval needs the raw
text to reconstruct ``example <stmt> := by ...``).

Sources (all rows already verified by the TrustedMathlibVerifier in prior runs;
``tactic_source == "verified"``):

* **Mathlib tier-C** — the v33 canonical specialist corpus
  (``v33_general_residual_train_rows.jsonl`` + ``val_rows.jsonl``). This is the
  exact data the v24/v33 token-AR engine trained on, so the flow-vs-AR
  comparison is matched at the data level too. Verified under ``import Mathlib``.
* **Core** — the v24 broad-plus-residual training rows
  (``v24_broad_plus_residual/train_rows.jsonl``). Verified under core Lean (no
  Mathlib). Included by default; ``--no-core`` drops it for a Mathlib-only run.

Honesty / guardrails (mirrors the rest of the project):

* ``state_after`` is **never** read. The condition is ``theorem_statement`` +
  ``state_before`` only (:func:`build_input_text`).
* Split is by ``theorem_name`` (deterministic md5 bucketing) and the builder
  **asserts** the train/val/test theorem sets are disjoint.
* The vocabulary is built from the **train split only**; val/test tokens that
  are train-OOV map to ``<unk>`` — no leakage from the eval splits into the
  tokenizer.
* ``sorry`` / ``admit`` / ``unsafe`` candidates are dropped (they are never
  valid targets); rows are de-duplicated by ``(theorem_name, tactic)``.
* Writes only ``v35_*`` artifacts (``data/processed/v35_elf_flow/``). Never
  touches the v24 broad-core or v33 specialist weights/configs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.tactic_sanitizer import contains_forbidden  # noqa: E402
from mini_elf_lean.tactic_tokenizer import tokenize  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402

P = ROOT / "data" / "processed"

# -- default verified-row sources ------------------------------------------- #
MATHLIB_SOURCES: Tuple[Path, ...] = (
    P / "v33_mathlib_specialist" / "configs" / "v33_general_residual_train_rows.jsonl",
    P / "v33_mathlib_specialist" / "configs" / "val_rows.jsonl",
)
CORE_SOURCES: Tuple[Path, ...] = (
    P / "v24_broad_plus_residual" / "train_rows.jsonl",
)

DEFAULT_OUT = P / "v35_elf_flow"


def _read(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _bucket(theorem_name: str, *, val_lo: int, test_lo: int) -> str:
    """Deterministic theorem-level split: md5(name) % 100 → train/val/test.

    ``val_lo``/``test_lo`` are the lower bounds (e.g. 80/90 → 80% train, 10%
    val, 10% test). Stable across runs and machines (md5, not Python ``hash``)."""
    h = int(hashlib.md5(theorem_name.encode("utf-8")).hexdigest(), 16) % 100
    if h >= test_lo:
        return "test"
    if h >= val_lo:
        return "val"
    return "train"


def _tier(row: Dict[str, Any]) -> str:
    """Verification tier. v33 rows carry ``mathlib=True`` (verified under
    ``import Mathlib``); v24 broad-core rows do not."""
    if row.get("mathlib") or row.get("transfer") == "mathlib":
        return "mathlib"
    return "core"


def _norm_row(row: Dict[str, Any], *, default_tier: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Reduce a raw verified row to the v35 schema, or ``None`` to drop it."""
    name = row.get("theorem_name")
    stmt = row.get("theorem_statement")
    state = row.get("state_before")
    tactic = row.get("tactic")
    if not (name and stmt and state and tactic):
        return None
    if row.get("tactic_source") not in (None, "verified"):
        # Only verified targets (None tolerated for legacy rows that predate the
        # field but are sourced from verified corpora).
        return None
    if contains_forbidden(tactic):
        return None
    tier = default_tier or _tier(row)
    return {
        "theorem_name": name,
        "theorem_statement": stmt,
        "state_before": state,
        "tactic": tactic,
        "tier": tier,
        "category": row.get("category"),
        "theorem_family": row.get("theorem_family") or row.get("family"),
        "density_group": row.get("density_group"),
        "transfer": row.get("transfer"),
        "required_operation": row.get("required_operation"),
        "corpus_source": row.get("corpus_source") or row.get("source"),
    }


def _tok_len(text: str) -> int:
    return len(tokenize(text))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--mathlib-sources", nargs="*", default=[str(p) for p in MATHLIB_SOURCES])
    ap.add_argument("--core-sources", nargs="*", default=[str(p) for p in CORE_SOURCES])
    ap.add_argument("--no-core", action="store_true", help="Mathlib-only dataset")
    ap.add_argument("--val-lo", type=int, default=80, help="md5%%100 lower bound for val")
    ap.add_argument("--test-lo", type=int, default=90, help="md5%%100 lower bound for test")
    ap.add_argument("--max-cond-len", type=int, default=96, help="cap condition token ids")
    ap.add_argument("--max-tgt-len", type=int, default=32, help="cap tactic token ids (incl bos/eos)")
    args = ap.parse_args(argv)

    # 1. Ingest + normalize + dedup -------------------------------------- #
    raw: List[Dict[str, Any]] = []
    for sp in args.mathlib_sources:
        for r in _read(Path(sp)):
            nr = _norm_row(r, default_tier="mathlib")
            if nr:
                raw.append(nr)
    if not args.no_core:
        for sp in args.core_sources:
            for r in _read(Path(sp)):
                nr = _norm_row(r, default_tier="core")
                if nr:
                    raw.append(nr)

    seen: set = set()
    rows: List[Dict[str, Any]] = []
    for r in raw:
        key = (r["theorem_name"], r["tactic"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)

    if not rows:
        print("ERROR: no verified rows ingested — check --mathlib-sources/--core-sources", file=sys.stderr)
        return 2

    # 2. Theorem-level split (by name) ----------------------------------- #
    for r in rows:
        r["split"] = _bucket(r["theorem_name"], val_lo=args.val_lo, test_lo=args.test_lo)
    splits = {"train": [], "val": [], "test": []}
    for r in rows:
        splits[r["split"]].append(r)

    train_names = {r["theorem_name"] for r in splits["train"]}
    val_names = {r["theorem_name"] for r in splits["val"]}
    test_names = {r["theorem_name"] for r in splits["test"]}
    # Hard guardrail: theorem sets must be pairwise disjoint.
    assert not (train_names & val_names), sorted(train_names & val_names)[:5]
    assert not (train_names & test_names), sorted(train_names & test_names)[:5]
    assert not (val_names & test_names), sorted(val_names & test_names)[:5]

    # 3. Vocab from TRAIN ONLY ------------------------------------------- #
    train_texts = [build_input_text(r["theorem_statement"], r["state_before"]) for r in splits["train"]]
    train_tactics = [r["tactic"] for r in splits["train"]]
    vocab = TokenVocab.build(train_texts, train_tactics)

    # 4. Tokenize every row (cond + tgt ids) ----------------------------- #
    cond_lens: List[int] = []
    tgt_lens: List[int] = []
    for r in rows:
        text = build_input_text(r["theorem_statement"], r["state_before"])
        cond_ids = vocab.encode_source(text)[: args.max_cond_len]
        tgt_ids = vocab.encode_target(r["tactic"])  # [bos ... eos]
        # Truncate target but always keep the trailing <eos>.
        if len(tgt_ids) > args.max_tgt_len:
            tgt_ids = tgt_ids[: args.max_tgt_len - 1] + [vocab.eos_id]
        r["cond_ids"] = cond_ids
        r["tgt_ids"] = tgt_ids
        cond_lens.append(len(cond_ids))
        tgt_lens.append(len(tgt_ids))

    # 5. Write artifacts -------------------------------------------------- #
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        with (out / f"{split}.jsonl").open("w", encoding="utf-8") as f:
            for r in splits[split]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    vocab.save(out / "vocab.json")

    def _pct(vals: List[int], q: float) -> int:
        if not vals:
            return 0
        s = sorted(vals)
        return s[min(len(s) - 1, int(q * len(s)))]

    manifest = {
        "config": "v35_elf_flow",
        "out_dir": str(out),
        "sources": {
            "mathlib": [str(p) for p in args.mathlib_sources],
            "core": [] if args.no_core else [str(p) for p in args.core_sources],
        },
        "n_rows": len(rows),
        "n_theorems": len({r["theorem_name"] for r in rows}),
        "split_counts": {s: len(splits[s]) for s in ("train", "val", "test")},
        "split_theorems": {"train": len(train_names), "val": len(val_names), "test": len(test_names)},
        "tier_counts": dict(Counter(r["tier"] for r in rows)),
        "test_tier_counts": dict(Counter(r["tier"] for r in splits["test"])),
        "category_counts": dict(Counter(r.get("category") for r in rows).most_common(20)),
        "vocab_size": len(vocab),
        "max_cond_len": args.max_cond_len,
        "max_tgt_len": args.max_tgt_len,
        "cond_len_p50_p95_max": [_pct(cond_lens, 0.5), _pct(cond_lens, 0.95), max(cond_lens, default=0)],
        "tgt_len_p50_p95_max": [_pct(tgt_lens, 0.5), _pct(tgt_lens, 0.95), max(tgt_lens, default=0)],
        "uses_state_after": False,
        "uses_manual_oracle": False,
        "split_rule": f"md5(theorem_name)%100: <{args.val_lo} train, <{args.test_lo} val, else test",
        "note": "verified-only; deduped by (theorem_name,tactic); vocab from train split only.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({k: manifest[k] for k in (
        "n_rows", "n_theorems", "split_counts", "split_theorems",
        "tier_counts", "test_tier_counts", "vocab_size",
        "cond_len_p50_p95_max", "tgt_len_p50_p95_max",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
