// Plane-fit normals and the 3×3 eigen solver behind them.

import assert from 'node:assert/strict';
import test from 'node:test';

import { MIN_FIT_SPLATS, planeNormals, symEigenSmallest } from '../../src/normals.js';
import { close, dot, rng } from './helpers.js';

const unit = (v) => {
  const n = Math.hypot(...v);
  return v.map((x) => x / n);
};

test('eigen: a diagonal matrix gives its smallest axis', () => {
  const e = symEigenSmallest(3, 1, 2, 0, 0, 0);
  assert.deepEqual(e.v, [0, 1, 0]);
  assert.equal(e.l0, 1);
  assert.equal(e.l1, 2);
});

test('eigen: A·v = l0·v for random symmetric matrices, with l0 <= l1', () => {
  const rand = rng(17);
  for (let k = 0; k < 200; k++) {
    const [xx, yy, zz, xy, xz, yz] = Array.from({ length: 6 }, () => rand() * 2 - 1);
    const e = symEigenSmallest(xx + 3, yy + 3, zz + 3, xy, xz, yz);
    const [a, b, c] = e.v;
    const Av = [
      (xx + 3) * a + xy * b + xz * c,
      xy * a + (yy + 3) * b + yz * c,
      xz * a + yz * b + (zz + 3) * c,
    ];
    for (let i = 0; i < 3; i++) close(Av[i], e.l0 * e.v[i], 1e-9, `A·v[${i}]`);
    close(Math.hypot(a, b, c), 1, 1e-12, '|v|');
    assert.ok(e.l0 <= e.l1 + 1e-12);
  }
});

// Splats scattered on the plane through the origin with normal `n`, ±noise off it, plus
// raw normals that are the true one with random sign and some jitter.
function planeCloud(n, count, { noise = 0.002, jitter = 0.3, seed = 2 } = {}) {
  const rand = rng(seed);
  const u = unit(Math.abs(n[0]) < 0.9 ? [n[2], 0, -n[0]] : [0, n[2], -n[1]]);
  const w = [n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0]];
  const f = () => new Float32Array(count);
  const c = { px: f(), py: f(), pz: f(), nx: f(), ny: f(), nz: f(), op: f().fill(0.9) };
  for (let i = 0; i < count; i++) {
    const a = rand() * 2 - 1,
      b = rand() * 2 - 1,
      h = (rand() * 2 - 1) * noise;
    c.px[i] = a * u[0] + b * w[0] + h * n[0];
    c.py[i] = a * u[1] + b * w[1] + h * n[1];
    c.pz[i] = a * u[2] + b * w[2] + h * n[2];
    const sign = rand() < 0.5 ? -1 : 1;
    const raw = unit(n.map((x) => x + (rand() * 2 - 1) * jitter));
    [c.nx[i], c.ny[i], c.nz[i]] = raw.map((x) => x * sign);
  }
  return c;
}

const fit = (c, n = c.px.length, res) =>
  planeNormals(c.px, c.py, c.pz, c.nx, c.ny, c.nz, c.op, n, res);

test('a dense plane gets its true normal, cleaner than the noisy raw normals', () => {
  const n = unit([0.3, 0.8, -0.5]);
  const c = planeCloud(n, 60000);
  const { nsx, nsy, nsz } = fit(c);
  let worst = 1;
  for (let i = 0; i < 60000; i += 7)
    worst = Math.min(worst, Math.abs(dot([nsx[i], nsy[i], nsz[i]], n)));
  assert.ok(worst > 0.995, `worst |cos| ${worst}`);
});

test('the fitted normal keeps the hemisphere of each splat’s own axis', () => {
  const c = planeCloud(unit([0, 0, 1]), 30000);
  const { nsx, nsy, nsz } = fit(c);
  for (let i = 0; i < 30000; i += 11) {
    assert.ok(nsx[i] * c.nx[i] + nsy[i] * c.ny[i] + nsz[i] * c.nz[i] >= 0, `splat ${i}`);
  }
});

