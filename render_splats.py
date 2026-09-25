import argparse
import math
import threading
import time
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


PLY_PATH = Path(__file__).with_name("father-day.ply")
_RENDER_TIMEOUT = 300  # seconds — abort renders that take longer than this
# 3DGS-standard screen-space low-pass (px^2) added to the 2D covariance diagonal;
# without it a splat is a zero-width line that mostly misses pixel centres.
_LOWPASS_PX2 = 0.3

# Cache parsed PLY data at module level
_cached_ply: Dict[str, np.ndarray] | None = None
_ply_cache_lock = threading.Lock()
_ply_load_error: Optional[Exception] = None


def invalidate_ply_cache() -> None:
    """Drop the parsed-PLY cache so the next render re-reads PLY_PATH from disk."""
    global _cached_ply, _ply_load_error
    with _ply_cache_lock:
        _cached_ply = None
        _ply_load_error = None


def _load_cached_ply() -> Dict[str, np.ndarray]:
    global _cached_ply, _ply_load_error
    if _cached_ply is None and _ply_load_error is None:
        with _ply_cache_lock:
            if _cached_ply is None and _ply_load_error is None:
                try:
                    _cached_ply = load_ply(PLY_PATH)
                except Exception as e:
                    _ply_load_error = e
                    raise
    if _ply_load_error is not None:
        raise _ply_load_error
    return _cached_ply


class RenderTimeoutError(Exception):
    """Raised when a render operation exceeds the timeout limit."""
    pass


