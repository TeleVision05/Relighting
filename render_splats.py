import argparse
import math
import threading
import time
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


PLY_PATH = Path(__file__).with_name("Buttons.ply")
_RENDER_TIMEOUT = 300  # seconds — abort renders that take longer than this
_PLY_LOAD_TIMEOUT = 120  # seconds — timeout for the initial PLY load

# Cache parsed PLY data at module level — only loaded once.
_cached_ply: Dict[str, np.ndarray] | None = None
_ply_cache_lock = threading.Lock()
_ply_load_error: Optional[Exception] = None


def _load_cached_ply() -> Dict[str, np.ndarray]:
    global _cached_ply, _ply_load_error
    if _cached_ply is None and _ply_load_error is None:
        with _ply_cache_lock:
            # Double-check after acquiring the lock (threading pattern)
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
                f"Render timed out after {_RENDER_TIMEOUT}s — use a smaller image or reduce splat count"
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
    yz = qy * z2
    wx = qw * x2
    wy = qw * y2
    wz = qw * z2
    return np.array([
        [1 - (yy + zz), xy - wz, xz + wy],
        [xy + wz, 1 - (xx + zz), yz - wx],
        [xz - wy, yz + wx, 1 - (xx + yy)],
        ], dtype=np.float32)


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
    return props


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def render_png(width: int = 1600, height: int = 1600, mode: str = "neutral", ambient: float = 0.16,
               dir_intensity: float = 1.0, dir_x: float = 0.3, dir_y: float = 0.8, dir_z: float = 0.5,
               dir_color: tuple = (1.0, 1.0, 1.0), point_intensity: float = 0.4,
               point_x: float = 0.6, point_y: float = 0.9, point_z: float = 0.2,
               point_color: tuple = (0.49, 0.82, 0.99)) -> bytes:
    guard = TimeoutGuard(time.monotonic())
    props = _load_cached_ply()  # Use cached PLY data instead of re-reading from disk
    positions = np.column_stack([props["x"], props["y"], props["z"]]).astype(np.float32)
    normals = np.column_stack([props["nx"], props["ny"], props["nz"]]).astype(np.float32)
    colors = np.column_stack([props["f_dc_0"], props["f_dc_1"], props["f_dc_2"]]).astype(np.float32)
    opacity = props["opacity"].astype(np.float32)
    scale0 = props["scale_0"].astype(np.float32)
    scale1 = props["scale_1"].astype(np.float32)
    scale2 = props["scale_2"].astype(np.float32)
    rot0 = props["rot_0"].astype(np.float32)
    rot1 = props["rot_1"].astype(np.float32)
    rot2 = props["rot_2"].astype(np.float32)
    rot3 = props["rot_3"].astype(np.float32)

    image = np.zeros((height, width, 4), dtype=np.float32)
    yaw = -0.45
    pitch = -0.15
    cy = math.cos(yaw)
    sy = math.sin(yaw)
    cx = math.cos(pitch)
    sx = math.sin(pitch)
    view_rot = np.array([
        [cy, 0.0, sy],
        [sy * sx, cx, -cy * sx],
        [-sy * cx, sx, cy * cx],
    ], dtype=np.float32)

    focal = min(width, height) * 0.72

    # First pass: collect all splat data with depth sorting
    n_total = len(positions)
    max_splats = n_total  # worst case
    
    # Pre-allocate arrays for splat properties
    valid_indices = []
    depths = np.zeros(max_splats, dtype=np.float32)
    sx2_arr = np.zeros(max_splats, dtype=np.float32)
    sy2_arr = np.zeros(max_splats, dtype=np.float32)
    radii = np.zeros(max_splats, dtype=np.int32)
    x0s = np.zeros(max_splats, dtype=np.int32)
    y0s = np.zeros(max_splats, dtype=np.int32)
    x1s = np.zeros(max_splats, dtype=np.int32)
    y1s = np.zeros(max_splats, dtype=np.int32)  # store y1 separately
    weights_list = [None] * max_splats  # variable-length weight arrays per splat
    alpha_list = [0.0] * max_splats     # per-splat alpha values
    
    n_valid = 0
    for i in range(0, n_total, stride):
        if (i % 16384) == 0:
            guard.check()
        pos = positions[i]
        normal = normals[i]
        color = colors[i]
        alpha0 = opacity[i]
        if alpha0 <= 0.0:
            continue

        view_pos = view_rot @ pos
        depth = 2.6 + view_pos[2]
        if depth <= 0.2:
            continue
        
        sx2 = width * 0.5 + (view_pos[0] / depth) * focal
        sy2 = height * 0.5 - (view_pos[1] / depth) * focal
        
        if sx2 < -24 or sx2 > width + 24 or sy2 < -24 or sy2 > height + 24:
            continue

        rot = quat_to_matrix(rot0[i], rot1[i], rot2[i], rot3[i])
        basis_x = rot[:, 0]
        basis_y = rot[:, 1]
        basis_xv = view_rot @ basis_x
        basis_yv = view_rot @ basis_y
        scale2d = focal / depth
        s0 = math.exp(clamp(scale0[i], -2.5, 1.6)) * 0.0025 * scale2d
        s1 = math.exp(clamp(scale1[i], -2.5, 1.6)) * 0.0025 * scale2d
        cov00 = (basis_xv[0] ** 2) * (s0 ** 2) + (basis_yv[0] ** 2) * (s1 ** 2)
        cov01 = (basis_xv[0] * basis_xv[1]) * (s0 ** 2) + (basis_yv[0] * basis_yv[1]) * (s1 ** 2)
        cov11 = (basis_xv[1] ** 2) * (s0 ** 2) + (basis_yv[1] ** 2) * (s1 ** 2)
        cov = np.array([[cov00, cov01], [cov01, cov11]], dtype=np.float32)
        cov += np.eye(2, dtype=np.float32) * 1e-6

        try:
            inv_cov = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            continue

        eigvals = np.linalg.eigvalsh(cov)
        radius = max(2, int(math.ceil(3.0 * math.sqrt(max(eigvals.max(), 1e-6)))))
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

        # Lighting calculation
        if mode == "relit":
            normal = normal / (np.linalg.norm(normal) or 1.0)
            light_dir = np.array([dir_x, dir_y, dir_z], dtype=np.float32)
            light_dir = light_dir / (np.linalg.norm(light_dir) or 1.0)
            diffuse = max(0.0, float(np.dot(normal, light_dir)))
            
            # Point light in world space
            point_vec = np.array([point_x, point_y, point_z], dtype=np.float32) - pos
            dist = np.linalg.norm(point_vec) or 1.0
            point_vec = point_vec / dist
            point_diff = max(0.0, float(np.dot(normal, point_vec)))
            dist_factor = 1.0 / max(0.2, 0.25 + dist * dist * 0.08)
            
            dir_rgb = np.array(dir_color, dtype=np.float32)
            point_rgb = np.array(point_color, dtype=np.float32)
            lit = color * (ambient + 0.2) + dir_rgb * (diffuse * dir_intensity) + point_rgb * (point_diff * point_intensity * dist_factor)
            base_rgb = np.clip(lit, 0.0, 1.0)
        else:
            base_rgb = np.clip(color, 0.0, 1.0)

        # Store splat data for depth sorting
        valid_indices.append(i)
        depths[n_valid] = depth
        sx2_arr[n_valid] = sx2
        sy2_arr[n_valid] = sy2
        radii[n_valid] = radius
        x0s[n_valid] = x0
        y0s[n_valid] = y0
        x1s[n_valid] = x1
        y1s[n_valid] = y1  # Fixed: now storing y1 value
        weights_list[n_valid] = weights  # variable-length, no fixed buffer limit
        alpha_list[n_valid] = float(alpha0)
        n_valid += 1

    # Second pass: sort splats by depth (far to near) and composite
    if n_valid > 0:
        sorted_idx = np.argsort(depths[:n_valid])[::-1]  # far to near
        
        for idx in sorted_idx[:n_valid]:
            i = valid_indices[idx]
            x0, x1 = int(x0s[idx]), int(x1s[idx])
            y0, y1 = int(y0s[idx]), int(y1s[idx])  # Fixed: now using stored y1 value
            
            # Ensure valid bounds
            if x1 <= x0 or y1 <= y0:
                continue
            
            alpha0_val = alpha_list[idx]  # use stored alpha from first pass
            weights = weights_list[idx]    # retrieve variable-length weight array
            alpha = np.clip(alpha0_val * 0.98 * weights, 0.0, 1.0)
            
            # Get RGB color for this splat
            if mode == "relit":
                normal = normals[i] / (np.linalg.norm(normals[i]) or 1.0)
                pos_i = positions[i]
                light_dir = np.array([dir_x, dir_y, dir_z], dtype=np.float32)
                light_dir = light_dir / (np.linalg.norm(light_dir) or 1.0)
                diffuse = max(0.0, float(np.dot(normal, light_dir)))
                point_vec = np.array([point_x, point_y, point_z], dtype=np.float32) - pos_i
                dist = np.linalg.norm(point_vec) or 1.0
                point_vec = point_vec / dist
                point_diff = max(0.0, float(np.dot(normal, point_vec)))
                dist_factor = 1.0 / max(0.2, 0.25 + dist * dist * 0.08)
                dir_rgb = np.array(dir_color, dtype=np.float32)
                point_rgb = np.array(point_color, dtype=np.float32)
                lit = colors[i] * (ambient + 0.2) + dir_rgb * (diffuse * dir_intensity) + point_rgb * (point_diff * point_intensity * dist_factor)
                base_rgb = np.clip(lit, 0.0, 1.0)
            else:
                base_rgb = np.clip(colors[i], 0.0, 1.0)
            
            # Alpha compositing with optimized vectorized approach
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
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/render":
            params = parse_qs(parsed.query)
            mode = params.get("mode", ["relit"])[0]
            ambient = float(params.get("ambient", ["0.16"])[0])
            dir_intensity = float(params.get("dirInt", ["1.0"])[0])
            dir_x = float(params.get("dirX", ["0.3"])[0])
            dir_y = float(params.get("dirY", ["0.8"])[0])
            dir_z = float(params.get("dirZ", ["0.5"])[0])
            point_intensity = float(params.get("pointInt", ["0.4"])[0])
            point_x = float(params.get("pointX", ["0.6"])[0])
            point_y = float(params.get("pointY", ["0.9"])[0])
            point_z = float(params.get("pointZ", ["0.2"])[0])
            dir_color = tuple(float(x) for x in params.get("dirColor", ["1,1,1"])[0].split(","))
            point_color = tuple(float(x) for x in params.get("pointColor", ["0.49,0.82,0.99"])[0].split(","))
            out_path = Path("rendered_neutral.png") if mode == "neutral" else Path("rendered_relit.png")
            png = render_png(
                mode=mode,
                ambient=ambient,
                dir_intensity=dir_intensity,
                dir_x=dir_x,
                dir_y=dir_y,
                dir_z=dir_z,
                dir_color=dir_color,
                point_intensity=point_intensity,
                point_x=point_x,
                point_y=point_y,
                point_z=point_z,
                point_color=point_color,
            )
            out_path.write_bytes(png)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
            return
        super().do_GET()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
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
        print("wrote", out, out2)
