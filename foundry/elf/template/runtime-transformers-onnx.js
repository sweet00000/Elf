// transformers.js + ONNX binding-runtime.
// Reads packaged segments (JSONL), embeddings (Float32Array), and chat template
// from the resource map. Loads embedding model + generation model from CDN.

const TRANSFORMERS_CDN = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.1.0/+esm';

// CacheStorage trap: in sandboxed iframes (sandbox="allow-scripts" only),
// even READING `window.caches` throws SecurityError. Plus some browsers ship
// a CacheStorage that explodes when transformers.js touches it. Stub both.
function patchCachesIfBroken() {
  const fakeCache = {
    match: async () => undefined,
    put: async () => undefined,
    add: async () => undefined,
    addAll: async () => undefined,
    delete: async () => false,
    keys: async () => [],
  };
  const fakeCaches = {
    open: async () => fakeCache,
    match: async () => undefined,
    has: async () => false,
    delete: async () => false,
    keys: async () => [],
  };

  let exists = false;
  try {
    exists = typeof globalThis.caches !== 'undefined';
  } catch {
    exists = false; // accessing the getter threw — sandbox or disabled.
  }

  if (!exists) {
    try {
      Object.defineProperty(globalThis, 'caches', {
        value: fakeCaches,
        writable: true,
        configurable: true,
      });
    } catch {
      // Can't even shadow it. Rely on env.useBrowserCache=false to keep
      // transformers.js off the cache path.
    }
  } else {
    try {
      globalThis.caches.open = async () => fakeCache;
    } catch {
      // ignore; the `useBrowserCache=false` flag below covers us.
    }
  }
}

function findResource(manifest, predicate) {
  return manifest.resources.find(predicate);
}

function findFulfillment(manifest, op) {
  const list = (manifest.fulfillments && manifest.fulfillments[op]) || [];
  return list[0] || null;
}

async function blobToFloat32(blob) {
  const buf = await blob.arrayBuffer();
  return new Float32Array(buf);
}

function cosine(a, b, dim) {
  // Both vectors are pre-normalized when produced by Forge's embed worker.
  let dot = 0;
  for (let i = 0; i < dim; i++) dot += a[i] * b[i];
  return dot;
}

function renderChatTemplate(template, messages) {
  // Minimal templating: deterministic chatml-style assembly.
  // template = { kind: 'chatml', system_prefix, user_prefix, assistant_prefix, eot }
  const parts = [];
  for (const m of messages) {
    const prefix =
      m.role === 'system'
        ? template.system_prefix
        : m.role === 'user'
          ? template.user_prefix
          : template.assistant_prefix;
    parts.push(`${prefix}${m.content}${template.eot}`);
  }
  parts.push(template.assistant_prefix);
  return parts.join('');
}

