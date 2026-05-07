# NotebookELF — Multi-notebook shell over Forge

> NotebookLM-style dashboard producing `.elf` artifacts. Forge stays the engine.
> Source plan: `working/NotebookELF/plan.md` (Phases 1–6).

## What it is

A browser-only studio for producing self-contained `.elf` knowledge artifacts
("embeddable teachers"). Dashboard of notebook cards. Each notebook holds sources
(PDFs / text / URLs / CSVs), an auto-generated title/icon/color/description/example-questions,
a grounded RAG chat with inline citations, and a side studio for notes. **Build** packages
the whole thing into a single-file `.elf.html` with the same chat UX baked in — so the
consumer of the `.elf` has the same teacher-with-citations experience the author had
while building it.

## Architectural commitments (do not relitigate)

1. Browser-only, no server. URL ingest = `fetch` + DOMParser. CORS-blocked URLs fail loudly.
2. Solid + Vite + Tailwind, dark theme. InsightsLM's spacing / patterns / IA on dark base.
3. A notebook is a workspace. `WorkspaceStore` becomes per-notebook. One active at a time.
4. Manifest stays source of truth for `.elf`. Notebook presentation meta lives **out-of-band**
   in `notebookMeta` — changing icon doesn't change artifact fingerprint. `manifest.title` +
   `manifest.description` stay in manifest because they affect identity.
5. All AI calls go through one `AgentClient`. Auto-generate-details + chat use the same client.
6. The `.elf` is the contract. Every host UX feature must be deliverable in `binding-ui` or
   explicitly excluded. Notes excluded. Citations included.
7. Citations are structured, not parsed from prose. Gemini `responseSchema` forces
   `{output: [{text, citations: [...]}]}`. Same shape `.elf` runtime emits. No regex over freeform.
8. One bundle, two chat runtimes. Host loop (`chat/ragLoop.ts`) and `.elf` loop
   (`runtimes/runtime-transformers-onnx.js`) share citation schema + prompt format.

## OPFS layout

```
/notebooks/index.json                       # NotebookSummary[]
/notebooks/<notebookId>/workspace.json      # NotebookSnapshot (WorkspaceSnapshot + meta + chats + notes)
/notebooks/<notebookId>/blobs/<sha[0:2]>/<sha>
/notebooks/<notebookId>/outputs/<buildId>.elf.html
```

## Phases

| Phase | Goal | Status |
|---|---|---|
| 1 | Notebook layer (dashboard + per-notebook workspace + migration) | scaffolded |
| 2 | Sources ingest UX (file / paste / URL dialog, status badges) | partial |
| 3 | Auto-generate notebook details (Gemini structured output) | not started |
| 4 | Chat loop with structured citations | not started |
| 5 | Studio (notes panel) | not started |
| 6 | `.elf` runtime upgrade (citations, source viewer) | not started |

## Source

`C:\Users\sweet\Documents\Embeded Language Format\working\NotebookELF\`

## Open work

- Decouple Forge engine for vendor reuse from Foundry (Python tool needs builder bindings)
- ZIP container variant for catalog browsing (range-request manifest without model download)
- Local-model `AgentClient` impl to retire Gemini dependency
