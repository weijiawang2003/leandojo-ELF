"""Evaluation harness for the tactic-prediction baselines.

Wraps a fitted :class:`~mini_elf_lean.baselines.Baseline` and computes two
families of metrics over an eval split:

  - **Offline exact-match** (no Lean needed):

    * ``top1_exact``  — predictions[0] == this row's recorded tactic.
    * ``topk_any_verified`` for k ∈ {1, 3, 5} — predictions[:k] intersects the
      verified-tactic set for ``(theorem_name, state_before)`` aggregated across
      the *whole* processed dataset. A baseline gets credit for proposing any
      tactic some collection run verified for that exact state, not just the
      single tactic of this row.

  - **Lean-cli verification** (optional, behind ``verify=True``):

    * Reconstruct the theorem template (``example <statement> := by\\n  __TACTIC__``)
      via :class:`~mini_elf_lean.lean_runner.LeanCliRunner`, run each
      deduplicated top-k tactic, and compute ``pass@k``.
    * Results are cached in :class:`VerificationCache` keyed by
      ``sha256(theorem_name || tactic)``, so re-runs are nearly free.

The metrics dict is exhaustive: it carries the leakage-check report from
:func:`mini_elf_lean.baselines.split_summary`, oracle coverage on the eval
split, and per-k breakdowns. Per-row results are also returned so the CLI can
write a ``predictions.jsonl`` for downstream inspection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .baselines import (
    Baseline,
    Example,
    RetrievalBaseline,
    oracle_verified_lookup,
    split_summary,
)
from .lean_runner import LeanCliRunner
from .schemas import TheoremSeed

logger = logging.getLogger(__name__)

DEFAULT_KS: Tuple[int, ...] = (1, 3, 5)
SMALL_SAMPLE_THRESHOLD = 5

# Families whose inputs are structurally near-identical but whose correct tactic
# differs — the cases the char-ngram retrieval baseline confused. Used to build
# a confusion table comparing baselines.
SIBLING_GROUPS: Dict[str, Tuple[str, ...]] = {
    "and_elim": ("and_elim_left", "and_elim_right"),
    "or_intro": ("or_intro_left", "or_intro_right"),
    "iff": ("iff_mp", "iff_mpr", "iff_intro"),
    "imp": ("imp_identity", "imp_compose", "modus_ponens"),
    "eq": ("eq_refl", "eq_symm", "eq_trans"),
}


# ---------------- verification cache ----------------


def _cache_key(theorem_name: str, tactic: str) -> str:
    """Stable hash combining theorem identity + the literal tactic string.
    Mirrors what the task brief asked for: ``theorem_name + tactic hash``."""
    h = hashlib.sha256()
    h.update(theorem_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(tactic.encode("utf-8"))
    return h.hexdigest()


@dataclass
class VerificationCache:
    """JSON-on-disk cache for Lean verification results.

    A miss runs the verifier; a hit returns the previously-stored result. We
    save *only* on explicit :meth:`save` (the eval loop does it once at the
    end) so a SIGINT mid-run doesn't truncate the file.
    """

    path: Optional[Path] = None
    enabled: bool = True
    _store: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dirty: bool = False

    @classmethod
    def load(cls, path: Optional[Path], *, enabled: bool = True) -> "VerificationCache":
        c = cls(path=path, enabled=enabled)
        if not enabled or path is None:
            return c
        if path.exists():
            try:
                c._store = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not read verification cache %s: %s", path, exc)
                c._store = {}
        return c

    def save(self) -> None:
        if not self.enabled or self.path is None or not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._store, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False

    def get(self, theorem_name: str, tactic: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        return self._store.get(_cache_key(theorem_name, tactic))

    def put(self, theorem_name: str, tactic: str, value: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        self._store[_cache_key(theorem_name, tactic)] = dict(value)
        self.dirty = True

    def __len__(self) -> int:
        return len(self._store)


# ---------------- verifier ----------------


VerifierFn = Callable[[str, str, str], Dict[str, Any]]
# (theorem_name, theorem_statement, tactic) -> {"success": bool, "error": str|None, "elapsed_ms": float}


def make_lean_cli_verifier(timeout: float = 30.0) -> VerifierFn:
    """Default verifier: spawn :class:`LeanCliRunner`, build a synthetic seed
    for each call (reconstructing the basic-corpus template convention
    ``example <statement> := by\\n  __TACTIC__``), and report whether lean
    accepts the candidate."""
    runner = LeanCliRunner()

    def verify(theorem_name: str, theorem_statement: str, tactic: str) -> Dict[str, Any]:
        seed = TheoremSeed(
            theorem_name=theorem_name,
            theorem_statement=theorem_statement,
            template=f"example {theorem_statement} := by\n  __TACTIC__",
            placeholder="__TACTIC__",
            imports=[],
        )
        state0 = runner.start(seed)
        t0 = time.perf_counter()
        try:
            res = runner.run_tactic(state0, tactic, timeout=timeout)
        finally:
            runner.close()
        return {
            "success": bool(res.success),
            "error": res.error,
            "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
        }

    return verify


def _verify_tactic(
    *, theorem_name: str, theorem_statement: str, tactic: str,
    verifier: VerifierFn, cache: VerificationCache,
) -> Dict[str, Any]:
    hit = cache.get(theorem_name, tactic)
    if hit is not None:
        return hit
    res = verifier(theorem_name, theorem_statement, tactic)
    cache.put(theorem_name, tactic, res)
    return res


# ---------------- evaluation ----------------


@dataclass
class EvaluationResult:
    metrics: Dict[str, Any]
    predictions: List[Dict[str, Any]]
    failures: List[Dict[str, Any]]


def _pass_at_k(verification_results: List[Dict[str, Any]], k: int) -> bool:
    """Returns True iff at least one of the first ``k`` deduped predictions
    typechecked. Empty input -> False (vacuously not a pass)."""
    if not verification_results:
        return False
    for r in verification_results[:k]:
        if r.get("success"):
            return True
    return False


def _topk_any_verified(predictions: Sequence[str], verified: frozenset, k: int) -> bool:
    if not predictions or not verified:
        return False
    for p in predictions[:k]:
        if p in verified:
            return True
    return False


def evaluate(
    baseline: Baseline,
    *,
    train: Sequence[Example],
    eval_examples: Sequence[Example],
    full_dataset: Sequence[Example],
    k_values: Sequence[int] = DEFAULT_KS,
    top_k: int = 5,
    verifier: Optional[VerifierFn] = None,
    cache: Optional[VerificationCache] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> EvaluationResult:
    """Run a fitted baseline on ``eval_examples``.

    ``full_dataset`` is the entire processed dataset (all splits); it feeds the
    oracle lookup so the eval row gets credit for verified alternates collected
    anywhere — but the *baseline itself* still sees only ``train``.

    ``verifier`` is optional. When omitted, only the offline exact-match
    metrics are populated; ``lean_pass_at_k`` and per-row ``lean_results`` are
    absent (not faked).
    """
    if cache is None:
        cache = VerificationCache(enabled=False)
    top_k = max(top_k, max(k_values))

    oracle = oracle_verified_lookup(full_dataset)

    predictions_rows: List[Dict[str, Any]] = []
    failures_rows: List[Dict[str, Any]] = []
    exact_top1 = 0
    any_verified_at_k = {k: 0 for k in k_values}
    pass_at_k = {k: 0 for k in k_values}
    tactics_verified = 0
    tactics_total = 0
    oracle_hits = 0

    for i, ex in enumerate(eval_examples):
        # Some baselines (retrieval) also surface per-candidate provenance; we
        # take it when offered so predictions.jsonl can explain "why this tactic".
        if hasattr(baseline, "predict_with_neighbors"):
            preds, prov = baseline.predict_with_neighbors(ex, k=top_k)  # type: ignore[attr-defined]
        else:
            preds = baseline.predict(ex, k=top_k)
            prov = [{} for _ in preds]

        verified = oracle.get((ex.theorem_name, ex.state_before), frozenset())
        # Exact-match metrics
        top1_exact = bool(preds and preds[0] == ex.tactic)
        if top1_exact:
            exact_top1 += 1
        topk_any = {}
        for k in k_values:
            ok = _topk_any_verified(preds, verified, k)
            topk_any[k] = ok
            if ok:
                any_verified_at_k[k] += 1
        if verified:
            oracle_hits += 1

        row: Dict[str, Any] = {
            "theorem_name": ex.theorem_name,
            "theorem_statement": ex.theorem_statement,
            "state_before": ex.state_before,
            "ground_truth_tactic": ex.tactic,
            "split": ex.split,
            "predictions": preds,
            "verified_tactics_for_this_state": sorted(verified),
            "top1_exact": top1_exact,
            "topk_any_verified": {str(k): bool(v) for k, v in topk_any.items()},
            "prediction_provenance": prov,
        }

        # Lean verification
        if verifier is not None:
            ver_results: List[Dict[str, Any]] = []
            per_tac: Dict[str, Dict[str, Any]] = {}
            seen: set = set()
            for tac in preds:
                if tac in seen:
                    continue  # never run lean twice on the same tactic
                seen.add(tac)
                res = _verify_tactic(
                    theorem_name=ex.theorem_name,
                    theorem_statement=ex.theorem_statement,
                    tactic=tac,
                    verifier=verifier,
                    cache=cache,
                )
                per_tac[tac] = res
                ver_results.append(res)
                tactics_total += 1
                if res.get("success"):
                    tactics_verified += 1
                elif res.get("error"):
                    failures_rows.append(
                        {
                            "theorem_name": ex.theorem_name,
                            "tactic": tac,
                            "error": res["error"],
                        }
                    )
            row_pass = {}
            for k in k_values:
                ok = _pass_at_k(ver_results, k)
                row_pass[str(k)] = bool(ok)
                if ok:
                    pass_at_k[k] += 1
            row["lean_results"] = per_tac
            row["lean_pass_at_k"] = row_pass

        predictions_rows.append(row)
        if progress is not None:
            progress(i + 1, len(eval_examples))

    n = len(eval_examples)
    n_theorems = len({e.theorem_name for e in eval_examples})

    metrics: Dict[str, Any] = {
        "baseline": getattr(baseline, "name", baseline.__class__.__name__),
        "retrieval_mode": getattr(baseline, "mode", None),
        "n_examples": n,
        "n_theorems": n_theorems,
        "small_sample_warning": n <= SMALL_SAMPLE_THRESHOLD,
        "k_values": list(k_values),
        "top_k": top_k,
        "split_diagnostics": split_summary(train, eval_examples),
        "exact_match": {
            "top1_exact": exact_top1 / n if n else 0.0,
            "top1_exact_count": exact_top1,
            "topk_any_verified": {
                str(k): {"rate": (any_verified_at_k[k] / n) if n else 0.0,
                         "count": any_verified_at_k[k]}
                for k in k_values
            },
        },
        "oracle": {
            "rows_with_verified_in_corpus": oracle_hits,
            "rows_with_verified_in_corpus_rate": (oracle_hits / n) if n else 0.0,
        },
    }
    if verifier is not None:
        metrics["lean_verification"] = {
            "pass_at_k": {
                str(k): {"rate": (pass_at_k[k] / n) if n else 0.0, "count": pass_at_k[k]}
                for k in k_values
            },
            "tactics_total": tactics_total,
            "tactics_verified": tactics_verified,
            "cache_size": len(cache),
        }
    return EvaluationResult(metrics=metrics, predictions=predictions_rows, failures=failures_rows)


# ---------------- pattern-family analysis (optional, post-eval) ----------------


def load_family_maps(seeds_path: Path) -> Tuple[Dict[str, str], Dict[str, set]]:
    """From a seeds JSONL with ``metadata.pattern_family`` +
    ``metadata.expected_success_tactics``, build:

      - ``theorem -> pattern_family``
      - ``tactic -> {families that list it as expected-correct}`` (a tactic in
        exactly one family is unambiguous; shared tactics like ``rfl`` map to
        several).
    """
    from .io_utils import read_jsonl

    thm2fam: Dict[str, str] = {}
    tac2fams: Dict[str, set] = {}
    for row in read_jsonl(seeds_path):
        meta = row.get("metadata") or {}
        fam = meta.get("pattern_family")
        name = row.get("theorem_name")
        if not (name and fam):
            continue
        thm2fam[name] = fam
        for tac in meta.get("expected_success_tactics", []) or []:
            tac2fams.setdefault(tac, set()).add(fam)
    return thm2fam, tac2fams


def per_family_pass_at_k(
    predictions: Sequence[Dict[str, Any]],
    thm2fam: Mapping[str, str],
    k_values: Sequence[int] = DEFAULT_KS,
) -> Dict[str, Any]:
    """Pass@k (and top-5-any-verified) grouped by pattern family, over eval rows.

    Requires that ``predictions`` rows carry ``lean_pass_at_k`` (i.e. the eval
    was run with a verifier). Rows whose family is unknown are skipped.
    """
    by_fam: Dict[str, Dict[str, Any]] = {}
    for row in predictions:
        fam = thm2fam.get(row.get("theorem_name", ""))
        if fam is None:
            continue
        e = by_fam.setdefault(
            fam, {"n_rows": 0, "pass_at_k": {str(k): 0 for k in k_values},
                  "any_verified_top5": 0, "theorems": set()}
        )
        e["n_rows"] += 1
        e["theorems"].add(row["theorem_name"])
        pk = row.get("lean_pass_at_k", {})
        for k in k_values:
            if pk.get(str(k)):
                e["pass_at_k"][str(k)] += 1
        if row.get("topk_any_verified", {}).get("5"):
            e["any_verified_top5"] += 1

    out: Dict[str, Any] = {}
    for fam, e in sorted(by_fam.items()):
        n = e["n_rows"]
        out[fam] = {
            "n_rows": n,
            "n_theorems": len(e["theorems"]),
            "pass_at_k": {k: {"rate": (c / n) if n else 0.0, "count": c}
                          for k, c in e["pass_at_k"].items()},
            "any_verified_top5_rate": (e["any_verified_top5"] / n) if n else 0.0,
        }
    return out


def sibling_confusion(
    predictions: Sequence[Dict[str, Any]],
    thm2fam: Mapping[str, str],
    tac2fams: Mapping[str, set],
    groups: Mapping[str, Sequence[str]] = SIBLING_GROUPS,
) -> Dict[str, Any]:
    """For each sibling group, a confusion matrix of *true family* vs
    *predicted family*, where predicted family is inferred from the **top-1**
    predicted tactic via ``tac2fams``. A top-1 tactic that maps to exactly one
    family gives that family; otherwise it is bucketed ``"<ambiguous/other>"``.

    This is what reveals whether a baseline tells, e.g., ``and_elim_left`` from
    ``and_elim_right`` (vs. blindly copying a sibling's tactic).
    """
    OTHER = "<ambiguous/other>"

    def pred_family(top1: Optional[str]) -> str:
        if not top1:
            return OTHER
        fams = tac2fams.get(top1)
        return next(iter(fams)) if fams and len(fams) == 1 else OTHER

    result: Dict[str, Any] = {}
    for group_name, fams in groups.items():
        fam_set = set(fams)
        matrix: Dict[str, Dict[str, int]] = {}
        diag = total = 0
        for row in predictions:
            true_fam = thm2fam.get(row.get("theorem_name", ""))
            if true_fam not in fam_set:
                continue
            preds = row.get("predictions") or []
            pf = pred_family(preds[0] if preds else None)
            cell = matrix.setdefault(true_fam, {})
            cell[pf] = cell.get(pf, 0) + 1
            total += 1
            if pf == true_fam:
                diag += 1
        if total:
            result[group_name] = {
                "families": list(fams),
                "matrix": matrix,
                "top1_family_accuracy": diag / total,
                "n_rows": total,
            }
    return result
