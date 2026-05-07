"""End-to-end orchestration: load an ELF, fetch its Wikipedia ground truth,
ask a judge to score the candidate against the truth.

This is the discriminator's outermost public surface. It judges only what
Phase 1+2 produces; per PLAN.md hard constraint #3.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

from .clients import JUDGE_SYSTEM_PROMPT, JudgeError, LLMJudge
from .playwright_runner import ElfRun, extract_elf_content, extract_static_content
from .wikipedia import WikiArticle, WikipediaError, fetch_article


@dataclass
class JudgeReport:
    target: str
    wiki_topic: str
    provider: str
    judged_at: str
    accuracy_score: float
    style_score: float
    overall_score: float
    critique: str
    elf: dict = field(default_factory=dict)
    wiki: dict = field(default_factory=dict)
    raw_response: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _build_user_prompt(wiki: WikiArticle, elf: ElfRun, max_chars_per_block: int) -> str:
    wiki_block = wiki.extract[:max_chars_per_block]
    elf_block = elf.text[:max_chars_per_block]
    return (
        f"Topic: {wiki.title}\n"
        f"Wikipedia URL: {wiki.url}\n"
        f"Candidate target: {elf.target}\n"
        f"Candidate page title: {elf.title}\n"
        f"Console error count: {len(elf.console_errors)}\n\n"
        f"--- WIKIPEDIA GROUND TRUTH ---\n{wiki_block}\n\n"
        f"--- ELF CANDIDATE ---\n{elf_block}\n\n"
        "Return a JSON object as specified in the system prompt."
    )


def compare_elf_against_wiki(
    target: str,
    wiki_topic: str,
    judge: LLMJudge,
    *,
    wait_selector: str | None = None,
    max_chars_per_block: int = 8000,
    user_agent: str = "ELF-Foundry/0.1",
    timeout_s: float = 30.0,
    use_browser: bool = True,
) -> JudgeReport:
    """Run the full pipeline: load → fetch → judge → report.

    `use_browser=False` skips Playwright and falls back to httpx + minimal
    HTML strip; useful for static .elf.html files or when Playwright's native
    deps aren't installed.

    Errors at each stage are captured in the report (`error` field) rather
    than raised, so the caller always gets a structured result.
    """
    judged_at = dt.datetime.now(dt.timezone.utc).isoformat()

    # Stage 1 — load target.
    try:
        if use_browser:
            elf = extract_elf_content(target, wait_selector=wait_selector)
        else:
            elf = extract_static_content(target, user_agent=user_agent, timeout_s=timeout_s)
    except (TimeoutError, RuntimeError, FileNotFoundError) as e:
        return JudgeReport(
            target=target,
            wiki_topic=wiki_topic,
            provider=judge.name,
            judged_at=judged_at,
            accuracy_score=0.0,
            style_score=0.0,
            overall_score=0.0,
            critique=f"[playwright] failed to load target: {e}",
            error=str(e),
        )

    # Stage 2 — fetch wiki ground truth.
    try:
        wiki = fetch_article(
            wiki_topic,
            user_agent=user_agent,
            timeout_s=timeout_s,
        )
    except WikipediaError as e:
        return JudgeReport(
            target=target,
            wiki_topic=wiki_topic,
            provider=judge.name,
            judged_at=judged_at,
            accuracy_score=0.0,
            style_score=0.0,
            overall_score=0.0,
            critique=f"[wikipedia] {e}",
            elf=elf.to_dict(),
            error=str(e),
        )

    # Stage 3 — score.
    user_prompt = _build_user_prompt(wiki, elf, max_chars_per_block)
    try:
        scores = judge.score(JUDGE_SYSTEM_PROMPT, user_prompt)
    except JudgeError as e:
        return JudgeReport(
            target=target,
            wiki_topic=wiki_topic,
            provider=judge.name,
            judged_at=judged_at,
            accuracy_score=0.0,
            style_score=0.0,
            overall_score=0.0,
            critique=f"[judge:{judge.name}] {e}",
            elf=elf.to_dict(),
            wiki=wiki.to_dict(),
            error=str(e),
        )

    raw = scores.pop("raw_response", None)
    return JudgeReport(
        target=target,
        wiki_topic=wiki_topic,
        provider=judge.name,
        judged_at=judged_at,
        accuracy_score=scores["accuracy_score"],
        style_score=scores["style_score"],
        overall_score=scores["overall_score"],
        critique=scores["critique"],
        elf=elf.to_dict(),
        wiki=wiki.to_dict(),
        raw_response=raw,
    )
