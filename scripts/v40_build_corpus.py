"""Mini-ELF v40 — whole-proof training corpus (statement -> whole_proof).

From LeanDojo train (corpus) + val (dev), reconstruct `example`-statement -> newline-joined
whole-proof pairs, train-only vocab, decontaminate vs BOTH real tiers + the v39 24-tier.
U-ladder {8k, 32k, MAX}. Rows are v38_data-shaped: theorem_statement=statement, state_before="",
tactic=whole_proof, precomputed cond_ids/tgt_ids. max_cond_len 256, max_tgt_len 48.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

from mini_elf_lean.tactic_tokenizer import tokenize
from mini_elf_lean.token_seq2seq_dataset import SPECIALS, TokenVocab
from mini_elf_lean.v38_data import load_dataset, mathlib_test_tier
from v40_wholeproof import state_to_example, whole_proof

RAW = ROOT / "data" / "v39" / "_raw" / "leandojo_benchmark_4" / "random"
OUT = ROOT / "data" / "v40" / "corpora" / "wholeproof"
TIERS = ROOT / "data" / "v40" / "tiers"


def toks(s):
    return [t.text for t in tokenize(s)]


def fp(rows):
    h = hashlib.sha256()
    for r in rows:
        h.update((r["theorem_name"] + "\x1f" + r["tactic"] + "\n").encode())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond-cap", type=int, default=256)
    ap.add_argument("--proof-cap", type=int, default=48)   # tgt_ids incl bos/eos
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--dev-n", type=int, default=1500)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    proof_content_cap = args.proof_cap - 2

    # decontam keys: both real tiers + v39 24-tier
    contam_names, contam_stmts = set(), set()
    for tf in ("tier_dev.jsonl", "tier_final.jsonl"):
        for ln in (TIERS / tf).read_text().splitlines():
            if ln.strip():
                c = json.loads(ln); contam_names.add(c["full_name"]); contam_stmts.add(c["statement"].strip())
    for r in mathlib_test_tier(load_dataset()["test"], cap=24):
        contam_names.add(r["theorem_name"]); contam_stmts.add(r["theorem_statement"].strip())

    def extract(split):
        data = json.load(open(RAW / f"{split}.json"))
        rows, drop = [], Counter()
        for th in data:
            tt = th.get("traced_tactics", [])
            if not tt:
                continue
            fn = th["full_name"]
            stmt = state_to_example(tt[0].get("state_before", ""))
            wp = whole_proof(tt)
            if stmt is None or wp is None:
                drop["unconvertible"] += 1; continue
            if fn in contam_names or stmt.strip() in contam_stmts:
                drop["contam"] += 1; continue
            ct, pt = toks(stmt), toks(wp)
            if len(ct) > args.cond_cap:
                drop["cond_long"] += 1; continue
            if len(pt) > proof_content_cap:
                drop["proof_long"] += 1; continue
            rows.append({"theorem_name": fn, "theorem_statement": stmt, "state_before": "",
                         "tactic": wp, "_ct": ct, "_pt": pt, "n_tactics": len(tt)})
        return rows, drop

    t0 = time.time()
    train, tr_drop = extract("train")
    dev_all, dv_drop = extract("val")
    # dedup train by (statement, proof)
    seen, dedup = set(), []
    for r in train:
        k = (r["theorem_statement"], r["tactic"])
        if k in seen:
            continue
        seen.add(k); dedup.append(r)
    train = dedup
    print(f"train kept {len(train)} (drops {dict(tr_drop)})  dev {len(dev_all)} (drops {dict(dv_drop)})  {time.time()-t0:.0f}s")

    # vocab from train only (freq-capped)
    cnt = Counter()
    for r in train:
        for tk in r["_ct"] + r["_pt"]:
            cnt[tk] += 1
    itos, sv = list(SPECIALS), set(SPECIALS)
    for key in ("_ct", "_pt"):
        for r in train:
            for tk in r[key]:
                if tk not in sv and cnt[tk] >= args.min_count:
                    itos.append(tk); sv.add(tk)
    vocab = TokenVocab(itos)
    stoi, unk = vocab.stoi, vocab.unk_id
    print(f"vocab {len(vocab)} (full {len(cnt)+len(SPECIALS)})")

    def enc(rows, split):
        oov = tot = 0
        for r in rows:
            cids = [stoi.get(tk, unk) for tk in r["_ct"]]
            tids = [vocab.bos_id] + [stoi.get(tk, unk) for tk in r["_pt"]] + [vocab.eos_id]
            for x in cids + tids:
                tot += 1; oov += (x == unk)
            r["cond_ids"] = cids; r["tgt_ids"] = tids; r["tier"] = "leandojo_wp"; r["split"] = split
            del r["_ct"]; del r["_pt"]
        return oov / max(tot, 1)
    tr_oov = enc(train, "train")
    dev = dev_all[: args.dev_n]
    dv_oov = enc(dev, "dev")
    # also drop the _ct/_pt from any leftover dev rows not encoded
    for r in dev_all[args.dev_n:]:
        r.pop("_ct", None); r.pop("_pt", None)
    print(f"OOV train {tr_oov:.4f} dev {dv_oov:.4f}")

    (OUT / "vocab.json").write_text(vocab.to_json(), encoding="utf-8")
    with (OUT / "train.jsonl").open("w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT / "dev.jsonl").open("w", encoding="utf-8") as f:
        for r in dev:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {
        "config": "v40_wholeproof", "source": "LeanDojo Benchmark 4 random/train+val",
        "max_cond_len": args.cond_cap, "max_tgt_len": args.proof_cap, "vocab_size": len(vocab),
        "n_train": len(train), "n_dev": len(dev), "min_count": args.min_count,
        "train_drops": dict(tr_drop), "dev_drops": dict(dv_drop),
        "oov_train": round(tr_oov, 5), "oov_dev": round(dv_oov, 5),
        "decontam_names": len(contam_names), "uses_state_after": False,
        "mean_n_tactics_train": round(sum(r["n_tactics"] for r in train) / max(len(train), 1), 2),
        "multi_tactic_frac_train": round(sum(r["n_tactics"] >= 2 for r in train) / max(len(train), 1), 3),
        "u_ladder": [8000, 32000, len(train)],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / "fingerprints.json").write_text(json.dumps(
        {"train_sha256": fp(train), "dev_sha256": fp(dev), "n_train": len(train), "vocab": len(vocab)}, indent=2))
    print(f"WROTE {OUT}  train={len(train)} dev={len(dev)} vocab={len(vocab)} "
          f"mean_tac={manifest['mean_n_tactics_train']} multi%={manifest['multi_tactic_frac_train']}")


if __name__ == "__main__":
    main()
