"""
synthetic/discriminator.py
===========================
LLM-based discriminator for scoring synthetic ELF documents.

The discriminator uses an LLM WITH web search access to fact-check
each chunk in a generated ELF knowledge base and assign:

  - accuracy_score  (0.0–1.0): factual correctness vs. live web sources
  - style_score     (0.0–1.0): how well it matches the ELF wiki aesthetic
  - overall_score   (0.0–1.0): weighted combination

Output per document: a JSON report saved alongside the .elf.html.

This module is intentionally not implemented yet.
The architecture is designed so discriminator.py is a drop-in
addition to generator.py's batch_generate loop.

TODO (future):
  - Pick a web-search-capable LLM endpoint (Perplexity, Gemini + grounding,
    or Claude with web search tool).
  - Implement score_chunk(chunk, web_results) → float.
  - Implement score_document(kb_json) → DiscriminatorReport.
  - Wire into batch_generate as an optional --discriminate flag.
  - Use scores to filter training data: only keep docs with overall_score > 0.8.
"""

# Nothing to implement yet. See docstring above.
