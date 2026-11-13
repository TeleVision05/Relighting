// Shared helpers for the viewer's unit tests (node --test, no browser, no GPU).

import assert from 'node:assert/strict';

const WRITERS = {
  float: ['setFloat32', 4],
  double: ['setFloat64', 8],
  uchar: ['setUint8', 1],
  char: ['setInt8', 1],
  ushort: ['setUint16', 2],
  short: ['setInt16', 2],
  uint: ['setUint32', 4],
  int: ['setInt32', 4],
};

// The vertex properties of a 3DGS export, in the order Buttons.ply uses, with `rest`
// f_rest_* coefficients (24 for SH degree 1, 45 for degree 3).
export function splatProps(rest = 24, { colorType = 'float', opacityType = 'float' } = {}) {
  const names = ['x', 'y', 'z', 'nx', 'ny', 'nz', 'f_dc_0', 'f_dc_1', 'f_dc_2'];
  for (let i = 0; i < rest; i++) names.push(`f_rest_${i}`);
  names.push('opacity', 'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3');
  return names.map((name) => {
    if (name.startsWith('f_dc_')) return { name, type: colorType };
    if (name === 'opacity') return { name, type: opacityType };
    return { name, type: 'float' };
  });
}

// A binary PLY. rows: one object per vertex, { propName: value }; missing values are 0.
// Returns an ArrayBuffer, as fetch() or File.arrayBuffer() would.
export function makePly(props, rows, { little = true, eol = '\n', declared = rows.length } = {}) {
  const fmt = little ? 'binary_little_endian' : 'binary_big_endian';
  const header =
    [
      'ply',
      `format ${fmt} 1.0`,
      'comment made by tests/js/helpers.js',
      `element vertex ${declared}`,
      ...props.map((p) => `property ${p.type} ${p.name}`),
      'end_header',
    ].join(eol) + eol;
  const stride = props.reduce((s, p) => s + WRITERS[p.type][1], 0);
  const head = new TextEncoder().encode(header);
  const buf = new ArrayBuffer(head.length + stride * rows.length);
  new Uint8Array(buf).set(head);
  const dv = new DataView(buf, head.length);
  rows.forEach((row, i) => {
    let o = i * stride;
    for (const p of props) {
      const [method, size] = WRITERS[p.type];
      dv[method](o, row[p.name] ?? 0, little);
      o += size;
    }
  });
  return buf;
}

export function text(s) {
  return new TextEncoder().encode(s).buffer;
}

// Deterministic pseudo-random numbers in [0, 1).
export function rng(seed = 1) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export function randomQuat(rand) {
  const q = [rand() - 0.5, rand() - 0.5, rand() - 0.5, rand() - 0.5];
  const n = Math.hypot(...q);
  return q.map((v) => v / n);
}

export function close(actual, expected, tol, msg) {
  assert.ok(
    Math.abs(actual - expected) <= tol,
    `${msg || 'value'}: ${actual} is not within ${tol} of ${expected}`,
  );
}

export function closeVec(actual, expected, tol, msg) {
  assert.equal(actual.length, expected.length, `${msg || 'vector'}: length`);
  for (let i = 0; i < expected.length; i++) close(actual[i], expected[i], tol, `${msg}[${i}]`);
}

export const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
