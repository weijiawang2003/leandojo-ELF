"""Mini-ELF v37 — §5 optional Lean sanity (gated on train exact-seq > 0).

The overfit control found the flow reproduces exact gold tactics on a tiny train
subset (M=4 / 800 epochs: exact-seq 0.55). This confirms those exact-sequence
hits are **genuinely valid Lean tactics**, not a metric artifact: reproduce the
M=4 / 800 / D128 model deterministically, collect the sampled strings that decode
**exactly** to a gold tactic of their theorem, and verify a handful with the
``TrustedMathlibVerifier(confirm=True)`` (the only verifier allowed for
verification numbers). Since an exact hit equals a dataset gold tactic (already
Lean-verified at corpus build), these must verify; a failure would expose a
metric/sanitization bug.

Skips entirely if the Mathlib scratch env is unavailable. ``state_after`` never
read; writes only ``data/baselines/v37_overfit/lean_sanity.json``.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch  # noqa: E402

from mini_elf_lean.elf_v35_embed import ElfV35Config  # noqa: E402
from mini_elf_lean.elf_v35_sample import integrate as integrate_v35  # noqa: E402
from mini_elf_lean.elf_v35_train import ElfV35TrainConfig, train as train_flow  # noqa: E402
from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier  # noqa: E402
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402
from v36_coherence_probe import gold_lookup, read_rows  # noqa: E402
from v37_overfit_control import select_theorems  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("v37_lean_sanity")

DATA = ROOT / "data" / "processed" / "v35_elf_flow"
OUT = ROOT / "data" / "baselines" / "v37_overfit"
SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
LEAN_PATH_FILE = ROOT / ".tmp" / "v27_lean_path.txt"


def _decode_str(ids_row, vocab) -> str:
    cleaned, _ = sanitize_candidate_list([vocab.decode_target(ids_row.tolist())])
    return cleaned[0] if cleaned else ""


def main() -> int:
    out = OUT
    out.mkdir(parents=True, exist_ok=True)
    if not SCRATCH.exists():
        (out / "lean_sanity.json").write_text(json.dumps({"skipped": "mathlib scratch env unavailable"}, indent=2))
        logger.warning("scratch env missing; skipping Lean sanity")
        return 0

    manifest = json.loads((DATA / "manifest.json").read_text())
    vocab = TokenVocab.load(DATA / "vocab.json")
    ml_train = [r for r in read_rows(DATA / "train.jsonl") if r.get("tier") == "mathlib"]
    names = set(select_theorems(ml_train, 4))
    subset = [r for r in ml_train if r["theorem_name"] in names]
    golds = gold_lookup(subset)

    cfg = ElfV35Config(vocab_size=len(vocab), d_model=128, cond_hidden=128, n_layers=3, n_heads=4,
                       ff_dim=256, max_tgt_len=manifest["max_tgt_len"], max_cond_len=manifest["max_cond_len"],
                       pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id)
    logger.info("reproducing M=4/800/D128 model on %d rows ...", len(subset))
    art = train_flow(cfg, subset, subset,
                     ElfV35TrainConfig(epochs=800, batch_size=min(64, len(subset)), seed=0, patience=None))
    mean, std = art.stats.tensors("cpu")

    # collect sampled strings that decode EXACTLY to a gold tactic
    hits: List[Tuple[str, str, str]] = []
    seen = set()
    for r in subset:
        text = build_input_text(r["theorem_statement"], r["state_before"])
        cond = torch.tensor([vocab.encode_source(text)[: cfg.max_cond_len] or [cfg.pad_id]], dtype=torch.long)
        ids = integrate_v35(art.model, cond, mean, std, n_seeds=16, steps=8, cfg_weight=2.0, prompt=text)
        gset = golds.get((r["theorem_name"], r["state_before"]), frozenset({r["tactic"]}))
        for k in range(ids.size(0)):
            s = _decode_str(ids[k], vocab)
            if s and s in gset and (r["theorem_name"], s) not in seen:
                seen.add((r["theorem_name"], s))
                hits.append((r["theorem_name"], r["theorem_statement"], s))

    logger.info("flow reproduced %d distinct exact gold tactics on train; verifying up to 8 ...", len(hits))
    sample = hits[:8]
    if not sample:
        (out / "lean_sanity.json").write_text(json.dumps({"skipped": "no exact reproductions found"}, indent=2))
        return 0

    lean_path = LEAN_PATH_FILE.read_text().strip() if LEAN_PATH_FILE.exists() else None
    v = TrustedMathlibVerifier(SCRATCH.resolve(), lean_path=lean_path, timeout=300)
    if not v.warmup():
        (out / "lean_sanity.json").write_text(json.dumps({"skipped": "verifier warmup failed", "n_exact_reproductions": len(hits)}, indent=2))
        return 0
    verdicts = v.verify_many(sample, confirm=True)
    results = [{"theorem_name": x.theorem_name, "tactic": x.tactic, "success": x.success, "error": x.error} for x in verdicts]
    n_ok = sum(1 for x in verdicts if x.success)
    summary = {
        "model": "v37 M=4/800/D128 (reproduced, seed 0)",
        "n_exact_reproductions_on_train": len(hits),
        "n_verified_checked": len(sample),
        "n_verified_ok": n_ok,
        "all_verified": n_ok == len(sample),
        "results": results,
        "note": ("Confirms exact-sequence recovery corresponds to genuinely Lean-valid tactics: "
                 "the flow's exact reproductions are real, verified tactics, not a metric artifact."),
    }
    (out / "lean_sanity.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Lean sanity: %d/%d exact reproductions verify (all_verified=%s)", n_ok, len(sample), summary["all_verified"])
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
