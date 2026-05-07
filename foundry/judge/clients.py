"""LLM judge clients — pluggable backends for scoring an ELF candidate.

Five providers shipped today:
    - heuristic   — offline, token-overlap Jaccard. Always available.
    - lmstudio    — OpenAI-compatible local endpoint (default :1234).
    - mercury     — Inception Labs Mercury diffusion LLM (OpenAI-compatible).
    - claude      — Anthropic Messages API.
    - gemini      — Google Generative Language API.
    - openai      — generic OpenAI-compatible (catch-all).

Each judge takes a (system, user) prompt pair and must return a dict shaped:

    {
        "accuracy_score": float in [0, 1],
        "style_score":    float in [0, 1],
        "overall_score":  float in [0, 1],
        "critique":       str,
        "raw":            optional raw provider response (omitted in heuristic),
    }

Caller is responsible for catching `JudgeError` and downgrading to heuristic.
"""

from __future__ import annotations

import abc
import json
import re
from collections.abc import Mapping
from typing import Any

import httpx


class JudgeError(RuntimeError):
    pass


# ── Helpers ──────────────────────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a possibly-noisy LLM response."""
    text = text.strip()
    # Strip ``` fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        raise JudgeError(f"could not parse JSON from response: {text[:200]!r}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise JudgeError(f"invalid JSON in response: {e}: {m.group(0)[:200]!r}") from e


def _coerce_score_dict(d: Mapping[str, Any]) -> dict:
    """Validate / coerce a judge response into the canonical shape."""
    def fclamp(v: Any) -> float:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, x))

    accuracy = fclamp(d.get("accuracy_score", d.get("accuracy", 0.0)))
    style = fclamp(d.get("style_score", d.get("style", 0.0)))
    overall = d.get("overall_score", d.get("overall"))
    if overall is None:
        overall = 0.6 * accuracy + 0.4 * style
    overall = fclamp(overall)
    critique = str(d.get("critique") or d.get("notes") or "")[:4000]
    return {
        "accuracy_score": accuracy,
        "style_score": style,
        "overall_score": overall,
        "critique": critique,
    }


# ── Base class ───────────────────────────────────────────────────────────────


