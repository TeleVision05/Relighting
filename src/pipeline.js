// Everything between "the file's bytes are here" and "ready to upload to the GPU".
// Pure: no DOM, no GL. Runs in the load worker (load-worker.js), or on the main thread
// when module workers are unavailable.

import { separateLighting } from './intrinsics.js';
import { planeNormals } from './normals.js';
import { packSplats } from './pack.js';
import { decodeSplats, readLayout } from './ply.js';

export { STAGES, overallProgress } from './stages.js';

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
