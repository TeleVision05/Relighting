// Splat fragment shaders. Moved verbatim from index.html.

// Left pane: original baked SH appearance (reference)
export const FRAG_NEUTRAL = `#version 300 es
precision highp float;

in vec2  vUV;
in mat2  vInvCov;
in vec3  vWorldPos;
in vec3  vNormal;
in vec3  vNormalSm;
in vec3  vAlbedo;
in vec3  vBaked;
in float vIrradiance;
in float vOpacity;

out vec4 fragColor;

void main() {
  float maha = dot(vUV, vInvCov * vUV);
  if (maha > 9.0) discard;
  float alpha = vOpacity * exp(-0.5 * maha);
  if (alpha < 0.003) discard;
  fragColor = vec4(vBaked, alpha);
}
`;

// Right pane: Cook-Torrance on *intrinsic* albedo, not baked SH color
export const FRAG_RELIT = `#version 300 es
precision highp float;
precision highp int;      // fragment ints default to mediump; the vertex stage
                          // uses highp, and shared uniforms must agree

in vec2  vUV;
in mat2  vInvCov;
in vec3  vWorldPos;
in vec3  vNormal;
in vec3  vNormalSm;
in vec3  vAlbedo;
in vec3  vBaked;
in float vIrradiance;
in float vOpacity;
in vec4  vShadowA;
in vec4  vShadowB;

uniform vec3  uCamPos;
uniform vec3  uAmbCol;   uniform float uAmbInt;
uniform float uRough;    uniform float uMetal;    uniform float uSpec;
uniform float uSep;
uniform float uKeepAO;
uniform float uNSmooth;
uniform float uExposure;
uniform int   uGBuf;

// Light rig. MAX_LIGHTS must match MAX_LIGHTS in the JS.
#define MAX_LIGHTS 8
uniform int   uNumLights;
uniform int   uLType[MAX_LIGHTS];    // 0 = point, 1 = directional, 2 = spot
uniform vec3  uLPos[MAX_LIGHTS];     // world position (point / spot)
uniform vec3  uLDir[MAX_LIGHTS];     // beam direction, away from the source
uniform vec3  uLCol[MAX_LIGHTS];
uniform float uLInt[MAX_LIGHTS];
uniform float uLRange[MAX_LIGHTS];   // distance at which falloff reaches ½
uniform vec2  uLCone[MAX_LIGHTS];    // cos(outer), cos(inner) for spots

out vec4 fragColor;

const float PI = 3.14159265359;

vec3 cookTorrance(vec3 N, vec3 V, vec3 L, vec3 albedo, float rough, float metal, float specScale) {
  float NdL = max(0.0, dot(N, L));
  if (NdL <= 0.0) return vec3(0.0);
  float NdV = max(0.001, dot(N, V));
  vec3  H   = normalize(L + V);
  float NdH = max(0.0, dot(N, H));
  float VdH = max(0.0, dot(V, H));

  float a  = max(0.01, rough * rough);
  float a2 = a * a;
  float d  = NdH*NdH*(a2-1.0)+1.0;
  float D  = a2 / (PI * d * d);

  vec3 F0 = mix(vec3(0.04 * specScale), albedo, metal);
  vec3 F  = F0 + (1.0-F0)*pow(1.0-VdH, 5.0);

  float k   = (rough+1.0)*(rough+1.0)/8.0;
  float GV  = NdV/(NdV*(1.0-k)+k);
  float GL  = NdL/(NdL*(1.0-k)+k);

  vec3 spec = (D * GV * GL * F) / (4.0*NdV*NdL + 0.001);
  vec3 kd   = (1.0-F)*(1.0-metal);
  return (kd*albedo/PI + spec) * NdL;
}

void main() {
  float maha = dot(vUV, vInvCov * vUV);
  if (maha > 9.0) discard;
  float alpha = vOpacity * exp(-0.5 * maha);
  if (alpha < 0.003) discard;

  vec3 Nraw = normalize(vNormal);
  vec3 Nsm  = normalize(vNormalSm);
  if (dot(Nsm, Nraw) < 0.0) Nsm = -Nsm;
  vec3 N = normalize(mix(Nraw, Nsm, clamp(uNSmooth, 0.0, 1.0)));
  vec3 V = normalize(uCamPos - vWorldPos);
  // A splat's normal sign is arbitrary — only the ±n axis is meaningful. We can
  // only ever see the face turned toward us, so resolve the sign against the
  // view direction. Without this, every back-facing splat shades as if lit from
  // behind and the specular lobe lands on the wrong side.
  if (dot(N, V) < 0.0) N = -N;

  // Blend toward intrinsic albedo as separation increases
  vec3 baseAlbedo = mix(vBaked, vAlbedo, clamp(uSep, 0.0, 1.0));

  if (uGBuf == 1) { fragColor = vec4(vAlbedo, alpha); return; }
  if (uGBuf == 2) { fragColor = vec4(vBaked, alpha); return; }
  if (uGBuf == 3) {
    float e = vIrradiance;
    fragColor = vec4(vec3(e), alpha);
    return;
  }
  if (uGBuf == 4) { fragColor = vec4(N*0.5+0.5, alpha); return; }

  vec3 color = baseAlbedo * uAmbCol * uAmbInt;
  vec3 specOnly = vec3(0.0);

  float shadow[MAX_LIGHTS];
  shadow[0]=vShadowA.x; shadow[1]=vShadowA.y; shadow[2]=vShadowA.z; shadow[3]=vShadowA.w;
  shadow[4]=vShadowB.x; shadow[5]=vShadowB.y; shadow[6]=vShadowB.z; shadow[7]=vShadowB.w;

  for (int i = 0; i < MAX_LIGHTS; i++) {
    if (i >= uNumLights) break;

    vec3  L;
    float atten = 1.0;

    if (uLType[i] == 1) {
      L = -uLDir[i];                       // sun: parallel rays, no falloff
    } else {
      vec3  pv = uLPos[i] - vWorldPos;
      float pd = length(pv);
      L = pv / max(0.001, pd);
      // Inverse-square shaped so the range slider is the half-brightness
      // distance, which makes it mean something physical.
      float r = max(0.05, uLRange[i]);
      atten = 1.0 / (1.0 + (pd*pd)/(r*r));
      if (uLType[i] == 2) {                // spot: fade across the cone edge
        float cosA = dot(uLDir[i], -L);
        atten *= smoothstep(uLCone[i].x, uLCone[i].y, cosA);
      }
    }
    atten *= shadow[i];
    if (atten <= 0.0005) continue;

    vec3 contrib = cookTorrance(N, V, L, baseAlbedo, uRough, uMetal, uSpec)
                 * uLCol[i] * uLInt[i] * PI * atten;
    color += contrib;

    if (uGBuf == 5) {                      // specular-only debug view
      vec3 H = normalize(L + V);
      float sp = pow(max(0.0, dot(N,H)), 2.0/max(0.01, uRough*uRough));
      specOnly += uLCol[i] * sp * uSpec * uLInt[i] * atten;
    }
  }

  // Optional: keep a fraction of baked AO/soft-shadow structure
  color *= mix(1.0, vIrradiance, clamp(uKeepAO, 0.0, 1.0));
  color *= uExposure;

  if (uGBuf == 5) { fragColor = vec4(clamp(specOnly*uExposure, 0.0, 1.0), alpha); return; }

  fragColor = vec4(clamp(color, 0.0, 1.0), alpha);
}
`;
