# V44 Phase 1 — S2: the gold-premise oracle decomposition (the headline)

**Verdict: the S2 *surprise branch* fired — gold ≈ none on the hard tier. The bottleneck for a
generative prover on non-trivial theorems is NOT retrieval but *generation given premises*: even
the gold-premise ORACLE lifts a 30M premise-conditioned generator to only 1/26, while Lean's
`exact?` unification search solves 18/26 of the same theorems.**

Premise-conditioned AR & MDLM (30M, trained on the premcond corpus), three conditioning arms on the
hard **dev** tier (n=26), pass@10, `verify_many_bisect`. Premise sets: none / BM25-retrieved /
gold-names (retriever-independent; never the gold tactic). `outputs/v44/oracle/decomp_dev.json`.

## The decomposition table (hard_dev, n=26)

| arm | AR solved | MDLM solved | what it measures |
|---|---|---|---|
| none (no premises) | 0/26 | 0/26 | pure generation |
| **retrieved (BM25)** | **0/26** | **0/26** | realistic retrieval → generation |
| **gold (oracle)** | **1/26** | **1/26** | perfect retrieval → generation |
| — `exact?` (Lean unification search) | **18/26** | — | premise + library unification |
| — not even wide-sweep-solvable | 8/26 truly hard | — | needs multi-step reasoning |

**(gold − none) = +1/26 = +0.039 for both families.** The retrieved arm equals none (BM25 doesn't
surface the gold premises — recall@10 0.10, `V44_03`). The single theorem the oracle unlocks for
both is `IsUnit.isUnit_iff_mulRight_bijective` (`simp [mul_assoc]` — a one-premise simp the model can
emit).

## Why this is generation-bound, not a confound (the control)
A premise-conditioned generator with a tiny gold−none gap could mean (a) retrieval doesn't help, or
(b) the model never learned to use premises. The **conditioning control** (`cond_control.json`,
in-distribution corpus-dev, exact-seq) rules out (b) for AR:

| family | exact-seq none | exact-seq gold | gold − none |
|---|---|---|---|
| AR | 0.000 | **0.137** | **+0.137** |
| MDLM | 0.000 | 0.000 | 0.000 |

**AR genuinely exploits premises** — in-distribution, gold premises lift exact-seq from 0 to 13.7%.
So its near-zero gain on the *hard* tier is real: hard theorems are simply beyond what knowing the
premise-name buys a generator. (MDLM never learned to condition — consistent with its weak exact-seq,
V43-B2; it still picks up the one `simp [premise]` theorem by sampling, not by conditioning.)

## The mechanism (and why it refines V43)
The hard theorems ARE premise-addressable in principle: `exact?` solves **18/26** by searching the
library for a lemma and *unifying* it with the goal (trying all argument fillings). But a generator —
even handed the exact gold premise *name* — must emit the precise verifying tactic (`exact h.mp hx`,
`simp [lemma]` with the right lemma set, a 2-tactic sequence …), and at 30M it manages **1/26**. The
**18-vs-1 gap is the generation wall**: converting "the right lemma exists" into "the verified
tactic" is the hard part, and unification *search* dominates *generation* there.

This **refines V43's "premise knowledge is the wall."** On the mixed (mostly simp-closable) tiers,
gold plans + grounding reached 0.267 (V43) — premise selection looked like the ceiling. On the
genuinely *hard* tier, premise knowledge is **necessary but far from sufficient**: even perfect
premises leave the generator at 1/26. The wall on hard theorems is generation/search, not retrieval
alone.

## Falsifier verdict (pre-registered)
S2's pre-registered surprise branch — *"if gold ≈ none on the hard tier ⇒ generation, not
retrieval, is the bound — revisit V43's diagnosis"* — is **the outcome**. gold−none = +1/26 (tiny).
Generation-given-premises bounds the hard tier. Retrieval is *also* weak (BM25 recall 0.10), but
fixing retrieval cannot help a generator whose gold-oracle is already 1/26. The lever is
tactic-execution/search (à la `exact?`/`apply` with unification, hammer-style), not bigger
generators or (alone) better retrievers.