class LLMJudge(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def score(self, system: str, user: str) -> dict:
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


# ── Heuristic (offline) ──────────────────────────────────────────────────────


_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def _tokenize(s: str) -> set[str]:
    return set(_TOKEN_RE.findall(s.lower()))


class HeuristicJudge(LLMJudge):
    """Token-set Jaccard between candidate text and ground-truth text.

    Expects the user prompt to contain two sections delimited by labels
    matching `--- WIKIPEDIA GROUND TRUTH ---` and `--- ELF CANDIDATE ---`.
    Falls back to whole-blob tokenization if those markers are absent.
    """

    name = "heuristic"

    def score(self, system: str, user: str) -> dict:
        wiki_text, elf_text = self._split(user)
        w = _tokenize(wiki_text)
        e = _tokenize(elf_text)
        if not w or not e:
            return _coerce_score_dict({
                "accuracy_score": 0.0,
                "style_score": 0.0,
                "overall_score": 0.0,
                "critique": "[heuristic] one of the two text blobs was empty",
            })
        jaccard = len(w & e) / len(w | e)
        coverage = len(w & e) / len(w)  # how much of wiki is reflected
        critique = (
            f"[heuristic] no LLM available. token Jaccard = {jaccard:.3f}, "
            f"wiki coverage = {coverage:.3f}, candidate tokens = {len(e)}, "
            f"wiki tokens = {len(w)}"
        )
        return _coerce_score_dict({
            "accuracy_score": coverage,
            "style_score": jaccard,
            "overall_score": 0.6 * coverage + 0.4 * jaccard,
            "critique": critique,
        })

    @staticmethod
    def _split(user: str) -> tuple[str, str]:
        """Best-effort split of the user prompt into (wiki, elf) sections."""
        wiki_marker = "--- WIKIPEDIA GROUND TRUTH ---"
        elf_marker = "--- ELF CANDIDATE ---"
        if wiki_marker in user and elf_marker in user:
            _, _, rest = user.partition(wiki_marker)
            wiki, _, elf = rest.partition(elf_marker)
            return wiki.strip(), elf.strip()
        return user, user


# ── Shared judge prompt ──────────────────────────────────────────────────────


JUDGE_SYSTEM_PROMPT = (
    "You are a strict fact-checking discriminator for ELF (Embedded Language "
    "Format) artifacts. You receive two blocks of text: the ground-truth "
    "Wikipedia extract for a topic, and the ELF candidate's rendered content. "
    "Score the candidate on:\n"
    "  - accuracy_score (0..1): factual alignment with Wikipedia. Penalize "
    "claims that contradict or hallucinate.\n"
    "  - style_score (0..1): clarity, structure, ELF-wiki aesthetic fit.\n"
    "  - overall_score (0..1): weighted combination, your judgment.\n"
    "Return ONLY a JSON object with keys "
    "{accuracy_score, style_score, overall_score, critique}. "
    "`critique` is at most 400 chars and lists concrete issues."
)


# ── OpenAI-compatible (LMStudio, Mercury, OpenAI proper, Ollama, vLLM) ──────


class OpenAICompatJudge(LLMJudge):
    """Any chat-completions endpoint that follows the OpenAI schema."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        name: str,
        timeout_s: float = 120.0,
        request_json_object: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name
        self.timeout_s = timeout_s
        self.request_json_object = request_json_object

    def score(self, system: str, user: str) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
        }
        if self.request_json_object:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise JudgeError(f"{self.name} request failed: {e}") from e
        data = r.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise JudgeError(f"{self.name} response missing content: {data!r}") from e
        parsed = _extract_json(content)
        out = _coerce_score_dict(parsed)
        out["raw_response"] = content
        return out


# ── Anthropic / Claude ───────────────────────────────────────────────────────


class AnthropicJudge(LLMJudge):
    name = "claude"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-opus-4-7",
        timeout_s: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def score(self, system: str, user: str) -> dict:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": 0.0,
        }
        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise JudgeError(f"claude request failed: {e}") from e
        data = r.json()
        try:
            content = data["content"][0]["text"]
        except (KeyError, IndexError) as e:
            raise JudgeError(f"claude response missing text: {data!r}") from e
        parsed = _extract_json(content)
        out = _coerce_score_dict(parsed)
        out["raw_response"] = content
        return out


# ── Google Gemini ────────────────────────────────────────────────────────────


class GeminiJudge(LLMJudge):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout_s: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def score(self, system: str, user: str) -> dict:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }
        try:
            r = httpx.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=self.timeout_s,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise JudgeError(f"gemini request failed: {e}") from e
        data = r.json()
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise JudgeError(f"gemini response missing text: {data!r}") from e
        parsed = _extract_json(content)
        out = _coerce_score_dict(parsed)
        out["raw_response"] = content
        return out


# ── Factory ──────────────────────────────────────────────────────────────────


_KNOWN_PROVIDERS = frozenset({
    "heuristic", "lmstudio", "mercury", "claude", "gemini", "openai",
})


def make_judge(provider: str, config) -> LLMJudge:
    """Build the requested judge from a FoundryConfig.

    - Unknown provider name → raises JudgeError.
    - Known online provider with no credentials → falls back to HeuristicJudge
      (offline-first contract from PLAN.md hard constraint #2).
    """
    provider = (provider or "heuristic").lower()

    if provider not in _KNOWN_PROVIDERS:
        raise JudgeError(
            f"unknown provider: {provider!r}. "
            f"Known: {sorted(_KNOWN_PROVIDERS)}"
        )

    if provider == "heuristic":
        return HeuristicJudge()

    if not config.has_provider(provider):
        h = HeuristicJudge()
        h.name = f"heuristic (fallback from {provider}: missing credentials)"
        return h

    if provider == "lmstudio":
        return OpenAICompatJudge(
            base_url=config.lmstudio_base_url,
            api_key=config.lmstudio_api_key,
            model=config.lmstudio_model,
            name="lmstudio",
            timeout_s=config.request_timeout_s,
        )
    if provider == "mercury":
        return OpenAICompatJudge(
            base_url=config.mercury_base_url,
            api_key=config.mercury_api_key,  # type: ignore[arg-type]
            model=config.mercury_model,
            name="mercury",
            timeout_s=config.request_timeout_s,
        )
    if provider == "openai":
        return OpenAICompatJudge(
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,  # type: ignore[arg-type]
            model=config.openai_model,
            name="openai",
            timeout_s=config.request_timeout_s,
        )
    if provider == "claude":
        return AnthropicJudge(
            api_key=config.anthropic_api_key,  # type: ignore[arg-type]
            model=config.claude_model,
            timeout_s=config.request_timeout_s,
        )
    if provider == "gemini":
        return GeminiJudge(
            api_key=config.gemini_api_key,  # type: ignore[arg-type]
            model=config.gemini_model,
            timeout_s=config.request_timeout_s,
        )
    raise JudgeError(f"unknown provider: {provider!r}")
