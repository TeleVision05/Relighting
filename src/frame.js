// Export frame → viewer frame, and the per-splat quantities derived from it.
//
// 3DGS exports use a Y-down convention, so the loader bakes a 180° rotation about X,
// (x, y, z) → (x, -y, -z), into positions and orientations as it reads them. Everything
// downstream (normals, smoothing, sorting, shading) then works in a right-side-up frame
// with no orientation special-casing anywhere.
//
// Pure functions only: no DOM, no GL. The parse loop calls them once per splat, so they
// write into a caller-owned `out` array instead of allocating.

export const SH_C0 = 0.28209479177387814;

// Position: the 180° rotation about X.
export function worldPosition(x, y, z, out) {
  out[0] = x;
  out[1] = -y;
  out[2] = -z;
  return out;
}

// Orientation: normalise (rot_0=w, rot_1=x, rot_2=y, rot_3=z), then apply the same 180° X
// rotation. Composing the quaternion (0,1,0,0) on the left gives (w,x,y,z) → (-x,w,-z,y).
// `out` receives (w, x, y, z).
export function worldQuaternion(r0, r1, r2, r3, out) {
  const qlen = Math.sqrt(r0 * r0 + r1 * r1 + r2 * r2 + r3 * r3) || 1;
  const uW = r0 / qlen,
    uX = r1 / qlen,
    uY = r2 / qlen,
    uZ = r3 / qlen;
  out[0] = -uX;
  out[1] = uW;
  out[2] = -uZ;
  out[3] = uY;
  return out;
}

// Columns of the rotation matrix R(q): the principal axes of the Gaussian.
export function quatAxes(qW, qX, qY, qZ) {
  return [
    [1 - 2 * (qY * qY + qZ * qZ), 2 * (qX * qY + qW * qZ), 2 * (qX * qZ - qW * qY)],
    [2 * (qX * qY - qW * qZ), 1 - 2 * (qX * qX + qZ * qZ), 2 * (qY * qZ + qW * qX)],
    [2 * (qX * qZ + qW * qY), 2 * (qY * qZ - qW * qX), 1 - 2 * (qX * qX + qY * qY)],
  ];
}

// Index (0, 1, 2) of the shortest axis, from the log-space scales a PLY stores.
export function thinAxis(logS0, logS1, logS2) {
  const s0 = Math.exp(logS0),
    s1 = Math.exp(logS1),
    s2 = Math.exp(logS2);
  if (s1 <= s0 && s1 <= s2) return 1;
  if (s2 <= s0 && s2 <= s1) return 2;
  return 0;
}

// Unit normal of a splat: its shortest principal axis (the flattening prior of the
// relightable-3DGS papers). The sign is arbitrary; see orientOutward in ply.js.
export function splatNormal(qW, qX, qY, qZ, logS0, logS1, logS2, out) {
  const axis = thinAxis(logS0, logS1, logS2);
  let x, y, z;
  if (axis === 0) {
    x = 1 - 2 * (qY * qY + qZ * qZ);
    y = 2 * (qX * qY + qW * qZ);
    z = 2 * (qX * qZ - qW * qY);
  } else if (axis === 1) {
    x = 2 * (qX * qY - qW * qZ);
    y = 1 - 2 * (qX * qX + qZ * qZ);
    z = 2 * (qY * qZ + qW * qX);
  } else {
    x = 2 * (qX * qZ + qW * qY);
    y = 2 * (qY * qZ - qW * qX);
    z = 1 - 2 * (qX * qX + qY * qY);
  }
  const nl = Math.sqrt(x * x + y * y + z * z) || 1;
  out[0] = x / nl;
  out[1] = y / nl;
  out[2] = z / nl;
  return out;
}

// SH degree-0 coefficient → baked linear appearance in [0, 1] (lighting still inside).
export function bakedFromSH(dc) {
  return Math.max(0, Math.min(1, 0.5 + dc * SH_C0));
}

// Logit opacity → [0, 1]. Clamped so extreme values cannot overflow exp().
export function sigmoidOpacity(raw) {
  return 1.0 / (1.0 + Math.exp(-Math.max(-20, Math.min(20, raw))));
}
