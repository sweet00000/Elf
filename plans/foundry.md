# Foundry — Python GAN that bootstraps the wiki brain

> Batch synth pipeline. Generator emits candidate `.elf` artifacts → Discriminator scores
> them → high-scoring outputs accumulate as **wiki brain** training corpus → fine-tune a
> small in-browser model that emits `.elf` content offline.

## Hard constraints (from user, non-negotiable)

1. **Python only.** No Node deps in Foundry runtime.
2. **Offline-first.** Every external call gated by API-key presence.
   Absence = local fallback. No crash. No network required to run.
3. **Discriminator only judges what its phase produces.** Don't promise scoring features
   for unbuilt content.
4. **API-key slot scaffolded today, dormant.** UI/CLI accept a key, store it, but don't
   require it. Paid features wired behind the same slot when they ship.

## Mission

Bootstrap a self-improving loop:

```
seeds.yaml → generator → candidate.elf → discriminator → verdict
                ▲                                            │
                └──────── refinement loop ◄──────────────────┘
                                                             │
                                                             ▼
                                                    library/ + index.json
                                                             │
                                                             ▼
                                                  wiki-brain.jsonl (training data)
                                                             │
                                                             ▼
                                              fine-tuned in-browser .elf-emitter model
```

## Phase plan

### Phase 0 — Landing page (today)
- Tabs for product family: Forge / NotebookELF / Codelves / Webelves / Foundry
- Each tab surfaces the product's plan (text + link to plan .md)
- Foundry tab: "coming soon" + key-input scaffold + waitlist
- Sample `.elf` demo link
- All offline. Static host.

### Phase 1 — Foundry scaffold (Python)
- `pyproject.toml` (anthropic, playwright, typer, pydantic, pyyaml, pytest)
- `foundry/{config,cli}.py`
- Offline-only mode default. Key slot: `ELF_LLM_API_KEY` (no-op if absent → emits stub `.elf`)
- CLI: `foundry generate|inspect|judge|loop|export`
- Acceptance: `foundry --help` lists all commands

### Phase 2 — Wiki-brain inspector + builder (Python re-impl of forge `buildSingle`)
- `elf/spec.py` — manifest schema (matches forge ELF v0.2)
- `elf/inspector.py` — parse `.elf` HTML, extract manifest + resources, recompute sha256,
  JCS-canonicalize manifest, compute fingerprint. Match forge fingerprint exactly.
- `elf/builder.py` — emits `.elf` from manifest + resources. Offline.
- `elf/template/` — vendor `bootstrap.js`, `binding-ui.html`, two runtimes from forge.
- Tests vs golden fixture. Acceptance: `foundry inspect golden.elf` prints JSON metadata.

### Phase 3 — Discriminator (judges Phase 2 outputs only)
- `discriminator/functional.py` — Playwright loads `.elf`, waits for ready signal, fires
  probe queries, asserts non-empty response within timeout.
- `discriminator/depth.py` — corpus token count, distinct-passage count, embedding dims × count.
- `discriminator/size.py` — bytes per capability unit.
- `discriminator/llm_judge.py` — Claude (key present) OR heuristic-only (offline).
- `discriminator/rubric.py` — `0.5*func + 0.3*depth + 0.2*size_eff`. Accept ≥ 0.7 AND func ≥ 0.6.
- Acceptance: `foundry judge golden.elf` prints scores + verdict in <30s.

### Phase 4 — Generator + GAN loop (Phase that bootstraps wiki brain)
- `generator/llm_generator.py` — topic → KB JSON → builder → `.elf`.
- `loop/orchestrator.py` — `for seed: for attempt: gen → judge → accept/refine`.
- `loop/feedback.py` — formats discriminator critique into next-attempt prompt prefix.
- Concurrency: asyncio, `--workers N`.
- Persist run state in `library/runs/<timestamp>.jsonl` for resumability.
- Acceptance: `foundry loop --seeds seeds/topics.yaml --workers 4` runs to completion;
  ≥50% of seeds produce accepted `.elf` on a 10-seed test.

### Phase 5 — Fine-tune target (1–3B in-browser model)
- Wiki-brain JSONL = training corpus (chunk-level + topic→KB-JSON pairs)
- Train on Modal / Lambda — produces `qwen3-*-elf-v1.0-q4_k_m.gguf` (or similar)
- Drop into Webelves / NotebookELF runtime paths; existing loaders pick it up
- One model per `schema_version`. Schema bump = new model; old `.elf`s keep working.

## Key-input scaffold (Phase 1)

`foundry/config.py`:

```python
class FoundryConfig(BaseSettings):
    elf_llm_api_key: str | None = Field(default=None, env="ELF_LLM_API_KEY")
    elf_llm_base_url: str = Field(default="https://api.anthropic.com/v1", env="ELF_LLM_BASE_URL")
    library_dir: Path = Field(default=Path("library"), env="ELF_LIBRARY_DIR")
    max_cost_usd: float = Field(default=5.0, env="ELF_MAX_COST_USD")

    @property
    def online(self) -> bool:
        return bool(self.elf_llm_api_key)
```

Every external call site:

```python
if not config.online:
    return offline_fallback(...)
return remote_call(...)
```

Fallbacks per phase:
- Phase 3 discriminator offline → heuristic-only (skip LLM judge)
- Phase 4 generator offline → emits stub `.elf` from a deterministic seed (for plumbing tests)

## Repo layout (target)

```
D:\cc\.elf\
├── index.html              # landing
├── plans/                  # product plans (forge/notebookelf/codelves/webelves/foundry)
├── PLAN.md                 # this project's plan (active)
├── README.md
├── pyproject.toml
├── foundry/
│   ├── __init__.py
│   ├── config.py
│   ├── cli.py
│   ├── elf/
│   │   ├── spec.py
│   │   ├── inspector.py
│   │   ├── builder.py
│   │   └── template/       # vendored from forge
│   ├── discriminator/
│   ├── generator/
│   └── loop/
├── library/                # accepted .elf artifacts (gitignored)
├── tests/
│   └── fixtures/
│       └── golden.elf
└── public/                 # static assets for landing
```

## Open questions resolved

- ELF format: align with forge ELF v0.2 (HTML wrap) for Phases 1–4. ZIP container variant
  (per WEBSITE_PLAN v1.0) deferred to a separate Phase F when catalog needs range-request.
- LLM: Anthropic (Claude Opus 4.7) when online. Cost cap default $5 per `foundry loop`.
- Python: 3.11+. Use `uv` if available else `venv`.

## Source tree references

- Forge buildSingle: `working/forge/src/tools/package.ts`
- Forge canonicalize: `working/forge/src/lib/canonicalize.ts`
- Forge runtimes: `working/forge/src/runtimes/`
- Forge digest: `working/forge/src/lib/digest.ts`
