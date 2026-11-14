// PLY parsing: header, typed readers, the decode loop and the files it must refuse.

import assert from 'node:assert/strict';
import test from 'node:test';

import { ViewerError } from '../../src/errors.js';
import { SH_C0 } from '../../src/frame.js';
import {
  dataStart,
  decodeSplats,
  findHeaderEnd,
  parsePLYHeader,
  plyReader,
  readLayout,
} from '../../src/ply.js';
import { close, closeVec, makePly, splatProps, text } from './helpers.js';

const kindOf = (fn) => {
  try {
    fn();
  } catch (e) {
    assert.ok(e instanceof ViewerError, `expected a ViewerError, got ${e}`);
    return e.kind;
  }
  assert.fail('expected a throw');
};

test('header: count, stride and offsets come from the property list', () => {
  const hdr = parsePLYHeader(
    'ply\nformat binary_little_endian 1.0\nelement vertex 7\n' +
      'property float x\nproperty uchar red\nproperty double d\nproperty short s\nend_header',
  );
  assert.equal(hdr.N, 7);
  assert.equal(hdr.stride, 4 + 1 + 8 + 2);
  assert.equal(hdr.little, true);
  assert.deepEqual(hdr.props.red, { offset: 4, type: 'uchar' });
  assert.deepEqual(hdr.props.s, { offset: 13, type: 'short' });
});

test('header: properties of other elements do not count toward the vertex stride', () => {
  const hdr = parsePLYHeader(
    'ply\nformat binary_big_endian 1.0\nelement vertex 2\nproperty float x\n' +
      'element face 1\nproperty int f\nend_header',
  );
  assert.equal(hdr.stride, 4);
  assert.equal(hdr.little, false);
  assert.equal(hdr.props.f, undefined);
});

test('header: unreadable layouts are unsupported-ply, not crashes', () => {
  const v = 'ply\nformat binary_little_endian 1.0\nelement vertex 3\n';
  assert.equal(
    kindOf(() => parsePLYHeader('ply\nformat ascii 1.0\nelement vertex 1')),
    'unsupported-ply',
  );
  assert.equal(
    kindOf(() => parsePLYHeader(v + 'property list uchar int i')),
    'unsupported-ply',
  );
  assert.equal(
    kindOf(() => parsePLYHeader(v + 'property quad q')),
    'unsupported-ply',
  );
  assert.equal(
    kindOf(() => parsePLYHeader('ply\nformat binary_little_endian 1.0')),
    'unsupported-ply',
  );
});

test('end_header is found, and the data starts after its line ending (LF or CRLF)', () => {
  for (const eol of ['\n', '\r\n']) {
    const bytes = new Uint8Array(makePly([{ name: 'x', type: 'float' }], [{ x: 1 }], { eol }));
    const end = findHeaderEnd(bytes);
    assert.equal(new TextDecoder().decode(bytes.subarray(end, end + 10)), 'end_header');
    assert.equal(dataStart(bytes, end), bytes.length - 4);
  }
  assert.equal(findHeaderEnd(new Uint8Array(text('ply\nno header end here'))), -1);
});

test('readers decode every PLY scalar type in both byte orders', () => {
  const types = ['float', 'double', 'uchar', 'char', 'ushort', 'short', 'uint', 'int'];
  const value = { float: 1.5, double: -2.25, uchar: 200, char: -5, ushort: 60000 };
  Object.assign(value, { short: -300, uint: 4000000000, int: -70000 });
  for (const little of [true, false]) {
    const props = types.map((t) => ({ name: t, type: t }));
    const buf = makePly(props, [value], { little });
    const { hdr, start } = readLayout(buf);
    const dv = new DataView(buf, start);
    for (const t of types)
      assert.equal(plyReader(hdr, [t], true)(dv, 0), value[t], `${t} ${little}`);
  }
});

test('readers fall back through alternative names, and say which property is missing', () => {
  const buf = makePly([{ name: 'red', type: 'uchar' }], [{ red: 9 }]);
  const { hdr, start } = readLayout(buf);
  assert.equal(plyReader(hdr, ['f_dc_0', 'red', 'r'], true)(new DataView(buf, start), 0), 9);
  assert.equal(plyReader(hdr, ['opacity'], false), null);
  assert.throws(
    () => plyReader(hdr, ['opacity', 'alpha'], true),
    /missing required property "opacity"/,
  );
});

const IDENTITY = { rot_0: 1, rot_1: 0, rot_2: 0, rot_3: 0 };

test('decode: positions get the 180° X flip and colours/opacity are activated', () => {
  const row = { x: 1, y: 2, z: 3, f_dc_0: 0.5, f_dc_1: -10, f_dc_2: 10, opacity: 0, ...IDENTITY };
  const d = decodeSplats(makePly(splatProps(), [row]));
  assert.equal(d.N, 1);
  assert.deepEqual([d.px[0], d.py[0], d.pz[0]], [1, -2, -3]);
  close(d.bakedR[0], 0.5 + 0.5 * SH_C0, 1e-6, 'bakedR');
  assert.equal(d.bakedG[0], 0, 'clamped at 0');
  assert.equal(d.bakedB[0], 1, 'clamped at 1');
  close(d.op[0], 0.5, 1e-7, 'sigmoid(0)');
});

