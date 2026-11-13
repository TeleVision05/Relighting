// Light-marker overlay shaders. Moved verbatim from index.html.

// A camera-facing quad at the light's world position. Uses the same projection
// as the splats so it sits exactly where the light does. Drawn additively after
// the cloud, and always on top — the splat pass writes no depth, and a light
// you can't find because it's behind the model is the thing we're fixing.
export const GIZMO_VERT = `#version 300 es
precision highp float;

in vec2 aCorner;

uniform vec2  uViewport;
uniform vec3  uCamPos;
uniform vec3  uR0, uR1, uR2;
uniform float uFocal;
uniform vec3  uLightPos;
uniform float uWorldRadius;

out vec2 vUV;

void main() {
  vec3 d = uLightPos - uCamPos;
  vec3 v = vec3(dot(uR0,d), dot(uR1,d), dot(uR2,d));
  float depth = -v.z;
  if (depth < 0.02) {           // behind the camera — skip
    gl_Position = vec4(0.0, 0.0, 2.0, 1.0);
    vUV = vec2(0.0);
    return;
  }
  vec2 half_ = uViewport * 0.5;
  vec2 ndc   = vec2(uFocal*v.x/(depth*half_.x), uFocal*v.y/(depth*half_.y));
  // Perspective-scaled so it reads as a position in space, but clamped so it
  // never shrinks to nothing or swallows the screen.
  float rpx = clamp(uFocal * uWorldRadius / depth, 20.0, 160.0);
  vUV = aCorner;
  gl_Position = vec4(ndc + 2.0*aCorner*rpx/uViewport, 0.0, 1.0);
}
`;

export const GIZMO_FRAG = `#version 300 es
precision highp float;

in vec2 vUV;
uniform vec3  uColor;
uniform float uDim;      // fades the marker when the light is off

out vec4 fragColor;

void main() {
  float r = length(vUV);
  if (r > 1.0) discard;

  float glow  = pow(max(0.0, 1.0 - r), 3.0) * 0.45;               // soft falloff
  float core  = smoothstep(0.15, 0.04, r);                        // bright centre
  float ring  = smoothstep(0.055, 0.0, abs(r - 0.70)) * 0.85;     // locator ring
  // Crosshair ticks, broken around the core so the exact centre stays readable
  float tick  = (smoothstep(0.030, 0.0, abs(vUV.x)) + smoothstep(0.030, 0.0, abs(vUV.y)))
                * step(0.26, r) * (1.0 - smoothstep(0.90, 1.0, r)) * 0.6;

  float a = clamp(glow + ring + tick + core, 0.0, 1.0) * uDim;
  vec3  c = mix(uColor, vec3(1.0), core * 0.85);
  fragColor = vec4(c * a, a);    // premultiplied — drawn additively
}
`;

// Thin screen-space line between two world points — the beam direction for
// spots and suns. Fades along its length so the direction is unambiguous.
export const LINE_VERT = `#version 300 es
precision highp float;

in vec2 aCorner;

uniform vec2  uViewport;
uniform vec3  uCamPos;
uniform vec3  uR0, uR1, uR2;
uniform float uFocal;
uniform vec3  uA, uB;
uniform float uWidth;

out float vT;

vec3 toView(vec3 p) {
  vec3 d = p - uCamPos;
  return vec3(dot(uR0,d), dot(uR1,d), dot(uR2,d));
}

void main() {
  vec3 va = toView(uA), vb = toView(uB);
  float da = -va.z, db = -vb.z;
  if (da < 0.05 || db < 0.05) {      // clipping a segment properly isn't worth it
    gl_Position = vec4(0.0, 0.0, 2.0, 1.0); vT = 0.0; return;
  }
  vec2 half_ = uViewport * 0.5;
  vec2 pa = vec2(uFocal*va.x/da, uFocal*va.y/da);   // pixels from centre
  vec2 pb = vec2(uFocal*vb.x/db, uFocal*vb.y/db);
  vec2 seg = pb - pa;
  float len = length(seg);
  vec2 dir = len > 1e-4 ? seg/len : vec2(1.0, 0.0);
  vec2 nrm = vec2(-dir.y, dir.x);

  float t = aCorner.x*0.5 + 0.5;
  vT = t;
  vec2 p = mix(pa, pb, t) + nrm * aCorner.y * uWidth;
  gl_Position = vec4(p / half_, 0.0, 1.0);
}
`;

export const LINE_FRAG = `#version 300 es
precision highp float;
in float vT;
uniform vec3  uColor;
uniform float uDim;
out vec4 fragColor;
void main() {
  float a = (1.0 - vT) * 0.55 * uDim;   // brightest at the source
  fragColor = vec4(uColor * a, a);
}
`;
