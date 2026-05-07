"""MediaWiki ground-truth fetcher.

Uses the public MediaWiki action API (no key required) to retrieve a
plaintext article extract. Offline-friendly: callers should expect HTTP
errors and fall back gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class WikiArticle:
    title: str
    url: str
    extract: str
    pageid: int

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "pageid": self.pageid,
            "char_count": len(self.extract),
        }


class WikipediaError(RuntimeError):
    pass


def fetch_article(
    title: str,
    *,
    lang: str = "en",
    user_agent: str = "ELF-Foundry/0.1",
    timeout_s: float = 30.0,
    max_chars: int | None = None,
) -> WikiArticle:
    """Fetch a Wikipedia article as plaintext.

    Follows redirects automatically. Raises WikipediaError if the article
    is missing or the request fails.
    """
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts|info",
        "explaintext": "1",
        "redirects": "1",
        "inprop": "url",
        "format": "json",
        "titles": title,
    }
    headers = {"User-Agent": user_agent}

    try:
        r = httpx.get(url, params=params, headers=headers, timeout=timeout_s)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise WikipediaError(f"Wikipedia request failed for {title!r}: {e}") from e

    data = r.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        raise WikipediaError(f"Wikipedia returned no pages for {title!r}")

    page = next(iter(pages.values()))
    if "missing" in page:
        raise WikipediaError(f"Wikipedia article not found: {title!r}")

    extract = page.get("extract", "")
    if not extract:
        raise WikipediaError(f"Wikipedia article {title!r} has no extractable text")

    if max_chars is not None and len(extract) > max_chars:
        extract = extract[:max_chars]

    return WikiArticle(
        title=page["title"],
        url=page.get("fullurl", ""),
        extract=extract,
        pageid=page.get("pageid", 0),
    )
