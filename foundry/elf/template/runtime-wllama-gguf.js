// wllama + GGUF binding-runtime.
// Same shape as runtime-transformers-onnx.js but uses @wllama/wllama for
// generation. The embedding model still flows through transformers.js.

const TRANSFORMERS_CDN = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.1.0/+esm';
const WLLAMA_CDN = 'https://cdn.jsdelivr.net/npm/@wllama/wllama@2.1.4/esm/index.js';

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
  try { exists = typeof globalThis.caches !== 'undefined'; } catch { exists = false; }
  if (!exists) {
    try {
      Object.defineProperty(globalThis, 'caches', { value: fakeCaches, writable: true, configurable: true });
    } catch {}
  } else {
    try { globalThis.caches.open = async () => fakeCache; } catch {}
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
  let dot = 0;
  for (let i = 0; i < dim; i++) dot += a[i] * b[i];
  return dot;
}

export async function init({ manifest, resources, log }) {
  patchCachesIfBroken();
  const ui = mountUi(manifest);
  const status = (msg) => {
    log && log(msg);
    ui.log(msg);
  };

  status('loading transformers.js for embeddings…');
  const { pipeline, env } = await import(/* @vite-ignore */ TRANSFORMERS_CDN);
  env.allowLocalModels = false;
  env.useBrowserCache = false;
  if (env.backends?.onnx?.wasm) env.backends.onnx.wasm.numThreads = 1;

  const segRes = findResource(manifest, (r) => r.role === 'segment-set');
  const embRes = findResource(manifest, (r) => r.role === 'embedding-set');
  const tplRes = findResource(manifest, (r) => r.role === 'template');
  const embedModel = findResource(manifest, (r) => r.role === 'model' && r.id.startsWith('res:model.embed.'));
  const ggufModel = findResource(manifest, (r) => r.role === 'model' && r.media_type === 'application/x-gguf');
  const genFulfill = findFulfillment(manifest, 'generate-text');

  if (!segRes || !embRes || !tplRes || !ggufModel) {
    throw new Error('manifest missing one of: segment-set, embedding-set, template, gguf model');
  }

  const embedModelId =
    (embedModel && embedModel.fetch_urls && embedModel.fetch_urls[0]
      ? embedModel.fetch_urls[0].replace('https://huggingface.co/', '')
      : 'Xenova/all-MiniLM-L6-v2');

  status(`loading embedding model (${embedModelId})…`);
  const extractor = await pipeline('feature-extraction', embedModelId, {
    device: 'wasm',
    dtype: 'q8',
  });

  status('loading wllama runtime…');
  const wllamaMod = await import(/* @vite-ignore */ WLLAMA_CDN);
  const Wllama = wllamaMod.Wllama || wllamaMod.default;
  const wllama = new Wllama({
    'single-thread/wllama.wasm': 'https://cdn.jsdelivr.net/npm/@wllama/wllama@2.1.4/esm/single-thread/wllama.wasm',
    'multi-thread/wllama.wasm': 'https://cdn.jsdelivr.net/npm/@wllama/wllama@2.1.4/esm/multi-thread/wllama.wasm',
  });

  status('loading GGUF model bytes…');
  const ggufBlob = resources.get(ggufModel.id);
  const ggufBytes = new Uint8Array(await ggufBlob.arrayBuffer());
  await wllama.loadModel([new File([ggufBytes], 'model.gguf')]);

  status('decoding segments + embeddings…');
  const segText = await resources.get(segRes.id).text();
  const segments = segText
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));
  const embedDim = manifest.knowledge.embeddings[0].dimensions;
  const embeddings = await blobToFloat32(resources.get(embRes.id));
  const template = JSON.parse(await resources.get(tplRes.id).text());

  status('ready.');
  ui.enableInput();

  ui.onAsk(async (query) => {
    ui.appendMessage('user', query);
    ui.appendMessage('assistant', '…thinking…');

    try {
      const qOut = await extractor(query, { pooling: 'mean', normalize: true });
      const qVec = qOut.data;

      const topK = (manifest.interaction['retrieve-segments'] || {}).top_k || 6;
      const scored = [];
      for (let i = 0; i < segments.length; i++) {
        const off = i * embedDim;
        scored.push({ idx: i, score: cosine(qVec, embeddings.subarray(off, off + embedDim), embedDim) });
      }
      scored.sort((a, b) => b.score - a.score);
      const top = scored.slice(0, topK);
      const context = top
        .map((t) => segments[t.idx].text.substring(0, 600))
        .join('\n\n---\n\n');
      ui.showSources(top.map((t) => ({ score: t.score, text: segments[t.idx].text })));

      const sys =
        manifest.interaction.system_prompt ||
        "Answer concisely using ONLY the provided context. If the answer is not in the context, say you don't know.";
      const messages = [
        { role: 'system', content: sys },
        { role: 'user', content: `Context:\n${context}\n\nQuestion: ${query}` },
      ];

      const prompt = renderChatTemplate(template, messages);
      const result = await wllama.createCompletion(prompt, {
        nPredict: genFulfill?.max_new_tokens || 256,
        sampling: { temp: 0.2 },
      });
      ui.replaceLastAssistant(result);
    } catch (err) {
      ui.replaceLastAssistant(`Error: ${err && err.message ? err.message : err}`);
      throw err;
    }
  });
}

function renderChatTemplate(template, messages) {
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

function mountUi(manifest) {
  const root = document.getElementById('elf-app') || document.body;
  root.innerHTML = `
    <header class="elf-header"><h1>${escapeHtml(manifest.title || '.elf chat')}</h1></header>
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
    try { await askHandler(q); } finally { askBtn.disabled = false; }
  });
  return {
    log: (msg) => { logEl.textContent += `\n${msg}`; logEl.scrollTop = logEl.scrollHeight; },
    enableInput: () => { input.disabled = false; askBtn.disabled = false; input.focus(); },
    onAsk: (fn) => { askHandler = fn; },
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
          .map((s) => `<div class="elf-source"><span class="elf-score">${s.score.toFixed(3)}</span> ${escapeHtml(s.text.substring(0, 240))}…</div>`)
          .join('');
    },
  };
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
