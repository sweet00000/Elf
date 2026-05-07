# synthetic/ — ELF synthetic data pipeline

A two-phase pipeline that generates ELF knowledge-base documents at scale and
filters them into clean training data for fine-tuning a small LLM that can
write ELF wikis on its own — fully in-browser, no API keys, no internet.

This directory is the engine behind the **Paid** tier on the landing page.
Everything here is currently a stub; this README explains the intended shape
so the implementation can land cleanly when we're ready.

---

## What this pipeline does

`synthetic/` turns a list of topics into a corpus of `.elf.html` documents,
scores each one for factual accuracy and stylistic fit, and exports the
high-scoring subset as JSONL training data.

The end goal is a 1–3B parameter model that, given a short topic prompt,
emits a valid ELF KB JSON that `elf_gen.py` can render — small enough to run
in-browser via `wllama` or `WebLLM`. Once that model exists, the entire
generator side of this pipeline collapses into a single browser tab.

We're bootstrapping it from larger frontier models for now. The synthetic
corpus is the bridge.

---

## Two-phase architecture

**Phase 1 — Generator (offline-friendly)**
`generator.py` takes a topic and produces a KB JSON conforming to
`kb/_schema.json`, then runs it through `elf_gen.build_html` to produce a
self-contained `.elf.html`. The LLM endpoint is configurable via
`ELF_LLM_BASE_URL` and `ELF_LLM_API_KEY` — any OpenAI-compatible API works,
including local servers (Ollama, llama.cpp, vLLM).

The generator does not need web access. It only needs a capable enough
language model to follow the schema.

**Phase 2 — Discriminator (web-enabled)**
`discriminator.py` takes a generated document and scores it. Critically, the
discriminator has live web access — it fact-checks chunks against current
sources rather than trusting the generator's training data. This is what
makes synthetic data viable: a fact-checked synthetic doc is better training
material than an unverified human-written one.

Each scored document gets a JSON report with `accuracy_score`, `style_score`,
and `overall_score`. Only documents above a threshold (default `0.8`) are
exported as training data.

The two phases are decoupled. You can run thousands of generations cheaply
on a local model, then discriminate selectively with an expensive web-search
endpoint — only paying for fact-checks on the candidates worth keeping.

---

## How to run (once implemented)

```bash
# generate documents from a list of topics
export ELF_LLM_API_KEY=sk-...
python synthetic/generator.py "Introduction to Thermodynamics" "Kalman Filters"

# discriminate everything in output/synthetic/ (future)
python synthetic/discriminator.py output/synthetic/

# export filtered training data (future)
python synthetic/export_training.py output/synthetic/ --threshold 0.8 --out training.jsonl
```

The pipeline is resumable: per-topic state lives in
`output/synthetic/<slug>.json` and `<slug>.score.json`, so re-running skips
work that's already done.

---

## Training data output format

Final output is a single JSONL file. One line per chunk (not per document) —
chunks are the atomic unit of an ELF KB, so a per-chunk format gives the
fine-tuning loop the most flexibility.

Each line:

```json
{
  "topic": "Introduction to Thermodynamics",
  "article_id": "first_law",
  "article_title": "The First Law",
  "keywords": ["energy", "conservation", "system"],
  "question": "What does the first law of thermodynamics state?",
  "content": "Energy in a closed system is conserved...",
  "discriminator_score": 0.92,
  "source_doc": "intro_to_thermodynamics.elf.html"
}
```

For a more conventional prompt→completion format, run
`export_training.py --format prompt_completion` to get topic→KB-JSON pairs
instead — that's the format you actually fine-tune on. The chunk-level JSONL
is the source of truth; other formats derive from it.

---

## Target model

A **1–3B parameter** model fine-tuned on the chunk + topic→KB JSONL.
Constraints:

- Must run in-browser. `wllama` (WASM) and `WebLLM` (WebGPU) are the two
  realistic runtimes. Both prefer GGUF; WebLLM also accepts MLC-compiled
  weights.
- Quantization: Q4_K_M is the sweet spot — small enough to download quickly,
  good enough for structured-output generation.
- No internet at inference time. The model has to know the ELF schema
  cold; we cannot lean on retrieval at generation time.

Reasonable starting points for the base model: Qwen3-1.7B, Llama-3.2-1B,
Gemma-3-1B. Start small, scale up only if quality demands it. A well-trained
1B model that emits valid schema beats a 4B model that occasionally drifts.

---

## Status

Stubs only. See the docstrings in `generator.py` and `discriminator.py` for
the implementation TODOs. Do not implement until the four hard constraints
in the root `PLAN.md` are still in force — when in doubt, ask.
