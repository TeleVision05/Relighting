// Interleave the per-splat arrays into the two GPU textures. Pure: no DOM, no GL.
// Runs once per model load; after this the GPU holds everything it needs except the order.

import { buildOccupancy } from './occupancy.js';

// Texture width in texels. WebGL2 guarantees MAX_TEXTURE_SIZE >= 2048, so the renderer
// always uses exactly this width, and arrays packed to whole rows upload without a copy.
export const TEX_WIDTH = 2048;

// Length of an RGBA array holding `texels` texels, padded to whole rows of TEX_WIDTH.
export function paddedLength(texels) {
  return Math.max(1, Math.ceil(texels / TEX_WIDTH)) * TEX_WIDTH * 4;
}

// Float32 → IEEE half, via the standard bit-twiddle (no Math.fround tricks).
export function f32ToF16(src) {
  const out = new Uint16Array(src.length);
  const f = new Float32Array(1),
    u = new Uint32Array(f.buffer);
  for (let i = 0; i < src.length; i++) {
    f[0] = src[i];
    const x = u[0];
    const sign = (x >>> 16) & 0x8000;
    let exp = (x >>> 23) & 0xff,
      man = x & 0x7fffff;
    if (exp === 255) {
      out[i] = sign | 0x7c00 | (man ? 0x200 : 0);
      continue;
    }
    let e = exp - 127 + 15;
    if (e >= 31) {
      out[i] = sign | 0x7c00;
      continue;
    } // overflow → inf
    if (e <= 0) {
      // subnormal / zero
      if (e < -10) {
        out[i] = sign;
        continue;
      }
      man = (man | 0x800000) >>> (1 - e);
      out[i] = sign | ((man + 0x1000) >>> 13);
      continue;
    }
    out[i] = sign | (e << 10) | ((man + 0x1000) >>> 13);
  }
  return out;
}

// 3 texels per splat: pos | log-scale | quat (w, x, y, z).
export function packGeometry(d) {
  const geom = new Float32Array(paddedLength(d.N * 3));
  for (let i = 0; i < d.N; i++) {
    const g = i * 12;
    geom[g] = d.px[i];
    geom[g + 1] = d.py[i];
    geom[g + 2] = d.pz[i];
    geom[g + 4] = d.sc0[i];
    geom[g + 5] = d.sc1[i];
    geom[g + 6] = d.sc2[i];
    geom[g + 8] = d.qw[i];
    geom[g + 9] = d.qx[i];
    geom[g + 10] = d.qy[i];
    geom[g + 11] = d.qz[i];
  }
  return geom;
}

// 4 texels per splat: albedo+irradiance | baked+opacity | raw normal | smoothed normal.
// Returned as half floats for the RGBA16F texture.
export function packShading(d) {
  const shade = new Float32Array(paddedLength(d.N * 4));
  for (let i = 0; i < d.N; i++) {
    const s = i * 16;
    shade[s] = d.alR[i];
    shade[s + 1] = d.alG[i];
    shade[s + 2] = d.alB[i];
    shade[s + 3] = d.irradiance[i];
    shade[s + 4] = d.bakedR[i];
    shade[s + 5] = d.bakedG[i];
    shade[s + 6] = d.bakedB[i];
    shade[s + 7] = d.op[i];
    shade[s + 8] = d.nx[i];
    shade[s + 9] = d.ny[i];
    shade[s + 10] = d.nz[i];
    shade[s + 12] = d.nsx[i];
    shade[s + 13] = d.nsy[i];
    shade[s + 14] = d.nsz[i];
  }
  return f32ToF16(shade);
}

export function packSplats(d) {
  return { N: d.N, geom: packGeometry(d), shade: packShading(d), occ: buildOccupancy(d) };
}
