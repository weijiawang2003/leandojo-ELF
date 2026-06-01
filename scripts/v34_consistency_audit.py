"""Mini-ELF v34 — Part 7: consistency / honesty audit.

Programmatically re-checks the project's standing honesty constraints and the
agreement of the headline numbers across the top-level docs. Stdlib only — runs
under plain `python3`. Writes data/baselines/v34_consistency/report.json; the
human summary is docs/V34_CONSISTENCY_AUDIT.md.

Checks:
  1. NO `state_after` anywhere in v25–v33 data (processed/seeds/manual).
  2. Every doc mention of "full theorem proving" is a disclaimer (negated).
  3. The v10 leakage guard test exists; no doc revives leaked combined_v10 as a
     headline result.
  4. The naive verifier is never the headline verifier (eval scripts use the
     trusted verifier; NaiveBatch appears only in tests / clearly-marked spots).
  5. README / RESULTS_SUMMARY / NEXT_STEPS / FINAL_REPORT agree on the final
     headline numbers (broad-core 0.9375/0.9583; routed tier-C 0.992 over 244).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def jsonl_files_v25_v33():
    pats = re.compile(r"v(2[5-9]|3[0-3])(?!\d)")
    roots = [ROOT / "data" / "processed", ROOT / "data" / "seeds", ROOT / "data" / "manual"]
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*.jsonl"):
            rel = str(p.relative_to(ROOT))
            if pats.search(rel):
                yield p


def check_no_state_after():
    offenders = []
    n_files = n_rows = 0
    for p in jsonl_files_v25_v33():
        n_files += 1
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            n_rows += 1
            if '"state_after"' in line:
                offenders.append(f"{p.relative_to(ROOT)}:{i+1}")
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "state_after" in obj:
                offenders.append(f"{p.relative_to(ROOT)}:{i+1}")
    return {"ok": not offenders, "n_files": n_files, "n_rows": n_rows,
            "offenders": offenders[:50]}


_NEG = ("no", "not", "never", "without", "avoid", "isn't", "is not", "don't",
        "do not", "claim", "n't", "deliberately", "out of scope", "imply",
        "indicate", "does not", "scope honesty")


def _strip_md(s: str) -> str:
    """Remove markdown emphasis/backticks/blockquote so '**no**' reads as 'no'."""
    return re.sub(r"[*_`>]", " ", s).lower()


def check_full_theorem_proving():
    pat = re.compile(r"full[\s-]?(theorem[\s-]?)?prov", re.IGNORECASE)
    hits, violations = [], []
    for p in sorted(DOCS.glob("*.md")):
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not pat.search(line):
                continue
            # check this line + the previous non-empty line (cross-line disclaimers)
            ctx = _strip_md(line)
            prev = _strip_md(lines[i - 1]) if i > 0 else ""
            words = set(re.findall(r"[a-z']+", ctx + " " + prev))
            disclaimer = any(tok in words for tok in _NEG) or \
                any(ph in (ctx + " " + prev) for ph in ("does not", "do not", "is not",
                                                        "out of scope", "scope honesty"))
            rec = {"file": p.name, "line": i + 1, "disclaimer": disclaimer,
                   "text": line.strip()[:140]}
            hits.append(rec)
            if not disclaimer:
                violations.append(rec)
    return {"ok": not violations, "n_hits": len(hits),
            "violations": violations, "sample_hits": hits[:8]}


def check_v10_leakage():
    """The constraint is: do NOT revive the *leaked* combined_v10 metrics as a
    headline. A doc that mentions combined_v10 is honest iff it also frames the
    leakage (clean re-measured tables + an explicit "leaked/corrected/invalid"
    note). We flag a doc only if it cites combined_v10 yet contains NO such
    framing anywhere — i.e. it could be passing leaked numbers off as real."""
    guard = ROOT / "tests" / "test_v10_no_leakage.py"
    frame = ("leak", "corrected", "superseded", "in-distribution", "memoris",
             "memoriz", "not actually held", "invalid", "not held-out", "bug",
             "earlier draft", "prior draft", "legacy")
    bad_docs = []
    pat = re.compile(r"combined_v10\b")
    for p in sorted(DOCS.glob("*.md")):
        txt = p.read_text(encoding="utf-8")
        if not pat.search(txt):
            continue
        low = txt.lower()
        if not any(t in low for t in frame):
            bad_docs.append(p.name)
    return {"ok": guard.exists() and not bad_docs, "guard_test_present": guard.exists(),
            "docs_citing_combined_v10_without_leakage_framing": bad_docs}


def check_naive_verifier():
    # headline eval scripts must use TrustedMathlibVerifier, not NaiveBatch.
    headline = list((ROOT / "scripts").glob("evaluate_v3*_routed_system.py")) + \
               list((ROOT / "scripts").glob("evaluate_v3*_mathlib_specialists.py"))
    bad = []
    for p in headline:
        txt = p.read_text(encoding="utf-8")
        if "NaiveBatch" in txt:
            bad.append(p.name)
        if "TrustedMathlibVerifier" not in txt:
            bad.append(f"{p.name} (no TrustedMathlibVerifier!)")
    # where does NaiveBatch appear at all?
    naive_uses = []
    for p in list((ROOT / "scripts").glob("*.py")) + list((ROOT / "tests").glob("*.py")):
        if "NaiveBatch" in p.read_text(encoding="utf-8"):
            naive_uses.append(str(p.relative_to(ROOT)))
    return {"ok": not bad, "headline_scripts_checked": len(headline),
            "bad": bad, "naive_appears_in": sorted(naive_uses)}


def check_metric_agreement():
    files = [ROOT / "README.md", DOCS / "RESULTS_SUMMARY.md", DOCS / "NEXT_STEPS.md",
             DOCS / "MINI_ELF_MATHLIB_FINAL_REPORT.md"]
    bc = re.compile(r"0\.9375\s*/\s*0\.9583")
    tc = re.compile(r"0\.992")
    n244 = re.compile(r"\b244\b")
    rows = {}
    for f in files:
        t = f.read_text(encoding="utf-8") if f.exists() else ""
        rows[f.name] = {"broad_core_0.9375/0.9583": bool(bc.search(t)),
                        "tierc_0.992": bool(tc.search(t)),
                        "n_244": bool(n244.search(t))}
    ok = all(all(v.values()) for v in rows.values())
    return {"ok": ok, "by_file": rows}


def main() -> int:
    report = {
        "1_no_state_after": check_no_state_after(),
        "2_full_theorem_proving_disclaimed": check_full_theorem_proving(),
        "3_v10_leakage_guarded": check_v10_leakage(),
        "4_naive_verifier_not_headline": check_naive_verifier(),
        "5_metric_agreement": check_metric_agreement(),
    }
    report["all_ok"] = all(v["ok"] for v in report.values() if isinstance(v, dict) and "ok" in v)

    out = ROOT / "data" / "baselines" / "v34_consistency"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== v34 consistency audit ===")
    print(f"1 no state_after (v25-v33 data): ok={report['1_no_state_after']['ok']} "
          f"({report['1_no_state_after']['n_rows']} rows / {report['1_no_state_after']['n_files']} files)")
    print(f"2 full-theorem-proving disclaimed: ok={report['2_full_theorem_proving_disclaimed']['ok']} "
          f"({report['2_full_theorem_proving_disclaimed']['n_hits']} mentions, "
          f"{len(report['2_full_theorem_proving_disclaimed']['violations'])} violations)")
    print(f"3 v10 leakage guarded: ok={report['3_v10_leakage_guarded']['ok']} "
          f"(guard test present={report['3_v10_leakage_guarded']['guard_test_present']})")
    print(f"4 naive verifier not headline: ok={report['4_naive_verifier_not_headline']['ok']} "
          f"(checked {report['4_naive_verifier_not_headline']['headline_scripts_checked']} headline scripts)")
    print(f"5 metric agreement: ok={report['5_metric_agreement']['ok']}")
    print(f"\nALL OK: {report['all_ok']}")
    print(f"wrote {out / 'report.json'}")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
