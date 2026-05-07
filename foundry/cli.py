"""Foundry CLI — Typer entrypoint.

Available commands today:
    foundry judge wiki TARGET TOPIC [--provider P] [--out FILE]

Phase 1 will add `inspect`, `judge` (full rubric), `loop`, `export`. See
plans/foundry.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from .config import FoundryConfig
from .judge.clients import make_judge
from .judge.compare import compare_elf_against_wiki

app = typer.Typer(
    name="foundry",
    help="Foundry — Python GAN that bootstraps the wiki-brain corpus.",
    no_args_is_help=True,
)

judge_app = typer.Typer(name="judge", help="Score candidate ELFs / websites.")
app.add_typer(judge_app, name="judge")


@judge_app.command("wiki")
def judge_wiki(
    target: str = typer.Argument(
        ...,
        help="URL or local path of the .elf / website to judge.",
    ),
    topic: str = typer.Argument(
        ...,
        help="Wikipedia article title used as ground truth (e.g. 'Kalman filter').",
    ),
    provider: str = typer.Option(
        "heuristic",
        "--provider",
        "-p",
        help=(
            "LLM judge backend: heuristic | lmstudio | mercury | claude | gemini | openai. "
            "Falls back to heuristic if credentials are missing."
        ),
    ),
    wait_selector: str | None = typer.Option(
        None,
        "--wait-selector",
        help="CSS selector to wait for before extracting (e.g. '#elf-ready').",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Skip Playwright; httpx + HTML strip only. Use for static .elf.html.",
    ),
    max_chars: int = typer.Option(
        8000,
        "--max-chars",
        help="Max characters per text block sent to the judge.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Write the JSON report to this path. If omitted, prints to stdout.",
    ),
    pretty: bool = typer.Option(
        True,
        "--pretty/--no-pretty",
        help="Pretty-print JSON output.",
    ),
) -> None:
    """Judge a website / .elf candidate against a Wikipedia article."""
    cfg = FoundryConfig()
    judge = make_judge(provider, cfg)

    typer.secho(f"[foundry] target   = {target}", fg=typer.colors.CYAN)
    typer.secho(f"[foundry] topic    = {topic}", fg=typer.colors.CYAN)
    typer.secho(f"[foundry] provider = {judge.name}", fg=typer.colors.CYAN)

    report = compare_elf_against_wiki(
        target=target,
        wiki_topic=topic,
        judge=judge,
        wait_selector=wait_selector,
        max_chars_per_block=max_chars,
        user_agent=cfg.user_agent,
        timeout_s=cfg.request_timeout_s,
        use_browser=not no_browser,
    )

    payload = report.to_dict()
    text = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.secho(f"[foundry] wrote {out}", fg=typer.colors.GREEN)

    typer.echo(text)
    if report.error:
        sys.exit(1)


@app.command("providers")
def providers() -> None:
    """List configured judge providers and whether each has credentials."""
    cfg = FoundryConfig()
    rows = [
        ("heuristic", True, "always available (offline)"),
        ("lmstudio", True, f"local: {cfg.lmstudio_base_url} ({cfg.lmstudio_model})"),
        (
            "mercury",
            cfg.has_provider("mercury"),
            f"{cfg.mercury_base_url} ({cfg.mercury_model})",
        ),
        ("claude", cfg.has_provider("claude"), cfg.claude_model),
        ("gemini", cfg.has_provider("gemini"), cfg.gemini_model),
        (
            "openai",
            cfg.has_provider("openai"),
            f"{cfg.openai_base_url} ({cfg.openai_model})",
        ),
    ]
    typer.echo(f"{'provider':<12} {'available':<10} target")
    typer.echo("-" * 60)
    for name, ok, target in rows:
        marker = "yes" if ok else "no"
        color = typer.colors.GREEN if ok else typer.colors.RED
        typer.secho(f"{name:<12} {marker:<10} {target}", fg=color)


if __name__ == "__main__":
    app()
