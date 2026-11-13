// Everything between "the file's bytes are here" and "ready to upload to the GPU".
// Pure: no DOM, no GL. Runs in the load worker (load-worker.js), or on the main thread
// when module workers are unavailable.

import { separateLighting } from './intrinsics.js';
import { planeNormals } from './normals.js';
import { packSplats } from './pack.js';
import { decodeSplats, readLayout } from './ply.js';

// Stages in order, with the share of the whole load each one starts at (the download
// before them takes the first 45%). The UI turns these into a progress bar and labels.
export const STAGES = {
  download: 0,
  parse: 0.45,
  normals: 0.65,
  lighting: 0.8,
  pack: 0.9,
  upload: 0.98,
};

// Overall fraction (0–1) for a stage and the fraction of that stage done.
export function overallProgress(stage, within = 0) {
  const names = Object.keys(STAGES);
  const k = names.indexOf(stage);
  const start = STAGES[stage] ?? 0;
  const end = k >= 0 && k + 1 < names.length ? STAGES[names[k + 1]] : 1;
  return start + (end - start) * Math.max(0, Math.min(1, within));
}

// The arrays the page keeps after a load: what the depth sort needs, plus the packed GPU
// data. Everything else (albedo, normals, ...) lives only inside `packed`.
export const KEPT_FIELDS = ['px', 'py', 'pz', 'op'];

// `report({ stage, within, n, stride })` may return a promise, which is awaited between
// stages: the main-thread fallback uses that to yield so the status line can repaint.
export async function preprocessScene(buf, report = () => {}) {
  const layout = readLayout(buf);
  const info = { n: layout.realN, stride: layout.hdr.stride };
  await report({ stage: 'parse', within: 0, ...info });
  const d = decodeSplats(buf, {
    layout,
    onProgress: (done, total) => report({ stage: 'parse', within: done / total, ...info }),
  });

  await report({ stage: 'normals', within: 0, ...info });
  Object.assign(d, planeNormals(d.px, d.py, d.pz, d.nx, d.ny, d.nz, d.op, d.N));

  await report({ stage: 'lighting', within: 0, ...info });
  Object.assign(d, separateLighting(d.px, d.py, d.pz, d.bakedR, d.bakedG, d.bakedB, d.op, d.N));

  await report({ stage: 'pack', within: 0, ...info });
  const packed = packSplats(d);
  const kept = Object.fromEntries(KEPT_FIELDS.map((k) => [k, d[k]]));
  return { N: d.N, ...kept, packed };
}

// The ArrayBuffers of a preprocessScene result, for postMessage's transfer list.
export function transferables(result) {
  const p = result.packed;
  return [
    ...KEPT_FIELDS.map((k) => result[k].buffer),
    p.geom.buffer,
    p.shade.buffer,
    p.occ.data.buffer,
  ];
}
