"""Mini-ELF v44 — premise-conditioned whole-proof corpus (for the S2 oracle decomposition).

Like the v40 whole-proof corpus, but the conditioning is `PREM: p1 p2 … STMT: <statement>` where
p1..pk are the premise NAMES used in the gold proof (from LeanDojo annotated deps — never the gold
tactic text). At eval the same model is run with three premise sets {none, retrieved, gold}; the
gold arm is retriever-independent, so the (gold−none) gap (the S2 headline) holds regardless of any
trained retriever. A fraction of train rows get empty premises (dropout) so the model also handles
the no-premise arm in-distribution.

Decontaminated against the v44 hard tier (dev+test) by name and statement.
"""
from __future__ import annotations

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
from v40_wholeproof import state_to_example, whole_proof

RAW = ROOT / "data/v39/_raw/leandojo_benchmark_4/random"
HARD = ROOT / "outputs/v44/hard_tier"
OUT = ROOT / "data/v44/corpora/premcond"
COND_CAP, PROOF_CAP, MAX_PREM = 320, 48, 12


def toks(s):
    return [t.text for t in tokenize(s)]


def gold_premises(traced):
    names, seen = [], set()
    for tt in traced:
        ann = tt.get("annotated_tactic")
        if ann and len(ann) > 1 and ann[1]:
            for pr in ann[1]:
                fn = pr.get("full_name")
                if fn and fn not in seen:
                    seen.add(fn); names.append(fn)
    return names[:MAX_PREM]


def cond_text(premises, stmt):
    pstr = " ".join(premises) if premises else ""
    return f"PREM: {pstr} STMT: {stmt}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    contam_names, contam_stmts = set(), set()
    for tf in ("hard_dev.jsonl", "hard_test.jsonl"):
        f = HARD / tf
        if f.exists():
            for ln in f.read_text().splitlines():
                if ln.strip():
                    c = json.loads(ln); contam_names.add(c["full_name"]); contam_stmts.add(c["statement"].strip())
    # also decontaminate the v40 tiers (defensive)
    for tf in ("tier_dev.jsonl", "tier_final.jsonl"):
        f = ROOT / "data/v40/tiers" / tf
        if f.exists():
            for ln in f.read_text().splitlines():
                if ln.strip():
                    c = json.loads(ln); contam_names.add(c["full_name"]); contam_stmts.add(c["statement"].strip())
    print(f"decontam keys: {len(contam_names)} names")

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
            prem = gold_premises(tt)
            ct = toks(cond_text(prem, stmt))
            pt = toks(wp)
            if len(ct) > COND_CAP:
                drop["cond_long"] += 1; continue
            if len(pt) > PROOF_CAP - 2:
                drop["proof_long"] += 1; continue
            rows.append({"theorem_name": fn, "theorem_statement": stmt, "premises": prem,
                         "state_before": "", "tactic": wp, "n_tactics": len(tt)})
        return rows, drop

    t0 = time.time()
    train, trd = extract("train")
    dev, dvd = extract("val")
    seen, dedup = set(), []
    for r in train:
        k = (r["theorem_statement"], r["tactic"])
        if k not in seen:
            seen.add(k); dedup.append(r)
    train = dedup
    print(f"train {len(train)} (drops {dict(trd)}) dev {len(dev)} (drops {dict(dvd)}) {time.time()-t0:.0f}s")

    # vocab from train (cond + target), incl premise names tokenized
    cnt = Counter()
    for r in train:
        for tk in toks(cond_text(r["premises"], r["theorem_statement"])) + toks(r["tactic"]):
            cnt[tk] += 1
    itos, sv = list(SPECIALS), set(SPECIALS)
    for tk, c in cnt.most_common():
        if c >= 2 and tk not in sv:
            itos.append(tk); sv.add(tk)
    vocab = TokenVocab(itos)
    stoi, unk = vocab.stoi, vocab.unk_id
    print(f"vocab {len(vocab)}")

    # 15% of train rows get empty-premise conditioning (so no-premise arm is in-distribution)
    def enc(rows, split, prem_dropout=0.0):
        kept, oov, tot = [], 0, 0
        for i, r in enumerate(rows):
            prem = [] if (prem_dropout and (i * 2654435761) % 100 < prem_dropout * 100) else r["premises"]
            cids = [stoi.get(tk, unk) for tk in toks(cond_text(prem, r["theorem_statement"]))][:COND_CAP]
            tt = toks(r["tactic"])
            tids = [vocab.bos_id] + [stoi.get(tk, unk) for tk in tt] + [vocab.eos_id]
            for x in cids + tids:
                tot += 1; oov += (x == unk)
            rr = dict(r); rr["cond_ids"] = cids; rr["tgt_ids"] = tids
            rr["split"] = split; rr["tier"] = "v44premcond"
            kept.append(rr)
        return kept, oov / max(tot, 1)

    train, po1 = enc(train, "train", prem_dropout=0.15)
    dev, po2 = enc(dev, "dev", prem_dropout=0.0)

    (OUT / "vocab.json").write_text(vocab.to_json(), encoding="utf-8")
    for nm, rows in (("train", train), ("dev", dev)):
        with (OUT / f"{nm}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    man = {"config": "v44_premcond", "vocab_size": len(vocab), "n_train": len(train), "n_dev": len(dev),
           "max_cond_len": COND_CAP, "max_tgt_len": PROOF_CAP, "max_prem": MAX_PREM,
           "prem_dropout_train": 0.15, "oov_train": round(po1, 5),
           "avg_prem_train": round(sum(len(r["premises"]) for r in train) / max(len(train), 1), 2)}
    (OUT / "manifest.json").write_text(json.dumps(man, indent=2))
    print(f"WROTE premcond train={len(train)} dev={len(dev)} vocab={len(vocab)} OOV={po1:.4f} avgprem={man['avg_prem_train']}")


if __name__ == "__main__":
    main()
