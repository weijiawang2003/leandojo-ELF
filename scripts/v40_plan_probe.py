"""Mini-ELF v40 — Phase 5: plan-level probe (LPSF-lite).

Factor each whole proof into a HEAD-PLAN: the sequence of tactic-head tokens only
(`intro simp exact ...`, <=8 slots). Reuses the whole-proof corpus statements + vocab
(heads already appear in the proof vocab). Build a `statement -> head_plan` corpus; the
caller trains a tiny FLOW and tiny AR on it. Question: at the plan level (short structured
object), does flow's per-token-vs-exact-seq coherence gap disappear or persist?
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

from mini_elf_lean.tactic_sanitizer import tactic_head
from mini_elf_lean.token_seq2seq_dataset import TokenVocab

SRC = ROOT / "data" / "v40" / "corpora" / "wholeproof"
OUT = ROOT / "data" / "v40" / "corpora" / "headplan"


def head_plan(proof: str, max_slots: int = 8) -> str:
    heads = []
    for line in proof.splitlines():
        line = line.strip()
        if not line:
            continue
        h = tactic_head(line) or line.split()[0] if line.split() else ""
        if h:
            heads.append(h)
    return " ".join(heads[:max_slots])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    vocab = TokenVocab.load(SRC / "vocab.json")
    man = json.loads((SRC / "manifest.json").read_text())
    max_tgt = 12  # <=8 heads + bos/eos + slack

    def convert(split):
        rows, oov_in = [], 0
        for ln in (SRC / f"{split}.jsonl").read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            hp = head_plan(r["tactic"])
            if not hp:
                continue
            tids = vocab.encode_target(hp)
            if len(tids) > max_tgt:
                tids = tids[:max_tgt - 1] + [vocab.eos_id]
            rows.append({"theorem_name": r["theorem_name"], "theorem_statement": r["theorem_statement"],
                         "state_before": "", "tactic": hp, "cond_ids": r["cond_ids"], "tgt_ids": tids,
                         "tier": "headplan", "split": split})
        return rows

    train, dev = convert("train"), convert("dev")
    with (OUT / "train.jsonl").open("w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT / "dev.jsonl").open("w", encoding="utf-8") as f:
        for r in dev:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "vocab.json").write_text(vocab.to_json(), encoding="utf-8")
    man2 = {**man, "config": "v40_headplan", "max_tgt_len": max_tgt, "n_train": len(train),
            "n_dev": len(dev), "note": "head-plan = tactic heads only, <=8 slots; reuses wholeproof vocab/statements"}
    (OUT / "manifest.json").write_text(json.dumps(man2, indent=2))
    from collections import Counter
    hc = Counter(h for r in train for h in r["tactic"].split())
    print(f"headplan corpus: train={len(train)} dev={len(dev)} distinct_heads={len(hc)} "
          f"top={[h for h,_ in hc.most_common(8)]}")
    print(f"mean plan len: {sum(len(r['tactic'].split()) for r in train)/max(len(train),1):.2f}")


if __name__ == "__main__":
    main()
