"""Mini-ELF v43 — build the COARSE plan-gen corpus (C1 intermediate granularity).

`statement -> coarse_plan_str` where coarse plans keep arity but collapse arg types to ARG
(see plan_coarse.py). Mirrors v41's plangen builder exactly (same whole-proof source, same
tokenizer, train-only vocab, decontamination by tier name). Output: data/v43/corpora/coarseplan/.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

from mini_elf_lean.tactic_tokenizer import tokenize
from mini_elf_lean.token_seq2seq_dataset import SPECIALS, TokenVocab
from mini_elf_lean.plan_coarse import coarse_plan, coarse_to_str

WP = ROOT / "data/v40/corpora/wholeproof"
TIERS = ROOT / "data/v40/tiers"
OUT = ROOT / "data/v43/corpora/coarseplan"
PLAN_CAP = 56


def toks(s):
    return [t.text for t in tokenize(s)]


def fp(rows):
    h = hashlib.sha256()
    for r in rows:
        h.update((r["theorem_name"] + "\x1f" + r["tactic"] + "\n").encode())
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tier_names = set()
    for tf in ("tier_dev.jsonl", "tier_final.jsonl"):
        for ln in (TIERS / tf).read_text().splitlines():
            if ln.strip():
                tier_names.add(json.loads(ln)["full_name"])

    def load(split):
        return [json.loads(l) for l in (WP / f"{split}.jsonl").read_text().splitlines() if l.strip()]

    def build(rows):
        out, contam = [], 0
        for r in rows:
            if r["theorem_name"] in tier_names:
                contam += 1
                continue
            plan = coarse_plan(r["tactic"])
            if not plan:
                continue
            ps = coarse_to_str(plan)
            out.append({"theorem_name": r["theorem_name"], "theorem_statement": r["theorem_statement"],
                        "state_before": "", "tactic": ps, "n_steps": len(plan)})
        return out, contam

    plan_train, c1 = build(load("train"))
    plan_dev, c2 = build(load("dev"))
    print(f"coarse plan-gen: train={len(plan_train)} dev={len(plan_dev)} contam={c1 + c2}")

    cnt = Counter()
    for r in plan_train:
        for tk in toks(r["theorem_statement"]) + toks(r["tactic"]):
            cnt[tk] += 1
    itos, sv = list(SPECIALS), set(SPECIALS)
    for tk, c in cnt.most_common():
        if c >= 2 and tk not in sv:
            itos.append(tk); sv.add(tk)
    vocab = TokenVocab(itos)
    stoi, unk = vocab.stoi, vocab.unk_id

    plan_tok = set()
    for r in plan_train:
        plan_tok |= set(toks(r["tactic"]))

    def enc(rows, split):
        oov = tot = 0; kept = []
        for r in rows:
            cids = [stoi.get(tk, unk) for tk in toks(r["theorem_statement"])][:256]
            tt = toks(r["tactic"])
            if len(tt) > PLAN_CAP - 2:
                continue
            tids = [vocab.bos_id] + [stoi.get(tk, unk) for tk in tt] + [vocab.eos_id]
            for x in cids + tids:
                tot += 1; oov += (x == unk)
            r["cond_ids"] = cids; r["tgt_ids"] = tids; r["split"] = split; r["tier"] = "v43coarse"
            kept.append(r)
        return kept, oov / max(tot, 1)

    plan_train, po1 = enc(plan_train, "train")
    plan_dev, po2 = enc(plan_dev, "dev")

    (OUT / "vocab.json").write_text(vocab.to_json(), encoding="utf-8")
    for nm, rows in (("train", plan_train), ("dev", plan_dev)):
        with (OUT / f"{nm}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    man = {"vocab_size": len(vocab), "n_train": len(plan_train), "n_dev": len(plan_dev),
           "config": "v43_coarseplan", "max_cond_len": 256, "max_tgt_len": PLAN_CAP,
           "oov_train": round(po1, 5), "plan_lattice_tokens": len(plan_tok),
           "lenL_dist": dict(Counter(r["n_steps"] for r in plan_train))}
    (OUT / "manifest.json").write_text(json.dumps(man, indent=2))
    (OUT / "fingerprints.json").write_text(json.dumps({"train_sha256": fp(plan_train), "n_train": len(plan_train)}, indent=2))
    print(f"WROTE coarseplan vocab={len(vocab)} lattice={len(plan_tok)} OOV={po1:.4f}; lenL={man['lenL_dist']}")


if __name__ == "__main__":
    main()
