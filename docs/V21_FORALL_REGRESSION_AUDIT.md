# v21 forall regression audit

Read-only comparison of the v18 and v20 candidate beams on the 3 v18-broad-core `forall` theorems, to answer research question 1: **why did forall regress under v20?**

- forall theorems: 3
- regressed vs v18 (v18 solved, v20 fails): 2
- classified `schema_lost`: 2

## Diagnosis

schema_lost dominates: the instantiate-forall schema (`exact h <literal>` / `exact h <var>`) present in the v18 beam is ABSENT from the v20 beam. This is a single-model capacity / distribution tradeoff — the 948 implication+bool rows (45% of the 2099-row v20 pool) shifted the model's forall-goal output onto destructuring shapes (`exact h with ⟨..⟩`, `exact h ⟨..⟩`). It is NOT a ranking problem, so ranker-time abstraction cannot recover it; the fix is corpus rebalancing, higher capacity, or routing.

## Per-theorem detail

### `v18_forall_inst_at_7` — test — `schema_lost`

- statement: `(p : Nat → Prop) (h : ∀ n, p n) : p 7`
- expected head: `exact`
- first-verified rank — v18 broad-only: `0`, v18 panel: `0`, **v20: `None`**
- v18 broad-only instantiate-forall schema candidates: `['exact h 7', 'exact h p', 'exact h 5', 'exact h 3', 'exact h 4', 'exact h 13', 'exact h 8', 'exact h 9']`
- **v20 instantiate-forall schema candidates: `[]`** (SCHEMA ABSENT)
- v20 top-3 candidates:
  - `'exact h with ⟨n, hp⟩'`
  - `'exact h with ⟨n, hq⟩'`
  - `'exact h with ⟨hp, hq⟩'`
- v20 top-3 errors:
  - `/tmp/mini_elf_lean_ym_zk3ni.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_wg39dp5w.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_2piyei_h.lean:2:2: error: Type mismatch`

### `v18_forall_inst_compose` — train — `still_unsolved_in_v18`

- statement: `(p q : Nat → Prop) (h : ∀ n, p n → q n) (hp : p 5) : q 5`
- expected head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 panel: `None`, **v20: `None`**
- v18 broad-only instantiate-forall schema candidates: `['exact h 5', 'exact h p', 'exact h 3', 'exact h 4', 'exact h 8', 'exact h 9', 'exact h 13', 'exact h 7']`
- **v20 instantiate-forall schema candidates: `['exact h p']`** 
- v20 top-3 candidates:
  - `'exact h p'`
  - `'exact h hp hq'`
  - `'exact h with ⟨n, hp⟩'`
- v20 top-3 errors:
  - `/tmp/mini_elf_lean_9_xlbunw.lean:2:10: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_2zs721xf.lean:2:10: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_tzyeuapf.lean:2:2: error: Type mismatch`

### `v18_forall_to_arrow` — val — `schema_lost`

- statement: `(p q : Nat → Prop) (h : ∀ n, p n → q n) : p 3 → q 3`
- expected head: `exact`
- first-verified rank — v18 broad-only: `0`, v18 panel: `1`, **v20: `None`**
- v18 broad-only instantiate-forall schema candidates: `['exact h 3', 'exact h p']`
- **v20 instantiate-forall schema candidates: `[]`** (SCHEMA ABSENT)
- v20 top-3 candidates:
  - `'intro h\n  exact h ⟨ha, hb⟩'`
  - `'exact h ⟨ha, hb⟩'`
  - `'exact fun _ => h ⟨ha, hb⟩'`
- v20 top-3 errors:
  - `/tmp/mini_elf_lean_ypaxegda.lean:3:8: error: Function expected at`
  - `/tmp/mini_elf_lean_xk_dnbjq.lean:2:10: error: Invalid '⟨...⟩' notation: The expected type 'Nat' has more than one constr`
  - `/tmp/mini_elf_lean_fmxkpf95.lean:2:19: error: Invalid '⟨...⟩' notation: The expected type 'Nat' has more than one constr`

## Answer to RQ1

The forall regression is a **single-model capacity / distribution tradeoff**, not a ranking failure. v18's broad-synthetic model emitted `exact h 7` / `exact h 3` at rank 0 on the instantiation goals; v20's broad-plus model — after absorbing 759 implication + 189 bool rows (45 % of its 2,099-row pool) heavily featuring `with ⟨..⟩` / anonymous-constructor / `cases .. with` shapes — collapsed its forall-goal output onto those destructuring shapes and dropped the `exact h <arg>` instantiation schema from the beam entirely. Because the schema is **absent from the beam** (not merely demoted), no reranker — including v20's ranker-time abstract-pattern reranker — can recover it. The fix must restore the schema to generation: corpus rebalancing (Part 2), higher model capacity (Part 3 config D), or a forall specialist via model routing (Parts 3C / 5).
