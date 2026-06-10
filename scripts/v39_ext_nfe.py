"""Mini-ELF v39 — E1: sampling-compute frontier (H4).

Headline FLOW snapshot: sweep ODE steps in {1,2,4,8,16,32} x CFG in {1,1.5,2};
metric = dev exact-seq (+ per-token, distinct) for all cells. Quantifies ELF's
few-step selling point on tactics: does flow retain >=90% of its 32-step quality
at <=8 steps? Overlay AR's "NFE" (~= mean generated tactic length, since AR costs
one forward per token). Plot quality vs NFE.

Reuses v39_train.dev_metrics on the Track-A v35 dev (val) split. Cheap (no Lean).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.v38_data import load_dataset, gold_lookup, cond_ids_for
from v39_train import dev_metrics, build_model

OUT = ROOT / "outputs" / "v39"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default="trackA")
    ap.add_argument("--flow-snap", default="headline_flow_30M_U3689")
    ap.add_argument("--ar-snap", default="headline_ar_30M_U3689")
    ap.add_argument("--steps", default="1,2,4,8,16,32")
    ap.add_argument("--cfgs", default="1.0,1.5,2.0")
    ap.add_argument("--dev-n", type=int, default=160)
    ap.add_argument("--K", type=int, default=8)
    args = ap.parse_args(argv)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    ds = load_dataset()
    vocab, man = ds["vocab"], ds["manifest"]
    dev_rows = ds["val"]
    golds = gold_lookup(ds["train"] + ds["val"] + ds["test"])

    snap_dir = OUT / args.run / "snapshots"
    fsnap = torch.load(snap_dir / f"{args.flow_snap}.pt", map_location="cpu", weights_only=False)
    cfg = V38Config.from_dict(fsnap["cfg"])
    flow = build_model("flow", cfg, **(fsnap.get("family_kw") or {})).to(dev)
    flow.load_state_dict({k: v.to(dev) for k, v in fsnap["state_dict"].items()})

    steps_list = [int(x) for x in args.steps.split(",")]
    cfg_list = [float(x) for x in args.cfgs.split(",")]
    rows = []
    print(f"{'steps':>6}{'cfg':>6}{'exact':>9}{'pertok':>9}{'distinct':>10}")
    for s in steps_list:
        for cw in cfg_list:
            m = dev_metrics(flow, dev_rows, vocab, cfg, golds, dev,
                            n_dev=args.dev_n, K=args.K, steps=s,
                            gen_kw={"cfg_weight": cw, "self_cond": True})
            rec = {"steps": s, "cfg": cw, **m, "nfe": s}
            rows.append(rec)
            print(f"{s:>6}{cw:>6}{m['dev_exact_seq']:>9}{m['dev_per_token']:>9}{m['dev_distinct_mean']:>10}")

    # AR "NFE" = mean generated tactic length (forward passes per sample)
    ar_nfe = None
    arp = snap_dir / f"{args.ar_snap}.pt"
    if arp.exists():
        asnap = torch.load(arp, map_location="cpu", weights_only=False)
        acfg = V38Config.from_dict(asnap["cfg"])
        ar = build_model("ar", acfg, **(asnap.get("family_kw") or {})).to(dev)
        ar.load_state_dict({k: v.to(dev) for k, v in asnap["state_dict"].items()})
        lens = []
        for r in dev_rows[:args.dev_n]:
            cond = cond_ids_for(r, vocab, max_cond_len=acfg.max_cond_len, device=dev)
            ids = ar.generate(cond, n_samples=args.K, steps=0, prompt=r["theorem_name"], device=dev)
            for k in range(ids.size(0)):
                seq = ids[k].tolist()
                L = next((i for i, t in enumerate(seq) if t == acfg.eos_id), len(seq))
                lens.append(max(L, 1))
        ar_nfe = sum(lens) / max(len(lens), 1)
        am = dev_metrics(ar, dev_rows, vocab, cfg, golds, dev, n_dev=args.dev_n, K=args.K, steps=0, gen_kw={})
        print(f"AR: mean NFE(tactic len)~{ar_nfe:.1f}  dev_exact={am['dev_exact_seq']}")

    # retention: best-cfg exact at each step vs at 32
    best_by_step = {}
    for s in steps_list:
        best_by_step[s] = max(r["dev_exact_seq"] for r in rows if r["steps"] == s)
    base = best_by_step.get(32, max(best_by_step.values()))
    retention = {s: (best_by_step[s] / base if base > 0 else 0.0) for s in steps_list}
    print("\nbest-cfg exact by steps:", {s: round(v, 4) for s, v in best_by_step.items()})
    print("retention vs 32-step:", {s: round(v, 3) for s, v in retention.items()})
    r8 = retention.get(8, 0.0)
    print(f"H4 (>=90% of 32-step quality at <=8 steps): {'SUPPORTED' if r8 >= 0.9 else 'REFUTED'} (8-step retention={r8:.3f})")

    out = OUT / args.run / "ext_nfe.json"
    out.write_text(json.dumps({"flow_sweep": rows, "ar_nfe": ar_nfe,
                               "best_by_step": best_by_step, "retention": retention}, indent=2))
    # plot quality vs NFE
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for cw in cfg_list:
        xs = [r["steps"] for r in rows if r["cfg"] == cw]
        ys = [r["dev_exact_seq"] for r in rows if r["cfg"] == cw]
        ax.plot(xs, ys, marker="o", label=f"flow cfg={cw}")
    if ar_nfe:
        ax.axvline(ar_nfe, color="k", ls="--", alpha=0.5, label=f"AR NFE~{ar_nfe:.0f}")
    ax.set_xscale("log"); ax.set_xlabel("NFE (ODE steps, log)"); ax.set_ylabel("dev exact-seq")
    ax.set_title("v39 E1 — flow quality vs sampling compute (H4)"); ax.legend(); ax.grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(OUT / args.run / "ext_nfe.png", dpi=130)
    print(f"wrote {out} and ext_nfe.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
