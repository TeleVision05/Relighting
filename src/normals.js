/** Surface normals by local plane fit. Pure: no DOM, no GL.
 *
 *  The per-splat normal (shortest principal axis of the Gaussian) is only
 *  meaningful for splats that are actually flat, and its sign is arbitrary —
 *  averaging those directly gives a noisy field, which is what made relit
 *  surfaces look like crumpled foil. Instead, fit a plane to the splat centres
 *  in each voxel's 3×3×3 neighbourhood via PCA: the eigenvector of the smallest
 *  eigenvalue of the local covariance is the surface normal, and the eigenvalue
 *  ratio says how planar the neighbourhood is. Where the fit is weak (sparse or
 *  volumetric, e.g. foliage) we keep the splat's own axis.
 *
 *  Sign is left arbitrary on purpose — the shader flips the normal into the
 *  view hemisphere, which is the only consistent choice for a splat cloud.
 */

import { OPAQUE, opaqueBounds } from './bounds.js';

/** Unit eigenvector of the smallest eigenvalue of a symmetric 3×3 matrix,
 *  plus the two smallest eigenvalues (used to judge how planar the patch is).
 *  Cardano closed form + adjugate — no iteration, no matrix inverse.
 *  Matrix is [[xx,xy,xz],[xy,yy,yz],[xz,yz,zz]].
 */
export function symEigenSmallest(xx, yy, zz, xy, xz, yz) {
  const p1 = xy * xy + xz * xz + yz * yz;
  if (p1 < 1e-20) {
    // already diagonal
    if (xx <= yy && xx <= zz) return { v: [1, 0, 0], l0: xx, l1: Math.min(yy, zz) };
    if (yy <= zz) return { v: [0, 1, 0], l0: yy, l1: Math.min(xx, zz) };
    return { v: [0, 0, 1], l0: zz, l1: Math.min(xx, yy) };
  }
  const q = (xx + yy + zz) / 3;
  const p2 = (xx - q) * (xx - q) + (yy - q) * (yy - q) + (zz - q) * (zz - q) + 2 * p1;
  const p = Math.sqrt(p2 / 6);
  const ip = 1 / p;
  const b11 = (xx - q) * ip,
    b22 = (yy - q) * ip,
    b33 = (zz - q) * ip;
  const b12 = xy * ip,
    b13 = xz * ip,
    b23 = yz * ip;
  const det =
    b11 * (b22 * b33 - b23 * b23) - b12 * (b12 * b33 - b23 * b13) + b13 * (b12 * b23 - b22 * b13);
  const phi = Math.acos(Math.max(-1, Math.min(1, det / 2))) / 3;
  const l0 = q + 2 * p * Math.cos(phi + (2 * Math.PI) / 3); // smallest
  const l2 = q + 2 * p * Math.cos(phi); // largest
  const l1 = 3 * q - l0 - l2; // trace − others

  // Eigenvector for l0: any nonzero column of adj(A − l0·I).
  const a11 = xx - l0,
    a22 = yy - l0,
    a33 = zz - l0;
  const c0 = [a22 * a33 - yz * yz, xz * yz - xy * a33, xy * yz - a22 * xz];
  const c1 = [xz * yz - xy * a33, a11 * a33 - xz * xz, xy * xz - a11 * yz];
  const c2 = [xy * yz - a22 * xz, xy * xz - a11 * yz, a11 * a22 - xy * xy];
  let best = c0,
    bn = c0[0] * c0[0] + c0[1] * c0[1] + c0[2] * c0[2];
  const n1 = c1[0] * c1[0] + c1[1] * c1[1] + c1[2] * c1[2];
  if (n1 > bn) {
    best = c1;
    bn = n1;
  }
  const n2 = c2[0] * c2[0] + c2[1] * c2[1] + c2[2] * c2[2];
  if (n2 > bn) {
    best = c2;
    bn = n2;
  }
  if (bn < 1e-30) return { v: [0, 0, 1], l0, l1 };
  const inv = 1 / Math.sqrt(bn);
  return { v: [best[0] * inv, best[1] * inv, best[2] * inv], l0, l1 };
}

// The sums kept per voxel, in this order: weight, the three first moments, the six
// distinct second moments (all opacity-weighted), and the plain count of splats.
const MOMENTS = ['w', 'x', 'y', 'z', 'xx', 'yy', 'zz', 'xy', 'xz', 'yz', 'n'];
const WEIGHT = 0;
const COUNT = 10;

// Fewest splats a 3×3×3 neighbourhood needs before its plane fit is trusted. Any three
// points are exactly coplanar, so a fit through a handful of sparse splats reports perfect
// planarity whatever their layout. Measured 2026-11-13 (tests/js/normals.test.js): on a
// 4,000-splat unit sphere, no minimum gave p99 error 72 degrees with 4.3% of splats over 20;
// any minimum from 4 up gives p99 2 degrees. At 8, 0.15% of Buttons.ply's splats and 0.03%
// of father-day.ply's fall back to their own axis; a dense sphere is unchanged up to 24.
export const MIN_FIT_SPLATS = 8;

function cellOfAxis(v, min, ext, res) {
  return Math.max(0, Math.min(res - 1, (((v - min) / ext) * (res - 1)) | 0));
}

