// Load a scene (a URL or a File from the picker) into GPU-ready arrays.
//
// The work runs in a module worker (load-worker.js): fetch, parse, normals, lighting split
// and packing all happen off the main thread, and the result comes back as transferred
// buffers. Where module workers are unavailable it runs here instead, yielding between
// stages so the status line can repaint.

import { ViewerError, deserializeError, errorKind } from './errors.js';
import { readSource } from './fetch-scene.js';

const nextTask = () => new Promise((r) => setTimeout(r, 0));

export function sourceName(source) {
  return typeof source === 'string' ? source.split('/').pop().split('?')[0] : source.name;
}

// What the worker needs: an absolute URL (a worker resolves relative URLs against its own
// script) or the File itself, which survives postMessage.
function workerSource(source) {
  return typeof source === 'string' ? new URL(source, location.href).href : source;
}

async function loadOnMainThread(source, request, onProgress) {
  const { preprocessScene } = await import('./pipeline.js');
  const buf = await readSource(workerSource(source), request, (within) =>
    onProgress({ stage: 'download', within }),
  );
  return preprocessScene(buf, async (p) => {
    onProgress(p);
    if (!p.within) await nextTask(); // stage starts only: yield so the status repaints
  });
}

function loadInWorker(worker, source, request, onProgress) {
  return new Promise((resolve, reject) => {
    let started = false;
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === 'ready') started = true;
      else if (m.type === 'progress') onProgress(m);
      else {
        worker.terminate();
        if (m.type === 'done') resolve(m.result);
        else reject(deserializeError(m.error));
      }
    };
    worker.onerror = (e) => {
      e.preventDefault();
      worker.terminate();
      // A worker that never started (no module-worker support) falls back to this thread.
      if (!started) resolve(loadOnMainThread(source, request, onProgress));
      else reject(new ViewerError(errorKind(e), `Load worker failed: ${e.message}`));
    };
    worker.postMessage({ source: workerSource(source), request });
  });
}

// onProgress({ stage, within, n?, stride? }) — see STAGES in stages.js.
// request: { bust, fresh } — see sceneRequest in fetch-scene.js.
export function loadScene(source, { request = {}, onProgress = () => {} } = {}) {
  let worker = null;
  try {
    worker = new Worker(new URL('./load-worker.js', import.meta.url), { type: 'module' });
  } catch (e) {
    console.warn('Load worker unavailable, loading on the main thread:', e);
  }
  if (!worker) return loadOnMainThread(source, request, onProgress);
  return loadInWorker(worker, source, request, onProgress);
}
