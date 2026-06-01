"""Mini-ELF v34 — Part 3: artifact inventory.

Scans the repo and groups artifacts by version (v24..v33, plus a legacy bucket
for pre-v24 experiments). For each version it reports the scripts / docs / data
baselines / processed corpora / model dirs / tests that belong to it, with sizes
and counts. It also flags large artifacts, likely-obsolete scratch, duplicate
report families, and confirms the external Mathlib scratch project is outside
the repo (and therefore never tracked).

Stdlib only — runs under plain `python3`. Writes JSON to
data/baselines/v34_inventory/inventory.json; the curated headline metrics and
narrative live in docs/V34_ARTIFACT_INVENTORY.md.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Versions we inventory in detail (the Mathlib specialist phase + the protected
# broad-core model). Everything else (< v24) is bucketed as "legacy".
VERSIONS = [f"v{n}" for n in range(24, 34)]

SCAN_DIRS = {
    "scripts": ROOT / "scripts",
    "docs": ROOT / "docs",
    "tests": ROOT / "tests",
    "baselines": ROOT / "data" / "baselines",
    "processed": ROOT / "data" / "processed",
    "models": ROOT / "data" / "models",
    "seeds": ROOT / "data" / "seeds",
    "manual": ROOT / "data" / "manual",
    "src": ROOT / "src" / "mini_elf_lean",
}

EXTERNAL_SCRATCH = Path.home() / "code" / "mini_elf_mathlib_probe"

# version token: vNN not followed by another digit (so "v3" never eats "v33").
_VER_RE = re.compile(r"v(\d{1,3})(?!\d)", re.IGNORECASE)


def du(path: Path) -> int:
    """Total bytes under path (file or dir), following no symlinks."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def human(n: int) -> str:
    f = float(n)
    for unit in ("B", "K", "M", "G"):
        if f < 1024 or unit == "G":
            return f"{f:.1f}{unit}" if unit != "B" else f"{int(f)}B"
        f /= 1024
    return f"{f:.1f}G"


def version_of(name: str) -> str | None:
    """Lowest-but-first version token in a name, normalized to vNN."""
    m = _VER_RE.search(name)
    if not m:
        return None
    return "v" + m.group(1)


def entries(d: Path) -> list[Path]:
    """Top-level entries of a scan dir (files for scripts/docs/tests/seeds/
    manual/src; immediate subdirs+files for baselines/processed/models)."""
    if not d.exists():
        return []
    return sorted(d.iterdir())


def main() -> int:
    inv: dict[str, dict] = {v: defaultdict(list) for v in VERSIONS}
    inv["legacy"] = defaultdict(list)
    sizes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for kind, d in SCAN_DIRS.items():
        for e in entries(d):
            # src/ holds routers named vNN_mathlib_router.py + shared modules
            v = version_of(e.name)
            bucket = v if v in inv else ("legacy" if v else None)
            if bucket is None:
                # shared / non-versioned (e.g. mathlib_batched_verifier.py)
                bucket = "shared"
                inv.setdefault("shared", defaultdict(list))
                sizes.setdefault("shared", defaultdict(int))
            sz = du(e)
            inv[bucket][kind].append({"name": e.name, "bytes": sz, "human": human(sz)})
            sizes[bucket][kind] += sz

    # ---- flags -------------------------------------------------------------
    flags: dict[str, object] = {}

    # large artifacts (> 5 MB single entry)
    large = []
    for d in (SCAN_DIRS["models"], SCAN_DIRS["baselines"], SCAN_DIRS["processed"]):
        for e in entries(d):
            sz = du(e)
            if sz > 5 * 1024 * 1024:
                large.append({"path": str(e.relative_to(ROOT)), "human": human(sz)})
    flags["large_artifacts_gt_5MB"] = sorted(large, key=lambda x: x["path"])

    # likely-obsolete scratch: stray *.log and *_stdout.log under data/
    logs = [str(p.relative_to(ROOT)) for p in (ROOT / "data").rglob("*.log")]
    flags["stray_logs"] = sorted(logs)

    # duplicate report families: count docs per version to spot heavy report sets
    flags["doc_counts_per_version"] = {
        v: len(inv[v]["docs"]) for v in list(VERSIONS) + ["legacy"] if inv.get(v)
    }

    # external scratch
    flags["external_mathlib_scratch"] = {
        "path": str(EXTERNAL_SCRATCH),
        "exists": EXTERNAL_SCRATCH.exists(),
        "inside_repo": str(EXTERNAL_SCRATCH).startswith(str(ROOT) + "/"),
        "human": human(du(EXTERNAL_SCRATCH)) if EXTERNAL_SCRATCH.exists() else "n/a",
        "note": "Outside the repo tree -> never tracked by git; keep separate.",
    }

    # protected / never-overwrite models present
    flags["protected_models_present"] = {
        "v24_broad_residual": (SCAN_DIRS["models"] / "token_seq2seq_v24_broad_residual").exists(),
        "v33_general_residual": (SCAN_DIRS["models"] / "token_seq2seq_v33_general_residual").exists(),
    }

    # ---- totals ------------------------------------------------------------
    totals = {}
    for bucket, byk in sizes.items():
        totals[bucket] = {"bytes": sum(byk.values()), "human": human(sum(byk.values())),
                          "by_kind": {k: human(v) for k, v in sorted(byk.items())}}

    out_dir = ROOT / "data" / "baselines" / "v34_inventory"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "versions_detailed": VERSIONS,
        "inventory": {b: {k: v for k, v in kinds.items()} for b, kinds in inv.items()},
        "totals": totals,
        "flags": flags,
    }
    (out_dir / "inventory.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- console summary ---------------------------------------------------
    print("=== Mini-ELF v34 artifact inventory ===")
    for v in list(VERSIONS) + ["legacy", "shared"]:
        if not inv.get(v):
            continue
        counts = {k: len(items) for k, items in inv[v].items() if items}
        tot = totals.get(v, {}).get("human", "0B")
        print(f"{v:8s} {tot:>8s}  " + "  ".join(f"{k}={n}" for k, n in sorted(counts.items())))
    print("\n-- flags --")
    print(f"large (>5MB): {len(flags['large_artifacts_gt_5MB'])} entries")
    print(f"stray logs:   {len(flags['stray_logs'])}")
    es = flags["external_mathlib_scratch"]
    print(f"external scratch: {es['path']} exists={es['exists']} inside_repo={es['inside_repo']} ({es['human']})")
    print(f"protected models: {flags['protected_models_present']}")
    print(f"\nwrote {out_dir / 'inventory.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
