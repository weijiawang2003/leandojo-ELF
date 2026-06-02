"""Mini-ELF v36 — coherence probe (offline; gates everything in v36).

The v35 negative result localized the flow's failure to **inter-token
incoherence**: the non-autoregressive flow recovers only ~32% of gold tokens
per position and decodes to "token salad" (right vocabulary / often the right
tactic head, but a garbled body), so 0% verify. v36 asks: is that gap closable
at CPU scale, by a coherence-enforcing sampler (§3) or by scale·objective (§4)?

This module is the shared, **offline** measuring stick. For a fixed probe set
(the Mathlib-tier val rows) and any sampler that **generates from noise**
(true generation, conditioned on the prompt — NOT teacher forcing), it reports:

* ``per_token_gold_recovery`` — mean per-position match of decoded ids vs the
  row's gold target ids (the v35 ≈0.32 bottleneck);
* ``exact_seq_recovery_rate`` — fraction of *samples* that decode exactly to a
  gold tactic (v35 ≈0);
* ``head_correct_body_wrong_rate`` — fraction of samples with the right tactic
  head but a non-gold body (quantifies "salad");
* ``mean_pairwise_jaccard`` — token-set diversity of the per-prompt samples
  (confirms we have not merely collapsed to one string).

``baseline`` mode records the v35 sampler numbers (sanity: per-token ≈0.32,
exact-seq ≈0). ``compare`` mode contrasts the v35 continuous-self-cond sampler
with the v36 iterative/discrete sampler over ``N ∈ {1,4,8,16,32}``.

Guardrails: ``state_after`` never read; the probe is val-only; no Lean here.
The metric functions are importable by ``v36_ladder.py``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch  # noqa: E402

from mini_elf_lean.baselines import oracle_verified_lookup, Example  # noqa: E402
from mini_elf_lean.elf_v35_sample import integrate as integrate_v35  # noqa: E402
from mini_elf_lean.elf_v35_train import load_model  # noqa: E402
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list, tactic_head  # noqa: E402
from mini_elf_lean.tactic_tokenizer import tokenize, TokenKind  # noqa: E402
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402

logger = logging.getLogger("v36_coherence_probe")

DATA = ROOT / "data" / "processed" / "v35_elf_flow"
OUT = ROOT / "data" / "baselines" / "v36_coherence"
DEFAULT_MODEL = ROOT / "data" / "models" / "v35_flow_model"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

# A sampler takes (cond_ids (1,S), prompt str, n_seeds, steps) -> ids (K, T).
Sampler = Callable[[torch.Tensor, str, int, int], torch.Tensor]


def read_rows(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def gold_lookup(all_rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], frozenset]:
    ex = [Example(r["theorem_name"], r["theorem_statement"], r["state_before"], r["tactic"], r.get("split", "train")) for r in all_rows]
    return oracle_verified_lookup(ex)


def _decode_str(ids_row: torch.Tensor, vocab: TokenVocab) -> str:
    s = vocab.decode_target(ids_row.tolist())
    cleaned, _ = sanitize_candidate_list([s])
    return cleaned[0] if cleaned else ""


def _tok_set(s: str) -> frozenset:
    return frozenset(t.text for t in tokenize(s) if t.kind is not TokenKind.WS and t.text.strip())


def _mean_pairwise_jaccard(strings: Sequence[str]) -> Optional[float]:
    sets = [_tok_set(s) for s in strings if s]
    if len(sets) < 2:
        return None
    js = []
    for a, b in itertools.combinations(range(len(sets)), 2):
        u = sets[a] | sets[b]
        js.append((len(sets[a] & sets[b]) / len(u)) if u else 1.0)
    return sum(js) / len(js)


def coherence_metrics(
    sampler: Sampler,
    probe_rows: Sequence[Dict[str, Any]],
    golds: Dict[Tuple[str, str], frozenset],
    vocab: TokenVocab,
    *,
    n_samples: int,
    steps: int,
    T: int,
    pad_id: int,
    max_cond_len: int,
    device: str = "cpu",
) -> Dict[str, Any]:
    """The four §2 coherence metrics for one (sampler, steps) over the probe set."""
    per_tok_rows: List[float] = []
    jacc_rows: List[float] = []
    n_exact = 0
    n_head_body = 0
    n_total = 0
    for r in probe_rows:
        text = build_input_text(r["theorem_statement"], r["state_before"])
        cond = torch.tensor([vocab.encode_source(text)[:max_cond_len] or [pad_id]], dtype=torch.long, device=device)
        ids = sampler(cond, text, n_samples, steps)            # (K, T)
        K = ids.size(0)
        gold_ids = (list(r["tgt_ids"])[:T] + [pad_id] * T)[:T]
        gold_pos = [i for i in range(T) if gold_ids[i] != pad_id]
        gset = golds.get((r["theorem_name"], r["state_before"]), frozenset({r["tactic"]}))
        gheads = {tactic_head(g) for g in gset}
        # per-token recovery, averaged over samples
        if gold_pos:
            per_sample = []
            for k in range(K):
                row = ids[k]
                hit = sum(1 for i in gold_pos if int(row[i]) == gold_ids[i])
                per_sample.append(hit / len(gold_pos))
            per_tok_rows.append(sum(per_sample) / K)
        # exact / head-body, per sample
        strings = []
        for k in range(K):
            s = _decode_str(ids[k], vocab)
            strings.append(s)
            n_total += 1
            if s and s in gset:
                n_exact += 1
            elif s and tactic_head(s) in gheads and tactic_head(s):
                n_head_body += 1
        j = _mean_pairwise_jaccard(strings)
        if j is not None:
            jacc_rows.append(j)
    return {
        "n_probe_rows": len(probe_rows),
        "n_samples_per_row": n_samples,
        "steps": steps,
        "per_token_gold_recovery": (sum(per_tok_rows) / len(per_tok_rows)) if per_tok_rows else 0.0,
        "exact_seq_recovery_rate": (n_exact / n_total) if n_total else 0.0,
        "head_correct_body_wrong_rate": (n_head_body / n_total) if n_total else 0.0,
        "mean_pairwise_jaccard": (sum(jacc_rows) / len(jacc_rows)) if jacc_rows else None,
    }


def make_v35_sampler(model, mean, std, *, cfg_weight: float = 2.0, self_cond: bool = True,
                     seed: int = 0, device: str = "cpu") -> Sampler:
    def _s(cond, prompt, n_seeds, steps):
        return integrate_v35(model, cond, mean, std, n_seeds=n_seeds, steps=steps,
                             cfg_weight=cfg_weight, self_cond=self_cond, seed=seed,
                             prompt=prompt, device=device)
    return _s


def make_v36_sampler(model, mean, std, *, cfg_weight: float = 2.0, remask: bool = True,
                     seed: int = 0, device: str = "cpu") -> Sampler:
    from mini_elf_lean.elf_v36_sample import integrate_discrete  # lazy: built in §3
    def _s(cond, prompt, n_seeds, steps):
        return integrate_discrete(model, cond, mean, std, n_seeds=n_seeds, steps=steps,
                                  cfg_weight=cfg_weight, remask=remask, seed=seed,
                                  prompt=prompt, device=device)
    return _s


def load_probe(data_dir: Path, *, tier: str = "mathlib", max_probe: int = 0):
    train = read_rows(data_dir / "train.jsonl")
    val = read_rows(data_dir / "val.jsonl")
    test = read_rows(data_dir / "test.jsonl")
    golds = gold_lookup(train + val + test)
    probe = [r for r in val if tier == "all" or r.get("tier") == tier]
    if max_probe:
        probe = probe[:max_probe]
    return probe, golds


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--mode", choices=["baseline", "compare"], default="baseline")
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL))
    ap.add_argument("--out-dir", default=str(OUT))
    ap.add_argument("--tier", default="mathlib")
    ap.add_argument("--max-probe", type=int, default=0, help="cap probe rows (0=all)")
    ap.add_argument("--n-samples", type=int, default=16)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--step-values", default="1,4,8,16,32")
    ap.add_argument("--cfg-weight", type=float, default=2.0)
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(out / "run.log")])

    model, cfg, stats = load_model(Path(args.model_dir))
    mean, std = stats.tensors("cpu")
    probe, golds = load_probe(Path(args.data_dir), tier=args.tier, max_probe=args.max_probe)
    vocab = TokenVocab.load(Path(args.data_dir) / "vocab.json")
    common = dict(T=cfg.max_tgt_len, pad_id=cfg.pad_id, max_cond_len=cfg.max_cond_len)
    logger.info("probe: %d %s val rows; model=%s", len(probe), args.tier, args.model_dir)

    if args.mode == "baseline":
        s35 = make_v35_sampler(model, mean, std, cfg_weight=args.cfg_weight)
        m = coherence_metrics(s35, probe, golds, vocab, n_samples=args.n_samples, steps=args.steps, **common)
        result = {"sampler": "v35_continuous_selfcond", "model": args.model_dir, **m}
        (out / "baseline_v35.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        logger.info("v35 BASELINE: per_token=%.3f exact_seq=%.3f head_body=%.3f jaccard=%s",
                    m["per_token_gold_recovery"], m["exact_seq_recovery_rate"],
                    m["head_correct_body_wrong_rate"], m["mean_pairwise_jaccard"])
        print(json.dumps(result, indent=2))
        return 0

    # compare: v35 vs v36 over the step sweep
    step_values = [int(x) for x in args.step_values.split(",") if x.strip()]
    s35 = make_v35_sampler(model, mean, std, cfg_weight=args.cfg_weight)
    s36 = make_v36_sampler(model, mean, std, cfg_weight=args.cfg_weight, remask=True)
    compare: Dict[str, Any] = {"model": args.model_dir, "by_steps": {}}
    for N in step_values:
        logger.info("compare N=%d ...", N)
        mv35 = coherence_metrics(s35, probe, golds, vocab, n_samples=args.n_samples, steps=N, **common)
        mv36 = coherence_metrics(s36, probe, golds, vocab, n_samples=args.n_samples, steps=N, **common)
        compare["by_steps"][str(N)] = {"v35_continuous": mv35, "v36_iterative": mv36}
        logger.info("N=%d  v35 per_tok=%.3f exact=%.3f | v36 per_tok=%.3f exact=%.3f",
                    N, mv35["per_token_gold_recovery"], mv35["exact_seq_recovery_rate"],
                    mv36["per_token_gold_recovery"], mv36["exact_seq_recovery_rate"])
        (out / "sampler_compare.json").write_text(json.dumps(compare, indent=2), encoding="utf-8")
    print(json.dumps(compare, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
