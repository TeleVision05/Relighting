// Module worker for the depth sort (see sort.js). Holds the splat positions; each request
// carries a camera and, after the first, the previous order buffer to reuse.

import { splatSortCore } from './sort.js';

let S = null;
self.onmessage = (e) => {
  const m = e.data;
  if (m.type === 'init') {
    S = { px: m.px, py: m.py, pz: m.pz, op: m.op, N: m.N };
    return;
  }
  if (!S) return;
  const r = splatSortCore(S, m);
  self.postMessage({ order: r.order, count: r.count }, [r.order.buffer]);
};
