# V41 Phase 1 — Plan language v2 (heads + typed slots) + corpora

A **plan** = sequence of ≤8 typed steps `head ( T1 , T2 , … )`, T ∈ {LEMMA, HYP, TERM, NONE}, dropping
concrete identifiers (the abstraction). `scripts/v41_plan_factorize.py`.

## Factorizer
- **Heads:** top ~28 tactic heads (LEMMAS rw/simp/simp_rw/rwa/dsimp/simpa/unfold…, HYPS intro/rintro,
  TERM exact/apply/refine/convert/have, TARGET cases/rcases/obtain/induction/subst/by_cases, NONE
  rfl/ring/omega/ext/constructor/…); the rest → `OTHER`. **Head coverage 92.1%** (>85% target).
- **Arg types per slot (≤3):** bracket contents → LEMMA; intro names → HYP; exact/apply args → TERM;
  cases/induction target → HYP; no-arg → NONE.
- **Plan-length distribution:** L1 23,522 · L2 14,648 · L3 5,140 · L4 1,638 · L5 409 → **48.7% multi-step**
  (this is why H14 stratifies by L — mode is 1). Slot types: LEMMA 70k, NONE 18k, TERM 17k, HYP 9k.

Round-trip samples (`proof → plan`): `simp [inter_assoc]`→`simp ( LEMMA )`; `rw [a,b]`→`rw ( LEMMA , LEMMA )`;
`induction' k with k ih ; rw […] ; exact …`→`induction' ( HYP ) ; rw ( LEMMA , LEMMA ) ; exact ( TERM )`.
(Combinators within a line, e.g. `cases f <;> rfl`, capture only the lead tactic — a known abstraction
loss, disclosed.)

## Corpora (`data/v41/corpora/`)
| corpus | rows (train/dev) | cond | target |
|--------|------------------|------|--------|
| **plangen** | 45,357 / 606 | statement | plan_str |
| **grounder** | 79,530 / 1,081 | `statement PLAN: <plan> STEP: <step> PREV: <prev tactics>` | the concrete tactic |

Shared train-only vocab **32,193** (OOV plan 0.000, grounder 0.001). **The plan-target lattice is 59
distinct tokens** — the small, well-separated space the LPSF bet wants for flow (vs token-level 24k).
0 tier-name contamination (inherited from the decontaminated whole-proof corpus). Fingerprints +
manifests committed; jsonl/vocab gitignored.
