// Module worker: downloads (or reads) one scene, parses and preprocesses it, and posts the
// GPU-ready arrays back as transferables, so the page stays responsive during the load.
//
// In:  { source: absolute URL | File, request: { bust, fresh } }
// Out: { type: 'ready' } once loaded, then any number of
//      { type: 'progress', stage, within, n?, stride? }, then exactly one of
//      { type: 'done', result } or { type: 'error', error } (see errors.js serializeError).

import { serializeError } from './errors.js';
import { readSource } from './fetch-scene.js';
import { preprocessScene, transferables } from './pipeline.js';

function downloadReporter() {
  let last = -1;
  return (within) => {
    // At most ~100 messages for a download, however small its chunks.
    if (within < 1 && within - last < 0.01) return;
    last = within;
    self.postMessage({ type: 'progress', stage: 'download', within });
  };
}

self.onmessage = async (e) => {
  const { source, request } = e.data;
  try {
    const buf = await readSource(source, request, downloadReporter());
    const result = await preprocessScene(buf, (p) => self.postMessage({ type: 'progress', ...p }));
    self.postMessage({ type: 'done', result }, transferables(result));
  } catch (err) {
    self.postMessage({ type: 'error', error: serializeError(err) });
  }
};

self.postMessage({ type: 'ready' });
