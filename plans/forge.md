# Forge — `.elf` Builder (browser-only)

> Solid + Vite + Tailwind. Browser-native builder for ELF v0.2 single-file HTML artifacts.
> Source plan: `working/NotebookELF/reference/forge-plan.md` (M0 → M2).

## What it is

Three-column workspace where a user (or an agent the user is chatting with) assembles
a `.elf` from sources, embeddings, runtime template, and an interaction contract.
Output = one self-contained HTML file that runs offline in any modern browser.

## Hard commitments

1. Solid + Vite + Tailwind. No React. Solid signals = state primitive.
2. Browser-only. No server. OPFS = filesystem. Workers do heavy work.
3. Single source of truth: `manifest$` + `resources$` + `blobs`. Everything else derived.
4. Tools = typed functions; user UI and agent call the same surface.
5. Identity = RFC 8785 JCS canonical SHA-256 over manifest with `signatures: []`. Live in toolbar.
6. Two runtime templates ship: `runtime-transformers-onnx.js`, `runtime-wllama-gguf.js`.
7. Preview = sandboxed iframe loading the actual built `.elf`. Same code path consumers run.
8. One `AgentClient` interface; MVP impl `GeminiAgentClient`. Local-model impl later.

## ELF v0.2 manifest (canonical)

```json
{
  "elf_version": "0.2",
  "id": "urn:uuid:...",
  "title": "...",
  "created": "ISO-8601",
  "resources": [
    { "id": "res:source.foo", "media_type": "application/pdf", "sha256": "...", "role": "document", "derived_from": [] }
  ],
  "interaction": { "kind": "chat", "operations": ["query"] },
  "fulfillments": { "query": ["res:runtime.wllama"] },
  "signatures": [],
  "provenance": { "builder": "forge/0.1", "built_at": "ISO-8601" }
}
```

`buildSingle` (in `src/tools/package.ts`) validates → fetches bytes → verifies sha256 →
canonicalizes manifest → computes fingerprint → base64-encodes resources via worker →
emits HTML with inlined `bootstrap.js`.

## Status

M0 + M1 shipped (skeleton + manual happy path). M2 (agent loop) deferred — folded into
NotebookELF Phase 3.

## Source

`C:\Users\sweet\Documents\Embeded Language Format\working\forge\`

## Open work

- M2 agent integration moved to NotebookELF
- Container profile (ZIP) deferred until catalog needs range-request access (see Foundry / WEBSITE_PLAN)
- LoRA / fine-tune adapter loading (post-v0.2)
