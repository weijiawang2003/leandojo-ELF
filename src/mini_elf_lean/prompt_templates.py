"""Prompt templates for the LLM tactic proposer.

We keep prompts in code (not in JSON/YAML) so type-checkers and grep work, and
so a prompt change shows up in a normal diff.

Four prompt *styles* shape what kind of candidates we ask for:

- ``conservative``  -- short, safe, single-token tactics.
- ``diverse``       -- genuinely different proof approaches (the default).
- ``no_automation`` -- explicitly forbid simp/aesop/omega/linarith/...
- ``tactic_block``  -- short 2-5 line tactic blocks instead of one-liners.

The style only changes the *instructions*; the verifier still has the final say.
"""

from __future__ import annotations

from typing import Optional

DEFAULT_PROMPT_STYLE = "diverse"
PROMPT_STYLES = ("conservative", "diverse", "no_automation", "tactic_block")

SYSTEM_PROMPT = """You are a Lean 4 tactic-suggestion assistant.

Your role: propose Lean tactics that an external verifier will execute. You are
not the judge; do not claim the proof is finished, and do not invent state.

Output rules:
- Return ONLY tactics. No prose, no explanations, no markdown fences, no numbering.
- Do NOT include `sorry`, `admit`, or `unsafe`.
- Prefer short, focused tactics over long combinators.
"""

# Style-specific guidance appended to the user message. Keep each entry to a
# couple of lines so the whole prompt stays cheap.
_STYLE_INSTRUCTIONS = {
    "conservative": (
        "Return up to {k} safe, single tactics, ONE PER LINE.\n"
        "Prefer the simplest closers: rfl, exact <hyp>, assumption, trivial, "
        "intro, constructor. Avoid heavy automation unless nothing else fits."
    ),
    "diverse": (
        "Return up to {k} GENUINELY DIFFERENT next tactics, ONE PER LINE.\n"
        "Vary the approach: a direct closer (rfl/exact/assumption), an "
        "introduction/destructuring step (intro/cases/constructor), a rewrite "
        "(rw/simp only), and at most one automation tactic. Do not repeat the "
        "same idea with trivial variations."
    ),
    "no_automation": (
        "Return up to {k} tactics, ONE PER LINE.\n"
        "DO NOT use automation tactics: no simp, simp_all, aesop, omega, "
        "linarith, nlinarith, ring, norm_num, decide, tauto, grind, exact?, "
        "apply?. Use explicit, elementary tactics only (rfl, exact, "
        "assumption, intro, apply, cases, constructor, rw)."
    ),
    "tactic_block": (
        "Return up to {k} SHORT TACTIC BLOCKS (2-5 lines each).\n"
        "Separate blocks with a single blank line. Each block should be a "
        "self-contained sequence of tactics (e.g. `intro h` then `exact h`). "
        "No prose between blocks."
    ),
}


def style_instructions(prompt_style: Optional[str], num_candidates: int) -> str:
    """Return the style-specific instruction block, defaulting to ``diverse``."""

    style = prompt_style if prompt_style in _STYLE_INSTRUCTIONS else DEFAULT_PROMPT_STYLE
    return _STYLE_INSTRUCTIONS[style].format(k=num_candidates)


def build_user_prompt(
    *,
    theorem_name: str,
    theorem_statement: str,
    state_before: str,
    num_candidates: int,
    prompt_style: Optional[str] = DEFAULT_PROMPT_STYLE,
) -> str:
    """Construct the user message for one proposal call."""

    return (
        f"Theorem: {theorem_name}\n"
        f"Statement:\n{theorem_statement}\n\n"
        f"Current proof state:\n{state_before}\n\n"
        f"{style_instructions(prompt_style, num_candidates)}"
    )
