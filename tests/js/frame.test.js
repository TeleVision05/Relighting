// The export → viewer frame conversion: position flip, quaternion remap, splat normal.

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  SH_C0,
  bakedFromSH,
  quatAxes,
  sigmoidOpacity,
  splatNormal,
  thinAxis,
  worldPosition,
  worldQuaternion,
} from '../../src/frame.js';
import { close, closeVec, dot, randomQuat, rng } from './helpers.js';

const flipX180 = (v) => [v[0], -v[1], -v[2]];

test('positions: the 180° rotation about X, (x, y, z) → (x, -y, -z)', () => {
  assert.deepEqual(Array.from(worldPosition(1, 2, -3, [0, 0, 0])), [1, -2, 3]);
});

test('quaternions: the remap rotates every axis of the splat by 180° about X', () => {
  // Whatever the stored quaternion, the world-frame axes must be the export-frame axes
  // carried through the same flip as the positions. This pins the remap without
  // restating its formula.
  const rand = rng(7);
  for (let k = 0; k < 200; k++) {
    const [w, x, y, z] = randomQuat(rand);
    const exportAxes = quatAxes(w, x, y, z);
    const q = worldQuaternion(w, x, y, z, [0, 0, 0, 0]);
    const worldAxes = quatAxes(q[0], q[1], q[2], q[3]);
    for (let a = 0; a < 3; a++) closeVec(worldAxes[a], flipX180(exportAxes[a]), 1e-12, `axis ${a}`);
  }
});

test('quaternions: stored values need not be normalised, and a zero quaternion is safe', () => {
  const q = worldQuaternion(2, 0, 0, 0, [0, 0, 0, 0]);
  assert.deepEqual(Array.from(q), [-0, 1, -0, 0]);
  assert.deepEqual(Array.from(worldQuaternion(0, 0, 0, 0, [9, 9, 9, 9])), [-0, 0, -0, 0]);
});

test('quaternions: same convention as the Python scene generator, (w, x, y, z) → (-x, w, -z, y)', () => {
  const q = worldQuaternion(0.1, 0.2, 0.3, 0.4, [0, 0, 0, 0]);
  const n = Math.hypot(0.1, 0.2, 0.3, 0.4);
  closeVec(Array.from(q), [-0.2 / n, 0.1 / n, -0.4 / n, 0.3 / n], 1e-15, 'q');
});

test('quatAxes returns orthonormal columns of R(q)', () => {
  const rand = rng(3);
  for (let k = 0; k < 50; k++) {
    const axes = quatAxes(...randomQuat(rand));
    for (let a = 0; a < 3; a++) {
      for (let b = 0; b < 3; b++) close(dot(axes[a], axes[b]), a === b ? 1 : 0, 1e-12, `${a}·${b}`);
    }
  }
  // 90° about Z takes x to y.
  const s = Math.SQRT1_2;
  closeVec(quatAxes(s, 0, 0, s)[0], [0, 1, 0], 1e-12, 'x axis');
});

test('thin axis: the smallest log scale wins; ties go to the earlier axis after 0', () => {
  assert.equal(thinAxis(-1, -2, -3), 2);
  assert.equal(thinAxis(-3, -2, -1), 0);
  assert.equal(thinAxis(0, -5, 1), 1);
  assert.equal(thinAxis(-1, -1, 0), 1);
});

test('splat normal: the unit column of R(q) along the thin axis', () => {
  const rand = rng(11);
  for (let k = 0; k < 100; k++) {
    const q = randomQuat(rand);
    const s = [rand() * -6, rand() * -6, rand() * -6];
    const n = splatNormal(...q, ...s, [0, 0, 0]);
    closeVec(Array.from(n), quatAxes(...q)[thinAxis(...s)], 1e-12, 'normal');
  }
});

test('colour and opacity activation', () => {
  assert.equal(bakedFromSH(0), 0.5);
  close(bakedFromSH(1), 0.5 + SH_C0, 1e-15);
  assert.equal(bakedFromSH(-100), 0);
  assert.equal(bakedFromSH(100), 1);
  assert.equal(sigmoidOpacity(0), 0.5);
  close(sigmoidOpacity(Math.log(3)), 0.75, 1e-12);
  assert.equal(sigmoidOpacity(1e9), sigmoidOpacity(20), 'clamped before exp');
  assert.ok(Number.isFinite(sigmoidOpacity(-1e9)));
});
