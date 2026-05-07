"""
synthetic/generator.py
======================
Synthetic ELF document generation pipeline.

Pipeline:
  1. topic_to_kb(topic, n_articles)  → KB dict (calls LLM)
  2. kb_to_elf(kb)                   → HTML string (calls elf_gen.build_html)
  3. save_elf(html, path)            → writes file
  4. batch_generate(topics_csv)      → runs 1–3 for each topic

This module is intentionally LLM-agnostic. Swap in any OpenAI-compatible
endpoint by setting ELF_LLM_BASE_URL and ELF_LLM_API_KEY env vars.
"""

import os, json, sys
from pathlib import Path

# TODO: import elf_gen.build_html once path is resolved
# sys.path.insert(0, str(Path(__file__).parent.parent))

ELF_LLM_BASE_URL = os.getenv("ELF_LLM_BASE_URL", "https://api.anthropic.com/v1")
ELF_LLM_API_KEY  = os.getenv("ELF_LLM_API_KEY",  "")

SCHEMA_PATH = Path(__file__).parent.parent / "kb" / "_schema.json"

GENERATOR_PROMPT = """
You are given a topic and must produce a complete ELF knowledge-base JSON
that conforms exactly to the schema in _schema.json.

Rules:
- Every article body must contain at least 3 content blocks.
- Every chunk must have at least 3 keywords and a complete, accurate answer.
- Do not hallucinate facts. If uncertain, mark the content clearly.
- Respond with raw JSON only. No markdown fences, no preamble.

Topic: {topic}
Target audience: {audience}
Accent color: {accent}
Number of articles: {n_articles}
"""

def topic_to_kb(topic: str, n_articles: int = 8, audience: str = "students",
                accent: str = "#ff6b3d") -> dict:
    """
    Call the configured LLM to generate a KB JSON for `topic`.
    Returns a parsed dict conforming to _schema.json.

    TODO: implement LLM call using ELF_LLM_BASE_URL + ELF_LLM_API_KEY.
    The prompt is GENERATOR_PROMPT.format(**kwargs).
    Parse the response as JSON. Validate against _schema.json.
    Retry up to 3 times on parse failure.
    """
    raise NotImplementedError("topic_to_kb: LLM call not yet implemented")

def kb_to_elf(kb: dict) -> str:
    """
    Call elf_gen.build_html(kb) and return the HTML string.
    TODO: resolve import path and call build_html.
    """
    raise NotImplementedError("kb_to_elf: import elf_gen and call build_html")

def save_elf(html: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    print(f"✓ {path}")

def batch_generate(topics: list[str], out_dir: Path = Path("output/synthetic")) -> None:
    """
    Generate one .elf.html per topic. Save to out_dir/<slug>.elf.html.
    Also save the raw KB JSON to out_dir/<slug>.json for inspection.
    TODO: add discriminator scoring call after each generation.
    """
    for topic in topics:
        slug = topic.lower().replace(" ", "_")[:40]
        print(f"Generating: {topic}")
        kb   = topic_to_kb(topic)
        html = kb_to_elf(kb)
        save_elf(html, out_dir / f"{slug}.elf.html")
        (out_dir / f"{slug}.json").write_text(json.dumps(kb, indent=2), encoding="utf-8")

if __name__ == "__main__":
    topics = sys.argv[1:] or ["Introduction to Thermodynamics"]
    batch_generate(topics)
