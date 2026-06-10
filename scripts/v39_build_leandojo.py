"""Mini-ELF v39 — build a LeanDojo (Track B) corpus for the scale arm + crossover.

From LeanDojo Benchmark 4 random split: (full_name, state_before) -> tactic pairs,
in v38_data's row format (theorem_statement := full_name, so build_input_text =
full_name\\nstate_before). Own train-only vocab (frequency-capped), own dev set
(the official random/val split, theorem-disjoint). Length-FILTERED (not truncated)
to cond<=cond_cap, tactic<=tac_cap-2 tokens so nothing is silently cut. Decontam
vs the v35 24-theorem tier (full_name OR state_before match) per guardrail 5.

Outputs under --out: train.jsonl (MAX), dev.jsonl, vocab.json, manifest.json,
fingerprints.json. Rows carry precomputed cond_ids/tgt_ids under the NEW vocab.
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
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.tactic_tokenizer import tokenize
from mini_elf_lean.token_seq2seq_dataset import (PAD, BOS, EOS, UNK, SPECIALS,
                                                 build_input_text, TokenVocab)
from mini_elf_lean.v38_data import load_dataset, mathlib_test_tier

RAW = ROOT / "data" / "v39" / "_raw" / "leandojo_benchmark_4" / "random"


def toks(s: str):
    return [t.text for t in tokenize(s)]


def sha256_file(rows, key=("theorem_name", "state_before", "tactic")) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(("\x1f".join(str(r.get(k, "")) for k in key) + "\n").encode("utf-8"))
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cond-cap", type=int, default=128)
    ap.add_argument("--tac-cap", type=int, default=40)   # tgt_ids incl bos/eos <= tac_cap
    ap.add_argument("--dev-n", type=int, default=2000)
    ap.add_argument("--min-count", type=int, default=2, help="drop train tokens rarer than this -> unk")
    ap.add_argument("--out", default=str(ROOT / "data" / "v39" / "corpora" / "leandojo"))
    ap.add_argument("--seed", type=int, default=3407)
    args = ap.parse_args(argv)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    tac_content_cap = args.tac_cap - 2  # leave room for bos+eos

    # ---- decontamination keys from the v35 24-theorem tier ----
    ds = load_dataset()
    tier = mathlib_test_tier(ds["test"], cap=24)
    contam_names = {r["theorem_name"] for r in tier}
    contam_states = {r["state_before"].strip() for r in tier}
    contam_tactics = {r["tactic"].strip() for r in tier}

    def extract(split_file):
        data = json.load(open(RAW / split_file))
        out_steps = []
        for th in data:
            fn = th["full_name"]
            for st in th.get("traced_tactics", []):
                sb = st.get("state_before", "")
                tac = (st.get("tactic", "") or "").strip()
                if not tac or "sorry" in tac or "admit" in tac:
                    continue
                out_steps.append((fn, sb, tac))
        return out_steps, len(data)

    t0 = time.time()
    train_steps, n_tr_thm = extract("train.json")
    dev_steps, n_dev_thm = extract("val.json")
    print(f"raw steps: train={len(train_steps)} ({n_tr_thm} thm)  dev={len(dev_steps)} ({n_dev_thm} thm)  {time.time()-t0:.1f}s")

    # ---- single-pass tokenize + length filter + dedup + decontam ----
    def process(steps, *, is_train):
        seen, kept, dropped = set(), [], Counter()
        for fn, sb, tac in steps:
            if fn in contam_names or sb.strip() in contam_states or (tac.strip() in contam_tactics and sb.strip() in contam_states):
                dropped["contam"] += 1; continue
            ct = toks(build_input_text(fn, sb))
            if len(ct) > args.cond_cap:
                dropped["cond_long"] += 1; continue
            tt = toks(tac)
            if len(tt) > tac_content_cap:
                dropped["tac_long"] += 1; continue
            key = (sb.strip(), tac)
            if key in seen:
                dropped["dup"] += 1; continue
            seen.add(key)
            kept.append({"theorem_name": fn, "theorem_statement": fn, "state_before": sb,
                         "tactic": tac, "_ct": ct, "_tt": tt})
        return kept, dropped

    train_kept, tr_drop = process(train_steps, is_train=True)
    dev_kept, dv_drop = process(dev_steps, is_train=False)
    # dev theorems must be disjoint from train (official split; assert + enforce)
    train_names = {r["theorem_name"] for r in train_kept}
    dev_kept = [r for r in dev_kept if r["theorem_name"] not in train_names][: args.dev_n]
    print(f"kept: train={len(train_kept)}  dev={len(dev_kept)}")
    print(f"train drops: {dict(tr_drop)}")
    print(f"dev drops:   {dict(dv_drop)}")

    # ---- vocab from train only (freq-capped), insertion order cond-then-tac ----
    cnt = Counter()
    for r in train_kept:
        for tk in r["_ct"]:
            cnt[tk] += 1
    for r in train_kept:
        for tk in r["_tt"]:
            cnt[tk] += 1
    itos = list(SPECIALS)
    seenv = set(itos)
    # preserve first-seen order over cond texts then tac texts (matches TokenVocab.build)
    for r in train_kept:
        for tk in r["_ct"]:
            if tk not in seenv and cnt[tk] >= args.min_count:
                itos.append(tk); seenv.add(tk)
    for r in train_kept:
        for tk in r["_tt"]:
            if tk not in seenv and cnt[tk] >= args.min_count:
                itos.append(tk); seenv.add(tk)
    vocab = TokenVocab(itos)
    full_vocab_n = len(set(cnt)) + len(SPECIALS)
    print(f"vocab: {len(vocab)} (min_count={args.min_count}; full unique-token vocab would be {full_vocab_n})")

    stoi = vocab.stoi; unk = vocab.unk_id

    def encode_rows(rows):
        oov_tok, tot_tok = 0, 0
        for r in rows:
            cids = [stoi.get(tk, unk) for tk in r["_ct"]]
            tids = [vocab.bos_id] + [stoi.get(tk, unk) for tk in r["_tt"]] + [vocab.eos_id]
            for x in cids + tids:
                tot_tok += 1
                if x == unk:
                    oov_tok += 1
            r["cond_ids"] = cids
            r["tgt_ids"] = tids
            r["tier"] = "leandojo"
            r["split"] = "train" if rows is train_kept else "dev"
            del r["_ct"]; del r["_tt"]
        return oov_tok / max(tot_tok, 1)

    tr_oov = encode_rows(train_kept)
    dv_oov = encode_rows(dev_kept)
    print(f"OOV(unk) token rate: train={tr_oov:.4f} dev={dv_oov:.4f}")

    # ---- write ----
    (out / "vocab.json").write_text(vocab.to_json(), encoding="utf-8")
    with (out / "train.jsonl").open("w", encoding="utf-8") as f:
        for r in train_kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out / "dev.jsonl").open("w", encoding="utf-8") as f:
        for r in dev_kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {
        "config": "v39_leandojo_trackB", "source": "LeanDojo Benchmark 4 random split (Zenodo 15382959)",
        "cond_cap": args.cond_cap, "tac_cap": args.tac_cap, "min_count": args.min_count,
        "max_cond_len": args.cond_cap, "max_tgt_len": args.tac_cap, "vocab_size": len(vocab),
        "n_train": len(train_kept), "n_dev": len(dev_kept),
        "train_drops": dict(tr_drop), "dev_drops": dict(dv_drop),
        "oov_train": round(tr_oov, 5), "oov_dev": round(dv_oov, 5),
        "decontam_tier_names": len(contam_names), "uses_state_after": False,
        "note": "theorem_statement := full_name; build_input_text=full_name\\nstate_before; verified-eval is Track A only (distribution mismatch).",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "fingerprints.json").write_text(json.dumps({
        "train_sha256": sha256_file(train_kept), "dev_sha256": sha256_file(dev_kept),
        "n_train": len(train_kept), "n_dev": len(dev_kept), "vocab_size": len(vocab),
    }, indent=2), encoding="utf-8")
    print(f"WROTE {out}  train={len(train_kept)} dev={len(dev_kept)} vocab={len(vocab)}")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
