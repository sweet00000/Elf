# Webelves — Browser-native Perplexity-style Search

> Static site. Local AI ("QAi") that searches the web, grounds answers in real sources,
> cites them inline. wllama (GGUF in WASM) + MiniLM embeddings + SearXNG.
> Source: `C:\Users\sweet\Documents\cc\webelves\README.md`.

## Stack

- Vite + React 18 + TypeScript + Tailwind
- Zustand (tabs, sessions, generation queue)
- react-resizable-panels (QAi side panel)
- @wllama/wllama (GGUF runtime in Web Worker, WASM v1)
- @xenova/transformers (MiniLM-L6-v2 embeddings, separate worker)
- @mozilla/readability (main-text extraction)
- SearXNG (pluggable search adapter)

No backend. No accounts. Ship `dist/` to any static host (Cloudflare Pages recommended).

## Architecture

```
dist/
├── /models/                ← GGUFs + MiniLM weights
├── UI shell (React + Tailwind)
├── src/lib/qai/            ← wllama worker (singleton engine)
├── src/lib/embed/          ← transformers.js worker
├── src/lib/search/         ← pluggable SearchAdapter + orchestrator
└── OPFS persistence        ← tabs + memories
```

**Single engine, many tabs.** One wllama Worker runs in the page. Every tab shares it.
A small generation queue (`runExclusive`) guarantees one completion at a time.
Non-active tabs with pending work show a "waiting" badge.

**Pluggable search.** `SearchAdapter` is a 2-method interface (`search`, `fetchPage`).
`SearXNGAdapter` shipped. Stubs for `CORSProxyAdapter` + `ExtensionAdapter` planned for v1.5.

**Grounded answers.** After search: top 4 pages fetched → Readability-extracted →
chunked (~300 words) → embedded with MiniLM → cosine-ranked vs query → top 5 chunks feed
a grounded prompt instructing the model to cite sources as `[N]`. Citations become
clickable chips that scroll the source card into view.

**Memory.** `src/lib/memory.ts` persists short natural-language facts to OPFS
(`memories.json`). After each chat (not search), model is asked to extract 0–3 durable
facts; new facts appended. All memories visible / editable / wipeable in Settings → Memory.

## Models (shipped slots)

| Slot | Default weights | Size | Path |
|---|---|---|---|
| Default | SmolLM2-360M-Instruct Q4_K_M | ~230MB | `public/models/smollm2-360m-q4_k_m.gguf` |
| Quality | Gemma-3-1B-Instruct Q4_K_M | ~800MB | `public/models/gemma3-1b-q4_k_m-*-of-*.gguf` (split) |

GGUF too large for npm. User drops them into `public/models/`. For quality tier, split
into ≤512MB chunks (CDN-friendly) via `llama-gguf-split`. Embedding weights fetched by
`scripts/download-models.mjs` during prebuild → no external network at runtime.

## COOP/COEP requirement

wllama multi-threading needs cross-origin-isolated context. `public/_headers`:

```
/*
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: require-corp
```

Without those, wllama silently drops to single-thread.

## NOT in v1

- No WebGPU / WebLLM path (wllama roadmap; stubbed)
- No extensions or CORS-proxy adapters (interfaces in)
- No fine-tuning / LoRAs — personalization is retrieval-only
- No accounts, sync, or mobile layout polish

## Open work

- WebGPU path via WebLLM (alongside wllama)
- Extension adapter for privileged fetch (bypasses CORS)
- `.elf` integration: dump a search session + grounded sources as a `.elf` artifact for offline replay
- Personal vector store growth strategy (size cap, dedup)
