// The Retinex split of baked colour into albedo × irradiance.

import assert from 'node:assert/strict';
import test from 'node:test';

import { blurLog, logLuminance, separateLighting } from '../../src/intrinsics.js';
import { close, rng } from './helpers.js';

// A dense cube of splats: albedo varies splat to splat (high frequency), the lighting is a
// smooth ramp along x (low frequency). baked = albedo × light.
function litCube(n = 20000, ramp = (x) => 0.25 + 0.75 * x) {
  const rand = rng(5);
  const f = () => new Float32Array(n);
  const s = { px: f(), py: f(), pz: f(), op: f(), albedo: f(), light: f() };
  s.bakedR = f();
  s.bakedG = f();
  s.bakedB = f();
  for (let i = 0; i < n; i++) {
    s.px[i] = rand();
    s.py[i] = rand();
    s.pz[i] = rand();
    s.op[i] = 0.9;
    s.albedo[i] = 0.2 + 0.6 * rand();
    s.light[i] = ramp(s.px[i]);
    s.bakedR[i] = s.bakedG[i] = s.bakedB[i] = s.albedo[i] * s.light[i];
  }
  return s;
}

const split = (s, n) => separateLighting(s.px, s.py, s.pz, s.bakedR, s.bakedG, s.bakedB, s.op, n);

function corr(a, b) {
  const n = a.length;
  const ma = a.reduce((x, y) => x + y, 0) / n;
  const mb = b.reduce((x, y) => x + y, 0) / n;
  let sab = 0,
    saa = 0,
    sbb = 0;
  for (let i = 0; i < n; i++) {
    sab += (a[i] - ma) * (b[i] - mb);
    saa += (a[i] - ma) ** 2;
    sbb += (b[i] - mb) ** 2;
  }
  return sab / Math.sqrt(saa * sbb);
}

test('the smooth lighting ramp goes into irradiance and out of the albedo', () => {
  // 100k splats is ~1.5 per Retinex voxel. Sparser clouds separate less, because empty
  // voxels hold the global mean before the blur (measured 2026-11-13: at 20k splats the
  // albedo still correlates 0.59 with the light; at 100k, 0.25; at 300k, 0.08).
  const s = litCube(100000);
  const out = split(s, s.px.length);
  const light = Array.from(s.light);
  assert.ok(corr(Array.from(out.irradiance), light) > 0.95, 'irradiance tracks the light');
  const bakedVsLight = corr(Array.from(s.bakedR), light);
  const albedoVsLight = corr(Array.from(out.alR), light);
  assert.ok(bakedVsLight > 0.6, `fixture: baked colour follows the light (${bakedVsLight})`);
  assert.ok(albedoVsLight < 0.35, `albedo still follows the light (${albedoVsLight})`);
  // And it tracks the true albedo far better than the baked colour does (0.96 vs 0.69).
  const albedo = Array.from(s.albedo);
  const recovered = corr(Array.from(out.alR), albedo);
  assert.ok(recovered > 0.9, `albedo vs true albedo ${recovered}`);
  assert.ok(recovered > corr(Array.from(s.bakedR), albedo) + 0.2);
});

test('under even lighting the albedo is the baked colour, and irradiance is about 1', () => {
  const s = litCube(8000, () => 0.6);
  const out = split(s, s.px.length);
  for (let i = 0; i < 8000; i += 97) {
    close(out.irradiance[i], 1, 0.05, `irradiance ${i}`);
    close(out.alR[i], s.bakedR[i], 0.03, `albedo ${i}`);
  }
});

test('irradiance is normalised so the median opaque splat has irradiance 1', () => {
  const s = litCube();
  const irr = Array.from(split(s, s.px.length).irradiance).sort((a, b) => a - b);
  close(irr[irr.length >> 1], 1, 0.02, 'median');
  assert.ok(irr[0] >= 0.05, 'floored at 0.05');
});

test('albedo stays in [0, 1] and keeps the colour ratios of the baked colour', () => {
  const s = litCube(4000);
  s.bakedR.fill(0.9);
  s.bakedG.fill(0.45);
  s.bakedB.fill(0.0);
  const out = split(s, 4000);
  for (let i = 0; i < 4000; i += 37) {
    assert.ok(out.alR[i] <= 1 && out.alB[i] >= 0);
    if (out.alR[i] < 1) close(out.alG[i] / out.alR[i], 0.5, 1e-5, 'G/R');
  }
});

test('transparent splats do not steer the lighting estimate', () => {
  const s = litCube(6000, () => 0.5);
  const n = 6000;
  const base = Array.from(split(s, n).irradiance);
  for (let i = 0; i < n; i += 3) {
    s.op[i] = 0.01; // nearly invisible...
    s.bakedR[i] = s.bakedG[i] = s.bakedB[i] = 0.001; // ...and black
  }
  const out = split(s, n);
  for (let i = 1; i < n; i += 3 * 50) close(out.irradiance[i], base[i], 0.06, `irr ${i}`);
});

test('helpers: luminance weights and a blur that preserves a constant field', () => {
  const one = new Float32Array([1]);
  const { lum, globalLog } = logLuminance(
    one,
    new Float32Array([0]),
    new Float32Array([0]),
    one,
    1,
  );
  close(lum[0], 0.2126, 1e-7);
  close(globalLog, Math.log(0.2126), 1e-6);
  const res = 6;
  const flat = new Float32Array(res ** 3).fill(-0.7);
  for (const v of blurLog(flat, res)) close(v, -0.7, 1e-6);
});
