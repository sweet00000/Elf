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
from .elf import BuildError, InspectError, build_single, inspect
from .elf.spec import Manifest
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


@app.command("inspect")
def inspect_cmd(
    path: Path = typer.Argument(..., help="Path to a .elf single-file HTML."),
    pretty: bool = typer.Option(True, "--pretty/--no-pretty"),
    out: Path | None = typer.Option(None, "--out", "-o"),
) -> None:
    """Parse a .elf, recompute fingerprint, verify each resource's sha256."""
    try:
        result = inspect(path)
    except InspectError as e:
        typer.secho(f"[foundry] inspect failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    payload = result.to_dict()
    text = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.secho(f"[foundry] wrote {out}", fg=typer.colors.GREEN)
    typer.echo(text)
    if not result.ok:
        raise typer.Exit(code=2)


@app.command("build")
def build_cmd(
    manifest_path: Path = typer.Argument(
        ...,
        help="Path to a manifest JSON file (matches ELF v0.2 schema).",
    ),
    resources_dir: Path = typer.Option(
        Path("."),
        "--resources",
        "-r",
        help=(
            "Directory containing resource bytes. Each manifest resource is "
            "looked up at <resources>/<resource.path>, falling back to "
            "<resources>/<resource.id>."
        ),
    ),
    out: Path = typer.Option(
        Path("output/build.elf.html"),
        "--out",
        "-o",
        help="Where to write the built .elf.",
    ),
) -> None:
    """Package a manifest + resource bytes into a single .elf HTML."""
    try:
        manifest_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        typer.secho(f"[foundry] cannot read manifest: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    try:
        manifest = Manifest.model_validate(manifest_dict)
    except Exception as e:
        typer.secho(f"[foundry] manifest invalid: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    resource_bytes: dict[str, bytes] = {}
    for r in manifest.resources:
        candidate = None
        if r.path:
            candidate = resources_dir / r.path
            if not candidate.exists():
                candidate = None
        if candidate is None:
            fallback = resources_dir / r.id
            if fallback.exists():
                candidate = fallback
        if candidate is None:
            if r.fetch_urls:
                continue  # reference-only allowed
            typer.secho(
                f"[foundry] resource {r.id!r}: bytes not found "
                f"(checked path={r.path!r}, id-fallback={r.id})",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        resource_bytes[r.id] = candidate.read_bytes()

    try:
        result = build_single(manifest, resource_bytes)
    except BuildError as e:
        typer.secho(f"[foundry] build failed:\n{e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    result.write(out)
    typer.secho(
        f"[foundry] built {out} ({result.byte_size} bytes, "
        f"fingerprint sha256:{result.fingerprint})",
        fg=typer.colors.GREEN,
    )
    typer.echo(json.dumps(result.summary(), indent=2))


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
