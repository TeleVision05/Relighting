// What goes to the GPU: half floats, texture packing and the shadow density volume.

import assert from 'node:assert/strict';
import test from 'node:test';

import { blurVolume, buildOccupancy, densityNorm } from '../../src/occupancy.js';
import { TEX_WIDTH, f32ToF16, packGeometry, packShading, paddedLength } from '../../src/pack.js';
import { close } from './helpers.js';

// IEEE half → number, for checking f32ToF16 round trips.
function f16ToNumber(h) {
  const s = h & 0x8000 ? -1 : 1;
  const e = (h >> 10) & 0x1f,
    m = h & 0x3ff;
  if (e === 0) return s * m * 2 ** -24;
  if (e === 31) return m ? NaN : s * Infinity;
  return s * (1 + m / 1024) * 2 ** (e - 15);
}

test('half floats: exact values, rounding, overflow, underflow, NaN', () => {
  const src = new Float32Array([0, -0, 1, -2, 0.5, 65504, 1e6, -1e6, 1e-9, Infinity, NaN]);
  const h = Array.from(f32ToF16(src));
  assert.deepEqual(h.slice(0, 6), [0x0000, 0x8000, 0x3c00, 0xc000, 0x3800, 0x7bff]);
  assert.equal(h[6], 0x7c00, 'overflow → +inf');
  assert.equal(h[7], 0xfc00, 'overflow → -inf');
  assert.equal(h[8], 0, 'underflow → 0');
  assert.equal(h[9], 0x7c00);
  assert.ok(Number.isNaN(f16ToNumber(h[10])));
});

test('half floats: values in [0, 1] survive to within half-float precision', () => {
  for (let i = 0; i <= 1000; i++) {
    const v = i / 1000;
    close(f16ToNumber(f32ToF16(new Float32Array([v]))[0]), v, 2 ** -11, `${v}`);
  }
  close(f16ToNumber(f32ToF16(new Float32Array([3e-6]))[0]), 3e-6, 2 ** -24, 'subnormal');
});

const splats = (N) => {
  const d = { N };
  const names = ['px', 'py', 'pz', 'sc0', 'sc1', 'sc2', 'qw', 'qx', 'qy', 'qz', 'alR', 'alG'];
  names.push('alB', 'irradiance', 'bakedR', 'bakedG', 'bakedB', 'op', 'nx', 'ny', 'nz');
  names.push('nsx', 'nsy', 'nsz');
  names.forEach(
    (k, j) => (d[k] = Float32Array.from({ length: N }, (_, i) => (j + 1) / 32 + i / 1024)),
  );
  return d;
};

test('packing: arrays are padded to whole texture rows', () => {
  assert.equal(paddedLength(1), TEX_WIDTH * 4);
  assert.equal(paddedLength(TEX_WIDTH), TEX_WIDTH * 4);
  assert.equal(paddedLength(TEX_WIDTH + 1), 2 * TEX_WIDTH * 4);
  assert.equal(packGeometry(splats(1000)).length, paddedLength(3000));
  assert.equal(packShading(splats(1000)).length, paddedLength(4000));
});

test('packing: geometry texels are pos | log-scale | quat (w, x, y, z)', () => {
  const d = splats(3);
  const g = packGeometry(d);
  const i = 2,
    o = i * 12;
  assert.deepEqual(Array.from(g.subarray(o, o + 12)), [
    ...[d.px[i], d.py[i], d.pz[i], 0],
    ...[d.sc0[i], d.sc1[i], d.sc2[i], 0],
    ...[d.qw[i], d.qx[i], d.qy[i], d.qz[i]],
  ]);
});

test('packing: shading texels are albedo+irr | baked+opacity | n | smoothed n', () => {
  const d = splats(3);
  const s = packShading(d);
  const i = 1,
    o = i * 16;
  const want = [d.alR, d.alG, d.alB, d.irradiance, d.bakedR, d.bakedG, d.bakedB, d.op];
  want.push(d.nx, d.ny, d.nz, null, d.nsx, d.nsy, d.nsz, null);
  want.forEach((arr, k) => close(f16ToNumber(s[o + k]), arr ? arr[i] : 0, 2 ** -10, `texel ${k}`));
});

function cloud(points, op = 0.9) {
  const N = points.length;
  const d = { N, px: new Float32Array(N), py: new Float32Array(N), pz: new Float32Array(N) };
  d.op = new Float32Array(N).fill(op);
  points.forEach(([x, y, z], i) => {
    d.px[i] = x;
    d.py[i] = y;
    d.pz[i] = z;
  });
  return d;
}

test('shadow volume: dense where the splats are, empty far from them', () => {
  const pts = [];
  for (let i = 0; i < 2000; i++) pts.push([(i % 10) / 10, 0.5 + ((i * 7) % 10) / 1000, 0.5]);
  pts.push([0, 0, 0], [1, 1, 1]); // bounds
  const o = buildOccupancy(cloud(pts), 32);
  assert.equal(o.data.length, 32 ** 3);
  const at = (x, y, z) => {
    const ix = Math.min(31, Math.floor(((x - o.min[0]) / o.ext[0]) * 32));
    const iy = Math.min(31, Math.floor(((y - o.min[1]) / o.ext[1]) * 32));
    const iz = Math.min(31, Math.floor(((z - o.min[2]) / o.ext[2]) * 32));
    return o.data[ix + 32 * (iy + 32 * iz)];
  };
  assert.ok(at(0.45, 0.5, 0.5) > 128, 'inside the slab');
  assert.equal(at(0.5, 0.95, 0.1), 0, 'far from it');
  assert.ok(o.min[0] < 0 && o.min[0] + o.ext[0] > 1, 'bounds are padded');
});

test('shadow volume: nothing opaque gives one transparent voxel', () => {
  const o = buildOccupancy(cloud([[0, 0, 0]], 0.01));
  assert.equal(o.res, 1);
  assert.deepEqual(Array.from(o.data), [0]);
});

test('shadow volume helpers: blur keeps the total in the interior, norm is the 90th percentile', () => {
  const res = 5;
  const v = new Float32Array(res ** 3);
  v[2 + 5 * (2 + 5 * 2)] = 27;
  const b = blurVolume(v, res);
  close(
    b.reduce((s, x) => s + x, 0),
    27,
    1e-4,
    'sum',
  );
  close(b[2 + 5 * (2 + 5 * 2)], 1, 1e-6, 'centre');
  const values = Float32Array.from({ length: 1000 }, (_, i) => i + 1);
  close(densityNorm(values), 900, 2, 'p90');
  assert.equal(densityNorm(new Float32Array(10)), 0);
});
