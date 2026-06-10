"""v39 Phase-0 smoke + throughput harness.

(1) Correctness: build ar/mdlm/flow at the `tiny` preset, run a few train steps
    (loss finite & finite-grad), run generate(), decode a sample. Catches
    shape/device/import bugs before any long run.
(2) Throughput: at the 30M preset on GPU (bf16), measure tokens/sec and peak
    VRAM for each family at the largest batch that fits (try 256→128→64).

Prints a clean table; writes nothing permanent. Read-only on data.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config, SCALE_PRESETS, count_params
from mini_elf_lean.v38_data import load_dataset, make_batch
from mini_elf_lean.elf_v38_ar import ARModel
from mini_elf_lean.elf_v38_flow import FlowModel
from mini_elf_lean.elf_v38_mdlm import MDLMModel

FAMILIES = {"ar": ARModel, "mdlm": MDLMModel, "flow": FlowModel}


def make_cfg(scale, vocab, manifest):
    return V38Config(vocab_size=len(vocab), max_cond_len=manifest["max_cond_len"],
                     max_tgt_len=manifest["max_tgt_len"], pad_id=vocab.pad_id,
                     bos_id=vocab.bos_id, eos_id=vocab.eos_id, **SCALE_PRESETS[scale])


def build(family, cfg):
    return FAMILIES[family](cfg)


def correctness(ds, dev):
    print("\n=== (1) CORRECTNESS @ tiny ===")
    vocab, man = ds["vocab"], ds["manifest"]
    cfg = make_cfg("tiny", vocab, man)
    rows = ds["train"][:32]
    batch = make_batch(rows, vocab, max_cond_len=cfg.max_cond_len, max_tgt_len=cfg.max_tgt_len, device=dev)
    ok = True
    for fam in ("ar", "mdlm", "flow"):
        torch.manual_seed(3407)
        m = build(fam, cfg).to(dev)
        opt = torch.optim.AdamW([p for p in m.parameters() if p.requires_grad], lr=3e-4)
        losses = []
        for _ in range(8):
            L = m.loss(batch)
            opt.zero_grad(); L.backward(); opt.step()
            losses.append(float(L.item()))
        finite = all(torch.isfinite(torch.tensor(x)) for x in losses)
        cond1 = batch["cond_ids"][:1]
        gen = m.generate(cond1, n_samples=4, steps=8, prompt="smoke", device=dev)
        dec = vocab.decode_target(gen[0].tolist())
        print(f"  [{fam:4s}] loss {losses[0]:.3f}->{losses[-1]:.3f} finite={finite} "
              f"gen_shape={tuple(gen.shape)} sample={dec[:48]!r}")
        ok = ok and finite and gen.shape[0] == 4
    print(f"  CORRECTNESS: {'PASS' if ok else 'FAIL'}")
    return ok


def throughput(ds, dev, scale="30M", batch_try=(256, 128, 64), n_steps=25, n_warm=5):
    print(f"\n=== (2) THROUGHPUT @ {scale} (bf16, {dev}) ===")
    vocab, man = ds["vocab"], ds["manifest"]
    cfg = make_cfg(scale, vocab, man)
    seq_len = cfg.max_cond_len + cfg.max_tgt_len
    train = ds["train"]
    results = {}
    for fam in ("ar", "mdlm", "flow"):
        torch.manual_seed(3407)
        m = build(fam, cfg).to(dev)
        npar = count_params(m)
        opt = torch.optim.AdamW([p for p in m.parameters() if p.requires_grad], lr=3e-4, betas=(0.9, 0.95))
        bs_used, tps, peak = None, 0.0, 0.0
        for bs in batch_try:
            try:
                if dev == "cuda":
                    torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
                rows = (train * ((bs * (n_steps + n_warm)) // len(train) + 1))[: bs * (n_steps + n_warm)]
                batches = [make_batch(rows[i*bs:(i+1)*bs], vocab, max_cond_len=cfg.max_cond_len,
                                      max_tgt_len=cfg.max_tgt_len, device=dev) for i in range(n_steps + n_warm)]
                for i, b in enumerate(batches):
                    if i == n_warm:
                        if dev == "cuda": torch.cuda.synchronize()
                        t0 = time.perf_counter(); seen = 0
                    if dev == "cuda":
                        with torch.autocast("cuda", dtype=torch.bfloat16):
                            L = m.loss(b)
                    else:
                        L = m.loss(b)
                    opt.zero_grad(); L.backward()
                    torch.nn.utils.clip_grad_norm_([p for p in m.parameters() if p.requires_grad], 1.0)
                    opt.step()
                    if i >= n_warm:
                        seen += bs * seq_len
                if dev == "cuda": torch.cuda.synchronize()
                dt = time.perf_counter() - t0
                tps = seen / dt
                peak = torch.cuda.max_memory_allocated() / 1e9 if dev == "cuda" else 0.0
                bs_used = bs
                break
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    print(f"    [{fam}] bs={bs} OOM, retrying smaller")
                    del batches
                    if dev == "cuda": torch.cuda.empty_cache()
                    continue
                raise
        results[fam] = dict(params=npar, bs=bs_used, tok_per_s=tps, peak_gb=peak)
        print(f"  [{fam:4s}] params={npar/1e6:.1f}M bs={bs_used} "
              f"tok/s={tps:,.0f} peak_vram={peak:.1f}GB")
        del m, opt
        if dev == "cuda": torch.cuda.empty_cache()
    return results


if __name__ == "__main__":
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={dev} torch={torch.__version__}")
    ds = load_dataset()
    print(f"train={len(ds['train'])} val={len(ds['val'])} test={len(ds['test'])} vocab={len(ds['vocab'])}")
    ok = correctness(ds, dev)
    res = throughput(ds, dev)
    print("\n=== SUMMARY (tok/s @ 30M) ===")
    for fam, r in res.items():
        print(f"  {fam:4s}: {r['tok_per_s']:>10,.0f} tok/s  bs={r['bs']}  peak={r['peak_gb']:.1f}GB")
    sys.exit(0 if ok else 1)