export async function init({ manifest, resources, log }) {
  patchCachesIfBroken();

  const ui = mountUi(manifest);
  const status = (msg) => {
    log && log(msg);
    ui.log(msg);
  };

  status('loading runtime…');
  const { pipeline, env } = await import(/* @vite-ignore */ TRANSFORMERS_CDN);
  env.allowLocalModels = false;
  env.useBrowserCache = false;
  if (env.backends?.onnx?.wasm) env.backends.onnx.wasm.numThreads = 1;

  // Resolve the segments + embeddings + template + models from the manifest.
  const segRes = findResource(manifest, (r) => r.role === 'segment-set');
  const embRes = findResource(manifest, (r) => r.role === 'embedding-set');
  const tplRes = findResource(manifest, (r) => r.role === 'template');
  const embedModel = findResource(
    manifest,
    (r) => r.role === 'model' && r.media_type === 'application/x-onnx-pipeline' && r.id.startsWith('res:model.embed.'),
  );
  const genFulfill = findFulfillment(manifest, 'generate-text');
  const genModelId = genFulfill && genFulfill.model;
  const embedModelId = embedModel && embedModel.fetch_urls && embedModel.fetch_urls[0]
    ? embedModel.fetch_urls[0].replace('https://huggingface.co/', '')
    : 'Xenova/all-MiniLM-L6-v2';

    //onnx-community/LFM2-1.2B-RAG-ONNX
    //

  if (!segRes || !embRes || !tplRes || !genModelId) {
    throw new Error('manifest missing one of: segment-set, embedding-set, template, generate-text fulfillment.model');
  }

  status(`loading embedding model (${embedModelId})…`);
  const extractor = await pipeline('feature-extraction', embedModelId, {
    device: 'wasm',
    dtype: 'q8',
  });

  status(`loading generation model (${genModelId})…`);
  const webgpuDtype = (genFulfill && genFulfill.dtype_webgpu) || 'q4';
  const wasmDtype = (genFulfill && genFulfill.dtype_wasm) || 'fp16';
  let generator;
  try {
    generator = await pipeline('text-generation', genModelId, {
      device: 'wasm',
      dtype: wasmDtype,
    });
    status(`wasm/${wasmDtype} ready`);
  } catch (err) {
    status(`wasm/${wasmDtype} failed (${err && err.message ? err.message : err}); trying webgpu/${webgpuDtype}…`);
    generator = await pipeline('text-generation', genModelId, {
      device: 'webgpu',
      dtype: webgpuDtype,
    });
    status(`webgpu/${webgpuDtype} ready`);
  }

  // Materialise segments + embeddings into RAM.
  status('decoding segments + embeddings…');
  const segText = await resources.get(segRes.id).text();
  const segments = segText
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));

  const embedDim = manifest.knowledge.embeddings[0].dimensions;
  const embeddings = await blobToFloat32(resources.get(embRes.id));
  if (embeddings.length !== segments.length * embedDim) {
    throw new Error(
      `embedding count mismatch: ${embeddings.length} floats != ${segments.length} × ${embedDim}`,
    );
  }

  const template = JSON.parse(await resources.get(tplRes.id).text());

  status('ready.');
  ui.enableInput();

  ui.onAsk(async (query) => {
    ui.appendMessage('user', query);
    ui.appendMessage('assistant', '…thinking…');

    try {
      // 1. Embed query.
      const qOut = await extractor(query, { pooling: 'mean', normalize: true });
      const qVec = qOut.data;

      // 2. Cosine search over flat embeddings.
      const topK = (manifest.interaction['retrieve-segments'] || {}).top_k || 4;
      const scored = [];
      for (let i = 0; i < segments.length; i++) {
        const off = i * embedDim;
        const view = embeddings.subarray(off, off + embedDim);
        scored.push({ idx: i, score: cosine(qVec, view, embedDim) });
      }
      scored.sort((a, b) => b.score - a.score);
      const top = scored.slice(0, topK);
      const context = top
        .map((t) => segments[t.idx].text.substring(0, 800))
        .join('\n\n---\n\n');
      ui.showSources(top.map((t) => ({ score: t.score, text: segments[t.idx].text })));

      // 3. Build messages, apply template, call generator.
      const sys = (manifest.interaction.system_prompt) ||
        ""//"You are a helpful AI assistant. Use the provided context to answer the question. If the context doesn't contain the answer, use your general knowledge but prioritize the context. Provide detailed.";
      const messages = [
        { role: 'system', content: sys },
        { role: 'user', content: `Given:\n${context}\n\n ${query}?` },
      ];

      // Yield to paint before WASM lock-up.
      await new Promise((r) => setTimeout(r, 50));

      const output = await generator(messages, {
        max_new_tokens: 512,
        temperature: 0.5,
        do_sample: false,
        top_p: 0.9,
      });
      const lastMsg = output[0].generated_text.at(-1);
      const answer = (lastMsg && lastMsg.content) || String(output[0].generated_text);
      ui.replaceLastAssistant(answer);
    } catch (err) {
      ui.replaceLastAssistant(`Error: ${err && err.message ? err.message : err}`);
      throw err;
    }
  });
}

// Minimal chat UI, injected if the binding-ui body left a #elf-app mount.
function mountUi(manifest) {
  const root = document.getElementById('elf-app') || document.body;
  root.innerHTML = `
    <header class="elf-header">
      <h1>${escapeHtml(manifest.title || '.elf chat')}</h1>
      <div class="elf-fp" title="Artifact identity">${escapeHtml(manifest.id || '')}</div>
    </header>
    <main class="elf-main">
      <div id="elf-thread" class="elf-thread"></div>
      <div id="elf-sources" class="elf-sources"></div>
      <form id="elf-form" class="elf-form">
        <input id="elf-input" type="text" placeholder="Ask a question…" disabled autocomplete="off" />
        <button id="elf-ask" type="submit" disabled>Ask</button>
      </form>
      <pre id="elf-log" class="elf-log">starting…</pre>
    </main>
  `;
  const thread = root.querySelector('#elf-thread');
  const sources = root.querySelector('#elf-sources');
  const input = root.querySelector('#elf-input');
  const askBtn = root.querySelector('#elf-ask');
  const form = root.querySelector('#elf-form');
  const logEl = root.querySelector('#elf-log');

  let askHandler = null;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || !askHandler) return;
    input.value = '';
    askBtn.disabled = true;
    try {
      await askHandler(q);
    } finally {
      askBtn.disabled = false;
    }
  });

  return {
    log: (msg) => {
      logEl.textContent += `\n${msg}`;
      logEl.scrollTop = logEl.scrollHeight;
    },
    enableInput: () => {
      input.disabled = false;
      askBtn.disabled = false;
      input.focus();
    },
    onAsk: (fn) => {
      askHandler = fn;
    },
    appendMessage: (role, content) => {
      const div = document.createElement('div');
      div.className = `elf-msg elf-${role}`;
      div.textContent = content;
      thread.appendChild(div);
      thread.scrollTop = thread.scrollHeight;
    },
    replaceLastAssistant: (content) => {
      const msgs = thread.querySelectorAll('.elf-assistant');
      const last = msgs[msgs.length - 1];
      if (last) last.textContent = content;
    },
    showSources: (items) => {
      sources.innerHTML =
        '<div class="elf-sources-title">Retrieved context</div>' +
        items
          .map(
            (s) =>
              `<div class="elf-source"><span class="elf-score">${s.score.toFixed(3)}</span> ${escapeHtml(s.text.substring(0, 240))}…</div>`,
          )
          .join('');
    },
  };
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
