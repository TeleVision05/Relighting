// Camera, lights and the depth sort: the maths the shaders and the sort worker share.

import assert from 'node:assert/strict';
import test from 'node:test';

import { focalFor, getCamPos, parseCamParam, viewRot } from '../../src/camera.js';
import {
  DIR_GIZMO_DIST,
  MAX_LIGHTS,
  hexRGB,
  lightAim,
  lightGizmoPos,
  makeLight,
  packLights,
} from '../../src/lights.js';
import { splatSortCore } from '../../src/sort.js';
import { close, closeVec, dot } from './helpers.js';

test('?cam= parses yaw,pitch,zoom, clamps pitch and zoom, and rejects anything else', () => {
  assert.deepEqual(parseCamParam('0.5,0.25,8'), { yaw: 0.5, pitch: 0.25, zoom: 8 });
  const c = parseCamParam('1,9,999');
  close(c.pitch, Math.PI / 2 - 0.01, 1e-12);
  assert.equal(c.zoom, 50);
  for (const bad of [null, '', '1,2', '1,2,3,4', 'a,b,c', '1,NaN,3', '1,Infinity,3']) {
    assert.equal(parseCamParam(bad), null, String(bad));
  }
});

test('view rotation is orthonormal and the camera looks at the origin', () => {
  for (const cam of [
    { yaw: 0.4, pitch: 0.25, zoom: 10 },
    { yaw: -2, pitch: -1.2, zoom: 3 },
  ]) {
    const R = viewRot(cam);
    const rows = [R.slice(0, 3), R.slice(3, 6), R.slice(6, 9)];
    for (let a = 0; a < 3; a++) {
      for (let b = 0; b < 3; b++) close(dot(rows[a], rows[b]), a === b ? 1 : 0, 1e-12);
    }
    const p = getCamPos(cam);
    const toOrigin = p.map((v) => -v);
    // The origin sits straight ahead: view x = y = 0, depth (-z) = zoom.
    closeVec([dot(rows[0], toOrigin), dot(rows[1], toOrigin)], [0, 0], 1e-9, 'centred');
    close(-dot(rows[2], toOrigin), cam.zoom, 1e-9, 'depth');
  }
  assert.equal(focalFor(1000, 500), 400);
});

test('lights: a sun’s az/el point at the light, so its beam travels the other way', () => {
  const sun = makeLight('dir', { az: 0, el: 90 });
  closeVec(lightAim(sun), [-0, -1, -0], 1e-12, 'sun straight up shines down');
  const spot = makeLight('spot', { az: 0, el: -90 });
  closeVec(lightAim(spot), [0, -1, 0], 1e-12, 'spot aimed down');
  closeVec(lightGizmoPos(sun), [0, DIR_GIZMO_DIST, 0], 1e-12, 'sun marker overhead');
  assert.deepEqual(lightGizmoPos(makeLight('point', { x: 1, y: 2, z: 3 })), [1, 2, 3]);
  assert.deepEqual(hexRGB('#ff8000'), [1, 128 / 255, 0]);
});

test('lights: packing skips zero-intensity lights and caps at MAX_LIGHTS', () => {
  const lights = [makeLight('point', { intensity: 0 })];
  for (let i = 0; i < 10; i++)
    lights.push(makeLight('spot', { intensity: 1 + i, cone: 60, soft: 0 }));
  const p = packLights(lights);
  assert.equal(p.n, MAX_LIGHTS);
  assert.equal(p.inten[0], 1, 'the zero-intensity light was skipped');
  assert.equal(p.type[0], 2);
  close(p.cone[0], 0.5, 1e-12, 'cos(60°)');
  close(p.cone[1], 0.5, 1e-12, 'softness 0 is a hard edge: inner = outer');
  const soft = packLights([makeLight('spot', { cone: 60, soft: 1 })]);
  close(soft.cone[1], Math.cos((60 * 0.02 * Math.PI) / 180), 1e-6, 'softness 1: inner is 2%');
  assert.equal(packLights([]).n, 0);
});

function sortState(points, op = 1) {
  const N = points.length;
  const S = { N, px: new Float32Array(N), py: new Float32Array(N), pz: new Float32Array(N) };
  S.op = new Float32Array(N).fill(op);
  points.forEach(([x, y, z], i) => {
    S.px[i] = x;
    S.py[i] = y;
    S.pz[i] = z;
  });
  return S;
}

const camera = (cam = { yaw: 0, pitch: 0, zoom: 10 }, w = 800, h = 600) => ({
  R: viewRot(cam),
  cp: getCamPos(cam),
  focal: focalFor(w, h),
  w,
  h,
});

test('sort: splats come back far to near, behind-camera and transparent ones dropped', () => {
  // Camera on +z at distance 10 looking at the origin: smaller z is farther.
  const S = sortState([
    [0, 0, 2],
    [0, 0, -3],
    [0, 0, 20], // behind the camera
    [0, 0, 0],
    [0, 0, 5],
  ]);
  S.op[4] = 0.001;
  const r = splatSortCore(S, camera());
  assert.equal(r.count, 3);
  assert.deepEqual(Array.from(r.order.subarray(0, r.count)), [1, 3, 0]);
});

test('sort: splats far outside the viewport are culled; the reuse buffer is used', () => {
  const S = sortState([
    [0, 0, 0],
    [1000, 0, 0],
  ]);
  const reuse = new Uint32Array(8);
  const r = splatSortCore(S, { ...camera(), reuse });
  assert.equal(r.count, 1);
  assert.equal(r.order, reuse);
  assert.equal(splatSortCore(sortState([]), camera()).count, 0);
});
