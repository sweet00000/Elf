# ELF Foundry — Generator/Discriminator Pipeline

A Python pipeline that synthesizes ELF artifacts at scale and scores them with an
LLM judge. Output is a curated library of accepted ELFs ready to publish to the
website.

## Context

- An **ELF** (Embedded Language File) is a self-contained offline artifact
  bundling a model + corpus + UI as a single HTML or ZIP per the existing ELF
  v0.2 spec.
- This pipeline produces ELFs in batch from topic seeds and filters them via
  an API-backed judge before they reach the public catalog.

## Architecture

```
seeds.yaml ──► generator ──► candidate.elf ──► discriminator ──► verdict
                  ▲                                                  │
                  └──────────── refinement loop ◄────────────────────┘
                                                                     │
                                                                     ▼
                                                              library/ + index.json
                                                                     │
                                                                     ▼
                                                                  website/
```

## Repo layout

```
forge-foundry/
├── pyproject.toml
├── PLAN.md                     ← this file
├── README.md
├── seeds/
│   └── topics.yaml             ← seed topics + generation params
├── foundry/
│   ├── __init__.py
│   ├── config.py               ← pydantic settings, API keys, paths
│   ├── elf/
│   │   ├── spec.py             ← ELF v0.2 parser/writer (use existing impl if available)
│   │   ├── builder.py          ← assembles HTML/ZIP from parts
│   │   └── inspector.py        ← parses + extracts metadata from .elf
│   ├── generator/
│   │   ├── base.py             ← Generator ABC
│   │   ├── llm_generator.py    ← LLM-driven ELF synthesis (Qwen3 local OR Claude API)
│   │   └── prompts.py          ← prompt templates per ELF section
│   ├── discriminator/
│   │   ├── base.py             ← Judge ABC
│   │   ├── functional.py       ← Playwright-based runtime tests
│   │   ├── depth.py            ← corpus/embedding/capability metrics
│   │   ├── size.py             ← bytes-per-capability score
│   │   ├── llm_judge.py        ← Claude/Gemini composite scorer
│   │   └── rubric.py           ← scoring weights, thresholds
│   ├── loop/
│   │   ├── orchestrator.py     ← gen → judge → accept/reject/refine
│   │   └── feedback.py         ← formats judge output as prompt feedback
│   ├── library/
│   │   ├── store.py            ← content-addressed library + index
│   │   └── exporter.py         ← writes website-ready manifest
│   └── cli.py                  ← Typer CLI entrypoints
├── library/                    ← accepted ELFs (gitignored)
│   ├── index.json
│   └── <hash>.elf
└── tests/
    ├── fixtures/
    │   └── golden.elf          ← known-good ELF for discriminator calibration
    └── test_*.py
```

## Phase order

Build in this exact order. Each phase has acceptance criteria; do not advance
until they pass.

### Phase 0 — scaffold (½ day)
- `pyproject.toml` with `anthropic`, `playwright`, `typer`, `pydantic`,
  `pyyaml`, `pytest`.
- `config.py` reads `ANTHROPIC_API_KEY` and paths from env.
- `cli.py` exposes `foundry --help` with stubbed `generate`, `judge`, `loop`,
  `export` commands.

**Acceptance:** `foundry --help` lists all commands.

### Phase 1 — ELF inspector (½ day)
- `elf/inspector.py` opens an `.elf` (HTML or ZIP), extracts:
  - manifest (model name, corpus title, embedding count, blob inventory)
  - asset sizes
  - JCS-canonicalized artifact ID
- `tests/test_inspector.py` runs against `fixtures/golden.elf`.

**Acceptance:** `foundry inspect fixtures/golden.elf` prints JSON metadata.

### Phase 2 — discriminator (2–3 days)

Build the judge BEFORE the generator. You can't filter what you can't measure.

- `discriminator/functional.py`: launches the ELF in a Playwright Chromium
  context, performs scripted interactions:
  1. Page loads without console errors
  2. Model loads (wait for ready signal exposed by ELF runtime)
  3. Submit a canned query, assert non-empty response within timeout
  4. Embedding search returns k>0 results for a probe query
- `discriminator/depth.py`: computes
  - corpus token count
  - distinct-passage count
  - embedding dimensionality × count
  - tool surface (count of registered tools/agent capabilities)
- `discriminator/size.py`: computes bytes per capability unit
  (`total_bytes / depth_score`).
- `discriminator/llm_judge.py`: sends a structured summary of the above to
  Claude with a rubric prompt; returns scores ∈ [0, 1] for
  `functionality`, `depth`, `size_efficiency`, plus a free-text critique.
- `discriminator/rubric.py`: configurable weights, default
  `0.5*func + 0.3*depth + 0.2*size_eff`. `accept` threshold default `0.7`.

**Acceptance:**
- `foundry judge fixtures/golden.elf` prints scores + verdict in <30s.
- `foundry judge tests/fixtures/broken.elf` rejects with a useful reason.

