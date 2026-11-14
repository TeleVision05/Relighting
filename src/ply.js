// Binary PLY → per-splat typed arrays in the viewer frame. Pure: no DOM, no GL.
//
// Splat PLYs differ in layout: SH degree 1 exports carry 24 f_rest_* properties
// (41 floats / 164 B per vertex), degree 3 exports carry 45 (62 floats / 248 B), and some
// exporters misspell nx as nxx. Anything that assumes a fixed stride reads garbage on the
// other layout, so the property table is built from the header and read by name.

import { ViewerError } from './errors.js';
import {
  bakedFromSH,
  sigmoidOpacity,
  splatNormal,
  worldPosition,
  worldQuaternion,
} from './frame.js';

export const PLY_TYPE_SIZE = {
  char: 1,
  int8: 1,
  uchar: 1,
  uint8: 1,
  short: 2,
  int16: 2,
  ushort: 2,
  uint16: 2,
  int: 4,
  int32: 4,
  uint: 4,
  uint32: 4,
  float: 4,
  float32: 4,
  double: 8,
  float64: 8,
};

const BYTE_TYPES = ['uchar', 'uint8', 'char', 'int8'];
const END_HEADER = [101, 110, 100, 95, 104, 101, 97, 100, 101, 114]; // "end_header"
const LFS_POINTER = 'version https://git-lfs';

function unsupported(detail) {
  return new ViewerError('unsupported-ply', detail);
}

// Byte offset of "end_header" within the first 64 KiB, or -1.
export function findHeaderEnd(bytes) {
  for (let i = 0; i < Math.min(bytes.length, 65536) - 10; i++) {
    let match = true;
    for (let j = 0; j < 10; j++)
      if (bytes[i + j] !== END_HEADER[j]) {
        match = false;
        break;
      }
    if (match) return i;
  }
  return -1;
}

// First byte of vertex data: after "end_header" and its line ending.
export function dataStart(bytes, hdrEnd) {
  let i = hdrEnd + 10;
  while (i < bytes.length && (bytes[i] === 10 || bytes[i] === 13)) i++;
  return i;
}

export function parsePLYHeader(hdrText) {
  let N = 0,
    stride = 0,
    little = true,
    inVertex = false;
  const props = {};
  for (const raw of hdrText.split('\n')) {
    const line = raw.trim();
    if (line.startsWith('format ')) {
      const fmt = line.split(/\s+/)[1];
      if (fmt === 'ascii') throw unsupported('ASCII PLY not supported — export as binary');
      little = fmt !== 'binary_big_endian';
    } else if (line.startsWith('element ')) {
      const t = line.split(/\s+/);
      inVertex = t[1] === 'vertex';
      if (inVertex) N = parseInt(t[2], 10);
    } else if (inVertex && line.startsWith('property ')) {
      const t = line.split(/\s+/);
      if (t[1] === 'list') throw unsupported('list properties not supported in vertex element');
      const size = PLY_TYPE_SIZE[t[1]];
      if (!size) throw unsupported(`Unknown PLY property type "${t[1]}"`);
      props[t[2]] = { offset: stride, type: t[1] };
      stride += size;
    }
  }
  if (!N) throw unsupported('No vertex element in PLY header');
  return { N, props, stride, little };
}

// Returns a (dataView, vertexBase) reader for the first name that exists.
export function plyReader(hdr, names, required) {
  for (const n of names) {
    const p = hdr.props[n];
    if (!p) continue;
    const o = p.offset,
      le = hdr.little;
    switch (p.type) {
      case 'float':
      case 'float32':
        return (dv, b) => dv.getFloat32(b + o, le);
      case 'double':
      case 'float64':
        return (dv, b) => dv.getFloat64(b + o, le);
      case 'uchar':
      case 'uint8':
        return (dv, b) => dv.getUint8(b + o);
      case 'char':
      case 'int8':
        return (dv, b) => dv.getInt8(b + o);
      case 'ushort':
      case 'uint16':
        return (dv, b) => dv.getUint16(b + o, le);
      case 'short':
      case 'int16':
        return (dv, b) => dv.getInt16(b + o, le);
      case 'uint':
      case 'uint32':
        return (dv, b) => dv.getUint32(b + o, le);
      case 'int':
      case 'int32':
        return (dv, b) => dv.getInt32(b + o, le);
    }
  }
  if (required) throw unsupported(`PLY is missing required property "${names[0]}"`);
  return null;
}

// Header + layout of a whole file. Throws ViewerError('unsupported-ply' | 'lfs-pointer').
export function readLayout(buf) {
  const bytes = new Uint8Array(buf);
  const head = new TextDecoder().decode(bytes.subarray(0, 64));
  if (head.startsWith(LFS_POINTER)) throw new ViewerError('lfs-pointer', 'Git LFS pointer file');
  const hdrEnd = findHeaderEnd(bytes);
  if (hdrEnd < 0) throw unsupported('No end_header found');
  const hdr = parsePLYHeader(new TextDecoder().decode(bytes.slice(0, hdrEnd)));
  const start = dataStart(bytes, hdrEnd);
  const available = Math.floor((buf.byteLength - start) / hdr.stride);
  const realN = Math.min(hdr.N, available);
  if (!(realN > 0)) throw unsupported(`No complete vertex records (stride ${hdr.stride} B)`);
  return { hdr, start, realN };
}

