"""Playwright runner — loads an ELF / website target and extracts visible text
plus runtime signals (console errors, page title, optional probe response).

Two extraction paths:
    - extract_elf_content()        — full Playwright/Chromium (handles JS/SPA)
    - extract_static_content()     — httpx + minimal HTML stripper (no JS)

The Playwright path is the canonical one for v0.2 .elf artifacts (which boot
a runtime). The static path is a fallback for plain static HTML and for
environments where Playwright's native deps haven't been installed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import httpx

# Playwright is imported lazily inside extract_elf_content() so that the rest
# of the foundry.judge package (heuristic, wiki fetch, LLM clients) stays
# importable on systems where Playwright/greenlet's binary deps haven't been
# installed yet (`playwright install` step missing, or VC++ runtime issue).


@dataclass
class ElfRun:
    target: str
    title: str
    url: str
    text: str
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    load_ms: float = 0.0
    bytes_text: int = 0

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "title": self.title,
            "url": self.url,
            "console_error_count": len(self.console_errors),
            "console_errors": self.console_errors[:20],
            "network_error_count": len(self.network_errors),
            "network_errors": self.network_errors[:20],
            "load_ms": round(self.load_ms, 1),
            "bytes_text": self.bytes_text,
        }


def _resolve_target(target: str) -> str:
    """Turn a local path into a file:// URL; pass URLs through."""
    if target.startswith(("http://", "https://", "file://", "about:")):
        return target
    p = Path(target).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"target does not exist: {target}")
    return p.as_uri()


def extract_elf_content(
    target: str,
    *,
    wait_selector: str | None = None,
    wait_ms: int = 3000,
    timeout_ms: int = 30000,
    max_chars: int = 50_000,
) -> ElfRun:
    """Load `target` in headless Chromium, return rendered text + runtime signals.

    `wait_selector` is optional; useful for ELF runtimes that expose a "ready"
    element after model load. Falls back to a fixed `wait_ms` settle delay.
    """
    try:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeout,
            sync_playwright,
        )
    except ImportError as e:
        raise RuntimeError(
            "playwright is not importable; install with `pip install playwright` "
            "and run `python -m playwright install chromium`"
        ) from e

    resolved = _resolve_target(target)
    console_errors: list[str] = []
    network_errors: list[str] = []
    t0 = time.perf_counter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        page.on("console", lambda msg: console_errors.append(msg.text)
                if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))
        page.on("requestfailed",
                lambda req: network_errors.append(f"{req.method} {req.url}: {req.failure}"))

        try:
            page.goto(resolved, timeout=timeout_ms, wait_until="domcontentloaded")
        except PlaywrightTimeout as e:
            browser.close()
            raise TimeoutError(f"page load timed out: {e}") from e
        except PlaywrightError as e:
            browser.close()
            raise RuntimeError(f"playwright failed to load {target!r}: {e}") from e

        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except PlaywrightTimeout:
                console_errors.append(f"wait_selector {wait_selector!r} never appeared")
        else:
            page.wait_for_timeout(wait_ms)

        title = page.title()
        try:
            text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except PlaywrightError as e:
            text = ""
            console_errors.append(f"innerText failed: {e}")
        url = page.url
        browser.close()

    load_ms = (time.perf_counter() - t0) * 1000
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]

    return ElfRun(
        target=target,
        title=title,
        url=url,
        text=text,
        console_errors=console_errors,
        network_errors=network_errors,
        load_ms=load_ms,
        bytes_text=len(text.encode("utf-8")),
    )


# ── Static (no-browser) extractor ────────────────────────────────────────────


class _TextExtractor(HTMLParser):
    """Minimal HTML → text. Drops <script>/<style>/<head>; preserves block breaks."""

    # Only tags with content; void tags (meta/link/img/br) carry no text and
    # would break depth tracking since they have no end tag.
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "head", "template", "svg"})
    _BLOCK_TAGS = frozenset({
        "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "tr", "td", "th", "section", "article", "header", "footer", "pre",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip_depth > 0:
            return
        self._chunks.append(data)

    def get_text(self) -> str:
        joined = "".join(self._chunks)
        # Collapse whitespace runs while keeping single newlines as paragraph breaks.
        joined = re.sub(r"[ \t\r\f\v]+", " ", joined)
        joined = re.sub(r"\n\s*\n+", "\n\n", joined)
        return joined.strip()


def extract_static_content(
    target: str,
    *,
    user_agent: str = "ELF-Foundry/0.1",
    timeout_s: float = 30.0,
    max_chars: int = 50_000,
) -> ElfRun:
    """No-browser fallback: httpx GET + minimal HTML strip.

    Cannot execute JavaScript — won't see anything an SPA renders client-side.
    Use this only for static .elf.html files or to bootstrap when Playwright
    isn't available.
    """
    t0 = time.perf_counter()
    if target.startswith(("http://", "https://")):
        try:
            r = httpx.get(
                target,
                headers={"User-Agent": user_agent},
                timeout=timeout_s,
                follow_redirects=True,
            )
            r.raise_for_status()
            html = r.text
            url = str(r.url)
        except httpx.HTTPError as e:
            raise RuntimeError(f"httpx failed to fetch {target!r}: {e}") from e
    else:
        p = Path(target).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"target does not exist: {target}")
        html = p.read_text(encoding="utf-8", errors="replace")
        url = p.as_uri()

    parser = _TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    title = parser.title.strip() or target

    if max_chars and len(text) > max_chars:
        text = text[:max_chars]

    return ElfRun(
        target=target,
        title=title,
        url=url,
        text=text,
        console_errors=[],
        network_errors=[],
        load_ms=(time.perf_counter() - t0) * 1000,
        bytes_text=len(text.encode("utf-8")),
    )
