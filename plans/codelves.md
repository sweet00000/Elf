# Codelves — AgentOS IDE

> Browser-native local-first multi-agent workspace. Pyodide + workers + OPFS.
> Source plan: `working/NotebookELF/reference/Workshop/Workshop/public/codelves/PLAN-v2.1.md`.

## What it is

An IDE-shaped workspace where many agents collaborate over TXT-first thread files. Built on:
- One app instance, one kernel worker, one shared Pyodide worker, many agent workers
- TXT-first threads as durable human-readable truth
- React UI over a persistent workspace
- JupyterLite as the visible workspace/editor surface
- LLM backends: Gemini, Ollama, LM Studio, local Transformers.js

## The four execution modes

Explicit product concepts. Don't conflate.

### Mode 1 — Recursive agent spawning (v2 core, shipped)
- one app instance, one kernel worker, one shared Pyodide worker
- many agent workers, many thread files, many child agent windows
- the multiplied resource = **agents**, not app instances

### Mode 2 — Nested child app shell (v2.1 target)
- generated child copy of Codelves launched in right preview pane
- separate instance identity + storage namespace
- may render thread UI + file tree, may be preview-only
- does NOT need own Pyodide / worker pool yet
- "Codelves in Codelves" first feature

### Mode 3 — Isolated child runtime
- nested child becomes real runtime: own kernel + agent workers + Pyodide + threads + workspace
- still bounded by outer-system policy

### Mode 4 — Local-LLM bot factory (roadmap, shape-only for v2.1)
- outer app creates specialized child runtime / child bot for user task
- optionally configured with local model stack

## Namespace model

Every app instance has a namespace id. Reserved: `main`, `child-001..N`, `bot-001..N`.
Every durable path / worker graph / runtime resource belongs to an instance namespace.
Rule prevents IndexedDB + OPFS + worker collisions across nested instances.

## Key features (shipped)

- File explorer with drag-to-resize panel
- Code editor + Browser Preview tabs
- Real-time chat (file-based at `.agency/orchestrator/chat.txt`)
- Pyodide Python runtime in-browser
- Multi-agent instances (Elves + Bots)
- OPFS persistent storage
- All file types upload + per-file download
- Snapshot/restore + export/import

## Source

`C:\Users\sweet\Documents\Embeded Language Format\working\NotebookELF\reference\Workshop\Workshop\public\codelves\`

Lives inside larger `Workshop/` React app shell that also hosts landing + workspace.

## Open work

- Mode 2 nested shell impl
- Mode 3 isolated runtime
- Tighter ELF integration: bake completed Codelves session as a `.elf` artifact (project archive + replay UI)