### Phase 3 — generator stub (1 day)
- `generator/base.py` defines `Generator.generate(seed) -> Path`.
- `generator/llm_generator.py` initial impl: takes a topic seed
  (`{"topic": "Kalman filters", "depth": "intro"}`), calls Claude API with a
  prompt that produces:
  - corpus passages (markdown)
  - tool/agent config
  - UI tweaks (optional)
  Then `elf/builder.py` packages these against a base ELF template
  (reuse Forge's existing template emission).
- Single ELF generation should be one CLI call:
  `foundry generate --topic "Kalman filters" --out candidate.elf`.

**Acceptance:** Generated ELF passes `foundry inspect` and produces a
non-zero score from `foundry judge` (does not need to be accepted yet).

### Phase 4 — refinement loop (1–2 days)
- `loop/orchestrator.py` implements:
  ```
  for seed in seeds:
      for attempt in range(max_attempts):
          elf = generator.generate(seed, feedback=last_critique)
          verdict = discriminator.judge(elf)
          if verdict.accepted:
              library.add(elf, verdict)
              break
          last_critique = verdict.critique
      else:
          library.record_failure(seed, last_critique)
  ```
- `loop/feedback.py` formats discriminator critique into generator-consumable
  guidance (prepend to next prompt).
- Concurrency: process seeds in parallel up to `--workers N` (asyncio).
- Persist run state in `library/runs/<timestamp>.jsonl` for resumability.

**Acceptance:**
- `foundry loop --seeds seeds/topics.yaml --workers 4` runs to completion.
- At least 50% of seeds produce an accepted ELF on a 10-seed test run.

### Phase 5 — library + web export (1 day)
- `library/store.py`: content-addressed by JCS hash, dedupes identical ELFs.
  `index.json` maps hash → `{title, topic, scores, size, created_at}`.
- `library/exporter.py`: emits a website-ready manifest
  (`website/catalog.json`) plus copies/symlinks accepted ELFs into
  `website/elfs/`. Pluggable schema so the website team can adapt.
- `foundry export --to website/` is the publish command.

**Acceptance:** `website/catalog.json` validates against
`website/catalog.schema.json` and lists every accepted ELF with a
working relative path.

## Discriminator rubric (default)

| Axis | Source | Weight | Notes |
|---|---|---|---|
| Functionality | Playwright runtime checks → 0/1 per check, averaged | 0.5 | Hard fail if model never loads |
| Depth | log-scaled corpus tokens × tool count, normalized | 0.3 | Capped to avoid rewarding bloat |
| Size efficiency | depth_score / log(bytes) | 0.2 | Penalizes >50MB unless depth justifies |
| Composite | weighted sum | — | Accept if ≥ 0.7 AND functionality ≥ 0.6 |

LLM judge runs in parallel and can veto (composite score < 0.4 from judge =
auto-reject regardless of metrics) to catch quality issues metrics miss
(e.g., corpus is on-topic but factually garbage).

## Generator prompt structure

Single Claude call per ELF, structured output (JSON):

```
SYSTEM: You are generating a self-contained learning artifact on {topic}.
Produce a JSON object with:
  - title: string
  - corpus: array of {heading, passages[]}, ≥ {min_passages}
  - tools: array of {name, description, args_schema}
  - agent_system_prompt: string
  - probe_queries: array of strings (used by discriminator to test the ELF)
Constraints:
  - Total corpus length: {min_tokens} – {max_tokens} tokens
  - Each passage: self-contained, ≤ 500 tokens
  - No external links, no images
{feedback_section}
```

`{feedback_section}` is empty on first attempt; on retry includes the
discriminator's critique verbatim with "Address the following issues:".

## Seeds format (`seeds/topics.yaml`)

```yaml
- topic: Kalman filters
  depth: intermediate
  min_passages: 12
  tools_hint: ["explain_step", "derive_update_eqn"]
- topic: photosynthesis (light reactions)
  depth: intro
  min_passages: 8
- topic: GLSL shader fundamentals
  depth: intermediate
  min_passages: 15
```

## Open questions to resolve before Phase 3

1. **Generator backend**: local Qwen3-4B (free, slow, lower quality) or
   Claude API (paid, fast, higher quality)? Recommend Claude for v0,
   swap in local later behind a `Generator` subclass.
2. **ELF template source of truth**: import from existing Forge repo or
   vendor a copy? Recommend vendoring a known-good template at
   `foundry/elf/template/` for reproducibility.
3. **Cost budget**: cap total Claude spend per `foundry loop` invocation
   via `--max-cost-usd` flag. Hard-stop on overrun.

## What "done" means

`foundry loop --seeds seeds/topics.yaml && foundry export --to website/`
produces a publishable catalog of accepted ELFs with verifiable scores
and complete provenance (run logs, prompts, judge outputs preserved per
artifact).

## Notes for Claude Code

- Build phase by phase. Run phase acceptance checks before moving on.
- Write tests alongside code, not after. Each module gets a `test_*.py`.
- Use `uv` for env management if available, else `venv`.
- All long-running commands (`loop`, batch judge) must support
  `--resume` from the run log.
- Log everything as JSONL to `library/runs/`. Pretty-print to stdout
  separately.
- Do not invent ELF format details; if anything is unclear, read the
  vendored template and existing Forge sources first and ask before
  guessing.
