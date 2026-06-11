"""Mini-ELF v41 — build the two LPSF corpora from the v40 whole-proof corpus.

(1) plan-gen   `statement -> plan_str`           (the flow/AR target = compact plan).
(2) grounder   `statement PLAN: plan STEP: s PREV: prev -> tactic`  (teacher-forced expansion).
Shared train-only vocab (statements + plans + tactics + markers). v38_data-shaped rows with
precomputed cond_ids/tgt_ids. Decontamination is inherited (whole-proof corpus already excludes
the tier theorems); we re-confirm zero tier-name overlap.
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
from v41_plan_factorize import factorize_tactic, factorize_proof, plan_to_str

WP = ROOT / "data/v40/corpora/wholeproof"
TIERS = ROOT / "data/v40/tiers"
OUT_PLAN = ROOT / "data/v41/corpora/plangen"
OUT_GND = ROOT / "data/v41/corpora/grounder"
PLAN_CAP, GND_COND_CAP, TAC_CAP = 56, 288, 48


def toks(s):
    return [t.text for t in tokenize(s)]


def step_str(step):
    h, a = step
    return f"{h} ( {' , '.join(a)} )"


def fac_lines(proof):
    out = []
    for line in proof.splitlines():
        if factorize_tactic(line) is not None:
            out.append(line.strip())
        if len(out) >= 8:
            break
    return out


def fp(rows, key="tactic"):
    h = hashlib.sha256()
    for r in rows:
        h.update((r["theorem_name"] + "\x1f" + r[key] + "\n").encode())
    return h.hexdigest()


def main():
    OUT_PLAN.mkdir(parents=True, exist_ok=True); OUT_GND.mkdir(parents=True, exist_ok=True)
    tier_names = set()
    for tf in ("tier_dev.jsonl", "tier_final.jsonl"):
        for ln in (TIERS / tf).read_text().splitlines():
            if ln.strip():
                tier_names.add(json.loads(ln)["full_name"])

    def load(split):
        return [json.loads(l) for l in (WP / f"{split}.jsonl").read_text().splitlines() if l.strip()]
    wp_train, wp_dev = load("train"), load("dev")

    # ---- build plan-gen rows + grounder rows ----
    plan_train, plan_dev, gnd_train, gnd_dev, n_contam = [], [], [], [], 0
    def build(wp_rows, split):
        plan_out, gnd_out = [], []
        for r in wp_rows:
            if r["theorem_name"] in tier_names:
                return None  # signal contamination (shouldn't happen)
            plan = factorize_proof(r["tactic"])
            if not plan:
                continue
            ps = plan_to_str(plan)
            plan_out.append({"theorem_name": r["theorem_name"], "theorem_statement": r["theorem_statement"],
                             "state_before": "", "tactic": ps, "n_steps": len(plan), "stmt": r["theorem_statement"]})
            lines = fac_lines(r["tactic"])
            for i, tac in enumerate(lines[:len(plan)]):
                cond = f"{r['theorem_statement']} PLAN: {ps} STEP: {step_str(plan[i])} PREV: {' ; '.join(lines[:i])}"
                gnd_out.append({"theorem_name": r["theorem_name"], "theorem_statement": cond,
                                "state_before": "", "tactic": tac, "stmt": r["theorem_statement"],
                                "plan": ps, "step_i": i})
        return plan_out, gnd_out
    for split, wp_rows, P, G in (("train", wp_train, plan_train, gnd_train), ("dev", wp_dev, plan_dev, gnd_dev)):
        res = build(wp_rows, split)
        assert res is not None, "tier contamination in corpus!"
        P.extend(res[0]); G.extend(res[1])
    print(f"plan-gen: train={len(plan_train)} dev={len(plan_dev)}")
    print(f"grounder: train={len(gnd_train)} dev={len(gnd_dev)}")

    # ---- shared vocab from TRAIN (plan statements + plan strs + grounder conds + tactic targets) ----
    cnt = Counter()
    for r in plan_train:
        for tk in toks(r["theorem_statement"]) + toks(r["tactic"]):
            cnt[tk] += 1
    for r in gnd_train:
        for tk in toks(r["theorem_statement"]) + toks(r["tactic"]):
            cnt[tk] += 1
    itos, sv = list(SPECIALS), set(SPECIALS)
    for tk, c in cnt.most_common():
        if c >= 2 and tk not in sv:
            itos.append(tk); sv.add(tk)
    vocab = TokenVocab(itos)
    stoi, unk = vocab.stoi, vocab.unk_id
    print(f"shared vocab: {len(vocab)}")
    # plan-token usage size (the flow lattice)
    plan_tok = set()
    for r in plan_train:
        plan_tok |= set(toks(r["tactic"]))
    print(f"plan-target distinct tokens (flow lattice in usage): {len(plan_tok)}")

    def enc(rows, cond_cap, tgt_cap, split):
        oov = tot = 0; kept = []
        for r in rows:
            cids = [stoi.get(tk, unk) for tk in toks(r["theorem_statement"])]
            if len(cids) > cond_cap:
                cids = cids[:cond_cap]  # truncate (grounder conds can be long)
            tt = toks(r["tactic"])
            if len(tt) > tgt_cap - 2:
                continue
            tids = [vocab.bos_id] + [stoi.get(tk, unk) for tk in tt] + [vocab.eos_id]
            for x in cids + tids:
                tot += 1; oov += (x == unk)
            r["cond_ids"] = cids; r["tgt_ids"] = tids; r["split"] = split; r["tier"] = "v41"
            r.pop("stmt", None)
            kept.append(r)
        return kept, oov / max(tot, 1)

    plan_train, po1 = enc(plan_train, 256, PLAN_CAP, "train")
    plan_dev, po2 = enc(plan_dev, 256, PLAN_CAP, "dev")
    gnd_train, go1 = enc(gnd_train, GND_COND_CAP, TAC_CAP, "train")
    gnd_dev, go2 = enc(gnd_dev, GND_COND_CAP, TAC_CAP, "dev")

    def write(d, vocab, rows_tr, rows_dev, man_extra):
        (d / "vocab.json").write_text(vocab.to_json(), encoding="utf-8")
        for nm, rows in (("train", rows_tr), ("dev", rows_dev)):
            with (d / f"{nm}.jsonl").open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        man = {"vocab_size": len(vocab), "n_train": len(rows_tr), "n_dev": len(rows_dev), **man_extra}
        (d / "manifest.json").write_text(json.dumps(man, indent=2))
        (d / "fingerprints.json").write_text(json.dumps({"train_sha256": fp(rows_tr), "n_train": len(rows_tr)}, indent=2))
        return man

    mp = write(OUT_PLAN, vocab, plan_train, plan_dev,
               {"config": "v41_plangen", "max_cond_len": 256, "max_tgt_len": PLAN_CAP, "oov_train": round(po1, 5),
                "plan_lattice_tokens": len(plan_tok), "lenL_dist": dict(Counter(r["n_steps"] for r in plan_train))})
    write(OUT_GND, vocab, gnd_train, gnd_dev,
          {"config": "v41_grounder", "max_cond_len": GND_COND_CAP, "max_tgt_len": TAC_CAP, "oov_train": round(go1, 5)})
    print(f"WROTE plangen ({len(plan_train)}/{len(plan_dev)}) + grounder ({len(gnd_train)}/{len(gnd_dev)}); "
          f"vocab {len(vocab)}, plan-lattice {len(plan_tok)} tokens; OOV plan {po1:.4f} gnd {go1:.4f}; contam {n_contam}")


if __name__ == "__main__":
    main()