// First and second moments of the opaque splat centres per voxel, in scene-local
// coordinates, weighted by opacity. `m[k]` is one Float64Array per entry of MOMENTS.
export function voxelMoments(px, py, pz, op, N, box, res) {
  const cells = res * res * res;
  const m = MOMENTS.map(() => new Float64Array(cells));
  const cellOf = new Int32Array(N);
  const [minX, minY, minZ] = box.min;
  const [extX, extY, extZ] = box.ext;
  for (let i = 0; i < N; i++) {
    const ix = cellOfAxis(px[i], minX, extX, res);
    const iy = cellOfAxis(py[i], minY, extY, res);
    const iz = cellOfAxis(pz[i], minZ, extZ, res);
    const f = ix + res * (iy + res * iz);
    cellOf[i] = f;
    const w = op[i];
    if (w <= OPAQUE) continue;
    const X = px[i] - minX,
      Y = py[i] - minY,
      Z = pz[i] - minZ;
    m[0][f] += w;
    m[1][f] += w * X;
    m[2][f] += w * Y;
    m[3][f] += w * Z;
    m[4][f] += w * X * X;
    m[5][f] += w * Y * Y;
    m[6][f] += w * Z * Z;
    m[7][f] += w * X * Y;
    m[8][f] += w * X * Z;
    m[9][f] += w * Y * Z;
    m[COUNT][f] += 1;
  }
  return { m, cellOf };
}

// Sum of each moment over the 3×3×3 neighbourhood of voxel (x, y, z), into `acc`.
function gatherNeighbourhood(m, res, x, y, z, acc) {
  acc.fill(0);
  for (let dz = -1; dz <= 1; dz++) {
    const zz = z + dz;
    if (zz < 0 || zz >= res) continue;
    for (let dy = -1; dy <= 1; dy++) {
      const yy = y + dy;
      if (yy < 0 || yy >= res) continue;
      for (let dx = -1; dx <= 1; dx++) {
        const xx = x + dx;
        if (xx < 0 || xx >= res) continue;
        const g = xx + res * (yy + res * zz);
        if (m[WEIGHT][g] <= 0) continue;
        for (let k = 0; k < MOMENTS.length; k++) acc[k] += m[k][g];
      }
    }
  }
  return acc;
}

// Plane normal from neighbourhood moments, or null when the patch is too sparse to judge
// or not planar enough.
export function fitPlane(acc, minSplats = MIN_FIT_SPLATS) {
  const [W, AX, AY, AZ, AXX, AYY, AZZ, AXY, AXZ, AYZ, count] = acc;
  if (W <= 1e-6 || count < minSplats) return null;
  const iW = 1 / W,
    mx = AX * iW,
    my = AY * iW,
    mz = AZ * iW;
  const e = symEigenSmallest(
    AXX * iW - mx * mx,
    AYY * iW - my * my,
    AZZ * iW - mz * mz,
    AXY * iW - mx * my,
    AXZ * iW - mx * mz,
    AYZ * iW - my * mz,
  );
  // Planarity: smallest eigenvalue must be well below the middle one.
  const planar = e.l1 > 1e-18 ? 1 - e.l0 / e.l1 : 0;
  if (planar < 0.35) return null; // volumetric patch — keep raw
  return e.v;
}

// Per-voxel plane fit over the 3×3×3 neighbourhood: normals (xyz per cell) and a mask of
// the cells whose fit was accepted.
export function fitVoxelPlanes(m, res, minSplats = MIN_FIT_SPLATS) {
  const cells = res * res * res;
  const vn = new Float32Array(cells * 3);
  const vok = new Uint8Array(cells);
  const acc = new Float64Array(MOMENTS.length);
  for (let z = 0; z < res; z++) {
    for (let y = 0; y < res; y++) {
      for (let x = 0; x < res; x++) {
        const f = x + res * (y + res * z);
        if (m[WEIGHT][f] <= 0) continue; // only fit where splats live
        const v = fitPlane(gatherNeighbourhood(m, res, x, y, z, acc), minSplats);
        if (!v) continue;
        vn[f * 3] = v[0];
        vn[f * 3 + 1] = v[1];
        vn[f * 3 + 2] = v[2];
        vok[f] = 1;
      }
    }
  }
  return { vn, vok };
}

export function planeNormals(
  px,
  py,
  pz,
  nx,
  ny,
  nz,
  op,
  N,
  gridRes = 64,
  minSplats = MIN_FIT_SPLATS,
) {
  const { min, max } = opaqueBounds(px, py, pz, op, N);
  if (!(min[0] <= max[0])) {
    // no usable splats
    return { nsx: nx.slice(), nsy: ny.slice(), nsz: nz.slice() };
  }
  const ext = [0, 1, 2].map((a) => Math.max(1e-6, max[a] - min[a]));
  const { m, cellOf } = voxelMoments(px, py, pz, op, N, { min, ext }, gridRes);
  const { vn, vok } = fitVoxelPlanes(m, gridRes, minSplats);

  const nsx = new Float32Array(N),
    nsy = new Float32Array(N),
    nsz = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const f = cellOf[i];
    if (!vok[f]) {
      nsx[i] = nx[i];
      nsy[i] = ny[i];
      nsz[i] = nz[i];
      continue;
    }
    // Keep it in the same hemisphere as the splat's own axis so the raw↔smooth blend in
    // the shader never cancels.
    const s = vn[f * 3] * nx[i] + vn[f * 3 + 1] * ny[i] + vn[f * 3 + 2] * nz[i] < 0 ? -1 : 1;
    nsx[i] = s * vn[f * 3];
    nsy[i] = s * vn[f * 3 + 1];
    nsz[i] = s * vn[f * 3 + 2];
  }
  return { nsx, nsy, nsz };
}
