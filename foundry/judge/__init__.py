"""Foundry judge — discriminator package.

Compares an ELF / website's rendered content against a Wikipedia ground-truth
article and scores it via a pluggable LLM judge (heuristic / lmstudio / mercury
/ claude / gemini / openai).
"""

from .clients import HeuristicJudge, LLMJudge, make_judge
from .wikipedia import fetch_article

# `compare` and `playwright_runner` are NOT re-exported eagerly because
# importing `playwright` can fail on systems missing native deps; we want
# the heuristic + wiki + LLM clients to stay importable regardless.

__all__ = [
    "HeuristicJudge",
    "LLMJudge",
    "make_judge",
    "fetch_article",
]
