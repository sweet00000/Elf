"""Foundry runtime config. Offline-first; every external call gated by the
presence of an API key.

Resolution order: explicit __init__ args → environment variables →
`.env.local` (if present) → defaults.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FoundryConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic / Claude
    anthropic_api_key: str | None = Field(default=None)
    claude_model: str = Field(default="claude-opus-4-7")

    # Google Gemini
    gemini_api_key: str | None = Field(default=None)
    gemini_model: str = Field(default="gemini-2.0-flash")

    # Inception Mercury (diffusion LLM, OpenAI-compatible)
    mercury_api_key: str | None = Field(default=None)
    mercury_base_url: str = Field(default="https://api.inceptionlabs.ai/v1")
    mercury_model: str = Field(default="mercury-coder-small")

    # Local LMStudio (OpenAI-compatible)
    lmstudio_base_url: str = Field(default="http://localhost:1234/v1")
    lmstudio_api_key: str = Field(default="lm-studio")
    lmstudio_model: str = Field(default="local-model")

    # Generic OpenAI-compatible (for any other endpoint, e.g. Ollama, vLLM)
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o-mini")

    # Foundry paths
    library_dir: Path = Field(default=Path("library"))
    reports_dir: Path = Field(default=Path("library/reports"))

    # Cost guardrails
    max_cost_usd: float = Field(default=5.0)
    request_timeout_s: float = Field(default=120.0)
    user_agent: str = Field(default="ELF-Foundry/0.1 (https://github.com/sweet00000/Elf)")

    def has_provider(self, provider: str) -> bool:
        """Return True iff the named provider has the credentials it needs."""
        match provider:
            case "heuristic":
                return True
            case "lmstudio":
                return True  # local; key is a placeholder
            case "mercury":
                return bool(self.mercury_api_key)
            case "claude":
                return bool(self.anthropic_api_key)
            case "gemini":
                return bool(self.gemini_api_key)
            case "openai":
                return bool(self.openai_api_key)
        return False