function makeReaders(hdr) {
  const r = (names) => plyReader(hdr, names, true);
  const typeOf = (...names) => (names.map((n) => hdr.props[n]).find(Boolean) || {}).type;
  return {
    x: r(['x']),
    y: r(['y']),
    z: r(['z']),
    dc: [r(['f_dc_0', 'red', 'r']), r(['f_dc_1', 'green', 'g']), r(['f_dc_2', 'blue', 'b'])],
    op: r(['opacity', 'alpha']),
    sc: [r(['scale_0']), r(['scale_1']), r(['scale_2'])],
    rot: [r(['rot_0']), r(['rot_1']), r(['rot_2']), r(['rot_3'])],
    // Colours stored as 0–255 bytes need a different SH-DC decode than raw floats, and
    // byte-encoded exports store opacity already activated.
    colorIsByte: BYTE_TYPES.includes(typeOf('f_dc_0', 'red', 'r')),
    opacityIsByte: BYTE_TYPES.includes(typeOf('opacity', 'alpha')),
  };
}

// Per-splat arrays the parser fills: position, baked colour, opacity, log scales, rotation
// quaternion (w, x, y, z) and the raw normal, all in the viewer frame.
export const SPLAT_FIELDS = [
  ...['px', 'py', 'pz', 'bakedR', 'bakedG', 'bakedB', 'op'],
  ...['sc0', 'sc1', 'sc2', 'qw', 'qx', 'qy', 'qz', 'nx', 'ny', 'nz'],
];

export function allocSplats(N) {
  return Object.fromEntries(SPLAT_FIELDS.map((k) => [k, new Float32Array(N)]));
}

// Decode splats [from, to) into `s`. Returns the opacity-weighted centroid sums.
function decodeRange(dv, stride, rd, s, from, to, acc) {
  const p = new Float64Array(3),
    q = new Float64Array(4),
    n = new Float64Array(3);
  for (let i = from; i < to; i++) {
    const b = i * stride;
    worldPosition(rd.x(dv, b), rd.y(dv, b), rd.z(dv, b), p);
    s.px[i] = p[0];
    s.py[i] = p[1];
    s.pz[i] = p[2];
    // SH DC → baked linear appearance (NOT albedo — lighting is still inside)
    const c0 = rd.dc[0](dv, b),
      c1 = rd.dc[1](dv, b),
      c2 = rd.dc[2](dv, b);
    s.bakedR[i] = rd.colorIsByte ? c0 / 255 : bakedFromSH(c0);
    s.bakedG[i] = rd.colorIsByte ? c1 / 255 : bakedFromSH(c1);
    s.bakedB[i] = rd.colorIsByte ? c2 / 255 : bakedFromSH(c2);
    const oRaw = rd.op(dv, b);
    s.op[i] = rd.opacityIsByte ? oRaw / 255 : sigmoidOpacity(oRaw);
    s.sc0[i] = rd.sc[0](dv, b); // log space
    s.sc1[i] = rd.sc[1](dv, b);
    s.sc2[i] = rd.sc[2](dv, b);
    worldQuaternion(rd.rot[0](dv, b), rd.rot[1](dv, b), rd.rot[2](dv, b), rd.rot[3](dv, b), q);
    s.qw[i] = q[0];
    s.qx[i] = q[1];
    s.qy[i] = q[2];
    s.qz[i] = q[3];
    splatNormal(q[0], q[1], q[2], q[3], s.sc0[i], s.sc1[i], s.sc2[i], n);
    s.nx[i] = n[0];
    s.ny[i] = n[1];
    s.nz[i] = n[2];
    if (s.op[i] > 0.05) {
      acc[0] += s.px[i];
      acc[1] += s.py[i];
      acc[2] += s.pz[i];
      acc[3]++;
    }
  }
}

// Orient normals outward from the scene centroid (a consistent hemisphere for shading).
export function orientOutward(s, N, acc) {
  if (!(acc[3] > 0)) return;
  const cx = acc[0] / acc[3],
    cy = acc[1] / acc[3],
    cz = acc[2] / acc[3];
  for (let i = 0; i < N; i++) {
    const ox = s.px[i] - cx,
      oy = s.py[i] - cy,
      oz = s.pz[i] - cz;
    if (s.nx[i] * ox + s.ny[i] * oy + s.nz[i] * oz < 0) {
      s.nx[i] = -s.nx[i];
      s.ny[i] = -s.ny[i];
      s.nz[i] = -s.nz[i];
    }
  }
}

const CHUNK = 1 << 16;

// Parse a whole PLY. `onProgress(done, total)` is called between chunks of splats.
// Arrays are sized by the header; `N` is the number of splats actually present.
export function decodeSplats(buf, { layout = readLayout(buf), onProgress } = {}) {
  const { hdr, start, realN } = layout;
  const rd = makeReaders(hdr);
  const s = allocSplats(hdr.N);
  const dv = new DataView(buf, start);
  const acc = [0, 0, 0, 0]; // centroid sums of the opaque splats, and their count
  for (let from = 0; from < realN; from += CHUNK) {
    decodeRange(dv, hdr.stride, rd, s, from, Math.min(realN, from + CHUNK), acc);
    if (onProgress) onProgress(Math.min(realN, from + CHUNK), realN);
  }
  orientOutward(s, realN, acc);
  return { N: realN, headerN: hdr.N, stride: hdr.stride, ...s };
}
