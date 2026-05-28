"""Runtime configuration, sourced from environment variables.

We deliberately keep this small. Anything that varies per-run (output paths,
seed file, K candidates, prompt style, ...) is a CLI flag in scripts/, not an
env var. Secrets and machine-specific paths are the things that belong here.

Defaults are chosen so that the *mock* path requires no API keys, no Lean
toolchain, and no machine-specific paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw is not None and raw != "" else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _first_env(*names: str) -> Optional[str]:
    """Return the first non-empty value among the given env var names."""

    for name in names:
        val = os.environ.get(name)
        if val:
            return val
    return None


@dataclass(frozen=True)
class Settings:
    """Read-only application settings.

    Concrete CLI scripts merge these defaults with their own flags.
    """

    llm_backend: str = "mock"  # "mock" | "manual-file" | "anthropic" | "openai"
    llm_model: str = "claude-sonnet-4-6"
    lean_backend: str = "mock"  # "mock" | "lean-cli" | "leandojo"

    tactic_timeout_s: float = 10.0
    cache_dir: str = ".cache"

    # Lean
    lean_command: Optional[str] = None  # e.g. "lake env lean"; None => autodetect

    # Secrets / endpoints (only required by the matching real backend).
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None


def load_settings() -> Settings:
    """Build a Settings instance from the current process environment.

    Reads .env if python-dotenv is installed; otherwise relies solely on the
    process environment. We never raise on missing keys here; the LLM client
    raises at construction time if the selected backend needs a key.
    """

    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:  # pragma: no cover - optional dep
        pass

    return Settings(
        llm_backend=_env_str("MINI_ELF_LLM_BACKEND", "mock"),
        llm_model=_env_str("MINI_ELF_LLM_MODEL", "claude-sonnet-4-6"),
        lean_backend=_env_str("MINI_ELF_LEAN_BACKEND", "mock"),
        tactic_timeout_s=_env_float("MINI_ELF_TACTIC_TIMEOUT", 10.0),
        cache_dir=_env_str("MINI_ELF_CACHE_DIR", ".cache"),
        lean_command=_first_env("MINI_ELF_LEAN_COMMAND"),
        anthropic_api_key=_first_env("ANTHROPIC_API_KEY"),
        # MINI_ELF_OPENAI_API_KEY takes precedence, then the standard OPENAI_API_KEY.
        openai_api_key=_first_env("MINI_ELF_OPENAI_API_KEY", "OPENAI_API_KEY"),
        openai_base_url=_first_env("OPENAI_BASE_URL"),
    )
