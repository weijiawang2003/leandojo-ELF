"""Mini-ELF v35 — Part 2: flow-vs-AR comparison under formal verification.

Trains (or loads) the v35 ELF-style flow model AND the **matched** token-AR
baseline (the v24/v33 engine) on the *same* v35 train/val split with the *same*
shared :class:`TokenVocab`, then runs them — plus a retrieval floor — through
:func:`mini_elf_lean.baseline_eval.evaluate` against the
:class:`TrustedMathlibVerifier` (headline metrics use this verifier only).

The research question is NOT higher pass@k (the curated tier is saturated): it is
whether embedded flow has a *different, useful generation profile*. So beyond
pass@{1,5,10} we report candidate diversity (distinct@k, mean pairwise token
Jaccard), novel-verified rate (verified strings absent from the train tactic
set), invalid-decode rate, a sampling-step sensitivity curve, and a
sampling-frequency → P(verify) calibration. A clean negative result is valid.

Verification is batched: every candidate from every baseline is collected and
verified in one ``verify_many(confirm=True)`` pass per tier (core vs Mathlib),
then the per-baseline ``evaluate`` reads the resulting verdict map — so Lean runs
once over the union, not once per (baseline, candidate). ``state_after`` is never
read; the eval test split is untouched by training.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch  # noqa: E402

from mini_elf_lean.baselines import Baseline, Example, RetrievalBaseline  # noqa: E402
from mini_elf_lean.baseline_eval import evaluate  # noqa: E402
from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier  # noqa: E402
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list  # noqa: E402
from mini_elf_lean.tactic_tokenizer import tokenize  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402
from mini_elf_lean.elf_v35_embed import ElfV35Config  # noqa: E402
from mini_elf_lean.elf_v35_train import ElfV35TrainConfig, train as train_flow, save_artifacts, load_model  # noqa: E402
from mini_elf_lean.elf_v35_sample import MiniElfV35Baseline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v35_flow")

DATA = ROOT / "data" / "processed" / "v35_elf_flow"
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
LEAN_PATH_FILE = ROOT / ".tmp" / "v27_lean_path.txt"
MODELS = ROOT / "data" / "models"
OUT = ROOT / "data" / "baselines" / "v35_flow_eval"


# --------------------------------------------------------------------------- #
# data helpers
# --------------------------------------------------------------------------- #


def _read(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _to_examples(rows: Sequence[Dict[str, Any]]) -> List[Example]:
    return [Example(r["theorem_name"], r["theorem_statement"], r["state_before"], r["tactic"], r.get("split", "train")) for r in rows]


def _dedup_by_state(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One eval row per (theorem_name, state_before) — predictions are a function
    of (statement, state), so multiple verified-tactic rows of the same theorem
    must not double-count in pass@k. The oracle still credits all alternates."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        key = (r["theorem_name"], r["state_before"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# --------------------------------------------------------------------------- #
# matched token-AR baseline (the v24/v33 engine), same vocab
# --------------------------------------------------------------------------- #


class TokenARBaseline(Baseline):
    name = "token_ar"

    def __init__(self, model, vocab, cfg, *, beam_width: int = 10, length_penalty: float = 0.7):
        from mini_elf_lean.token_seq2seq import predict_beams  # noqa: E402
        self._predict_beams = predict_beams
        self.model = model
        self.vocab = vocab
        self.cfg = cfg
        self.beam_width = beam_width
        self.length_penalty = length_penalty

    @property
    def mode(self) -> str:
        return f"token_ar(beam={self.beam_width})"

    def fit(self, train) -> "TokenARBaseline":  # noqa: ARG002
        return self

    def predict(self, example: Example, *, k: int) -> List[str]:
        beams = self._predict_beams(
            self.model, self.vocab, self.cfg,
            example.theorem_statement, example.state_before,
            beam_width=max(self.beam_width, k), length_penalty=self.length_penalty,
        )
        cands = [b for b, _ in beams]
        survivors, _ = sanitize_candidate_list(cands)
        return survivors[:k]


class _CachedBaseline(Baseline):
    """Memoize predict by (theorem_name, state_before) so the candidate-collection
    pass and the subsequent ``evaluate`` call don't sample/beam twice. Only used
    for the expensive generative baselines (flow, token-AR)."""

    def __init__(self, inner: Baseline, *, top_k: int):
        self.inner = inner
        self.name = getattr(inner, "name", inner.__class__.__name__)
        self._top_k = top_k
        self._cache: Dict[Tuple[str, str], List[str]] = {}

    @property
    def mode(self):
        return getattr(self.inner, "mode", None)

    def fit(self, train):  # noqa: ARG002
        return self

    def predict(self, example: Example, *, k: int) -> List[str]:
        key = (example.theorem_name, example.state_before)
        if key not in self._cache:
            self._cache[key] = self.inner.predict(example, k=self._top_k)
        return self._cache[key][:k]


# --------------------------------------------------------------------------- #
# training (train-if-missing)
# --------------------------------------------------------------------------- #


def get_flow_baseline(train_rows, val_rows, vocab, manifest, args) -> MiniElfV35Baseline:
    out_dir = MODELS / "v35_flow_model"
    if args.retrain or not (out_dir / "model.pt").exists():
        cfg = ElfV35Config(
            vocab_size=len(vocab),
            d_model=args.d_model, cond_hidden=args.d_model,
            n_layers=args.flow_layers, n_heads=4, ff_dim=2 * args.d_model,
            max_tgt_len=manifest["max_tgt_len"], max_cond_len=manifest["max_cond_len"],
            pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
        )
        tcfg = ElfV35TrainConfig(epochs=args.flow_epochs, batch_size=args.batch_size, seed=args.seed)
        logger.info("training v35 flow (%d epochs, %d train rows, D=%d, %d layers)",
                    tcfg.epochs, len(train_rows), cfg.d_model, cfg.n_layers)
        art = train_flow(cfg, train_rows, val_rows, tcfg, log_fn=lambda r: logger.info("flow %s", r) if r["epoch"] % 10 == 0 else None)
        save_artifacts(out_dir, art, vocab_src=DATA / "vocab.json")
        logger.info("flow trained: %s params, best_epoch=%s val_fm=%s",
                    art.summary["n_parameters"], art.summary["best_epoch"], art.summary["best_val_fm"])
    return MiniElfV35Baseline.load(
        out_dir, vocab_path=DATA / "vocab.json",
        n_samples=args.n_samples, steps=args.steps, cfg_weight=args.cfg_weight,
        self_cond=True, sde=args.sde, seed=args.seed,
    )


def get_token_ar_baseline(train_examples, val_examples, vocab, args) -> TokenARBaseline:
    from mini_elf_lean.token_seq2seq import (  # noqa: E402
        TokenTrainConfig, train_token, save_token_artifacts, load_token_model,
    )
    out_dir = MODELS / "v35_token_ar"
    if args.retrain or not (out_dir / "model.pt").exists():
        tcfg = TokenTrainConfig(epochs=args.ar_epochs, batch_size=args.batch_size, seed=args.seed,
                                beam_width=10)
        logger.info("training matched token-AR (%d epochs, %d train rows, shared vocab=%d)",
                    tcfg.epochs, len(train_examples), len(vocab))
        art = train_token(train_examples, val_examples, vocab, tcfg)
        save_token_artifacts(out_dir, art, tcfg)
        logger.info("token-AR trained: %s params best_epoch=%s", art.summary["n_parameters"], art.summary["best_epoch"])
    model, vcb, cfg = load_token_model(out_dir)
    return TokenARBaseline(model, vcb, cfg, beam_width=10)


# --------------------------------------------------------------------------- #
# generation-profile metrics
# --------------------------------------------------------------------------- #


def _tok_set(s: str) -> frozenset:
    return frozenset(t.text for t in tokenize(s) if t.text.strip())


def distinct_and_diversity(predictions: Sequence[Dict[str, Any]], k: int) -> Dict[str, float]:
    """distinct@k and mean pairwise token-Jaccard (a self-BLEU proxy without
    external deps; higher Jaccard = less diverse)."""
    distinct_ratios: List[float] = []
    jaccards: List[float] = []
    for row in predictions:
        preds = (row.get("predictions") or [])[:k]
        if not preds:
            continue
        distinct_ratios.append(len(set(preds)) / len(preds))
        sets = [_tok_set(p) for p in preds]
        pairs = list(itertools.combinations(range(len(sets)), 2))
        if pairs:
            js = []
            for a, b in pairs:
                u = sets[a] | sets[b]
                js.append((len(sets[a] & sets[b]) / len(u)) if u else 1.0)
            jaccards.append(sum(js) / len(js))
    return {
        f"distinct@{k}": sum(distinct_ratios) / len(distinct_ratios) if distinct_ratios else 0.0,
        f"mean_pairwise_jaccard@{k}": sum(jaccards) / len(jaccards) if jaccards else 0.0,
    }


def novel_verified_rate(predictions: Sequence[Dict[str, Any]], train_tactics: set, k: int) -> Dict[str, Any]:
    """Fraction of eval rows whose top-k contains a VERIFIED tactic that is NOT
    in the train tactic set (open-vocabulary success)."""
    n_rows = 0
    n_novel = 0
    novel_examples: List[str] = []
    for row in predictions:
        lean = row.get("lean_results") or {}
        if not lean:
            continue
        n_rows += 1
        for p in (row.get("predictions") or [])[:k]:
            if lean.get(p, {}).get("success") and p not in train_tactics:
                n_novel += 1
                if len(novel_examples) < 25:
                    novel_examples.append(f"{row['theorem_name']} :: {p}")
                break
    return {
        "novel_verified_rate": n_novel / n_rows if n_rows else 0.0,
        "n_novel_verified": n_novel,
        "n_rows": n_rows,
        "examples": novel_examples,
    }


def calibration(ranked_with_counts: List[Tuple[str, int, bool]]) -> Dict[str, Any]:
    """sampling-frequency → P(verify). Buckets candidates by count and reports
    the verified fraction per bucket."""
    buckets: Dict[str, List[int]] = {}
    for _cand, count, ok in ranked_with_counts:
        b = "1" if count == 1 else ("2-3" if count <= 3 else ("4-7" if count <= 7 else "8+"))
        buckets.setdefault(b, []).append(1 if ok else 0)
    return {b: {"n": len(v), "p_verify": sum(v) / len(v)} for b, v in sorted(buckets.items())}


# --------------------------------------------------------------------------- #
# verification (batched per tier)
# --------------------------------------------------------------------------- #


def build_verifiers(scratch: Path):
    lean_path = LEAN_PATH_FILE.read_text().strip() if LEAN_PATH_FILE.exists() else None
    core_v = TrustedMathlibVerifier(scratch, core=True, timeout=120)
    mathlib_v = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    return core_v, mathlib_v


def batch_verify(items_by_tier: Dict[str, List[Tuple[str, str, str]]], scratch: Path) -> Dict[Tuple[str, str], Dict[str, Any]]:
    core_v, mathlib_v = build_verifiers(scratch)
    vmap: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if items_by_tier.get("mathlib"):
        if not mathlib_v.warmup():
            logger.error("mathlib verifier warmup failed")
        v = mathlib_v.verify_many(items_by_tier["mathlib"], confirm=True)
        for x in v:
            vmap[(x.theorem_name, x.tactic)] = {"success": x.success, "error": x.error}
        logger.info("mathlib verified %d items in %.1fs", len(items_by_tier["mathlib"]), mathlib_v.total_lean_seconds)
    if items_by_tier.get("core"):
        v = core_v.verify_many(items_by_tier["core"], confirm=True)
        for x in v:
            vmap[(x.theorem_name, x.tactic)] = {"success": x.success, "error": x.error}
        logger.info("core verified %d items in %.1fs", len(items_by_tier["core"]), core_v.total_lean_seconds)
    return vmap


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--out-dir", default=str(OUT))
    ap.add_argument("--tier", default="mathlib", choices=["mathlib", "core", "all"], help="test tier (headline=mathlib)")
    ap.add_argument("--max-test", type=int, default=24, help="cap test theorems (Lean cost)")
    ap.add_argument("--train-cap", type=int, default=0, help="cap train rows (0=all); for quick runs")
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--flow-layers", type=int, default=3)
    ap.add_argument("--flow-epochs", type=int, default=60)
    ap.add_argument("--ar-epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--n-samples", type=int, default=32)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--cfg-weight", type=float, default=2.0)
    ap.add_argument("--sde", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--retrain", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="offline only (skip Lean)")
    ap.add_argument("--step-sweep", action="store_true", help="pass@10 vs N (extra Lean cost)")
    ap.add_argument("--step-values", default="1,2,4,8,16,32")
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed)
    data = Path(args.data_dir)
    manifest = json.loads((data / "manifest.json").read_text())
    vocab = TokenVocab.load(data / "vocab.json")
    train_rows = _read(data / "train.jsonl")
    val_rows = _read(data / "val.jsonl")
    test_rows = _read(data / "test.jsonl")
    if args.train_cap:
        train_rows = train_rows[: args.train_cap]
    train_examples = _to_examples(train_rows)
    val_examples = _to_examples(val_rows)
    full_examples = _to_examples(train_rows + val_rows + test_rows)
    train_tactics = {r["tactic"] for r in train_rows}

    # eval test split: one row per (theorem, state), tier-filtered + capped.
    test_eval = _dedup_by_state(test_rows)
    if args.tier != "all":
        test_eval = [r for r in test_eval if r.get("tier") == args.tier]
    test_eval = test_eval[: args.max_test] if args.max_test else test_eval
    test_examples = _to_examples(test_eval)
    name2tier = {r["theorem_name"]: r.get("tier", "core") for r in test_eval}
    name2stmt = {r["theorem_name"]: r["theorem_statement"] for r in test_eval}
    logger.info("test: %d theorems (tier=%s) | train rows=%d val=%d vocab=%d",
                len(test_examples), args.tier, len(train_rows), len(val_rows), len(vocab))

    # baselines (matched: same train/val/vocab) ------------------------------ #
    TOP_K = 10
    retrieval = RetrievalBaseline(neighbors=16).fit(train_examples)
    flow_inner = get_flow_baseline(train_rows, val_rows, vocab, manifest, args)
    token_ar_inner = get_token_ar_baseline(train_examples, val_examples, vocab, args)
    flow = _CachedBaseline(flow_inner, top_k=TOP_K)
    token_ar = _CachedBaseline(token_ar_inner, top_k=TOP_K)
    baselines: List[Baseline] = [retrieval, token_ar, flow]

    # candidate collection + batched verification --------------------------- #
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vmap: Dict[Tuple[str, str], Dict[str, Any]] = {}
    verifier_fn = None
    if not args.no_verify:
        items_by_tier: Dict[str, List[Tuple[str, str, str]]] = {"mathlib": [], "core": []}
        seen: set = set()
        for bl in baselines:
            for ex in test_examples:
                for tac in bl.predict(ex, k=TOP_K):
                    key = (ex.theorem_name, tac)
                    if key in seen:
                        continue
                    seen.add(key)
                    items_by_tier[name2tier.get(ex.theorem_name, "core")].append(
                        (ex.theorem_name, name2stmt.get(ex.theorem_name, ex.theorem_statement), tac))
        logger.info("collected unique candidates: mathlib=%d core=%d",
                    len(items_by_tier["mathlib"]), len(items_by_tier["core"]))
        vmap = batch_verify(items_by_tier, Path(args.scratch_dir).resolve())

        def verifier_fn(name, stmt, tactic):  # noqa: E306
            return vmap.get((name, tactic), {"success": False, "error": "cache-miss"})

    # per-baseline evaluate -------------------------------------------------- #
    comparison: Dict[str, Any] = {
        "tier": args.tier, "n_test_theorems": len(test_examples),
        "n_train_rows": len(train_rows), "vocab_size": len(vocab),
        "sampler": {"n_samples": args.n_samples, "steps": args.steps, "cfg_weight": args.cfg_weight, "sde": args.sde},
        "verifier": "TrustedMathlibVerifier (confirm=True, sound+complete)",
        "baselines": {},
    }
    per_baseline_results: Dict[str, Any] = {}
    for bl in baselines:
        res = evaluate(bl, train=train_examples, eval_examples=test_examples,
                       full_dataset=full_examples, k_values=(1, 5, 10), top_k=TOP_K,
                       verifier=verifier_fn, cache=None)
        per_baseline_results[bl.name] = res
        (out / f"metrics_{bl.name}.json").write_text(json.dumps(res.metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        prof = {}
        prof.update(distinct_and_diversity(res.predictions, 5))
        prof.update(distinct_and_diversity(res.predictions, 10))
        if not args.no_verify:
            prof["novel_verified@10"] = novel_verified_rate(res.predictions, train_tactics, 10)
        entry: Dict[str, Any] = {"mode": getattr(bl, "mode", None), "profile": prof}
        if not args.no_verify and "lean_verification" in res.metrics:
            entry["pass_at_k"] = {kk: res.metrics["lean_verification"]["pass_at_k"][kk]["rate"] for kk in ("1", "5", "10")}
        entry["top1_exact"] = res.metrics["exact_match"]["top1_exact"]
        comparison["baselines"][bl.name] = entry
        logger.info("%s: pass@k=%s profile=%s", bl.name, entry.get("pass_at_k"), prof)

    # flow-specific: invalid-decode, calibration, step sweep ----------------- #
    flow_diag = {
        "invalid_decode_rate_mean": (
            sum(d["invalid_decode_rate"] for d in flow_inner.diagnostics_log) / len(flow_inner.diagnostics_log)
            if flow_inner.diagnostics_log else None),
        "per_prompt": flow_inner.diagnostics_log,
    }
    if not args.no_verify:
        cal_rows: List[Tuple[str, int, bool]] = []
        for ex in test_examples:
            for cand, count in flow_inner.predict_with_counts(ex):
                ok = vmap.get((ex.theorem_name, cand), {}).get("success", False)
                cal_rows.append((cand, count, ok))
        flow_diag["calibration_freq_to_pverify"] = calibration(cal_rows)
    (out / "flow_diagnostics.json").write_text(json.dumps(flow_diag, indent=2, ensure_ascii=False), encoding="utf-8")
    comparison["flow_invalid_decode_rate_mean"] = flow_diag["invalid_decode_rate_mean"]

    # step-sensitivity curve (offline always; pass@10 if --step-sweep) ------- #
    step_values = [int(x) for x in args.step_values.split(",") if x.strip()]
    step_curve: Dict[str, Any] = {}
    for N in step_values:
        flow_inner.steps = N
        diags = []
        cand_by_ex = {}
        for ex in test_examples:
            text = build_input_text(ex.theorem_statement, ex.state_before)
            ranked, d = flow_inner.sample_candidates(text, steps=N)
            diags.append(d)
            cand_by_ex[ex.theorem_name] = [c for c, _ in ranked[:10]]
        entry = {
            "invalid_decode_rate": sum(x["invalid_decode_rate"] for x in diags) / len(diags) if diags else None,
            "mean_distinct_valid": sum(x["n_distinct_valid"] for x in diags) / len(diags) if diags else None,
        }
        if args.step_sweep and not args.no_verify:
            # extend vmap with any new candidates this N produced, then pass@10.
            new_items: Dict[str, List[Tuple[str, str, str]]] = {"mathlib": [], "core": []}
            for ex in test_examples:
                for tac in cand_by_ex[ex.theorem_name]:
                    if (ex.theorem_name, tac) not in vmap:
                        new_items[name2tier.get(ex.theorem_name, "core")].append(
                            (ex.theorem_name, name2stmt[ex.theorem_name], tac))
            if new_items["mathlib"] or new_items["core"]:
                vmap.update(batch_verify(new_items, Path(args.scratch_dir).resolve()))
            n_pass = sum(1 for ex in test_examples
                         if any(vmap.get((ex.theorem_name, t), {}).get("success") for t in cand_by_ex[ex.theorem_name]))
            entry["pass@10"] = n_pass / len(test_examples) if test_examples else 0.0
        step_curve[str(N)] = entry
    flow_inner.steps = args.steps
    comparison["step_sensitivity"] = step_curve
    (out / "step_sensitivity.json").write_text(json.dumps(step_curve, indent=2), encoding="utf-8")

    (out / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("DONE — wrote %s", out)
    print(json.dumps(comparison["baselines"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
