// Load a scene (a URL or a File from the picker) into GPU-ready arrays.

import { preprocessScene } from './pipeline.js';
import { setStatus, stageLabel } from './status.js';

const nextTask = () => new Promise((r) => setTimeout(r, 0));

// Fetch a PLY, defeating every layer of caching (HTTP cache + bfcache + proxies).
async function fetchPLY(url) {
  const bust = url + (url.includes('?') ? '&' : '?') + '_=' + Date.now();
  const resp = await fetch(bust, {
    cache: 'reload',
    headers: { 'Cache-Control': 'no-cache' },
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${url}`);
  return resp.arrayBuffer();
}

export function sourceName(source) {
  return source instanceof Blob ? source.name : source.split('/').pop().split('?')[0];
}

export async function loadScene(source) {
  const local = source instanceof Blob;
  setStatus(stageLabel({ stage: 'download', local, name: sourceName(source) }), 'busy');
  const buf = local ? await source.arrayBuffer() : await fetchPLY(source);
  return preprocessScene(buf, async (p) => {
    if (p.within) return; // stage starts only: the main thread cannot repaint mid-stage
    setStatus(stageLabel(p));
    await nextTask();
  });
}