test('inside a dense volumetric blob the raw normals are kept', () => {
  // About 190 splats per 3×3×3 neighbourhood at grid 16: plenty for a fit, and the fit
  // must see that the patch is not a surface. (On the blob's faces the neighbourhood is
  // cut in half, which does read as a surface; only the interior is checked.)
  const rand = rng(9);
  const N = 30000;
  const f = () => new Float32Array(N);
  const c = { px: f(), py: f(), pz: f(), nx: f(), ny: f(), nz: f(), op: f().fill(0.9) };
  for (let i = 0; i < N; i++) {
    c.px[i] = rand();
    c.py[i] = rand();
    c.pz[i] = rand();
    [c.nx[i], c.ny[i], c.nz[i]] = unit([rand() - 0.5, rand() - 0.5, rand() - 0.5]);
  }
  const { nsx, nsy, nsz } = fit(c, N, 16);
  const inside = (i) => [c.px[i], c.py[i], c.pz[i]].every((v) => v > 0.2 && v < 0.8);
  let kept = 0,
    total = 0;
  for (let i = 0; i < N; i++) {
    if (!inside(i)) continue;
    total++;
    if (nsx[i] === c.nx[i] && nsy[i] === c.ny[i] && nsz[i] === c.nz[i]) kept++;
  }
  assert.ok(total > 5000);
  assert.ok(
    kept / total > 0.95,
    `only ${((100 * kept) / total).toFixed(1)}% kept their raw normal`,
  );
});

test('with no opaque splat the raw normals come back unchanged', () => {
  const c = planeCloud([0, 1, 0], 100);
  c.op.fill(0.01);
  const out = fit(c);
  assert.deepEqual(out.nsx, c.nx);
  assert.notEqual(out.nsx, c.nx, 'a copy, not the same array');
});

// A Fibonacci sphere like tests/viewer/splat_scenes.py's (radius 1), with raw normals that are
// the true radial ones, random sign, ~1.5 degrees of jitter.
function sparseSphere(n) {
  const rand = rng(4);
  const f = () => new Float32Array(n);
  const c = { px: f(), py: f(), pz: f(), nx: f(), ny: f(), nz: f(), op: f().fill(0.95) };
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (2 * (i + 0.5)) / n,
      r = Math.sqrt(1 - y * y);
    [c.px[i], c.py[i], c.pz[i]] = [Math.cos(golden * i) * r, y, Math.sin(golden * i) * r];
    const raw = unit([c.px[i], c.py[i], c.pz[i]].map((v) => v + (rand() * 2 - 1) * 0.025));
    const sign = rand() < 0.5 ? -1 : 1;
    [c.nx[i], c.ny[i], c.nz[i]] = raw.map((v) => v * sign);
  }
  return c;
}

function angleErrors(c, out) {
  const errs = [];
  for (let i = 0; i < c.px.length; i++) {
    const d = Math.abs(out.nsx[i] * c.px[i] + out.nsy[i] * c.py[i] + out.nsz[i] * c.pz[i]);
    errs.push((Math.acos(Math.min(1, d)) * 180) / Math.PI);
  }
  return errs.sort((a, b) => a - b);
}

test('a sparse surface is not fitted through a handful of splats', () => {
  // 4,000 splats on a unit sphere at grid 64 leaves about three per neighbourhood. Three
  // points always fit a plane exactly, so without a minimum the fit was accepted wherever
  // they happened to fall: p99 error 72 degrees, 4.3% of splats off by over 20 (measured
  // 2026-11-13 with minSplats 0, which this test also runs to show it still detects that).
  const c = sparseSphere(4000);
  const p99 = (e) => e[Math.floor(0.99 * e.length)];
  const fixed = angleErrors(c, fit(c));
  assert.ok(p99(fixed) < 5, `p99 ${p99(fixed).toFixed(1)} deg`);
  assert.equal(fixed.filter((e) => e > 20).length, 0);
  const old = angleErrors(c, planeNormals(c.px, c.py, c.pz, c.nx, c.ny, c.nz, c.op, 4000, 64, 0));
  assert.ok(p99(old) > 20, 'with no minimum the old failure comes back');
});

test('sparse random splats keep their raw normals instead of a three-point fit', () => {
  const rand = rng(9);
  const N = 30000; // about 3 per neighbourhood at grid 64
  const f = () => new Float32Array(N);
  const c = { px: f(), py: f(), pz: f(), nx: f(), ny: f(), nz: f(), op: f().fill(0.9) };
  for (let i = 0; i < N; i++) {
    [c.px[i], c.py[i], c.pz[i]] = [rand(), rand(), rand()];
    [c.nx[i], c.ny[i], c.nz[i]] = unit([rand() - 0.5, rand() - 0.5, rand() - 0.5]);
  }
  const out = fit(c);
  let kept = 0;
  for (let i = 0; i < N; i++) if (out.nsx[i] === c.nx[i] && out.nsz[i] === c.nz[i]) kept++;
  // Measured 2026-11-13: 14.8% kept with no minimum, 96.3% with MIN_FIT_SPLATS = 8 (the rest
  // are neighbourhoods that by chance hold 8 or more splats).
  assert.ok(kept / N > 0.9, `only ${((100 * kept) / N).toFixed(1)}% kept their raw normal`);
  assert.ok(MIN_FIT_SPLATS >= 6, 'a fit needs clearly more than three splats');
});
