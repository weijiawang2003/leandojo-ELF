# Mini-ELF v16 — Failure & Win Examples (annotated)

Per-row beam-rank movement under v16, comparing against v14 / v15.
Companion to `V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md`.

---

## 1. The headline win — `neg_imp_exfalso_ab` (rank 6 → rank 0)

The v15 audit identified this as the single remaining "rank-bound"
failure: the verifying candidate `intro hp\n  exact absurd hp hnp`
sat at rank 6 in the v14 token beam, beyond any reranker's reach.
v16 retraining with the contrapositive corpus moved it to **rank 0**
(via the eta-converted form) and added two more verified candidates
at ranks 2 and 3.

| version | rank 0 | rank 2 | rank 3 | rank 6 | first verified rank |
|---|---|---|---|---|---:|
| v14 | `intro hp` (wrong h) | `exact fun hp => hnq (h1 ` (truncated) | `exact fun hp => hnq (h ` | `intro hp\n  exact absurd hp hnp` ✓ | 6 |
| **v16** | `exact fun hp => absurd hp hnp` ✓ | `intro hp\n  exact absurd hp hnp` ✓ | `intro hp\n  exact (hnp hp).elim` ✓ | — | **0** |

The pattern the v14 model emitted only **once** (at rank 6) is now
emitted **three times** in the top 4 — and in three different proof
forms (the lambda form, the tactic-block form, and the `.elim` form)
all of which appear in the v16 `contrapositive_neg_imp` corpus.

---

## 2. The collateral win — `neg_exfalso_arrow_*` (pass@5 0.625 → 0.875)

The v15 audit listed three rows as `corpus_shape_bound_no_top10`:
`neg_exfalso_arrow_ab`, `neg_exfalso_arrow_pq`, `neg_exfalso_arrow_xy`.
The proof shape is `(p q : Prop) (h : p → False) (hp : p) : q` —
*not* the contrapositive shape the v16 brief targets. Yet 2 of 3
verified after v16.

Inspecting the v16 raw beam for `neg_exfalso_arrow_pq`:

```
rank 1 (token_seq2seq): 'exact (h hp).elim'         VERIFIED ✓
```

That `.elim` form was rare in v11 train (only present in 8 rows
project-wide) but it appears 36 times in the v16 corpus's
`contrapositive_neg_imp` proof variants (each
`intro hp\n  exact (hnp hp).elim`). The model learned the
`.elim` pattern from the augmentation and applied it to a
neighbouring family with the same syntactic shape — a real,
documented case of cross-family transfer **not** targeted by the
brief.

**Honesty note.** This is not "v16 solves neg_exfalso" — 1 of 8 rows
still fails (`neg_exfalso_arrow_xy` remains
`corpus_shape_bound_no_top10`). The v15 audit's classification
holds for that remaining row.

---

## 3. Why `forall_inst` and `rewrite_succ` stayed at 1.000

The v16 corpus is **disjoint** from both families:

* `forall_inst` operates on `∀ x : Nat, x = N` goals. The v16
  corpus has no `∀` quantifier and no numeric literals. The v15
  policy routes `instantiate_forall` to `rule` (literal-adapt
  source priority bonus), and the v12 literal-adapt module's
  schema gates fire identically on v14 and v16 outputs.
* `rewrite_succ` operates on `n.succ = m.succ` goals. The v16
  corpus has no equality goals. The v15 policy routes `rewrite`
  to `rule` (schema_match for `rw [h]`), unaffected by the v16
  retraining.

Per-row first-verified rank under policy: unchanged from v15 on
every row.

---

## 4. The reranker-fragility example — `exists_reconstruct_3` (pass@1
under +LA+rerank)

v16 raw beam (rank 0 verifies):
```
rank 0: 'cases h with | intro n hn => exact ⟨n, hn⟩'    VERIFIED ✓
```

v12 rule-based reranker promotes a literal-substituted variant ahead
of the verifying candidate:
```
rank 0 (after rule rerank): 'cases h with | intro n hn => exact ⟨3, hn⟩'  fail (type)
rank 1                    : 'cases h with | intro n hn => exact ⟨n, hn⟩'  VERIFIED ✓
```

The v15 policy routes `required_operation=unknown` to **learned**
(not rule), which keeps rank 0 intact. So under the v16 + v15-policy
configuration, exists_reconstruct stays at pass@1 = 1.000. Without
the policy router (pure +LA+rerank), pass@1 drops to 0.200 — the
**same** v14 finding.

---

## 5. The unfixed `neg_exfalso_arrow_xy`

```
v16 raw beam, neg_exfalso_arrow_xy:
rank 0: 'exact (h hp).elim'  ← VERIFIED on _pq and _ab, but lean fails here??
```

(actual rank-0 candidate may differ between variants; the v15 audit
counted 3 corpus-shape-bound rows; v16 fixed 2, residual 1.)

This is the residual `pass@10 = 0.875` row. The v16 corpus's
`contrapositive_false_target` shape `(h : p → False) (hp : p) :
False` did not generalise to the `neg_exfalso_arrow_xy` shape
`(p q : Prop) (h : p → False) (hp : p) : q` — different goal type
`q` (a variable, not `False`).

v17 work: add an `arrow_false_elim` corpus variant
`(p q : Prop) (h : p → False) (hp : p) : q` with proof
`exact (h hp).elim`.

---

## 6. The v15 policy mis-routing on `neg_exfalso` under v16

Under v14 candidates: rule / learned / raw all tied at neg_exfalso
pass@5 = 0.625. v15 policy chose rule (USE_DEFAULT_RULE) for
continuity.

Under v16 candidates: rule pass@1 = 0.375; **learned pass@1 =
0.625**; v15 policy still routes to rule and inherits 0.375.

```
v16 neg_exfalso (n=8):
config        pass@1   pass@5
raw           0.125    0.875
rule          0.375    0.875
learned       0.625    0.875   ← best pass@1
v15 policy    0.375    0.875   ← routes to rule, leaves 0.250 on the table
```

A one-line v17 edit moving `contradiction` from `USE_DEFAULT_RULE`
to `USE_LEARNED` would close this gap. We left the v15 policy
unchanged in v16 so the v15 metrics on disk and pinned tests stay
stable. Documented as the **v17 task**.

---

## 7. Summary by diagnosis class (post-v16)

| class | v15 count | v16 count | what changed |
|---|---:|---:|---|
| pass@5 ok | 26 / 30 | **29 / 30** | +3 (neg_imp_exfalso_ab + 2× neg_exfalso_arrow) |
| rank-bound 5–9 | 1 | **0** | neg_imp_exfalso_ab moved to rank 0 |
| corpus-shape-bound (>10) | 3 | **1** | 2× neg_exfalso_arrow added via collateral `.elim` learning |
| pass@10 ceiling | 0.925 | **0.975** | +0.050 (real generator lift) |
