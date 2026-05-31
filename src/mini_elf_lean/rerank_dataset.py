"""Mini-ELF v15 — candidate-outcome dataset for the learned reranker.

Walks v11/v12/v13/v14 predictions and verification caches and produces
one row per (theorem, candidate) pair with the lean-verified label,
the source it came from, beam rank, and a feature dict.

The schema is deliberately **flat** and **no `state_after`** anywhere
(the v15 brief is explicit: no `state_after`). Feature extraction is
torch-free pure Python so we can train a logistic regression without
adding a heavy dep.

Honesty contract (verbatim from the v15 brief):
  * Do not change token seq2seq generation.
  * Do not add new hand-written proof templates as the main solution.
  * Do not use manual oracle candidates.
  * Do not use state_after.
  * Do not revive leaked v10 metrics.
  * Do not claim full theorem proving.

Leakage rule: when evaluating on a held family, the reranker training
set must exclude every candidate row drawn from a theorem in that
family's test set. ``leave_family_out_split`` enforces this.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Set, Tuple)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# row dataclass
# --------------------------------------------------------------------------- #


@dataclass
class CandidateRow:
    """One (theorem, candidate) row with verified label + features.

    Honest scope:
      * ``verified`` is **always** sourced from lean (cached or run).
        We never label a row from a heuristic.
      * ``state_after`` is structurally absent from this class.
      * ``source_run`` distinguishes ``v11`` vs ``v12`` vs ``v14`` vs
        their ``timeout_rerun`` siblings — the trainer can class-weight
        or filter by source.
    """

    theorem_name: str
    family: str
    required_operation: Optional[str]
    theorem_statement: str
    state_before: str
    candidate: str
    candidate_source: str
    beam_rank: int
    verified: bool
    error_class: str  # "ok" if verified, else classified error string
    source_run: str   # 'v11','v12_raw','v12_literal_adapt_rerank','v14_raw','v14_literal_adapt_rerank',...
    split: str = "train"  # consumer can override

    def to_jsonable(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# error-class classifier (mirrors v14 eval taxonomy)
# --------------------------------------------------------------------------- #


def classify_error(err: Optional[str]) -> str:
    if err is None:
        return "ok"
    s = err.lower()
    if "timeout" in s:
        return "timeout"
    if "type mismatch" in s or "expected to have type" in s:
        return "type_mismatch"
    if "unknown identifier" in s:
        return "unknown_identifier"
    if "unknown tactic" in s:
        return "unknown_tactic"
    if ("unexpected end of input" in s or "unexpected token" in s
            or "unexpected" in s or "expected " in s):
        return "parse_error"
    if "unsolved goals" in s:
        return "unsolved_goals"
    if "invalid `⟨" in s or "invalid '⟨'" in s:
        return "anon_constructor"
    return "other"


# --------------------------------------------------------------------------- #
# IO helpers
# --------------------------------------------------------------------------- #


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _index_test_meta(fold_root: Path,
                    families: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """theorem_name -> a representative test-row dict carrying
    family/required_operation/state_before/theorem_statement. The
    predictions.jsonl files in v11/v12/v14 store only theorem_name and
    candidates, so we look up the rest here."""
    out: Dict[str, Dict[str, Any]] = {}
    for fam in families:
        for split in ("test.jsonl", "train.jsonl"):
            for r in _read_jsonl(fold_root / fam / split):
                nm = r.get("theorem_name")
                if nm and nm not in out:
                    out[nm] = {
                        "family": r.get("family", fam),
                        "required_operation": r.get("required_operation"),
                        "theorem_statement": r.get("theorem_statement", ""),
                        "state_before": r.get("state_before", ""),
                        "split_in_v11_lofo": (
                            "test" if split == "test.jsonl" else "train"),
                    }
    return out


# --------------------------------------------------------------------------- #
# candidate-row extraction (v14, v12, etc)
# --------------------------------------------------------------------------- #


def _extract_predictions(predictions_dir: Path, source_run: str,
                         family: str, meta: Mapping[str, Dict[str, Any]],
                         ) -> List[CandidateRow]:
    """Walk a predictions.jsonl tree and yield CandidateRow per
    (theorem, candidate, beam_rank) entry. Reads only fields present
    in the v12/v14 prediction schema (no state_after)."""
    p = predictions_dir / "predictions.jsonl"
    out: List[CandidateRow] = []
    for r in _read_jsonl(p):
        nm = r["theorem_name"]
        m = meta.get(nm) or {}
        cands = r.get("candidates") or []
        srcs = r.get("sources") or []
        vers = r.get("verifications") or []
        for i, c in enumerate(cands):
            src = srcs[i] if i < len(srcs) else "unknown"
            v = vers[i] if i < len(vers) else {}
            out.append(CandidateRow(
                theorem_name=nm,
                family=m.get("family", family),
                required_operation=m.get("required_operation"),
                theorem_statement=m.get("theorem_statement", ""),
                state_before=m.get("state_before", ""),
                candidate=c,
                candidate_source=src,
                beam_rank=i,
                verified=bool(v.get("success")),
                error_class=classify_error(v.get("error")),
                source_run=source_run,
            ))
    return out


def build_candidate_outcome_dataset(
    *,
    fold_root: Path,
    v12_root: Optional[Path] = None,
    v14_root: Optional[Path] = None,
    v13_rerun_root: Optional[Path] = None,
    v14_rerun_root: Optional[Path] = None,
    families: Sequence[str] = ("forall_inst", "rewrite_succ", "neg_exfalso",
                               "exists_reconstruct", "neg_imp_exfalso"),
) -> List[CandidateRow]:
    """Aggregate every predictions.jsonl row across the project history.
    Returns a list of CandidateRow (deduplicated by (theorem, candidate,
    source_run, beam_rank))."""
    meta = _index_test_meta(fold_root, families)
    rows: List[CandidateRow] = []

    # v12 configs (4 each)
    v12_root = v12_root or (fold_root.parent.parent / "baselines" / "v12_eval")
    if v12_root.exists():
        for fam in families:
            for cfg in ("raw", "literal_adapt", "rerank",
                        "literal_adapt_rerank"):
                d = v12_root / fam / cfg
                if d.exists():
                    rows.extend(_extract_predictions(
                        d, source_run=f"v12_{cfg}", family=fam, meta=meta))

    # v14 configs (raw, +LA+rerank)
    v14_root = v14_root or (fold_root.parent.parent / "baselines"
                            / "v14_token_seq2seq")
    if v14_root.exists():
        for fam in families:
            for cfg in ("raw", "literal_adapt_rerank"):
                d = v14_root / fam / cfg
                if d.exists():
                    rows.extend(_extract_predictions(
                        d, source_run=f"v14_{cfg}", family=fam, meta=meta))

    # Apply v13 and v14 timeout-rerun corrections — they flip the
    # verified label on specific (theorem, candidate) pairs.
    correction = _load_timeout_corrections(v13_rerun_root, v14_rerun_root)
    if correction:
        for r in rows:
            key = (r.theorem_name, r.candidate)
            new = correction.get(key)
            if new is not None and r.error_class == "timeout":
                r.verified = bool(new.get("success"))
                r.error_class = classify_error(new.get("error"))

    # Dedup by (theorem, candidate, source_run, beam_rank) - keep first
    seen = set()
    out: List[CandidateRow] = []
    for r in rows:
        k = (r.theorem_name, r.candidate, r.source_run, r.beam_rank)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _load_timeout_corrections(
    v13_root: Optional[Path], v14_root: Optional[Path],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Read the changed_results.jsonl files written by v13 and v14
    rerun scripts. Returns {(theorem_name, candidate): {success, error}}.
    Both files share the schema: each row has a ``rerun`` (v13) or
    direct ``rerun_success``/``rerun_error`` (v14) section."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for root in (v13_root, v14_root):
        if root is None or not root.exists():
            continue
        p = root / "changed_results.jsonl"
        for r in _read_jsonl(p):
            nm = r.get("theorem_name")
            cand = r.get("candidate")
            if not nm or cand is None:
                continue
            if "rerun" in r and isinstance(r["rerun"], dict):
                out[(nm, cand)] = r["rerun"]
            else:
                out[(nm, cand)] = {
                    "success": bool(r.get("rerun_success")),
                    "error": r.get("rerun_error"),
                }
    return out


# --------------------------------------------------------------------------- #
# split / leakage guard
# --------------------------------------------------------------------------- #


def leave_family_out_split(
    rows: Sequence[CandidateRow], held_family: str,
) -> Tuple[List[CandidateRow], List[CandidateRow]]:
    """Return (train_rows, eval_rows).

    ``eval_rows`` = all candidate rows whose theorem appears in
    ``held_family`` AND whose source run is a v14 config (so the
    reranker is judged on the same v14 candidates v14 was evaluated
    on).

    ``train_rows`` = everything else, with **every theorem in
    ``held_family`` excluded** regardless of source_run. This is the
    leakage guard the brief calls out.
    """
    held_theorems: Set[str] = {r.theorem_name for r in rows
                               if r.family == held_family}
    train: List[CandidateRow] = []
    evalr: List[CandidateRow] = []
    for r in rows:
        in_held = r.theorem_name in held_theorems
        if in_held:
            # any v14 candidate on this theorem is eval
            if r.source_run.startswith("v14_"):
                evalr.append(r)
            # else: dropped (held-out from train)
        else:
            train.append(r)
    return train, evalr


# --------------------------------------------------------------------------- #
# features
# --------------------------------------------------------------------------- #


_NUM_RE = re.compile(r"\d+")
_TACTIC_HEAD_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)")
_KNOWN_HEADS = (
    "exact", "intro", "intros", "apply", "rw", "rcases", "cases",
    "refine", "constructor", "use", "exists", "have", "show",
    "rfl", "simp", "omega", "decide", "trivial", "absurd",
    "linarith", "norm_num", "ring", "tauto", "exfalso",
    "contradiction", "by", "all_goals", "any_goals", "try",
)


def _hash_str(s: str, mod: int) -> int:
    h = 1469598103934665603
    for c in s.encode("utf-8"):
        h ^= c
        h = (h * 1099511628211) & ((1 << 64) - 1)
    return h % mod


def _tactic_head(t: str) -> str:
    m = _TACTIC_HEAD_RE.match(t)
    return m.group(1) if m else ""


def _candidate_literals(t: str) -> List[str]:
    return _NUM_RE.findall(t)


def _first_goal_literal(state: str) -> Optional[str]:
    """The first numeric literal appearing after the turnstile (`⊢`)
    in the goal block; used to test 'goal-literal match' features."""
    if not state:
        return None
    after_turn = state.split("⊢", 1)[-1]
    m = _NUM_RE.search(after_turn)
    return m.group(0) if m else None


def _is_malformed(t: str) -> bool:
    if not t.strip():
        return True
    opens = t.count("[") + t.count("(") + t.count("⟨") + t.count("{")
    closes = t.count("]") + t.count(")") + t.count("⟩") + t.count("}")
    if opens != closes:
        return True
    if t.strip().endswith(("[", "(", "{", ",", "→", "with", "wi")):
        return True
    for fused in ("refintro", "rwexact", "casexact", "introexact"):
        if fused in t:
            return True
    return False


# Pattern feature set the v15 brief explicitly names.
PATTERN_FEATURES: Tuple[str, ...] = (
    # general intros / structure
    "contains_intro", "contains_intros", "has_intro",
    "contains_apply", "contains_exact", "contains_refine",
    "contains_rfl",
    # contradiction patterns
    "contains_absurd", "contains_false_elim", "contains_exfalso",
    "contains_contradiction", "contains_application_h_hp",
    # rewrite patterns
    "contains_rw", "contains_congrArg", "contains_eq_symm",
    # exists patterns
    "contains_angle_open", "contains_cases", "contains_rcases",
    "contains_obtain", "contains_constructor",
    # disjunction
    "contains_or_intro_left", "contains_or_intro_right",
    "contains_inl", "contains_inr",
    # boilerplate flags
    "is_malformed", "is_truncated_shape",
    "has_goal_literal_match", "has_stale_literal",
    "has_known_head", "has_seq2seq_literal_adapt_source",
    "has_token_seq2seq_source",
    "tactic_has_newline", "tactic_has_semicolon",
    # required_operation alignment (a small set of operation labels we
    # know about; each becomes a boolean feature 'op_<name>')
    "op_instantiate_forall", "op_rewrite",
    "op_intro_negation", "op_contradiction",
    "op_exists_reconstruct", "op_disjunction_elim",
    "op_implication", "op_other",
)


_OPERATION_MAP = {
    "instantiate_forall": "op_instantiate_forall",
    "rewrite": "op_rewrite",
    "intro_negation": "op_intro_negation",
    "contradiction": "op_contradiction",
    "exists_reconstruct": "op_exists_reconstruct",
    "disjunction_elim": "op_disjunction_elim",
    "implication": "op_implication",
}


def extract_features(row: CandidateRow, *, hashed_dim: int = 256) -> Dict[str, float]:
    """Compute the numeric + hashed-ngram feature dict for one
    CandidateRow. Stable: same input ⇒ same output. Numeric features
    are 0/1 unless documented otherwise.
    """
    t = row.candidate or ""
    state = row.state_before or ""
    head = _tactic_head(t).lower()
    lits = _candidate_literals(t)
    goal_lit = _first_goal_literal(state)

    features: Dict[str, float] = {}

    # ---- pattern features ----
    pf = {k: 0.0 for k in PATTERN_FEATURES}
    pf["contains_intro"] = 1.0 if (" intro " in (" " + t + " ")
                                   or t.strip().startswith("intro")) else 0.0
    pf["contains_intros"] = 1.0 if "intros" in t else 0.0
    pf["has_intro"] = pf["contains_intro"] or pf["contains_intros"]
    pf["contains_apply"] = 1.0 if "apply " in t else 0.0
    pf["contains_exact"] = 1.0 if "exact " in t or t.strip().startswith("exact") else 0.0
    pf["contains_refine"] = 1.0 if "refine" in t else 0.0
    pf["contains_rfl"] = 1.0 if "rfl" in t else 0.0
    pf["contains_absurd"] = 1.0 if "absurd" in t else 0.0
    pf["contains_false_elim"] = 1.0 if "False.elim" in t else 0.0
    pf["contains_exfalso"] = 1.0 if "exfalso" in t else 0.0
    pf["contains_contradiction"] = 1.0 if "contradiction" in t else 0.0
    pf["contains_application_h_hp"] = 1.0 if re.search(
        r"\b[hH][a-z]*\s+[hH][a-z]+", t) else 0.0
    pf["contains_rw"] = 1.0 if (" rw " in (" " + t + " ")
                                or t.strip().startswith("rw")) else 0.0
    pf["contains_congrArg"] = 1.0 if "congrArg" in t else 0.0
    pf["contains_eq_symm"] = 1.0 if "Eq.symm" in t or ".symm" in t else 0.0
    pf["contains_angle_open"] = 1.0 if "⟨" in t else 0.0
    pf["contains_cases"] = 1.0 if "cases " in t else 0.0
    pf["contains_rcases"] = 1.0 if "rcases" in t else 0.0
    pf["contains_obtain"] = 1.0 if "obtain" in t else 0.0
    pf["contains_constructor"] = 1.0 if "constructor" in t else 0.0
    pf["contains_or_intro_left"] = 1.0 if "Or.inl" in t else 0.0
    pf["contains_or_intro_right"] = 1.0 if "Or.inr" in t else 0.0
    pf["contains_inl"] = 1.0 if "inl" in t else 0.0
    pf["contains_inr"] = 1.0 if "inr" in t else 0.0

    pf["is_malformed"] = 1.0 if _is_malformed(t) else 0.0
    truncated = (t.strip().endswith((".", "with", "wi", "[")) and not pf["is_malformed"])
    # ('is_malformed' already covers most truncations; keep separate flag
    # so the trainer can disentangle them)
    pf["is_truncated_shape"] = 1.0 if truncated else 0.0

    pf["has_goal_literal_match"] = (1.0 if (goal_lit and goal_lit in lits)
                                    else 0.0)
    pf["has_stale_literal"] = (1.0 if (goal_lit and lits
                                       and goal_lit not in lits) else 0.0)
    pf["has_known_head"] = 1.0 if head in _KNOWN_HEADS else 0.0
    pf["has_seq2seq_literal_adapt_source"] = (
        1.0 if row.candidate_source == "seq2seq_literal_adapt" else 0.0)
    pf["has_token_seq2seq_source"] = (
        1.0 if row.candidate_source == "token_seq2seq" else 0.0)

    pf["tactic_has_newline"] = 1.0 if "\n" in t else 0.0
    pf["tactic_has_semicolon"] = 1.0 if ";" in t else 0.0

    # required_operation features — all-zero if unknown / 'other'
    op = row.required_operation
    op_feat = _OPERATION_MAP.get(op or "", "op_other")
    pf[op_feat] = 1.0

    features.update(pf)

    # ---- scalar features ----
    features["beam_rank"] = float(row.beam_rank)
    features["beam_rank_norm"] = float(row.beam_rank) / 10.0
    features["candidate_len_chars"] = float(len(t))
    features["candidate_len_norm"] = min(1.0, len(t) / 80.0)
    features["bias"] = 1.0

    # ---- hashed char-3-gram features ----
    for i in range(len(t) - 2):
        g = t[i: i + 3]
        h = _hash_str(g, hashed_dim)
        features[f"ngram_{h}"] = features.get(f"ngram_{h}", 0.0) + 1.0
    # ---- hashed tactic-head feature (also gets one-hot id) ----
    features[f"head_{head}"] = 1.0
    # source bucket
    features[f"src_{row.candidate_source}"] = 1.0
    features[f"run_{row.source_run}"] = 1.0

    return features


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #


def write_rows(rows: Iterable[CandidateRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r.to_jsonable(), ensure_ascii=False) + "\n")


def read_rows(path: Path) -> List[CandidateRow]:
    out: List[CandidateRow] = []
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        d = json.loads(s)
        out.append(CandidateRow(**d))
    return out


@dataclass
class DatasetStats:
    n_total: int
    n_verified: int
    n_failed: int
    positive_fraction: float
    by_family: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_source_run: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_error_class: Dict[str, int] = field(default_factory=dict)

    def to_jsonable(self) -> Dict[str, Any]:
        return asdict(self)


def compute_stats(rows: Sequence[CandidateRow]) -> DatasetStats:
    n = len(rows)
    n_ver = sum(1 for r in rows if r.verified)
    by_fam: Dict[str, Dict[str, int]] = {}
    by_src: Dict[str, Dict[str, int]] = {}
    by_err: Dict[str, int] = {}
    for r in rows:
        d = by_fam.setdefault(r.family, {"n": 0, "verified": 0})
        d["n"] += 1
        d["verified"] += int(r.verified)
        s = by_src.setdefault(r.source_run, {"n": 0, "verified": 0})
        s["n"] += 1
        s["verified"] += int(r.verified)
        by_err[r.error_class] = by_err.get(r.error_class, 0) + 1
    return DatasetStats(
        n_total=n,
        n_verified=n_ver,
        n_failed=n - n_ver,
        positive_fraction=(n_ver / n if n else 0.0),
        by_family=by_fam,
        by_source_run=by_src,
        by_error_class=by_err,
    )


__all__ = [
    "CandidateRow",
    "DatasetStats",
    "PATTERN_FEATURES",
    "build_candidate_outcome_dataset",
    "classify_error",
    "compute_stats",
    "extract_features",
    "leave_family_out_split",
    "read_rows",
    "write_rows",
]
