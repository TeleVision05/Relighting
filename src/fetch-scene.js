// Read a scene's bytes from a URL or a File, reporting download progress. No DOM: runs in
// the load worker, or on the main thread as a fallback.

import { ViewerError } from './errors.js';

// The request for a scene URL. `bust` appends a unique query string (only worth it on a
// local dev server, where the file changes under the same name); `fresh` bypasses the
// HTTP cache for this request (Reload).
export function sceneRequest(url, { bust = false, fresh = false, now = Date.now() } = {}) {
  const target = bust ? url + (url.includes('?') ? '&' : '?') + '_=' + now : url;
  const init = fresh ? { cache: 'reload', headers: { 'Cache-Control': 'no-cache' } } : {};
  return { url: target, init };
}

// The body as one ArrayBuffer, calling onProgress(fraction) as bytes arrive when the size
// is known. Falls back to collecting chunks if the body outgrows Content-Length (a
// compressed response reports the compressed size).
async function readBody(resp, onProgress) {
  const total = Number(resp.headers.get('Content-Length')) || 0;
  if (!resp.body || !total) return resp.arrayBuffer();
  const reader = resp.body.getReader();
  let out = new Uint8Array(total),
    received = 0,
    chunks = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!chunks && received + value.length > total) chunks = [out.subarray(0, received)];
    if (chunks) chunks.push(value);
    else out.set(value, received);
    received += value.length;
    if (onProgress) onProgress(Math.min(1, received / total));
  }
  if (chunks) {
    out = new Uint8Array(received);
    let at = 0;
    for (const c of chunks) {
      out.set(c, at);
      at += c.length;
    }
  }
  return received === out.length ? out.buffer : out.slice(0, received).buffer;
}

export async function fetchScene(url, options, onProgress) {
  const req = sceneRequest(url, options);
  let resp;
  try {
    resp = await fetch(req.url, req.init);
  } catch (e) {
    throw new ViewerError('network', `${e.name}: ${e.message} (${url})`);
  }
  if (resp.status === 404 || resp.status === 410) {
    throw new ViewerError('not-found', `HTTP ${resp.status}: ${url}`);
  }
  if (!resp.ok) throw new ViewerError('network', `HTTP ${resp.status}: ${url}`);
  return readBody(resp, onProgress);
}

// `source` is an absolute URL string or a File/Blob from the file picker.
export async function readSource(source, options, onProgress) {
  if (typeof source !== 'string') {
    const buf = await source.arrayBuffer();
    if (onProgress) onProgress(1);
    return buf;
  }
  return fetchScene(source, options, onProgress);
}
