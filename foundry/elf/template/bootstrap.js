// .elf bootstrap. Lives inline in every Forge-built single-file artifact.
// Walks the inert <script type="application/elf-resource"> tags, base64-decodes
// each one, verifies SHA-256 against the data-sha256 attribute, then hands a
// Map<resourceId, Blob> to the binding-runtime resource's exported init().

(async () => {
  const log = (...args) => console.log('[elf]', ...args);
  const fail = (msg, err) => {
    document.body.innerHTML =
      '<pre style="padding:1rem;color:#b91c1c;font-family:ui-monospace,monospace;white-space:pre-wrap">' +
      `.elf bootstrap failed: ${msg}\n\n${err && err.stack ? err.stack : err || ''}` +
      '</pre>';
    throw err || new Error(msg);
  };

  try {
    const manifestNode = document.querySelector('script[type="application/elf-manifest"]');
    if (!manifestNode) throw new Error('missing elf-manifest script');
    const manifest = JSON.parse(manifestNode.textContent);

    const nodes = Array.from(
      document.querySelectorAll('script[type="application/elf-resource"]'),
    );
    log(`decoding ${nodes.length} resources`);

    const resources = new Map();
    for (const node of nodes) {
      const id = node.getAttribute('data-id');
      const declaredSha = (node.getAttribute('data-sha256') || '').toLowerCase();
      const mediaType = node.getAttribute('data-media-type') || 'application/octet-stream';
      const encoding = node.getAttribute('data-encoding') || 'base64';
      const b64 = (node.textContent || '').replace(/\s+/g, '');

      let bytes;
      if (encoding === 'base64') {
        const bin = atob(b64);
        bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      } else {
        throw new Error(`unsupported encoding "${encoding}" for ${id}`);
      }

      // Verify SHA-256 in the browser; refuse to load tampered resources.
      const digest = await crypto.subtle.digest('SHA-256', bytes);
      let actualSha = '';
      const dv = new Uint8Array(digest);
      for (let i = 0; i < dv.length; i++) {
        actualSha += dv[i].toString(16).padStart(2, '0');
      }
      if (declaredSha && actualSha !== declaredSha) {
        throw new Error(
          `sha256 mismatch for ${id}: expected ${declaredSha}, got ${actualSha}`,
        );
      }

      resources.set(id, new Blob([bytes], { type: mediaType }));
    }

    // Find the binding-runtime resource and dynamic-import it as an ES module.
    const runtimeEntry = manifest.resources.find((r) => r.role === 'binding-runtime');
    if (!runtimeEntry) throw new Error('no binding-runtime resource declared');
    const runtimeBlob = resources.get(runtimeEntry.id);
    if (!runtimeBlob) throw new Error(`binding-runtime resource missing bytes: ${runtimeEntry.id}`);

    const moduleUrl = URL.createObjectURL(
      new Blob([await runtimeBlob.text()], { type: 'text/javascript' }),
    );
    const mod = await import(/* @vite-ignore */ moduleUrl);
    if (typeof mod.init !== 'function') {
      throw new Error('binding-runtime did not export init({manifest, resources})');
    }
    await mod.init({ manifest, resources, log });
  } catch (err) {
    fail(err && err.message ? err.message : String(err), err);
  }
})();
