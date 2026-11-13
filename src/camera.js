// Orbit camera looking at the scene centre (origin).
// cam.yaw = horizontal rotation, cam.pitch = vertical tilt, cam.zoom = distance.

const PI = Math.PI;
export const DEFAULT_VIEW = { yaw: 0.4, pitch: 0.25, zoom: 10 };
const PITCH_LIMIT = PI / 2 - 0.01;
const clampPitch = (p) => Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, p));
const clampZoom = (z) => Math.max(1, Math.min(50, z));

export function makeCamera() {
  return { ...DEFAULT_VIEW, dirty: true };
}

// Camera is at spherical position (yaw, pitch, zoom) looking at origin.
// Returns camera world position.
export function getCamPos(cam) {
  const cy = Math.cos(cam.yaw),
    sy = Math.sin(cam.yaw);
  const cp = Math.cos(cam.pitch),
    sp = Math.sin(cam.pitch);
  return [sy * cp * cam.zoom, sp * cam.zoom, cy * cp * cam.zoom];
}

// Row-major 3×3 view rotation: transforms (world - cam_pos) to view coords.
// The camera looks down its -Z axis in view space.
// This is the transpose of the standard camera-to-world rotation.
export function viewRot(cam) {
  const cy = Math.cos(cam.yaw),
    sy = Math.sin(cam.yaw);
  const cp = Math.cos(cam.pitch),
    sp = Math.sin(cam.pitch);
  // Row 0: right vector
  // Row 1: up vector
  // Row 2: -forward vector (camera looks in -Z, so this row = +forward in world)
  return [cy, 0, -sy, -sy * sp, cp, -cy * sp, sy * cp, sp, cy * cp];
}

// Focal length in pixels — shared by the shader and the sort worker's cull test.
export function focalFor(w, h) {
  return Math.min(w, h) * 0.8;
}

// ?cam=yaw,pitch,zoom (radians, radians, distance) fixes the starting view, so a view can
// be shared and the browser tests (tests/viewer/) see a known camera. Anything that does
// not parse gives null, and the default camera is used.
export function parseCamParam(text) {
  const v = (text || '').split(',').map(Number);
  if (v.length !== 3 || !v.every(Number.isFinite)) return null;
  return { yaw: v[0], pitch: clampPitch(v[1]), zoom: clampZoom(v[2]) };
}

function copyView(from, to) {
  to.yaw = from.yaw;
  to.pitch = from.pitch;
  to.zoom = from.zoom;
  to.dirty = true;
}

// Drag to orbit, wheel to zoom. `other` is the camera of the other pane, kept in lockstep.
export function attachOrbit(canvas, cam, other) {
  let down = false,
    sx = 0,
    sy = 0;
  canvas.addEventListener('pointerdown', (e) => {
    down = true;
    sx = e.clientX;
    sy = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!down) return;
    cam.yaw -= (e.clientX - sx) * 0.005;
    cam.pitch = clampPitch(cam.pitch + (e.clientY - sy) * 0.005);
    sx = e.clientX;
    sy = e.clientY;
    cam.dirty = true;
    copyView(cam, other);
  });
  canvas.addEventListener('pointerup', () => (down = false));
  canvas.addEventListener('pointercancel', () => (down = false));
  const onWheel = (e) => {
    e.preventDefault();
    cam.zoom = clampZoom(cam.zoom * Math.exp(e.deltaY * 0.001));
    cam.dirty = true;
    other.zoom = cam.zoom;
    other.dirty = true;
  };
  canvas.addEventListener('wheel', onWheel, { passive: false });
}
