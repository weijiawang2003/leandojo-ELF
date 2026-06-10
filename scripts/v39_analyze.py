"""Mini-ELF v39 — crossover analysis + plots from matrix_metrics.jsonl.

Reads outputs/v39/<run>/matrix_metrics.jsonl, takes each cell's FINAL checkpoint
(frac==1.0), and produces:
  * a per-cell table (val_loss, dev exact-seq, per-token, distinct, completed?)
  * the crossover reading: gap = AR - FLOW (and AR - MDLM) on dev exact-seq at each
    U; H2 supported iff the gap shrinks (or flips) monotonically as U falls.
  * crossover PNG: x = epochs-per-unique-token (log), y = dev exact-seq, 3 lines.
  * training-curves PNG: dev exact-seq vs token-fraction for the largest-U cells.

Pure read/plot; writes only PNGs + an optional markdown table to outputs/v39/<run>/.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "v39"
FAM_COLOR = {"ar": "#1f77b4", "mdlm": "#2ca02c", "flow": "#d62728"}
FAM_MARK = {"ar": "o", "mdlm": "s", "flow": "^"}


def load_metrics(run):
    rows = [json.loads(l) for l in (OUT / run / "matrix_metrics.jsonl").read_text().splitlines() if l.strip()]
    return [r for r in rows if "status" not in r]


def finals(rows, tag=None):
    """Last (highest-step) metric row per cell, optionally filtered by tag."""
    by = {}
    for r in rows:
        if tag and r.get("tag") != tag:
            continue
        c = r["cell"]
        if c not in by or r["step"] > by[c]["step"]:
            by[c] = r
    return by


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default="trackA")
    ap.add_argument("--tag", default="grid", help="which tag defines the crossover grid")
    ap.add_argument("--title", default=None)
    args = ap.parse_args(argv)
    run = args.run
    rows = load_metrics(run)
    fin = finals(rows, tag=args.tag)
    if not fin:
        print(f"no '{args.tag}' cells yet in {run}"); return 0

    # group by (family, U)
    cells = sorted(fin.values(), key=lambda r: (r["family"], r["U"]))
    Us = sorted({r["U"] for r in cells})
    fams = sorted({r["family"] for r in cells})

    print(f"\n=== {run} / {args.tag} — final-checkpoint metrics ===")
    hdr = f"{'family':<6}{'U':>8}{'epochs':>8}{'val':>9}{'exact':>8}{'pertok':>8}{'distinct':>9}{'done':>6}"
    print(hdr)
    table = {}
    for r in cells:
        done = "ok" if r.get("step") == r.get("total_steps") else "INC"
        print(f"{r['family']:<6}{r['U']:>8}{r.get('epochs',0):>8}{r['val_loss']:>9}"
              f"{r['dev_exact_seq']:>8}{r['dev_per_token']:>8}{r['dev_distinct_mean']:>9}{done:>6}")
        table[(r["family"], r["U"])] = r

    # crossover gap analysis
    print(f"\n=== crossover gap (dev exact-seq) ===")
    print(f"{'U':>8}{'AR':>8}{'MDLM':>8}{'FLOW':>8}{'AR-FLOW':>9}{'AR-MDLM':>9}")
    gaps_flow, gaps_mdlm = [], []
    for U in Us:
        ar = table.get(("ar", U), {}).get("dev_exact_seq")
        md = table.get(("mdlm", U), {}).get("dev_exact_seq")
        fl = table.get(("flow", U), {}).get("dev_exact_seq")
        gf = (ar - fl) if (ar is not None and fl is not None) else None
        gm = (ar - md) if (ar is not None and md is not None) else None
        gaps_flow.append((U, gf)); gaps_mdlm.append((U, gm))
        print(f"{U:>8}{ar if ar is not None else float('nan'):>8}"
              f"{md if md is not None else float('nan'):>8}{fl if fl is not None else float('nan'):>8}"
              f"{gf if gf is not None else float('nan'):>9.4f}{gm if gm is not None else float('nan'):>9.4f}"
              if gf is not None and gm is not None else f"{U:>8} (incomplete)")
    # H2: gap shrinks monotonically as U decreases?
    gf_seq = [g for _, g in sorted(gaps_flow) if g is not None]  # sorted by U ascending
    if len(gf_seq) >= 2:
        # as U decreases -> reverse order; check monotone non-increasing of gap as U falls
        falling = list(reversed(gf_seq))  # largest U first ... smallest U last
        mono = all(falling[i] >= falling[i+1] - 1e-9 for i in range(len(falling)-1))
        print(f"\nH2 (AR-FLOW gap shrinks as U falls): {'SUPPORTED' if mono else 'NOT monotonic'} "
              f"| gaps by U-desc: {[round(x,4) for x in falling]}")

    # ---- crossover plot: x = epochs-per-unique-token (log) ----
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for fam in fams:
        pts = sorted([(table[(fam, U)]["epochs"], table[(fam, U)]["dev_exact_seq"], U)
                      for U in Us if (fam, U) in table])
        if not pts:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        axes[0].plot(xs, ys, marker=FAM_MARK.get(fam, "o"), color=FAM_COLOR.get(fam), label=fam.upper())
        # x = U (log) on second panel
        ptsU = sorted([(table[(fam, U)]["U"], table[(fam, U)]["dev_exact_seq"]) for U in Us if (fam, U) in table])
        axes[1].plot([p[0] for p in ptsU], [p[1] for p in ptsU], marker=FAM_MARK.get(fam, "o"),
                     color=FAM_COLOR.get(fam), label=fam.upper())
    axes[0].set_xscale("log"); axes[0].set_xlabel("epochs per unique pair (log)")
    axes[0].set_ylabel("dev exact-seq"); axes[0].set_title("crossover vs epochs/unique-token")
    axes[0].legend(); axes[0].grid(True, alpha=0.3)
    axes[1].set_xscale("log"); axes[1].set_xlabel("U = unique training pairs (log)")
    axes[1].set_ylabel("dev exact-seq"); axes[1].set_title("crossover vs data size")
    axes[1].legend(); axes[1].grid(True, alpha=0.3)
    fig.suptitle(args.title or f"v39 {run} matched-budget crossover (3-way, dev exact-seq)")
    fig.tight_layout()
    p1 = OUT / run / f"crossover_{run}.png"
    fig.savefig(p1, dpi=130); print(f"\nwrote {p1}")

    # ---- training curves at largest U ----
    bigU = max(Us)
    fig2, ax = plt.subplots(figsize=(7, 4.5))
    for fam in fams:
        cell = table.get((fam, bigU))
        if not cell:
            continue
        cur = sorted([r for r in rows if r.get("cell") == cell["cell"]], key=lambda r: r["step"])
        ax.plot([r["frac"] for r in cur], [r["dev_exact_seq"] for r in cur],
                marker=FAM_MARK.get(fam, "o"), color=FAM_COLOR.get(fam), label=f"{fam.upper()} exact")
    ax.set_xlabel("token-budget fraction"); ax.set_ylabel("dev exact-seq")
    ax.set_title(f"v39 {run} training curve @ U={bigU}"); ax.legend(); ax.grid(True, alpha=0.3)
    fig2.tight_layout()
    p2 = OUT / run / f"curves_{run}.png"
    fig2.savefig(p2, dpi=130); print(f"wrote {p2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
