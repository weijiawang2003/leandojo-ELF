"""Mini-ELF v40 — Phase 3 decode-time coherence mechanisms on the whole-proof flow.

Reuses the Phase-2 flow checkpoint (zero retraining). Two samplers:
  H7 block/semi-AR: generate target in n_blocks; block b predicted from cond + the
     already-snapped (clean) prefix blocks, future blocks masked out (key-padding).
     NFE = n_blocks * steps_per_block.
  H8 snap-repair: 1-step predict -> snap -> re-embed -> re-noise to t -> 1-step
     re-predict, R rounds. NFE = 1 + R.
Metric = dev exact-seq (full 614-row dev set, K samples). Criteria:
  H7: best (NFE<=8) >= 1.5 x FLOW@1.   H8: best > FLOW@1 by >=10% rel.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from mini_elf_lean.v38_data import cond_ids_for, gold_lookup
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list
from v39_train import build_model


def _ctx(model, cond_ids, K, device):
    cfg = model.cfg
    cond = cond_ids.expand(K, -1).to(device)
    cond_pad = cond == cfg.pad_id
    cond_in = model._std(model.trunk.embed_tokens(cond))
    return cfg, cond_in, cond_pad


@torch.no_grad()
def flow_plain(model, cond_ids, *, steps, cfg_weight, K, device, seed=0, prompt=""):
    cfg, cond_in, cond_pad = _ctx(model, cond_ids, K, device)
    Sc, Tt = cfg.max_cond_len, cfg.max_tgt_len
    kpm_c = torch.cat([cond_pad, torch.zeros(K, Tt, dtype=torch.bool, device=device)], 1)
    kpm_u = torch.cat([torch.ones(K, Sc, dtype=torch.bool, device=device),
                       torch.zeros(K, Tt, dtype=torch.bool, device=device)], 1)
    g = torch.Generator(device=device); g.manual_seed((seed ^ zlib.crc32(prompt.encode())) & 0x7FFFFFFF)
    z = torch.randn(K, Tt, cfg.d_model, generator=g, device=device) * model.noise_scale
    sc = torch.zeros_like(z); use_cfg = abs(cfg_weight - 1) > 1e-9; x_hat = z
    for i in range(max(steps, 1)):
        tv = i / max(steps, 1); t = torch.full((K,), tv, device=device)
        xc = model._core(cond_in, z, sc, t, kpm_c)
        if use_cfg:
            xu = model._core(cond_in, z, sc, t, kpm_u); x_hat = xu + cfg_weight * (xc - xu)
        else:
            x_hat = xc
        v = (x_hat - z) / max(1 - tv, 1e-3); sc = x_hat
        z = z + (1.0 / max(steps, 1)) * v
    return model.trunk.readout_ids(model._unstd(x_hat))


@torch.no_grad()
def flow_block(model, cond_ids, *, n_blocks, steps_per_block, cfg_weight, K, device, seed=0, prompt=""):
    cfg, cond_in, cond_pad = _ctx(model, cond_ids, K, device)
    Sc, Tt = cfg.max_cond_len, cfg.max_tgt_len
    g = torch.Generator(device=device); g.manual_seed((seed ^ zlib.crc32(prompt.encode())) & 0x7FFFFFFF)
    z = torch.randn(K, Tt, cfg.d_model, generator=g, device=device) * model.noise_scale
    ids = torch.full((K, Tt), cfg.pad_id, dtype=torch.long, device=device)
    edges = [round(i * Tt / n_blocks) for i in range(n_blocks + 1)]
    use_cfg = abs(cfg_weight - 1) > 1e-9
    for bi in range(n_blocks):
        lo, hi = edges[bi], edges[bi + 1]
        if hi <= lo:
            continue
        # mask future-block target positions (>= hi) so block bi sees only cond + clean prefix + itself
        fut = torch.zeros(K, Tt, dtype=torch.bool, device=device); fut[:, hi:] = True
        kpm = torch.cat([cond_pad, fut], 1)
        sc = torch.zeros_like(z); x_hat = z
        for s in range(max(steps_per_block, 1)):
            tv = s / max(steps_per_block, 1); t = torch.full((K,), tv, device=device)
            x_hat = model._core(cond_in, z, sc, t, kpm)
            if use_cfg:
                kpm_u = kpm.clone(); kpm_u[:, :Sc] = True
                xu = model._core(cond_in, z, sc, t, kpm_u); x_hat = xu + cfg_weight * (x_hat - xu)
            v = (x_hat - z) / max(1 - tv, 1e-3); sc = x_hat
            z[:, lo:hi, :] = z[:, lo:hi, :] + (1.0 / max(steps_per_block, 1)) * v[:, lo:hi, :]
        blk = model.trunk.readout_ids(model._unstd(x_hat[:, lo:hi, :]))
        ids[:, lo:hi] = blk
        z[:, lo:hi, :] = model._std(model.trunk.embed_tokens(blk))   # fix snapped block as clean
    return ids


@torch.no_grad()
def flow_snap_repair(model, cond_ids, *, R, t_renoise, cfg_weight, K, device, seed=0, prompt=""):
    cfg, cond_in, cond_pad = _ctx(model, cond_ids, K, device)
    Sc, Tt = cfg.max_cond_len, cfg.max_tgt_len
    kpm_c = torch.cat([cond_pad, torch.zeros(K, Tt, dtype=torch.bool, device=device)], 1)
    g = torch.Generator(device=device); g.manual_seed((seed ^ zlib.crc32(prompt.encode())) & 0x7FFFFFFF)
    z = torch.randn(K, Tt, cfg.d_model, generator=g, device=device) * model.noise_scale
    sc = torch.zeros_like(z); t0 = torch.zeros(K, device=device)
    x_hat = model._core(cond_in, z, sc, t0, kpm_c)
    ids = model.trunk.readout_ids(model._unstd(x_hat))
    for _ in range(R):
        z1 = model._std(model.trunk.embed_tokens(ids))
        noise = torch.randn(K, Tt, cfg.d_model, generator=g, device=device) * model.noise_scale
        z_t = (1 - t_renoise) * noise + t_renoise * z1
        t = torch.full((K,), t_renoise, device=device)
        x_hat = model._core(cond_in, z_t, sc, t, kpm_c)
        ids = model.trunk.readout_ids(model._unstd(x_hat))
    return ids


def _san(s):
    cl, _ = sanitize_candidate_list([s]); return cl[0] if cl else ""


@torch.no_grad()
def exact_seq(model, sampler, dev_rows, vocab, cfg, golds, device, *, n_dev, K):
    Tt = cfg.max_tgt_len
    exact = n = 0; per = []
    for r in dev_rows[:n_dev]:
        cond = cond_ids_for(r, vocab, max_cond_len=cfg.max_cond_len, device=device)
        ids = sampler(model, cond, K=K, device=device, prompt=r["theorem_name"])
        gold = (list(r["tgt_ids"])[:Tt] + [cfg.pad_id] * Tt)[:Tt]
        gpos = [i for i in range(Tt) if gold[i] != cfg.pad_id]
        gset = golds.get((r["theorem_name"], r["state_before"]), frozenset({r["tactic"]}))
        if gpos:
            per.append(sum(sum(1 for i in gpos if int(ids[k][i]) == gold[i]) / len(gpos) for k in range(ids.size(0))) / ids.size(0))
        for k in range(ids.size(0)):
            if _san(vocab.decode_target(ids[k].tolist())) in gset:
                exact += 1
            n += 1
    return exact / max(n, 1), (sum(per) / len(per) if per else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=str(ROOT / "outputs/v40/wholeproof/snapshots/scale_flow_30M_U45820.pt"))
    ap.add_argument("--corpus-dir", default=str(ROOT / "data/v40/corpora/wholeproof"))
    ap.add_argument("--n-dev", type=int, default=614)
    ap.add_argument("--K", type=int, default=4)
    ap.add_argument("--cfg-weight", type=float, default=2.0)
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    cdir = Path(args.corpus_dir)
    vocab = TokenVocab.load(cdir / "vocab.json")
    dev_rows = [json.loads(l) for l in (cdir / "dev.jsonl").read_text().splitlines() if l.strip()]
    train_rows = [json.loads(l) for l in (cdir / "train.jsonl").read_text().splitlines() if l.strip()]
    golds = gold_lookup(train_rows + dev_rows)
    snap = torch.load(args.snapshot, map_location="cpu", weights_only=False)
    cfg = V38Config.from_dict(snap["cfg"])
    model = build_model("flow", cfg, **(snap.get("family_kw") or {})).to(dev)
    model.load_state_dict({k: v.to(dev) for k, v in snap["state_dict"].items()}); model.eval()
    cw = args.cfg_weight

    rows = []
    # baseline FLOW@1
    base_ex, base_pt = exact_seq(model, lambda m, c, **kw: flow_plain(m, c, steps=1, cfg_weight=cw, **kw),
                                 dev_rows, vocab, cfg, golds, dev, n_dev=args.n_dev, K=args.K)
    rows.append({"name": "FLOW@1", "kind": "baseline", "nfe": 1, "dev_exact": base_ex, "dev_pertok": base_pt})
    print(f"FLOW@1 baseline: dev_exact={base_ex:.4f} pertok={base_pt:.4f}")

    # H7 block decode
    h7 = []
    for nb in (4, 8):
        for spb in (1, 2):
            nfe = nb * spb
            ex, pt = exact_seq(model, lambda m, c, _nb=nb, _spb=spb, **kw: flow_block(m, c, n_blocks=_nb, steps_per_block=_spb, cfg_weight=cw, **kw),
                               dev_rows, vocab, cfg, golds, dev, n_dev=args.n_dev, K=args.K)
            r = {"name": f"block_nb{nb}_spb{spb}", "kind": "H7", "nfe": nfe, "dev_exact": ex, "dev_pertok": pt}
            rows.append(r); h7.append(r); print(f"  H7 {r['name']} NFE={nfe} dev_exact={ex:.4f} pertok={pt:.4f}")
    # H8 snap-repair
    h8 = []
    for R in (1, 2, 3):
        for tr in (0.2, 0.4):
            nfe = 1 + R
            ex, pt = exact_seq(model, lambda m, c, _R=R, _tr=tr, **kw: flow_snap_repair(m, c, R=_R, t_renoise=_tr, cfg_weight=cw, **kw),
                               dev_rows, vocab, cfg, golds, dev, n_dev=args.n_dev, K=args.K)
            r = {"name": f"snaprepair_R{R}_t{tr}", "kind": "H8", "nfe": nfe, "dev_exact": ex, "dev_pertok": pt}
            rows.append(r); h8.append(r); print(f"  H8 {r['name']} NFE={nfe} dev_exact={ex:.4f} pertok={pt:.4f}")

    best_h7 = max((r for r in h7 if r["nfe"] <= 8), key=lambda r: r["dev_exact"], default=None)
    best_h8 = max(h8, key=lambda r: r["dev_exact"], default=None)
    h7_ok = best_h7 and base_ex > 0 and best_h7["dev_exact"] >= 1.5 * base_ex
    h8_ok = best_h8 and base_ex > 0 and best_h8["dev_exact"] >= 1.10 * base_ex
    verdict = {
        "FLOW@1_dev_exact": base_ex,
        "H7_best_nfe<=8": best_h7, "H7_criterion": ">=1.5x FLOW@1", "H7_verdict": "SUPPORTED" if h7_ok else "REFUTED",
        "H8_best": best_h8, "H8_criterion": ">=1.10x FLOW@1", "H8_verdict": "SUPPORTED" if h8_ok else "REFUTED",
    }
    out = ROOT / "outputs/v40/coherence.json"
    out.write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=2))
    print("\nVERDICT:", json.dumps(verdict, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
