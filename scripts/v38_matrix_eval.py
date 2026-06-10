"""Mini-ELF v38 — research matrix: continuous flow (A) vs masked diffusion (B) vs AR (C).

The first three-way, compute-matched comparison of continuous embedded flow,
masked-discrete diffusion, and autoregression on formally-verified single-tactic
Lean/Mathlib generation, in the data-constrained regime. Trains all families on
the SAME small verified split (shared vocab) for many epochs, checkpoints at
{10,25,50,100,200}, and at gated checkpoints evaluates verified pass@{1,5,10} on
the 24-theorem Mathlib tier with TrustedMathlibVerifier(confirm=True) + the v36
coherence metrics + novel-verified rate, logging compute (tokens / approx FLOPs).

Phases (budget-gated, skip+log over-budget): §3 headline 3-way @100M; §2 scale
arm @30M; §4 ablations @best (D1 x-pred vs v-pred [most important], D4 frozen vs
learned emb, D5 CFG/self-cond). D2 block / D3 ar-init / D6 schedule are scaffolded
in the families but not swept here (logged as skipped:scope). Writes
{crossover,scale,ablations,matrix}.json incrementally; pushes hourly via the
caller. Guardrails: no state_after; train-on-train, val-checkpoint; verified
metrics via TrustedMathlibVerifier only; v38_* artifacts only.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config, SCALE_PRESETS, count_params
from mini_elf_lean.v38_data import load_dataset, make_batch, mathlib_test_tier, cond_ids_for, gold_lookup
from mini_elf_lean.elf_v38_ar import ARModel
from mini_elf_lean.elf_v38_flow import FlowModel
from mini_elf_lean.elf_v38_mdlm import MDLMModel
from mini_elf_lean.elf_v35_sample import decode_and_rank
from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier
from mini_elf_lean.tactic_sanitizer import tactic_head
from mini_elf_lean.tactic_tokenizer import tokenize, TokenKind

OUT = ROOT / "data" / "baselines" / "v38_matrix"
SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
LEAN_PATH_FILE = ROOT / ".tmp" / "v27_lean_path.txt"
logger = logging.getLogger("v38_matrix")

FAMILIES = {"flow": FlowModel, "mdlm": MDLMModel, "ar": ARModel}


def build_model(family: str, cfg: V38Config, **kw):
    if family == "flow":
        return FlowModel(cfg, **kw)
    if family == "mdlm":
        return MDLMModel(cfg)
    if family == "ar":
        return ARModel(cfg)
    raise ValueError(family)


def make_cfg(scale: str, vocab, manifest) -> V38Config:
    return V38Config(vocab_size=len(vocab), max_cond_len=manifest["max_cond_len"],
                     max_tgt_len=manifest["max_tgt_len"], pad_id=vocab.pad_id,
                     bos_id=vocab.bos_id, eos_id=vocab.eos_id, **SCALE_PRESETS[scale])


# ---------------- training with checkpoint snapshots ---------------- #


@torch.no_grad()
def _val_loss(model, val_rows, vocab, cfg, device, bs=256, n_rep=3) -> float:
    model.eval()
    tot, n = 0.0, 0
    for _ in range(n_rep):
        for s in range(0, len(val_rows), bs):
            b = make_batch(val_rows[s:s + bs], vocab, max_cond_len=cfg.max_cond_len, max_tgt_len=cfg.max_tgt_len, device=device)
            tot += float(model.loss(b).item()); n += 1
    return tot / max(n, 1)


def train_family(family, cfg, train_rows, val_rows, vocab, *, checkpoint_epochs, max_epochs,
                 max_seconds, patience, batch_size, lr, device, seed=0, bf16=True, **family_kw):
    torch.manual_seed(seed)
    model = build_model(family, cfg, **family_kw).to(device)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01, betas=(0.9, 0.95))
    g = torch.Generator(device="cpu"); g.manual_seed(seed)
    seq_len = cfg.max_cond_len + cfg.max_tgt_len
    n_params = count_params(model)
    snaps: Dict[int, Dict[str, torch.Tensor]] = {}
    log: List[Dict[str, Any]] = []
    best_val, no_imp = float("inf"), 0
    t0 = time.perf_counter()
    tokens_seen = 0
    ckpt_set = sorted(set(checkpoint_epochs) | {max_epochs})
    for epoch in range(1, max_epochs + 1):
        model.train()
        perm = torch.randperm(len(train_rows), generator=g).tolist()
        for s in range(0, len(perm), batch_size):
            rows = [train_rows[i] for i in perm[s:s + batch_size]]
            b = make_batch(rows, vocab, max_cond_len=cfg.max_cond_len, max_tgt_len=cfg.max_tgt_len, device=device)
            if bf16:
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    L = model.loss(b)
            else:
                L = model.loss(b)
            opt.zero_grad(); L.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step()
            tokens_seen += len(rows) * seq_len
        if epoch in ckpt_set:
            vl = _val_loss(model, val_rows, vocab, cfg, device)
            snaps[epoch] = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            flops = 6 * n_params * tokens_seen
            log.append({"epoch": epoch, "val_loss": round(vl, 4), "tokens_seen": tokens_seen, "approx_flops": flops})
            logger.info("  [%s] epoch %d val_loss=%.4f tokens=%.2e", family, epoch, vl, tokens_seen)
            if vl < best_val - 1e-4:
                best_val, no_imp = vl, 0
            else:
                no_imp += 1
            if no_imp >= patience:
                logger.info("  [%s] early stop @ epoch %d", family, epoch); break
        if (time.perf_counter() - t0) > max_seconds:
            logger.warning("  [%s] train cap hit @ epoch %d", family, epoch)
            if epoch not in snaps:
                snaps[epoch] = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            break
    return model, snaps, log, n_params


# ---------------- evaluation (coherence + verified pass@k) ---------------- #


def _toks(s): return frozenset(t.text for t in tokenize(s) if t.kind is not TokenKind.WS and t.text.strip())


@torch.no_grad()
def eval_checkpoint(model, state, test_tier, vocab, cfg, golds, train_tactics, *,
                    K, steps, device, verifier=None, gen_kw=None, return_detail=False):
    model.load_state_dict({k: v.to(device) for k, v in state.items()})
    model.eval()
    gen_kw = gen_kw or {}
    per_tok_rows, exact_samples, head_body, n_samples_tot = [], 0, 0, 0
    pred_topk: Dict[str, List[str]] = {}
    cand_items: Dict[Tuple[str, str], str] = {}
    name2stmt = {}
    vmap: Dict[Tuple[str, str], bool] = {}   # bound even when verifier is None (for return_detail)
    for r in test_tier:
        text_name = r["theorem_name"]; name2stmt[text_name] = r["theorem_statement"]
        cond = cond_ids_for(r, vocab, max_cond_len=cfg.max_cond_len, device=device)
        ids = model.generate(cond, n_samples=K, steps=steps, prompt=text_name, device=device, **gen_kw)
        gold_ids = (list(r["tgt_ids"])[:cfg.max_tgt_len] + [cfg.pad_id] * cfg.max_tgt_len)[:cfg.max_tgt_len]
        gpos = [i for i in range(cfg.max_tgt_len) if gold_ids[i] != cfg.pad_id]
        gset = golds.get((text_name, r["state_before"]), frozenset({r["tactic"]}))
        gheads = {tactic_head(g) for g in gset}
        if gpos:
            ps = [sum(1 for i in gpos if int(ids[k][i]) == gold_ids[i]) / len(gpos) for k in range(ids.size(0))]
            per_tok_rows.append(sum(ps) / len(ps))
        ranked, _ = decode_and_rank(ids, vocab)
        for k in range(ids.size(0)):
            s = vocab.decode_target(ids[k].tolist())
            from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list
            cl, _ = sanitize_candidate_list([s]); cand = cl[0] if cl else ""
            n_samples_tot += 1
            if cand and cand in gset: exact_samples += 1
            elif cand and tactic_head(cand) in gheads and tactic_head(cand): head_body += 1
        topk = [t for t, _ in ranked[:10]]
        pred_topk[text_name] = topk
        for tac in topk:
            cand_items[(text_name, tac)] = tac
    metrics = {
        "per_token_gold_recovery": sum(per_tok_rows) / len(per_tok_rows) if per_tok_rows else 0.0,
        "exact_seq_recovery_rate": exact_samples / max(n_samples_tot, 1),
        "head_correct_body_wrong_rate": head_body / max(n_samples_tot, 1),
    }
    if verifier is not None:
        items = [(nm, name2stmt[nm], tac) for (nm, tac) in cand_items]
        if items:
            for x in verifier.verify_many(items, confirm=True):
                vmap[(x.theorem_name, x.tactic)] = x.success
        passk = {}
        for kk in (1, 5, 10):
            npass = sum(1 for nm, topk in pred_topk.items() if any(vmap.get((nm, t)) for t in topk[:kk]))
            passk[str(kk)] = npass / max(len(pred_topk), 1)
        novel = sum(1 for nm, topk in pred_topk.items()
                    for t in topk[:10] if vmap.get((nm, t)) and t not in train_tactics)
        metrics["pass_at_k"] = passk
        metrics["novel_verified_count"] = novel
        metrics["n_candidates_verified"] = len(items)
    if return_detail:
        detail = {
            "pred_topk": pred_topk,                                    # name -> [top-10 tactics]
            "vmap": {f"{n}\x1f{t}": bool(v) for (n, t), v in vmap.items()},  # "name\x1ftactic" -> verified
            "name2stmt": name2stmt, "K": K, "steps": steps, "n_theorems": len(pred_topk),
        }
        return metrics, detail
    return metrics


def get_verifier():
    if not SCRATCH.exists():
        return None
    lp = LEAN_PATH_FILE.read_text().strip() if LEAN_PATH_FILE.exists() else None
    v = TrustedMathlibVerifier(SCRATCH.resolve(), lean_path=lp, timeout=300)
    if not v.warmup():
        logger.error("verifier warmup failed"); return None
    return v


# ---------------- orchestration ---------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-dir", default=str(OUT))
    ap.add_argument("--budget-hours", type=float, default=7.0)
    ap.add_argument("--headline-scale", default="100M")
    ap.add_argument("--scale-arm", default="30M")
    ap.add_argument("--checkpoints", default="10,25,50,100,200")
    ap.add_argument("--verify-epochs", default="50,100,200")
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--gen-steps", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--per-train-min", type=float, default=45.0)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--phases", default="headline,scale,ablations")
    args = ap.parse_args(argv)

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(out / "run.log")])
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    deadline = time.perf_counter() + args.budget_hours * 3600
    ckpts = [int(x) for x in args.checkpoints.split(",")]
    vepochs = set(int(x) for x in args.verify_epochs.split(","))
    max_epochs = max(ckpts)

    ds = load_dataset(); vocab = ds["vocab"]; man = ds["manifest"]
    train_rows = ds["train"]; val_rows = ds["val"]
    test_tier = mathlib_test_tier(ds["test"], cap=24)
    golds = gold_lookup(train_rows + val_rows + ds["test"])
    train_tactics = {r["tactic"] for r in train_rows}
    verifier = None if args.no_verify else get_verifier()
    logger.info("device=%s gpu=%s | train=%d test_tier=%d verify=%s deadline=%.1fh",
                dev, torch.cuda.get_device_name(0) if dev == "cuda" else "-", len(train_rows), len(test_tier),
                verifier is not None, args.budget_hours)

    def time_left(): return deadline - time.perf_counter()

    def run_family_curve(family, scale, verify_epochs, tag, store, extra_kw=None):
        if time_left() < 600:
            logger.warning("skip %s/%s: <10min budget left", family, scale); store.append({"family": family, "scale": scale, "skipped": "budget"}); return
        cfg = make_cfg(scale, vocab, man)
        t0 = time.perf_counter()
        model, snaps, tlog, npar = train_family(
            family, cfg, train_rows, val_rows, vocab, checkpoint_epochs=ckpts, max_epochs=max_epochs,
            max_seconds=args.per_train_min * 60, patience=args.patience, batch_size=args.batch_size,
            lr=args.lr, device=dev, **(extra_kw or {}))
        logger.info("[%s/%s] trained %d params, %d ckpts, %.0fs", family, scale, npar, len(snaps), time.perf_counter() - t0)
        for ep in sorted(snaps):
            use_verifier = verifier if (ep in verify_epochs) else None
            m = eval_checkpoint(model, snaps[ep], test_tier, vocab, cfg, golds, train_tactics,
                                K=args.K, steps=args.gen_steps, device=dev, verifier=use_verifier,
                                gen_kw=(extra_kw_gen(family, extra_kw)))
            rec = {"family": family, "scale": scale, "params": npar, "epoch": ep,
                   "tokens_seen": next((x["tokens_seen"] for x in tlog if x["epoch"] == ep), None),
                   "approx_flops": next((x["approx_flops"] for x in tlog if x["epoch"] == ep), None),
                   "val_loss": next((x["val_loss"] for x in tlog if x["epoch"] == ep), None), **m}
            store.append(rec)
            (out / f"{tag}.json").write_text(json.dumps(store, indent=2), encoding="utf-8")
            logger.info("[%s/%s e%d] per_tok=%.3f exact=%.3f pass@k=%s", family, scale, ep,
                        m["per_token_gold_recovery"], m["exact_seq_recovery_rate"], m.get("pass_at_k"))
        del model
        if dev == "cuda": torch.cuda.empty_cache()
        return snaps

    def extra_kw_gen(family, extra_kw):
        # flow generate honors cfg_weight/self_cond; default cfg_weight=2.0
        if family == "flow":
            return {"cfg_weight": 2.0, "self_cond": True}
        return {}

    phases = args.phases.split(",")

    # §3 headline 3-way @100M
    if "headline" in phases:
        logger.info("=== PHASE headline: 3-way @ %s ===", args.headline_scale)
        crossover: List[Dict[str, Any]] = []
        for fam in ("ar", "mdlm", "flow"):
            run_family_curve(fam, args.headline_scale, vepochs, "crossover", crossover)

    # §2 scale arm @30M (verify at 100,200 only)
    if "scale" in phases and time_left() > 1200:
        logger.info("=== PHASE scale: 3-way @ %s ===", args.scale_arm)
        scale_store: List[Dict[str, Any]] = []
        for fam in ("ar", "mdlm", "flow"):
            run_family_curve(fam, args.scale_arm, {100, 200}, "scale", scale_store)

    # §4 ablations @ best scale (flow), best-effort
    if "ablations" in phases and time_left() > 1200:
        logger.info("=== PHASE ablations (flow @ %s) ===", args.scale_arm)
        abl: List[Dict[str, Any]] = []
        ascale = args.scale_arm  # ablate at the cheaper scale to fit budget
        cfg = make_cfg(ascale, vocab, man)
        variants = [
            ("D1_xpred", dict(predict="x")),
            ("D1_vpred", dict(predict="v")),
            ("D4_frozen_emb", dict(predict="x", freeze_emb=True)),
            ("D4_learned_emb", dict(predict="x", freeze_emb=False)),
        ]
        for name, kw in variants:
            if time_left() < 900:
                abl.append({"variant": name, "skipped": "budget"}); (out / "ablations.json").write_text(json.dumps(abl, indent=2)); continue
            try:
                model, snaps, tlog, npar = train_family(
                    "flow", cfg, train_rows, val_rows, vocab, checkpoint_epochs=[100], max_epochs=100,
                    max_seconds=args.per_train_min * 60, patience=args.patience, batch_size=args.batch_size,
                    lr=args.lr, device=dev, **kw)
                ep = max(snaps)
                # D5 also sweeps cfg/self_cond at sample time on the x-pred frozen model
                base_m = eval_checkpoint(model, snaps[ep], test_tier, vocab, cfg, golds, train_tactics,
                                         K=args.K, steps=args.gen_steps, device=dev, verifier=verifier,
                                         gen_kw={"cfg_weight": 2.0, "self_cond": True})
                rec = {"variant": name, "params": npar, "epoch": ep, **base_m}
                if name == "D1_xpred":
                    d5 = {}
                    for w in (1.0, 2.0, 3.0):
                        d5[f"cfg{w}"] = eval_checkpoint(model, snaps[ep], test_tier, vocab, cfg, golds, train_tactics,
                                                        K=args.K, steps=args.gen_steps, device=dev, verifier=None,
                                                        gen_kw={"cfg_weight": w, "self_cond": True})
                    d5["self_cond_off"] = eval_checkpoint(model, snaps[ep], test_tier, vocab, cfg, golds, train_tactics,
                                                          K=args.K, steps=args.gen_steps, device=dev, verifier=None,
                                                          gen_kw={"cfg_weight": 2.0, "self_cond": False})
                    rec["D5_cfg_selfcond"] = d5
                abl.append(rec)
                del model; torch.cuda.empty_cache()
            except Exception as exc:  # noqa: BLE001
                logger.exception("ablation %s failed", name); abl.append({"variant": name, "error": str(exc)})
            (out / "ablations.json").write_text(json.dumps(abl, indent=2), encoding="utf-8")
        abl.append({"note": "D2 block / D3 ar-init / D6 schedule scaffolded in families but not swept (skipped:scope/budget)."})
        (out / "ablations.json").write_text(json.dumps(abl, indent=2), encoding="utf-8")

    logger.info("=== v38 matrix DONE (%.0fs used) ===", args.budget_hours * 3600 - time_left())
    if verifier is not None:
        logger.info("total lean seconds: %.1f", verifier.total_lean_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
