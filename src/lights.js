/* Light rig maths. Pure: no DOM, no GL.
 *
 * MAX_LIGHTS is mirrored by the shaders' uniform array size (src/shaders/), so raising it
 * means raising both.
 */

const PI = Math.PI;
export const MAX_LIGHTS = 8;
export const LIGHT_TYPE = { point: 0, dir: 1, spot: 2 };
export const TYPE_LABEL = { point: 'Point', dir: 'Sun (directional)', spot: 'Spot' };

let lightSeq = 0;

export function makeLight(type, over = {}) {
  return Object.assign(
    {
      id: ++lightSeq,
      type,
      on: true,
      color: type === 'dir' ? '#ffffff' : '#38bdf8',
      intensity: type === 'dir' ? 1.8 : 1.5,
      x: 2,
      y: 2,
      z: 1, // position (point / spot)
      az: 45,
      el: 35, // sun: direction toward the light; spot: beam aim
      range: 4, // distance at which intensity halves
      cone: 30, // spot outer half-angle, degrees
      soft: 0.5, // spot edge softness, 0 = hard
      shadow: true, // marches the density volume
    },
    over,
  );
}

export function hexRGB(hex) {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16) / 255,
    parseInt(h.slice(2, 4), 16) / 255,
    parseInt(h.slice(4, 6), 16) / 255,
  ];
}

// Beam direction: the way light travels, away from the source.
export function lightAim(l) {
  const az = (l.az * PI) / 180,
    el = (l.el * PI) / 180,
    ce = Math.cos(el);
  const toward = [ce * Math.sin(az), Math.sin(el), ce * Math.cos(az)];
  // For a sun, az/el point at the light, so the beam travels the other way.
  // For a spot, az/el are the aim itself.
  return l.type === 'dir' ? [-toward[0], -toward[1], -toward[2]] : toward;
}

// Where to draw a directional light's marker — it has no position, so park it
// up-beam from the origin at a fixed distance.
export const DIR_GIZMO_DIST = 6.0;
export function lightGizmoPos(l) {
  if (l.type !== 'dir') return [l.x, l.y, l.z];
  const a = lightAim(l);
  return [-a[0] * DIR_GIZMO_DIST, -a[1] * DIR_GIZMO_DIST, -a[2] * DIR_GIZMO_DIST];
}

function emptyPack() {
  const f = (k) => new Float32Array(MAX_LIGHTS * k);
  return {
    n: 0,
    type: new Int32Array(MAX_LIGHTS),
    ...{ pos: f(3), dir: f(3), col: f(3), inten: f(1), range: f(1), cone: f(2), shadow: f(1) },
  };
}

// Pack the enabled lights into the flat arrays the shaders want. Lights turned down to
// zero are skipped here (they still get a marker), and at most MAX_LIGHTS are kept.
export function packLights(enabled) {
  const active = enabled.filter((l) => l.intensity > 0.0001);
  const p = emptyPack();
  p.n = Math.min(active.length, MAX_LIGHTS);
  for (let i = 0; i < p.n; i++) {
    const l = active[i],
      a = lightAim(l),
      c = hexRGB(l.color);
    p.type[i] = LIGHT_TYPE[l.type];
    p.pos.set([l.x, l.y, l.z], i * 3);
    p.dir.set(a, i * 3);
    p.col.set(c, i * 3);
    p.inten[i] = l.intensity;
    p.range[i] = l.range;
    p.shadow[i] = l.shadow ? 1 : 0;
    // cos(outer), cos(inner) — smoothstep between them softens the edge
    const outer = (l.cone * PI) / 180;
    const inner = outer * (1 - 0.98 * l.soft);
    p.cone[i * 2] = Math.cos(outer);
    p.cone[i * 2 + 1] = Math.cos(inner);
  }
  return p;
}
