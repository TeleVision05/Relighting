/* Shadow occupancy volume. Pure: no DOM, no GL.
 *
 * A splat cloud has no surfaces to rasterise a shadow map from, and a point
 * light would need a cube map per light. Instead we bake the cloud into a
 * density volume once per model and ray-march it toward each light, which
 * costs one 3D texture regardless of light count and gives the soft,
 * partially-transmissive shadows a splat cloud should have.
 *
 * The march happens per splat in the vertex shader, not per fragment: splat
 * rendering has enormous overdraw, so marching per pixel would cost one to two
 * orders of magnitude more. A splat is small on screen, so evaluating
 * visibility at its centre is enough.
 */

import { OPAQUE, opaqueBounds } from './bounds.js';

// One 3×3×3 box blur, done separably. Splat surfaces are a voxel or two thick;
// a march that steps over several voxels at a time would miss them entirely and
// produce a flat dim instead of a shadow. Blurring thickens occluders so coarse
// sampling still registers them, and softens the shadow edge for free.
export function blurVolume(src, res) {
  const n = src.length;
  let a = src,
    b = new Float32Array(n);
  const r2 = res * res;
  for (let axis = 0; axis < 3; axis++) {
    const stride = axis === 0 ? 1 : axis === 1 ? res : r2;
    const limit = res;
    for (let z = 0; z < res; z++) {
      for (let y = 0; y < res; y++) {
        for (let x = 0; x < res; x++) {
          const i = x + res * y + r2 * z;
          const c = axis === 0 ? x : axis === 1 ? y : z;
          const lo = c > 0 ? a[i - stride] : a[i];
          const hi = c < limit - 1 ? a[i + stride] : a[i];
          b[i] = (lo + a[i] + hi) * (1 / 3);
        }
      }
    }
    const t = a;
    a = b;
    b = t === src ? new Float32Array(n) : t;
  }
  return a;
}

// Opacity summed into a res³ grid over the padded bounds.
function splatDensity(d, box, res) {
  const acc = new Float32Array(res * res * res);
  const [minX, minY, minZ] = box.min;
  const [extX, extY, extZ] = box.ext;
  for (let i = 0; i < d.N; i++) {
    const o = d.op[i];
    if (o <= OPAQUE) continue;
    const ix = Math.min(res - 1, (((d.px[i] - minX) / extX) * res) | 0);
    const iy = Math.min(res - 1, (((d.py[i] - minY) / extY) * res) | 0);
    const iz = Math.min(res - 1, (((d.pz[i] - minZ) / extZ) * res) | 0);
    acc[ix + res * (iy + res * iz)] += o;
  }
  return acc;
}

// The 90th percentile of the non-zero cells (histogram estimate), not the max: a couple
// of very dense cells would otherwise flatten the whole volume to near-zero density.
export function densityNorm(values) {
  let peak = 0;
  for (let i = 0; i < values.length; i++) if (values[i] > peak) peak = values[i];
  if (!(peak > 0)) return peak;
  const BINS = 1024,
    hist = new Uint32Array(BINS);
  let nonzero = 0;
  for (let i = 0; i < values.length; i++) {
    if (values[i] <= 0) continue;
    hist[Math.min(BINS - 1, ((values[i] / peak) * BINS) | 0)]++;
    nonzero++;
  }
  let cum = 0;
  const target = nonzero * 0.9;
  for (let b = 0; b < BINS; b++) {
    cum += hist[b];
    if (cum >= target) return ((b + 1) / BINS) * peak;
  }
  return peak;
}

// Density volume as R8 bytes plus its world bounds: { res, data, min, ext }.
export function buildOccupancy(d, res = 96) {
  const { min, max } = opaqueBounds(d.px, d.py, d.pz, d.op, d.N);
  if (!(min[0] <= max[0])) {
    // nothing opaque — a fully transparent volume
    return { res: 1, data: new Uint8Array(1), min: [0, 0, 0], ext: [1, 1, 1] };
  }
  // Pad so splats sitting exactly on the bound still land inside the grid.
  const lo = [0, 0, 0],
    ext = [0, 0, 0];
  for (let a = 0; a < 3; a++) {
    const pad = (max[a] - min[a]) * 0.02 + 1e-3;
    lo[a] = min[a] - pad;
    ext[a] = Math.max(1e-6, max[a] + pad - lo[a]);
  }
  const blurred = blurVolume(blurVolume(splatDensity(d, { min: lo, ext }, res), res), res);
  const scale = 255 / Math.max(1e-6, densityNorm(blurred));
  const data = new Uint8Array(blurred.length);
  for (let i = 0; i < blurred.length; i++) data[i] = Math.min(255, blurred[i] * scale);
  return { res, data, min: lo, ext };
}
