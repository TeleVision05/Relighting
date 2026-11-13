/* Depth sort.
 * Runs in a Web Worker (sort-worker.js) so orbiting never blocks the main thread. A
 * counting sort over 16-bit quantised depth is O(N) — a comparator sort of ~250k splats
 * was the single biggest frame cost in an earlier version. splatSortCore is pure, so it
 * runs in the worker and directly on the main thread when workers are unavailable.
 */

// Ensure the scratch arrays in `S` hold at least N entries.
function scratch(S, N) {
  if (!S.cand || S.cand.length < N) {
    S.cand = new Uint32Array(N);
    S.bucket = new Uint16Array(N);
  }
  if (!S.counts) S.counts = new Uint32Array(65536);
  if (!S.depths || S.depths.length < N) S.depths = new Float32Array(N);
}

// Splats in front of the camera and within 512 px of the viewport, with their depths.
function cullVisible(S, m) {
  const { px, py, pz, op, N, cand, depths } = S;
  const { R, cp, focal } = m;
  const hw = m.w * 0.5,
    hh = m.h * 0.5;
  let nv = 0,
    minD = Infinity,
    maxD = -Infinity;
  for (let i = 0; i < N; i++) {
    if (op[i] < 0.003) continue;
    const dx = px[i] - cp[0],
      dy = py[i] - cp[1],
      dz = pz[i] - cp[2];
    const depth = -(R[6] * dx + R[7] * dy + R[8] * dz);
    if (depth < 0.05) continue;
    const sx = hw + (focal * (R[0] * dx + R[1] * dy + R[2] * dz)) / depth;
    if (sx < -512 || sx > m.w + 512) continue;
    const sy = hh - (focal * (R[3] * dx + R[4] * dy + R[5] * dz)) / depth;
    if (sy < -512 || sy > m.h + 512) continue;
    cand[nv] = i;
    depths[nv] = depth;
    nv++;
    if (depth < minD) minD = depth;
    if (depth > maxD) maxD = depth;
  }
  return { nv, minD, maxD };
}

// S: { px, py, pz, op, N } plus scratch; m: { R, cp, focal, w, h, reuse? }.
// Returns { order, count }: splat ids far → near in order[0 .. count).
export function splatSortCore(S, m) {
  scratch(S, S.N);
  const { nv, minD, maxD } = cullVisible(S, m);
  const order = m.reuse && m.reuse.length >= nv ? m.reuse : new Uint32Array(Math.max(nv, 1));
  if (nv === 0) return { order, count: 0 };

  const { cand, bucket, counts, depths } = S;
  counts.fill(0);
  const scale = 65535 / Math.max(1e-9, maxD - minD);
  for (let k = 0; k < nv; k++) {
    const b = ((depths[k] - minD) * scale) | 0;
    bucket[k] = b;
    counts[b]++;
  }
  // Prefix-sum from the far end so bucket 65535 (farthest) lands first.
  let sum = 0;
  for (let b = 65535; b >= 0; b--) {
    const c = counts[b];
    counts[b] = sum;
    sum += c;
  }
  for (let k = 0; k < nv; k++) order[counts[bucket[k]]++] = cand[k];
  return { order, count: nv };
}

// Owns the worker (or the synchronous fallback) and the ping-pong buffer.
export class SplatSorter {
  constructor(onResult) {
    this.onResult = onResult;
    this.busy = false;
    this.pending = null; // most recent camera state while busy
    this.last = null; // request currently in flight
    this.spare = null; // buffer handed back for reuse
    this.state = null;
    this.worker = null;
    try {
      this.worker = new Worker(new URL('./sort-worker.js', import.meta.url), { type: 'module' });
      this.worker.onmessage = (e) => this._done(e.data.order, e.data.count);
      this.worker.onerror = (e) => this._workerFailed(e);
    } catch (e) {
      this.worker = null;
    }
  }

  // Drop to synchronous sorting rather than leaving `busy` stuck forever.
  _workerFailed(e) {
    console.warn('Sort worker failed, falling back to main thread:', e.message || e);
    try {
      this.worker.terminate();
    } catch (_) {}
    this.worker = null;
    this.spare = null;
    const retry = this.pending || this.last;
    this.busy = false;
    this.pending = null;
    if (retry) this._run(retry);
  }

  setModel(d) {
    this.state = { px: d.px, py: d.py, pz: d.pz, op: d.op, N: d.N };
    this.spare = null;
    this.busy = false;
    this.pending = null;
    if (this.worker) {
      this.worker.postMessage({ type: 'init', px: d.px, py: d.py, pz: d.pz, op: d.op, N: d.N });
    }
  }

  // Coalescing: while a sort is in flight, keep only the newest request.
  request(msg) {
    if (!this.state) return;
    if (this.busy) {
      this.pending = msg;
      return;
    }
    this._run(msg);
  }

  _run(msg) {
    this.busy = true;
    this.last = msg; // replayed if the worker dies mid-sort
    const reuse = this.spare;
    this.spare = null;
    msg.reuse = reuse;
    if (this.worker) {
      this.worker.postMessage(msg, reuse ? [reuse.buffer] : []);
    } else {
      const r = splatSortCore(this.state, msg);
      this._done(r.order, r.count);
    }
  }

  _done(order, count) {
    this.busy = false;
    this.onResult(order, count);
    this.spare = order; // hand it back on the next request
    if (this.pending) {
      const p = this.pending;
      this.pending = null;
      this._run(p);
    }
  }
}
