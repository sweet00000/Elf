# elf

> A family of browser-native, offline-first AI tools producing and consuming `.elf`
> artifacts — self-contained portable knowledge bundles.

| Product | What |
|---|---|
| **Forge** | Browser builder for `.elf` (Solid + Vite + Tailwind) |
| **NotebookELF** | NotebookLM-style multi-notebook shell over Forge |
| **Codelves** | AgentOS IDE — multi-agent workspace (Pyodide, OPFS, browser-native) |
| **Webelves** | Perplexity-style local search (wllama + GGUF + MiniLM) |
| **Foundry** | Python GAN that bootstraps the wiki-brain training corpus |

Read [`PLAN.md`](PLAN.md) for the active project plan and [`plans/`](plans/) for per-product detail.

## Layout

```
.elf/
├── PLAN.md                 # active root plan
├── README.md
├── index.html              # landing page (tabs per product)
├── plans/                  # one plan per product
│   ├── forge.md
│   ├── notebookelf.md
│   ├── codelves.md
│   ├── webelves.md
│   ├── foundry.md
│   └── _archive/           # superseded plans + early stubs
├── foundry/                # Python pipeline (Phase 1 onward)
└── public/                 # static assets (sample .elf demos)
```

## Hard constraints

1. **Python only for Foundry.** No Node deps in the Foundry runtime.
2. **Offline-first.** External calls gated by `ELF_LLM_API_KEY`. Absence = local fallback.
3. **Forge owns the canonical `.elf` v0.2 format.** Foundry re-implements builder in Python.

## License

CC BY-NC-SA 4.0
