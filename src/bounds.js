// Axis-aligned bounds of the splats that matter for shading (opacity above 0.05).
// Shared by the lighting split, the normal fit and the shadow volume. Pure.

export const OPAQUE = 0.05;

// Returns { min: [x, y, z], max: [x, y, z] }. With no opaque splat, min is +Infinity and
// max is -Infinity on every axis; callers test `min[0] <= max[0]` before using them.
export function opaqueBounds(px, py, pz, op, N) {
  let minX = Infinity,
    minY = Infinity,
    minZ = Infinity,
    maxX = -Infinity,
    maxY = -Infinity,
    maxZ = -Infinity;
  for (let i = 0; i < N; i++) {
    if (op[i] <= OPAQUE) continue;
    if (px[i] < minX) minX = px[i];
    if (py[i] < minY) minY = py[i];
    if (pz[i] < minZ) minZ = pz[i];
    if (px[i] > maxX) maxX = px[i];
    if (py[i] > maxY) maxY = py[i];
    if (pz[i] > maxZ) maxZ = pz[i];
  }
  return { min: [minX, minY, minZ], max: [maxX, maxY, maxZ] };
}
