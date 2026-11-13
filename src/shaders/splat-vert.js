// Splat vertex shader, shared by the baked and relit panes. Moved verbatim from index.html.
// Single vertex shader for both neutral and relit modes.
// Each splat is an instanced quad (TRIANGLE_STRIP, 4 vertices).
//
// Per-splat data lives in two static textures uploaded once at load time;
// the only per-frame vertex input is aIndex, the depth-sorted splat id.
// Projection and 2D covariance are computed here rather than on the CPU, so
// a camera move costs one 4-byte-per-splat index upload instead of re-packing
// and re-uploading every attribute.
export const VERT = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;

in vec2 aCorner;
in uint aIndex;        // splat id, sorted far→near

uniform highp sampler2D uGeom;   // 3 texels/splat: pos | log-scale | quat
uniform highp sampler2D uShade;  // 4 texels/splat: albedo+irr | baked+opacity | n | nSm
uniform int   uGeomW, uShadeW;   // texture widths in texels

uniform vec2  uViewport;
uniform vec3  uCamPos;
uniform vec3  uR0, uR1, uR2;     // rows of the world→view rotation
uniform float uFocal;            // focal length in pixels

// Shadowing — see buildOccupancy(). Marched here, per splat, rather than per
// fragment: splat overdraw is enormous, and a splat is small enough on screen
// that visibility at its centre is a fine approximation.
#define MAX_LIGHTS 8
uniform highp sampler3D uOcc;
uniform vec3  uGridMin, uGridInvExt;
uniform float uGridDiag;
uniform int   uShadowOn;         // 0 on the reference pane — skip all of this
uniform int   uShadowSteps;
uniform float uShadowStrength;
uniform float uShadowBias;
uniform float uShadowReach;      // how far along the ray to look, in world units
uniform int   uNumLights;
uniform int   uLType[MAX_LIGHTS];
uniform vec3  uLPos[MAX_LIGHTS];
uniform vec3  uLDir[MAX_LIGHTS];
uniform float uLShadow[MAX_LIGHTS];   // 1 = this light casts

out vec2  vUV;
out mat2  vInvCov;
out vec3  vWorldPos;
out vec3  vNormal;
out vec3  vNormalSm;
out vec3  vAlbedo;
out vec3  vBaked;
out float vIrradiance;
out float vOpacity;
out vec4  vShadowA;              // transmittance for lights 0–3
out vec4  vShadowB;              // …and 4–7

// Beer-Lambert transmittance along a ray through the density volume.
float traceShadow(vec3 P, vec3 L, float maxDist) {
  int steps = uShadowSteps;
  float stepLen = maxDist / float(steps);
  float t = uShadowBias;
  float sum = 0.0;
  for (int s = 0; s < 64; s++) {
    if (s >= steps || t >= maxDist) break;
    vec3 q = (P + L*t - uGridMin) * uGridInvExt;
    if (any(lessThan(q, vec3(0.0))) || any(greaterThan(q, vec3(1.0)))) break;
    sum += textureLod(uOcc, q, 0.0).r;
    t += stepLen;
  }
  return exp(-sum * stepLen * uShadowStrength);
}

vec4 fetch(highp sampler2D tex, int w, int i) {
  return texelFetch(tex, ivec2(i % w, i / w), 0);
}

// Park the vertex outside clip space; nothing downstream runs.
void killVertex() {
  gl_Position = vec4(0.0, 0.0, 2.0, 1.0);
  vUV = vec2(0.0); vInvCov = mat2(1.0);
  vWorldPos = vec3(0.0); vNormal = vec3(0.0,0.0,1.0); vNormalSm = vec3(0.0,0.0,1.0);
  vAlbedo = vec3(0.0); vBaked = vec3(0.0); vIrradiance = 1.0; vOpacity = 0.0;
  vShadowA = vec4(1.0); vShadowB = vec4(1.0);
}