class TimeoutGuard:
    """Context manager that raises RenderTimeoutError if timeout is exceeded."""
    def __init__(self, start_time: float):
        self.start_time = start_time

    def check(self):
        if time.monotonic() - self.start_time > _RENDER_TIMEOUT:
            raise RenderTimeoutError(
                f"Render timed out after {_RENDER_TIMEOUT}s — reduce splat count or resolution"
            )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def quat_to_matrix(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    x2 = qx + qx
    y2 = qy + qy
    z2 = qz + qz
    xx = qx * x2
    yy = qy * y2
    zz = qz * z2
    xy = qx * y2
    xz = qx * z2
    yz = qy * y2
    wx = qw * x2
    wy = qw * y2
    wz = qw * z2
    return np.array([
        [1 - (yy + zz), xy - wz, xz + wy],
        [xy + wz, 1 - (xx + zz), yz - wx],
        [xz - wy, yz + wx, 1 - (xx + yy)],
    ], dtype=np.float32)


def separate_lighting(
    positions: np.ndarray,
    appearance: np.ndarray,
    opacity: np.ndarray,
    grid_res: int = 40,
) -> Tuple[np.ndarray, np.ndarray]:
    """Retinex-style baked-irradiance / intrinsic-albedo split for a single PLY.

    Standard 3DGS SH DC stores outgoing radiance (albedo × lighting), not albedo.
    Multiplying new lights onto SH DC only changes intensity of baked lighting.
    Without multi-view images we cannot run full inverse rendering; instead we
    estimate spatially smooth irradiance E and recover albedo ≈ appearance / E.
    """
    lum = np.maximum(
        0.2126 * appearance[:, 0] + 0.7152 * appearance[:, 1] + 0.0722 * appearance[:, 2],
        1e-4,
    )
    valid = opacity > 0.05
    if not np.any(valid):
        return appearance.copy(), np.ones(len(appearance), dtype=np.float32)

    global_log = float(np.mean(np.log(lum[valid])))
    mins = positions[valid].min(axis=0)
    maxs = positions[valid].max(axis=0)
    extent = np.maximum(maxs - mins, 1e-6)

    gi = np.clip(((positions - mins) / extent * (grid_res - 1)).astype(np.int32), 0, grid_res - 1)
    flat = gi[:, 0] + grid_res * (gi[:, 1] + grid_res * gi[:, 2])
    cells = grid_res ** 3
    sum_log = np.zeros(cells, dtype=np.float64)
    count = np.zeros(cells, dtype=np.float64)
    np.add.at(sum_log, flat[valid], np.log(lum[valid]))
    np.add.at(count, flat[valid], 1.0)

    grid = np.full(cells, global_log, dtype=np.float64)
    nz = count > 0
    grid[nz] = sum_log[nz] / count[nz]

    def blur_log(src: np.ndarray) -> np.ndarray:
        vol = src.reshape(grid_res, grid_res, grid_res)
        pad = np.pad(vol, 2, mode="edge")
        out = np.zeros_like(vol)
        for dz in range(5):
            for dy in range(5):
                for dx in range(5):
                    out += pad[dz:dz + grid_res, dy:dy + grid_res, dx:dx + grid_res]
        return (out / 125.0).ravel()

    grid = blur_log(blur_log(grid))
    irradiance = np.exp(grid[flat]).astype(np.float64)
    median = float(np.median(irradiance[valid])) or 1.0
    irradiance = np.maximum(irradiance / median, 0.05)
    albedo = np.clip(appearance / irradiance[:, None], 0.0, 1.0).astype(np.float32)
    return albedo, irradiance.astype(np.float32)


def load_ply(path: Path = PLY_PATH) -> Dict[str, np.ndarray]:
    data = path.read_bytes()
    marker = b"end_header"
    idx = data.find(marker)
    if idx < 0:
        raise RuntimeError("Unable to find end_header in PLY")
    header_text = data[:idx].decode("latin1", "ignore")
    body = data[idx + len(marker):]
    while body.startswith((b"\r", b"\n", b" ")):
        body = body[1:]

    lines = header_text.splitlines()
    vertex_count = None
    property_names: List[str] = []
    for line in lines:
        if line.startswith("element vertex"):
            vertex_count = int(line.split()[-1])
        elif line.startswith("property float"):
            property_names.append(line.split()[-1])
    if vertex_count is None:
        raise RuntimeError("Unable to parse vertex count")

    values = np.frombuffer(body, dtype="<f4")
    expected = vertex_count * len(property_names)
    if len(values) < expected:
        raise RuntimeError(f"PLY payload is too short: expected {expected} values, got {len(values)}")
    values = values[:expected].reshape(vertex_count, len(property_names))

    props = {name: values[:, i] for i, name in enumerate(property_names)}

    # SH DC → baked linear appearance (lighting still entangled)
    sh_c0 = 0.28209479177387814
    baked = np.clip(
        0.5
        + np.column_stack([props["f_dc_0"], props["f_dc_1"], props["f_dc_2"]]) * sh_c0,
        0.0,
        1.0,
    ).astype(np.float32)
    props["baked_r"], props["baked_g"], props["baked_b"] = baked[:, 0], baked[:, 1], baked[:, 2]

    # Sigmoid opacity
    props["opacity_sig"] = 1.0 / (1.0 + np.exp(-np.clip(props["opacity"], -20.0, 20.0)))

    # Shortest principal axis as surface normal (paper: flatten → normal)
    r0, r1, r2, r3 = props["rot_0"], props["rot_1"], props["rot_2"], props["rot_3"]
    qlen = np.sqrt(r0**2 + r1**2 + r2**2 + r3**2)
    qlen[qlen == 0] = 1.0
    qx, qy, qz, qw = r0 / qlen, r1 / qlen, r2 / qlen, r3 / qlen

    c0 = np.column_stack([1 - 2 * (qy**2 + qz**2), 2 * (qx * qy + qw * qz), 2 * (qx * qz - qw * qy)])
    c1 = np.column_stack([2 * (qx * qy - qw * qz), 1 - 2 * (qx**2 + qz**2), 2 * (qy * qz + qw * qx)])
    c2 = np.column_stack([2 * (qx * qz + qw * qy), 2 * (qy * qz - qw * qx), 1 - 2 * (qx**2 + qy**2)])
    scales = np.exp(np.column_stack([props["scale_0"], props["scale_1"], props["scale_2"]]))
    axis = np.argmin(scales, axis=1)
    normals = np.where(axis[:, None] == 0, c0, np.where(axis[:, None] == 1, c1, c2)).astype(np.float32)
    n_norms = np.linalg.norm(normals, axis=1, keepdims=True)
    n_norms[n_norms == 0] = 1.0
    normals = normals / n_norms

    positions = np.column_stack([props["x"], props["y"], props["z"]]).astype(np.float32)
    center = positions[props["opacity_sig"] > 0.05].mean(axis=0) if np.any(props["opacity_sig"] > 0.05) else positions.mean(axis=0)
    outward = positions - center
    flip = np.sign((normals * outward).sum(axis=1, keepdims=True) + 1e-8)
    normals = normals * flip.astype(np.float32)
    props["nx"], props["ny"], props["nz"] = normals[:, 0], normals[:, 1], normals[:, 2]

    albedo, irradiance = separate_lighting(positions, baked, props["opacity_sig"])
    props["albedo_r"], props["albedo_g"], props["albedo_b"] = albedo[:, 0], albedo[:, 1], albedo[:, 2]
    props["irradiance"] = irradiance

    return props


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def render_png(width: int = 1600, height: int = 1600, mode: str = "relit", ambient: float = 0.20,
               ambient_color: Tuple[float, float, float] = (0.8, 0.84, 0.88),
               dir_intensity: float = 1.5, dir_x: float = 0.5, dir_y: float = 0.7, dir_z: float = 0.5,
               dir_color: Tuple[float, float, float] = (1.0, 1.0, 1.0),
               point_intensity: float = 1.0, point_x: float = 1.2, point_y: float = 1.5, point_z: float = 0.8,
               point_color: Tuple[float, float, float] = (0.22, 0.74, 0.97),
               roughness: float = 0.30, metallic: float = 0.10, specular_gain: float = 1.2,
               separation: float = 1.0, keep_ao: float = 0.0,
               stride: int = 1) -> bytes:
    guard = TimeoutGuard(time.monotonic())
    props = _load_cached_ply()

    positions = np.column_stack([props["x"], props["y"], props["z"]]).astype(np.float32)
    normals = np.column_stack([props["nx"], props["ny"], props["nz"]]).astype(np.float32)

    # Normalize normals
    n_norms = np.linalg.norm(normals, axis=1, keepdims=True)
    n_norms[n_norms == 0] = 1.0
    normals = normals / n_norms

    intrinsic = np.column_stack([props["albedo_r"], props["albedo_g"], props["albedo_b"]]).astype(np.float32)
    baked = np.column_stack([props["baked_r"], props["baked_g"], props["baked_b"]]).astype(np.float32)
    irradiance = props["irradiance"].astype(np.float32)
    # sep=1 → intrinsic albedo; sep=0 → old incorrect "SH as albedo" path
    sep = float(np.clip(separation, 0.0, 1.0))
    albedo = (baked * (1.0 - sep) + intrinsic * sep).astype(np.float32)
    opacity = props["opacity_sig"].astype(np.float32)

    scale0 = props["scale_0"].astype(np.float32)
    rot0 = props["rot_0"].astype(np.float32)
    rot1 = props["rot_1"].astype(np.float32)
    rot2 = props["rot_2"].astype(np.float32)
    rot3 = props["rot_3"].astype(np.float32)

    image = np.zeros((height, width, 4), dtype=np.float32)
    yaw = -0.45
    pitch = -0.15
    cy, sy = math.cos(yaw), math.sin(yaw)
    cx, sx = math.cos(pitch), math.sin(pitch)
    view_rot = np.array([
        [cy, 0.0, sy],
        [sy * sx, cx, -cy * sx],
        [-sy * cx, sx, cy * cx],
    ], dtype=np.float32)

    focal = min(width, height) * 0.75
    n_total = len(positions)
    max_splats = n_total

    valid_indices = []
    depths = np.zeros(max_splats, dtype=np.float32)
    x0s = np.zeros(max_splats, dtype=np.int32)
    y0s = np.zeros(max_splats, dtype=np.int32)
    x1s = np.zeros(max_splats, dtype=np.int32)
    y1s = np.zeros(max_splats, dtype=np.int32)
    weights_list = [None] * max_splats
    alpha_list = [0.0] * max_splats

    # Normalize directional light vector
    l_dir = np.array([dir_x, dir_y, dir_z], dtype=np.float32)
    l_dir_norm = np.linalg.norm(l_dir) or 1.0
    l_dir = l_dir / l_dir_norm
    l_dir_col = np.array(dir_color, dtype=np.float32)
    point_col = np.array(point_color, dtype=np.float32)
    amb_col = np.array(ambient_color, dtype=np.float32)

    n_valid = 0
    for i in range(0, n_total, stride):
        if (i % 16384) == 0:
            guard.check()
        pos = positions[i]
        alpha0 = opacity[i]
        if alpha0 <= 0.01:
            continue

        view_pos = view_rot @ pos
        depth = 5.5 - view_pos[2]
        if depth <= 0.2:
            continue

        sx2 = width * 0.5 + (view_pos[0] / depth) * focal
        sy2 = height * 0.5 - (view_pos[1] / depth) * focal

        if sx2 < -48 or sx2 > width + 48 or sy2 < -48 or sy2 > height + 48:
            continue

        rot = quat_to_matrix(rot0[i], rot1[i], rot2[i], rot3[i])
        basis_xv = view_rot @ rot[:, 0]
        basis_yv = view_rot @ rot[:, 1]
        scale2d = focal / depth
        s0 = math.exp(clamp(scale0[i], -2.5, 1.6)) * 0.0025 * scale2d

        cov00 = (basis_xv[0] ** 2) * (s0 ** 2) + _LOWPASS_PX2
        cov01 = (basis_xv[0] * basis_xv[1]) * (s0 ** 2)
        cov11 = (basis_xv[1] ** 2) * (s0 ** 2) + _LOWPASS_PX2

        det = cov00 * cov11 - cov01 * cov01
        if det <= 1e-12:
            continue

        inv_cov = np.array([[cov11 / det, -cov01 / det], [-cov01 / det, cov00 / det]], dtype=np.float32)

        radius = max(2, int(math.ceil(3.0 * math.sqrt(max(cov00, cov11)))))
        x0 = max(0, int(math.floor(sx2 - radius)))
        x1 = min(width, int(math.ceil(sx2 + radius)))
        y0 = max(0, int(math.floor(sy2 - radius)))
        y1 = min(height, int(math.ceil(sy2 + radius)))
        if x1 <= x0 or y1 <= y0:
            continue

        yy, xx = np.mgrid[y0:y1, x0:x1]
        dx = xx.astype(np.float32) - sx2
        dy = yy.astype(np.float32) - sy2
        delta = np.stack([dx, dy], axis=-1).reshape(-1, 2)
        exponent = -0.5 * np.einsum('...i,ij,...j->...', delta, inv_cov, delta)
        weights = np.exp(np.clip(exponent, -20.0, 0.0))

        valid_indices.append(i)
        depths[n_valid] = depth
        x0s[n_valid] = x0
        y0s[n_valid] = y0
        x1s[n_valid] = x1
        y1s[n_valid] = y1
        weights_list[n_valid] = weights
        alpha_list[n_valid] = float(alpha0)
        n_valid += 1

    if n_valid > 0:
        sorted_idx = np.argsort(depths[:n_valid])[::-1]  # far to near

        for idx in sorted_idx[:n_valid]:
            i = valid_indices[idx]
            x0, x1 = int(x0s[idx]), int(x1s[idx])
            y0, y1 = int(y0s[idx]), int(y1s[idx])

            if x1 <= x0 or y1 <= y0:
                continue

            alpha0_val = alpha_list[idx]
            weights = weights_list[idx]
            alpha = np.clip(alpha0_val * weights, 0.0, 1.0)

            # Evaluate Microfacet PBR on intrinsic albedo, or show baked/neutral
            if mode == "relit":
                pos_i = positions[i]
                norm_i = normals[i]
                alb_i = albedo[i]
                irr_i = float(irradiance[i])

                # Ambient
                lit = alb_i * amb_col * ambient

                # Directional light Cook-Torrance
                ndotl = max(0.0, float(np.dot(norm_i, l_dir)))
                if ndotl > 0 and dir_intensity > 0:
                    v_dir = np.array([-view_rot[2, 0], -view_rot[2, 1], -view_rot[2, 2]], dtype=np.float32)
                    v_dir = v_dir / (np.linalg.norm(v_dir) or 1.0)
                    ndotv = max(0.001, float(np.dot(norm_i, v_dir)))

                    h_dir = l_dir + v_dir
                    h_dir = h_dir / (np.linalg.norm(h_dir) or 1.0)
                    ndoth = max(0.0, float(np.dot(norm_i, h_dir)))
                    vdoth = max(0.0, float(np.dot(v_dir, h_dir)))

                    a2 = max(0.001, roughness * roughness) ** 2
                    d_denom = (ndoth * ndoth * (a2 - 1.0) + 1.0)
                    d_ggx = a2 / (math.pi * d_denom * d_denom)

                    f0 = (1.0 - metallic) * 0.04 * specular_gain + metallic * alb_i
                    fresnel = f0 + (1.0 - f0) * ((1.0 - vdoth) ** 5)

                    k_smith = ((roughness + 1.0) ** 2) / 8.0
                    g1v = ndotv / (ndotv * (1.0 - k_smith) + k_smith)
                    g1l = ndotl / (ndotl * (1.0 - k_smith) + k_smith)
                    g_smith = g1v * g1l

                    specular = (g_smith * d_ggx) / (4.0 * ndotv * ndotl + 1e-4)
                    spec_rgb = fresnel * specular

                    kd = (1.0 - fresnel) * (1.0 - metallic)
                    diff_rgb = (kd * alb_i / math.pi)

                    lit += (diff_rgb + spec_rgb) * l_dir_col * dir_intensity * ndotl * math.pi

                # Point light
                if point_intensity > 0:
                    p_pos = np.array([point_x, point_y, point_z], dtype=np.float32)
                    p_vec = p_pos - pos_i
                    p_dist = float(np.linalg.norm(p_vec)) or 1.0
                    p_dir = p_vec / p_dist
                    p_ndotl = max(0.0, float(np.dot(norm_i, p_dir)))
                    if p_ndotl > 0:
                        p_atten = 1.0 / (0.25 + p_dist * p_dist * 0.12)
                        lit += alb_i * point_col * point_intensity * p_ndotl * p_atten

                if keep_ao > 0:
                    lit = lit * ((1.0 - keep_ao) + keep_ao * irr_i)

                base_rgb = np.clip(lit, 0.0, 1.0)
            elif mode == "albedo":
                base_rgb = intrinsic[i]
            else:
                # Neutral / baked SH appearance
                base_rgb = baked[i]

            # Vectorized alpha compositing
            for j in range(y1 - y0):
                for k in range(x1 - x0):
                    a_new = alpha[j * (x1 - x0) + k]
                    if a_new <= 1e-4:
                        continue
                    a_old = image[y0 + j, x0 + k, 3]
                    alpha_out = a_new + a_old * (1.0 - a_new)
                    if alpha_out <= 1e-4:
                        continue
                    image[y0 + j, x0 + k, :3] = (
                        image[y0 + j, x0 + k, :3] * (a_old * (1.0 - a_new) / alpha_out) +
                        base_rgb * (a_new / alpha_out)
                    )
                    image[y0 + j, x0 + k, 3] = alpha_out

    rgba = np.clip(image, 0.0, 1.0)
    rgba = (rgba * 255.0).astype(np.uint8)
    pil = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    pil.save(buffer, format="PNG")
    return buffer.getvalue()


class RenderHandler(SimpleHTTPRequestHandler):
    def _send_json(self, payload) -> None:
        import json

        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Never let the browser cache assets — swapping a .ply on disk must take
        # effect on the next request, not after a hard refresh.
        if "Cache-Control" not in self._headers_buffer_names():
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def _headers_buffer_names(self) -> set:
        names = set()
        for raw in getattr(self, "_headers_buffer", []) or []:
            line = raw.decode("latin-1", "replace")
            if ":" in line:
                names.add(line.split(":", 1)[0].strip())
        return names

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/models":
            root = Path(self.directory) if getattr(self, "directory", None) else Path.cwd()
            names = sorted(p.name for p in root.glob("*.ply"))
            self._send_json(names)
            return
        if parsed.path == "/reload":
            invalidate_ply_cache()
            self._send_json({"ok": True, "ply": PLY_PATH.name})
            return
        if parsed.path == "/render":
            params = parse_qs(parsed.query)
            mode = params.get("mode", ["relit"])[0]
            ambient = float(params.get("ambient", ["0.20"])[0])
            dir_intensity = float(params.get("dirInt", ["1.5"])[0])
            dir_x = float(params.get("dirX", ["0.5"])[0])
            dir_y = float(params.get("dirY", ["0.7"])[0])
            dir_z = float(params.get("dirZ", ["0.5"])[0])
            point_intensity = float(params.get("pointInt", ["1.0"])[0])
            point_x = float(params.get("pointX", ["1.2"])[0])
            point_y = float(params.get("pointY", ["1.5"])[0])
            point_z = float(params.get("pointZ", ["0.8"])[0])
            roughness = float(params.get("roughness", ["0.30"])[0])
            metallic = float(params.get("metallic", ["0.10"])[0])
            separation = float(params.get("sep", ["1.0"])[0])
            keep_ao = float(params.get("keepAO", ["0.0"])[0])
            width = int(clamp(int(params.get("w", ["1600"])[0]), 16, 2048))
            height = int(clamp(int(params.get("h", ["1600"])[0]), 16, 2048))
            stride = int(clamp(int(params.get("stride", ["1"])[0]), 1, 64))

            png = render_png(
                width=width,
                height=height,
                stride=stride,
                mode=mode,
                ambient=ambient,
                dir_intensity=dir_intensity,
                dir_x=dir_x,
                dir_y=dir_y,
                dir_z=dir_z,
                point_intensity=point_intensity,
                point_x=point_x,
                point_y=point_y,
                point_z=point_z,
                roughness=roughness,
                metallic=metallic,
                separation=separation,
                keep_ao=keep_ao,
            )
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
            return
        super().do_GET()

    def log_message(self, format: str, *args) -> None:
        return


def serve(port: int = 8000) -> None:
    handler = partial(RenderHandler, directory=str(Path.cwd()))
    with ThreadingHTTPServer(("0.0.0.0", port), handler) as httpd:
        print(f"Serving on http://127.0.0.1:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.serve:
        serve(args.port)
    else:
        out = Path("rendered_neutral.png")
        out.write_bytes(render_png(mode="neutral"))
        out2 = Path("rendered_relit.png")
        out2.write_bytes(render_png(mode="relit"))
        print("Successfully rendered:", out, out2)
