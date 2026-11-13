/**
 * Separate baked illumination from intrinsic albedo. Pure: no DOM, no GL.
 *
 * A standard 3DGS PLY stores SH coefficients of *outgoing radiance*, not BRDF
 * albedo. Treating SH DC as albedo and multiplying new lights only scales the
 * already-lit appearance (intensity knobs), it does not disentangle lighting.
 *
 * From a single baked PLY (no multi-view images) we cannot run full inverse
 * rendering. Instead we use a 3D Retinex prior that matches what is actually
 * baked into this asset:
 *   - Higher-order SH (f_rest) is discarded → strips view-dependent specular
 *   - Spatially smooth log-luminance ≈ baked irradiance / AO / soft shadows
 *   - appearance ≈ albedo × irradiance  ⇒  albedo = appearance / E^sep
 *
 * Analysis of Buttons.ply: luminance is almost uncorrelated with normals
 * (directional light is weak in DC) but has clear spatial low-frequency
 * shading — so voxel Retinex is the right separator here.
 */

import { OPAQUE, opaqueBounds } from './bounds.js';

export const RETINEX_RES = 40;

// Rec. 709 luminance per splat (floored at 1e-4), and the mean log-luminance of the
// opaque splats (log 0.4 when there are none).
export function logLuminance(bakedR, bakedG, bakedB, op, N) {
  const lum = new Float32Array(N);
  let lumSum = 0,
    lumCount = 0;
  for (let i = 0; i < N; i++) {
    const y = Math.max(1e-4, 0.2126 * bakedR[i] + 0.7152 * bakedG[i] + 0.0722 * bakedB[i]);
    lum[i] = y;
    if (op[i] > OPAQUE) {
      lumSum += Math.log(y);
      lumCount++;
    }
  }
  return { lum, globalLog: lumCount ? lumSum / lumCount : Math.log(0.4) };
}

function cellIndex(v, min, ext, res) {
  return Math.max(0, Math.min(res - 1, Math.floor(((v - min) / ext) * (res - 1))));
}

// Mean log-luminance per voxel; empty voxels get the global mean. Also returns each
// splat's voxel so the blurred field can be read back per splat.
export function voxelLogMean(px, py, pz, op, lum, N, globalLog, res) {
  const { min, max } = opaqueBounds(px, py, pz, op, N);
  const ext = [0, 1, 2].map((a) => Math.max(1e-6, max[a] - min[a]));
  const cells = res * res * res;
  const sumLog = new Float32Array(cells);
  const cnt = new Float32Array(cells);
  const flatIdx = new Int32Array(N);
  for (let i = 0; i < N; i++) {
    const ix = cellIndex(px[i], min[0], ext[0], res);
    const iy = cellIndex(py[i], min[1], ext[1], res);
    const iz = cellIndex(pz[i], min[2], ext[2], res);
    const f = ix + res * (iy + res * iz);
    flatIdx[i] = f;
    if (op[i] > OPAQUE) {
      sumLog[f] += Math.log(lum[i]);
      cnt[f] += 1;
    }
  }
  const grid = new Float32Array(cells);
  for (let i = 0; i < cells; i++) grid[i] = cnt[i] > 0 ? sumLog[i] / cnt[i] : globalLog;
  return { grid, flatIdx };
}

// One 5³ box blur of a res³ volume (Retinex low-pass); the window shrinks at the edges.
export function blurLog(src, res) {
  const out = new Float32Array(res * res * res);
  for (let z = 0; z < res; z++) {
    for (let y = 0; y < res; y++) {
      for (let x = 0; x < res; x++) {
        let s = 0,
          n = 0;
        for (let dz = -2; dz <= 2; dz++) {
          const zz = z + dz;
          if (zz < 0 || zz >= res) continue;
          for (let dy = -2; dy <= 2; dy++) {
            const yy = y + dy;
            if (yy < 0 || yy >= res) continue;
            for (let dx = -2; dx <= 2; dx++) {
              const xx = x + dx;
              if (xx < 0 || xx >= res) continue;
              s += src[xx + res * (yy + res * zz)];
              n++;
            }
          }
        }
        out[x + res * (y + res * z)] = s / n;
      }
    }
  }
  return out;
}

// Per-splat irradiance from the blurred log field, normalised so the median opaque splat
// has irradiance 1, and floored at 0.05.
export function irradianceFromField(grid, flatIdx, op, N) {
  const irradiance = new Float32Array(N);
  const samples = [];
  for (let i = 0; i < N; i++) {
    irradiance[i] = Math.exp(grid[flatIdx[i]]);
    if (op[i] > OPAQUE) samples.push(irradiance[i]);
  }
  samples.sort((a, b) => a - b);
  const median = samples.length ? samples[samples.length >> 1] : 1;
  const invMed = 1 / Math.max(1e-6, median);
  for (let i = 0; i < N; i++) irradiance[i] = Math.max(0.05, irradiance[i] * invMed);
  return irradiance;
}

// Intrinsic albedo under a white-illuminant assumption: chrominance preserved, intensity
// divided by the estimated irradiance, clamped to [0, 1].
export function albedoFromIrradiance(bakedR, bakedG, bakedB, irradiance, N) {
  const alR = new Float32Array(N),
    alG = new Float32Array(N),
    alB = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const invE = 1 / irradiance[i];
    alR[i] = Math.max(0, Math.min(1, bakedR[i] * invE));
    alG[i] = Math.max(0, Math.min(1, bakedG[i] * invE));
    alB[i] = Math.max(0, Math.min(1, bakedB[i] * invE));
  }
  return { alR, alG, alB };
}

export function separateLighting(px, py, pz, bakedR, bakedG, bakedB, op, N) {
  const res = RETINEX_RES;
  const { lum, globalLog } = logLuminance(bakedR, bakedG, bakedB, op, N);
  const { grid, flatIdx } = voxelLogMean(px, py, pz, op, lum, N, globalLog, res);
  // Two passes of the 5³ box blur on the log-irradiance volume.
  const smooth = blurLog(blurLog(grid, res), res);
  const irradiance = irradianceFromField(smooth, flatIdx, op, N);
  return { ...albedoFromIrradiance(bakedR, bakedG, bakedB, irradiance, N), irradiance };
}