void main() {
  int i = int(aIndex);
  vec4 g0 = fetch(uGeom,  uGeomW,  i*3    );   // xyz = world position
  vec4 g1 = fetch(uGeom,  uGeomW,  i*3 + 1);   // xyz = log scales
  vec4 g2 = fetch(uGeom,  uGeomW,  i*3 + 2);   // quaternion (w,x,y,z)
  vec4 s0 = fetch(uShade, uShadeW, i*4    );   // rgb = intrinsic albedo, a = irradiance
  vec4 s1 = fetch(uShade, uShadeW, i*4 + 1);   // rgb = baked SH appearance, a = opacity
  vec4 s2 = fetch(uShade, uShadeW, i*4 + 2);   // xyz = raw normal
  vec4 s3 = fetch(uShade, uShadeW, i*4 + 3);   // xyz = smoothed normal

  vec3 wpos = g0.xyz;
  vec3 nRaw = s2.xyz;
  vec3 nSm  = s3.xyz;

  // World → view
  vec3 d = wpos - uCamPos;
  vec3 v = vec3(dot(uR0, d), dot(uR1, d), dot(uR2, d));
  float depth = -v.z;
  if (depth < 0.05) { killVertex(); return; }

  // Splat rotation from quaternion (rows)
  float qw = g2.x, qx = g2.y, qy = g2.z, qz = g2.w;
  vec3 rr0 = vec3(1.0-2.0*(qy*qy+qz*qz), 2.0*(qx*qy-qw*qz),     2.0*(qx*qz+qw*qy));
  vec3 rr1 = vec3(2.0*(qx*qy+qw*qz),     1.0-2.0*(qx*qx+qz*qz), 2.0*(qy*qz-qw*qx));
  vec3 rr2 = vec3(2.0*(qx*qz-qw*qy),     2.0*(qy*qz+qw*qx),     1.0-2.0*(qx*qx+qy*qy));

  // M = R_view * R_splat: row k is view axis k expressed in the splat's principal axes
  vec3 c0 = vec3(rr0.x, rr1.x, rr2.x);
  vec3 c1 = vec3(rr0.y, rr1.y, rr2.y);
  vec3 c2 = vec3(rr0.z, rr1.z, rr2.z);
  vec3 m0 = vec3(dot(uR0,c0), dot(uR0,c1), dot(uR0,c2));
  vec3 m1 = vec3(dot(uR1,c0), dot(uR1,c1), dot(uR1,c2));
  vec3 m2 = vec3(dot(uR2,c0), dot(uR2,c1), dot(uR2,c2));

  vec3 sc  = exp(g1.xyz);
  vec3 sc2 = sc * sc;
  float fd  = uFocal / depth;
  float fd2 = fd * fd;

  // Full perspective Jacobian (EWA splatting, as in 3DGS): pixel x = f*v.x/depth also moves
  // with the splat's depth extent, by f*v.x/depth^2 per unit of view z. Dropping that column
  // (a scaled orthographic projection) mis-shapes every off-axis splat: 40-80% covariance
  // error a third of the way to the edge, measured against projected samples. v/depth is
  // clamped to 1.3x the half field of view, as the 3DGS rasteriser does, so splats far
  // outside the frustum do not blow up. cpu_render/project.py does the same on the CPU.
  vec2 tLim = 1.3 * 0.5 * uViewport / uFocal;
  vec2 t = clamp(v.xy / depth, -tLim, tLim);
  vec3 j0 = m0 + t.x * m2;
  vec3 j1 = m1 + t.y * m2;

  float c00 = fd2 * dot(j0*j0, sc2) + 0.3;   // +0.3 px dilation, as before
  float c01 = fd2 * dot(j0*j1, sc2);
  float c11 = fd2 * dot(j1*j1, sc2) + 0.3;
  float det = c00*c11 - c01*c01;
  if (det < 1e-6) { killVertex(); return; }

  vInvCov = mat2(c11, -c01, -c01, c00) / det;

  float tr  = c00 + c11;
  float rad = sqrt(0.5*(tr + sqrt(max(0.0, tr*tr - 4.0*det))));
  vec2 pixOff = aCorner * (3.0 * rad);

  vUV         = pixOff;
  vWorldPos   = wpos;
  vNormal     = nRaw;
  vNormalSm   = nSm;
  vAlbedo     = s0.rgb;
  vIrradiance = s0.a;
  vBaked      = s1.rgb;
  vOpacity    = s1.a;

  float sh[MAX_LIGHTS];
  for (int i = 0; i < MAX_LIGHTS; i++) sh[i] = 1.0;
  if (uShadowOn == 1) {
    for (int i = 0; i < MAX_LIGHTS; i++) {
      if (i >= uNumLights) break;
      if (uLShadow[i] < 0.5) continue;
      // Cap the march at uShadowReach. Occlusion is dominated by nearby
      // geometry, and a shorter ray means each step is small enough to
      // actually land on the occluder rather than straddle it.
      if (uLType[i] == 1) {
        sh[i] = traceShadow(wpos, -uLDir[i], uShadowReach);
      } else {
        vec3 pv = uLPos[i] - wpos;
        float pd = length(pv);
        sh[i] = traceShadow(wpos, pv/max(pd, 1e-4), min(pd, uShadowReach));
      }
    }
  }
  vShadowA = vec4(sh[0], sh[1], sh[2], sh[3]);
  vShadowB = vec4(sh[4], sh[5], sh[6], sh[7]);

  vec2 half_ = uViewport * 0.5;
  vec2 ndc   = vec2(uFocal*v.x/(depth*half_.x), uFocal*v.y/(depth*half_.y));
  gl_Position = vec4(ndc + 2.0*pixOff/uViewport, 0.0, 1.0);
}
`;
