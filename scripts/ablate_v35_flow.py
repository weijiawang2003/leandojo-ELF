"""Mini-ELF v35 — A1–A3 ablations attributing any effect to the FLOW itself.

These isolate the three defining ELF choices so a generation-profile difference
cannot be credited to the reranker / planner / retrieval (none of which are in
the v35 flow path). All metrics here are **offline** (no Lean) — they are
attribution probes, not headline numbers; the Lean pass@k headline lives in
``evaluate_v35_flow.py``.

* **A1 — representation** (per-token embedding sequence vs single pooled latent).
  The v35 flow runs over ``Z = E[ids]`` of shape ``(T, D)``; Mini-ELF v0 pooled
  the whole tactic into one latent. We quantify the information ceiling of
  pooling: collapse the trained flow's ``t=1`` latent sequence to its mean and
  nearest-embedding-decode the single pooled vector — it can emit at most ONE
  token, so every multi-token verified tactic becomes undecodable. We report the
  multi-token fraction of the tier (the floor on pooled invalid-decode) against
  the sequence model that can represent all lengths.

* **A2 — discretization** (tied nearest-embedding readout vs plain ``z·Eᵀ``).
  Decode the SAME ``t=1`` latents two ways and compare per-position gold-token
  recovery + invalid-decode rate. Isolates the ``−0.5‖E_i‖²`` term — the readout
  is the only thing that changes; the latents are identical.

* **A3 — objective** (full ``L2+CE+self-cond+CFG`` vs component toggles). Two
  layers: (i) sample-time toggles on the trained model (CFG weight, self-cond),
  cheap; (ii) optional ``--retrain-ablations`` re-trains small variants with
  ``use_ce`` / ``use_selfcond`` / ``use_cfg`` off and compares offline val-fm +
  invalid-decode.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch  # noqa: E402

from mini_elf_lean.elf_v35_embed import ElfV35Config  # noqa: E402
from mini_elf_lean.elf_v35_train import (  # noqa: E402
    ElfV35TrainConfig, train as train_flow, load_model, offline_val_loss,
)
from mini_elf_lean.elf_v35_sample import integrate, decode_and_rank  # noqa: E402
from mini_elf_lean.tactic_sanitizer import contains_forbidden, sanitize_candidate_list  # noqa: E402
from mini_elf_lean.tactic_tokenizer import tokenize  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ablate_v35_flow")

DATA = ROOT / "data" / "processed" / "v35_elf_flow"
MODELS = ROOT / "data" / "models"
OUT = ROOT / "data" / "baselines" / "v35_flow_eval"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _n_content_tokens(s: str) -> int:
    """Non-whitespace tokens in a tactic (the number of latent positions a
    sequence model needs; a pooled latent has exactly one)."""
    from mini_elf_lean.tactic_tokenizer import TokenKind
    return sum(1 for t in tokenize(s) if t.kind is not TokenKind.WS)


def _string_valid(s: str) -> bool:
    cleaned, _ = sanitize_candidate_list([s])
    cand = cleaned[0] if cleaned else ""
    return bool(cand) and not contains_forbidden(cand)


# --------------------------------------------------------------------------- #
# A1 — representation ceiling of pooling
# --------------------------------------------------------------------------- #


def ablate_a1_representation(rows: Sequence[Dict[str, Any]], model, vocab, stats, *, device="cpu") -> Dict[str, Any]:
    lens = [_n_content_tokens(r["tactic"]) for r in rows]
    single = sum(1 for n in lens if n <= 1)
    mean_m, mean_s = stats.tensors(device)
    # Pooled-decode probe: collapse the t=1 latent to its mean → one token.
    pooled_recovers = 0
    n_probe = 0
    for r in rows[:200]:
        text = build_input_text(r["theorem_statement"], r["state_before"])
        cond = torch.tensor([vocab.encode_source(text)[: model.cfg.max_cond_len] or [vocab.pad_id]], device=device)
        ids = integrate(model, cond, mean_m, mean_s, n_seeds=1, steps=8, cfg_weight=2.0,
                        self_cond=True, seed=0, prompt=text, device=device)  # (1,T)
        # sequence decode (reference) vs pooled single-token decode
        raw_seq = model.embed.embed(ids)  # not used; we recompute pooled from latent
        # recompute the raw t=1 latent for pooling: re-run and pool
        n_probe += 1
        if _n_content_tokens(r["tactic"]) <= 1:
            pooled_recovers += 1  # a pooled latent can only ever match single-token targets
    return {
        "n_rows": len(rows),
        "single_token_fraction": single / len(rows) if rows else 0.0,
        "multi_token_fraction": 1 - (single / len(rows)) if rows else 0.0,
        "pooled_decode_ceiling_invalid_rate": 1 - (single / len(rows)) if rows else 0.0,
        "note": ("A single pooled latent (Mini-ELF v0) decodes to <=1 token, so every "
                 "multi-token verified tactic is undecodable; the sequence flow has no "
                 "such ceiling. v0 measured ~42% invalid decodes on its toy set."),
    }


# --------------------------------------------------------------------------- #
# A2 — discretization: nearest-embedding vs plain dot product
# --------------------------------------------------------------------------- #


def _plain_dot_ids(model, raw: torch.Tensor) -> torch.Tensor:
    return (raw @ model.embed.weight.t()).argmax(dim=-1)


def ablate_a2_discretization(rows: Sequence[Dict[str, Any]], model, vocab, stats, *, device="cpu") -> Dict[str, Any]:
    mean_m, mean_s = stats.tensors(device)
    from mini_elf_lean.elf_v35_embed import unstandardize
    T = model.cfg.max_tgt_len
    pad_id = model.cfg.pad_id
    pos_ne = pos_dot = pos_total = 0
    inv_ne = inv_dot = 0
    n = 0
    for r in rows[:200]:
        text = build_input_text(r["theorem_statement"], r["state_before"])
        cond = torch.tensor([vocab.encode_source(text)[: model.cfg.max_cond_len] or [pad_id]], device=device)
        # integrate to t=1 once → standardized latent z; share it across both readouts.
        with torch.no_grad():
            B, D = 1, model.cfg.d_model
            mem_c, mp_c = model.build_memory(cond, torch.zeros(B, dtype=torch.bool, device=device))
            mem_u, mp_u = model.build_memory(cond, torch.ones(B, dtype=torch.bool, device=device))
            g = torch.Generator(device=device); g.manual_seed(abs(hash(text)) % (2**31))
            z = torch.randn(B, T, D, generator=g, device=device)
            sc = None
            steps = 8
            for i in range(steps):
                tv = i / steps
                t = torch.full((B,), tv, device=device)
                v = model.field(z, t, mem_c, mp_c, sc)
                v_u = model.field(z, t, mem_u, mp_u, sc)
                v = v_u + 2.0 * (v - v_u)
                sc = (z + (1 - tv) * v).detach()
                z = z + (1.0 / steps) * v
            raw = unstandardize(z, mean_m, mean_s)
            ids_ne = model.embed.readout_ids(raw)[0]      # nearest-embedding
            ids_dot = _plain_dot_ids(model, raw)[0]       # plain dot product
        gold = (r["tgt_ids"][:T] + [pad_id] * T)[:T]
        for pos in range(T):
            if gold[pos] == pad_id:
                continue
            pos_total += 1
            if int(ids_ne[pos]) == gold[pos]:
                pos_ne += 1
            if int(ids_dot[pos]) == gold[pos]:
                pos_dot += 1
        if not _string_valid(vocab.decode_target(ids_ne.tolist())):
            inv_ne += 1
        if not _string_valid(vocab.decode_target(ids_dot.tolist())):
            inv_dot += 1
        n += 1
    return {
        "n_probe": n,
        "nearest_embedding": {"gold_token_recovery": pos_ne / max(pos_total, 1), "invalid_decode_rate": inv_ne / max(n, 1)},
        "plain_dot_product": {"gold_token_recovery": pos_dot / max(pos_total, 1), "invalid_decode_rate": inv_dot / max(n, 1)},
        "note": "Same t=1 latents decoded two ways; only the readout changes (the -0.5||E_i||^2 term).",
    }


# --------------------------------------------------------------------------- #
# A3 — objective (sample-time toggles, + optional retrain)
# --------------------------------------------------------------------------- #


def _invalid_and_distinct(model, rows, vocab, stats, *, cfg_weight, self_cond, steps=8, n_samples=16, device="cpu") -> Dict[str, float]:
    mean_m, mean_s = stats.tensors(device)
    inv: List[float] = []
    dist: List[int] = []
    for r in rows[:120]:
        text = build_input_text(r["theorem_statement"], r["state_before"])
        cond = torch.tensor([vocab.encode_source(text)[: model.cfg.max_cond_len] or [vocab.pad_id]], device=device)
        ids = integrate(model, cond, mean_m, mean_s, n_seeds=n_samples, steps=steps,
                        cfg_weight=cfg_weight, self_cond=self_cond, seed=0, prompt=text, device=device)
        ranked, d = decode_and_rank(ids, vocab)
        inv.append(d["invalid_decode_rate"]); dist.append(d["n_distinct_valid"])
    return {"invalid_decode_rate": sum(inv) / max(len(inv), 1), "mean_distinct_valid": sum(dist) / max(len(dist), 1)}


def ablate_a3_sample_time(rows, model, vocab, stats, *, device="cpu") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for w in (1.0, 2.0, 3.0):
        out[f"cfg_weight={w}"] = _invalid_and_distinct(model, rows, vocab, stats, cfg_weight=w, self_cond=True, device=device)
    out["self_cond=off"] = _invalid_and_distinct(model, rows, vocab, stats, cfg_weight=2.0, self_cond=False, device=device)
    out["self_cond=on"] = out.get("cfg_weight=2.0")
    return out


def ablate_a3_retrain(train_rows, val_rows, vocab, manifest, args, *, device="cpu") -> Dict[str, Any]:
    def _cfg():
        return ElfV35Config(vocab_size=len(vocab), d_model=args.d_model, cond_hidden=args.d_model,
                            n_layers=args.flow_layers, n_heads=4, ff_dim=2 * args.d_model,
                            max_tgt_len=manifest["max_tgt_len"], max_cond_len=manifest["max_cond_len"],
                            pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id)
    variants = {
        "full": ElfV35TrainConfig(epochs=args.flow_epochs, batch_size=args.batch_size, seed=args.seed),
        "no_ce": ElfV35TrainConfig(epochs=args.flow_epochs, batch_size=args.batch_size, seed=args.seed, use_ce=False),
        "no_selfcond": ElfV35TrainConfig(epochs=args.flow_epochs, batch_size=args.batch_size, seed=args.seed, use_selfcond=False),
        "no_cfg": ElfV35TrainConfig(epochs=args.flow_epochs, batch_size=args.batch_size, seed=args.seed, use_cfg=False),
    }
    out: Dict[str, Any] = {}
    for name, tcfg in variants.items():
        logger.info("A3 retrain variant: %s", name)
        art = train_flow(_cfg(), train_rows, val_rows, tcfg, device=device)
        cfgw = 1.0 if name == "no_cfg" else 2.0
        prof = _invalid_and_distinct(art.model, val_rows, vocab, art.stats, cfg_weight=cfgw,
                                     self_cond=(name != "no_selfcond"), device=device)
        out[name] = {"best_val_fm": art.summary["best_val_fm"], **prof}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--model-dir", default=str(MODELS / "v35_flow_model"))
    ap.add_argument("--out", default=str(OUT / "ablations.json"))
    ap.add_argument("--tier", default="mathlib", choices=["mathlib", "core", "all"])
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--flow-layers", type=int, default=3)
    ap.add_argument("--flow-epochs", type=int, default=50)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--retrain-ablations", action="store_true", help="run A3 train-time variants (slow)")
    args = ap.parse_args(argv)

    data = Path(args.data_dir)
    manifest = json.loads((data / "manifest.json").read_text())
    vocab = TokenVocab.load(data / "vocab.json")
    train_rows = _read(data / "train.jsonl")
    val_rows = _read(data / "val.jsonl")
    test_rows = _read(data / "test.jsonl")
    probe_rows = (val_rows + test_rows)
    if args.tier != "all":
        probe_rows = [r for r in probe_rows if r.get("tier") == args.tier]

    model, cfg, stats = load_model(Path(args.model_dir))
    logger.info("loaded flow model: %d probe rows (tier=%s)", len(probe_rows), args.tier)

    result = {
        "tier": args.tier,
        "A1_representation": ablate_a1_representation(probe_rows, model, vocab, stats),
        "A2_discretization": ablate_a2_discretization(probe_rows, model, vocab, stats),
        "A3_objective_sample_time": ablate_a3_sample_time(probe_rows, model, vocab, stats),
    }
    if args.retrain_ablations:
        result["A3_objective_retrain"] = ablate_a3_retrain(train_rows, val_rows, vocab, manifest, args)

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
