# ELF — Project Plan (root)

> Repo: `sweet00000/elf`. Working dir: `D:\cc\.elf`.
> This file is the **active** plan. Per-product plans live in `plans/`.
> Archived predecessors live in `plans/_archive/`.

## What ELF is

ELF (Embedded Language Format) is a family of browser-native, offline-first AI tools
that produce and consume `.elf` artifacts — self-contained portable knowledge bundles
(model + corpus + UI as one HTML file or ZIP).

**Products:**

| Product | What | Status | Plan |
|---|---|---|---|
| Forge | Browser builder for `.elf` | M0+M1 shipped, M2 deferred | [`plans/forge.md`](plans/forge.md) |
| NotebookELF | NotebookLM-style multi-notebook shell over Forge | Phase 1 partial | [`plans/notebookelf.md`](plans/notebookelf.md) |
| Codelves | AgentOS IDE, Pyodide multi-agent | v2 shipped, v2.1 in plan | [`plans/codelves.md`](plans/codelves.md) |
| Webelves | Browser Perplexity-style search (wllama + GGUF) | v1 shipped | [`plans/webelves.md`](plans/webelves.md) |
| Foundry | Python GAN that bootstraps wiki-brain training corpus | Phase 0 (this plan) | [`plans/foundry.md`](plans/foundry.md) |
| Catalog | Hosted index + viewer of public `.elf` artifacts | Deferred | (see WEBSITE_PLAN archive) |

## What this directory holds

- `index.html` — public landing page. Tabs surface each product.
- `plans/` — one plan per product + archived predecessors.
- `foundry/` — Python implementation of the Foundry pipeline (Phase 1 onward).
- `public/` — static assets (sample `.elf` demos, plan exports).
- `tests/` — fixtures + pytest suites (per Foundry phase).

## Cross-cutting commitments

1. **Python only for Foundry.** No Node deps in the runtime.
2. **Offline-first.** Every external call gated by `ELF_LLM_API_KEY`. Absence = local
   fallback. Never crash.
3. **Each product owns its plan.** Cross-product changes update both the consumer plan
   and this root plan in the same commit.
4. **Forge owns the canonical `.elf` builder.** Foundry re-implements it in Python by
   matching forge's manifest schema + JCS canonicalization byte-for-byte. ZIP container
   variant (WEBSITE_PLAN v1.0) is a separate, opt-in profile — not v0 work.
5. **`.elf` v0.2** is the format Phases 1–4 of Foundry target. ZIP container (`.elf` v1.0)
   only when catalog browsing requires range-request access.

## Phase order (this repo)

| Phase | Owner | Output | Acceptance |
|---|---|---|---|
| 0 | landing | `index.html` with product tabs + plan links | All 5 product tabs render; sample `.elf` demo loads |
| 1 | foundry | scaffold (`pyproject.toml` + `foundry/{config,cli}.py`) | `foundry --help` lists `generate inspect judge loop export` |
| 2 | foundry | inspector + Python builder | `foundry inspect golden.elf` prints metadata; fingerprint matches forge |
| 3 | foundry | discriminator (functional + depth + size + LLM judge) | `foundry judge golden.elf` < 30s, scores + verdict |
| 4 | foundry | generator + GAN refinement loop | `foundry loop --workers 4` produces ≥ 50% accepted on 10-seed test |
| 5 | training | wiki-brain JSONL → fine-tuned in-browser model | One `.gguf` shipped; existing loaders pick it up |

## Status (today)

- Phase 0 — **shipped** (landing page + plans + repo init)
- Phase 1 — **partial** (`pyproject.toml`, `foundry/{config,cli,judge/}` shipped; full builder commands stubbed)
- Phase 2 — not started (Python re-impl of forge `buildSingle`)
- Phase 3 — **partial** (LLM judge vs Wikipedia ground truth shipped; full rubric — Playwright probe queries, depth/size scoring — not yet)
- Phases 4–5 — not started

The Phase 3 judge ships ahead of the full Phase 2 builder because
discriminating an arbitrary HTML/.elf candidate against Wikipedia is
useful even without a custom builder behind it.

## Open work tracked in plans

See per-product `plans/*.md` for implementation TODOs.