test('decode: byte-encoded colour and opacity are already activated', () => {
  const props = splatProps(0, { colorType: 'uchar', opacityType: 'uchar' });
  const row = { f_dc_0: 255, f_dc_1: 0, f_dc_2: 51, opacity: 102, ...IDENTITY };
  const d = decodeSplats(makePly(props, [row]));
  closeVec([d.bakedR[0], d.bakedG[0], d.bakedB[0], d.op[0]], [1, 0, 0.2, 0.4], 1e-6, 'bytes');
});

test('decode: the quaternion is normalised and remapped (w,x,y,z) → (-x,w,-z,y)', () => {
  const row = { rot_0: 2, rot_1: 4, rot_2: 6, rot_3: 8, scale_0: -1, scale_1: -2, scale_2: -3 };
  const d = decodeSplats(makePly(splatProps(), [row]));
  const n = Math.hypot(2, 4, 6, 8);
  closeVec([d.qw[0], d.qx[0], d.qy[0], d.qz[0]], [-4 / n, 2 / n, -8 / n, 6 / n], 1e-6, 'q');
  assert.deepEqual([d.sc0[0], d.sc1[0], d.sc2[0]], [-1, -2, -3]);
});

test('decode: the normal is the thin axis, flipped to face away from the centroid', () => {
  // Two splats flat along their own z (scale_2 smallest), with the identity export rotation,
  // one at z = +1 and one at z = -1 in the export frame. Their thin axis is world ±z, and
  // each normal must point away from the pair's centroid.
  const flat = { scale_0: 0, scale_1: 0, scale_2: -5, opacity: 5, ...IDENTITY };
  const d = decodeSplats(
    makePly(splatProps(), [
      { ...flat, z: 1 },
      { ...flat, z: -1 },
    ]),
  );
  for (const i of [0, 1]) {
    closeVec([d.nx[i], d.ny[i], Math.abs(d.nz[i])], [0, 0, 1], 1e-6, `normal ${i}`);
    assert.ok(d.nz[i] * d.pz[i] > 0, `normal ${i} faces outward`);
  }
});

test('decode: SH degree 1 and degree 3 layouts give identical splats', () => {
  const rows = [
    { x: 0.3, y: -0.7, z: 2, f_dc_0: 0.1, opacity: 1.2, scale_1: -4, rot_0: 0.9, rot_2: 0.4 },
  ];
  const a = decodeSplats(makePly(splatProps(24), rows));
  const b = decodeSplats(makePly(splatProps(45), rows));
  for (const k of ['px', 'py', 'pz', 'bakedR', 'op', 'qw', 'qy', 'nx', 'ny', 'nz']) {
    assert.deepEqual(a[k], b[k], k);
  }
});

test('decode: a big-endian file reads the same as a little-endian one', () => {
  const rows = [{ x: 1.25, y: 2, z: -3, f_dc_2: 0.4, opacity: -1, scale_0: -2, rot_3: 1 }];
  const a = decodeSplats(makePly(splatProps(), rows, { little: true }));
  const b = decodeSplats(makePly(splatProps(), rows, { little: false }));
  for (const k of ['px', 'py', 'pz', 'bakedB', 'op', 'qw', 'qx', 'qy', 'qz'])
    assert.deepEqual(a[k], b[k], k);
});

test('decode: a truncated file keeps only its complete records; none at all is refused', () => {
  const rows = [
    { x: 1, ...IDENTITY },
    { x: 2, ...IDENTITY },
  ];
  const d = decodeSplats(makePly(splatProps(), rows, { declared: 5 }));
  assert.equal(d.N, 2);
  assert.equal(d.headerN, 5);
  assert.equal(
    kindOf(() => decodeSplats(makePly(splatProps(), [], { declared: 5 }))),
    'unsupported-ply',
  );
});

test('decode: progress is reported up to the full count', () => {
  const rows = Array.from({ length: 70000 }, (_, i) => ({ x: i, ...IDENTITY }));
  const seen = [];
  decodeSplats(makePly(splatProps(0), rows), {
    onProgress: (done, total) => seen.push([done, total]),
  });
  assert.deepEqual(seen, [
    [65536, 70000],
    [70000, 70000],
  ]);
});

test('files that are not splat PLYs are named for what they are', () => {
  assert.equal(
    kindOf(() => readLayout(text('hello, not a scene'))),
    'unsupported-ply',
  );
  const lfs = 'version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 12\n';
  assert.equal(
    kindOf(() => readLayout(text(lfs))),
    'lfs-pointer',
  );
  const noRot = splatProps().filter((p) => p.name !== 'rot_3');
  assert.equal(
    kindOf(() => decodeSplats(makePly(noRot, [{}]))),
    'unsupported-ply',
  );
});
