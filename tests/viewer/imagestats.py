"""Numeric image statistics for the viewer tests: tolerances, never golden images."""

from __future__ import annotations

import base64

import numpy as np

# gl.clearColor(0.01, 0.015, 0.035) in src/renderer.js, as bytes.
BACKGROUND = np.array([0.01, 0.015, 0.035])


def decode_pane(pane: dict) -> np.ndarray:
    """A pane from ``__relightTest.capture()`` to float RGB (h, w, 3) in 0..1, row 0 at the top."""
    w, h = pane["w"], pane["h"]
    rgba = np.frombuffer(base64.b64decode(pane["rgba"]), dtype=np.uint8).reshape(h, w, 4)
    return rgba[::-1, :, :3].astype(np.float64) / 255.0  # readPixels starts at the bottom row


def luminance(img: np.ndarray) -> np.ndarray:
    return img @ np.array([0.2126, 0.7152, 0.0722])


def covered(img: np.ndarray, threshold: float = 0.06) -> np.ndarray:
    """Pixels that clearly differ from the clear colour."""
    return np.abs(img - BACKGROUND).max(axis=-1) > threshold


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Keep only pixels whose whole (2r+1) square neighbourhood is in the mask."""
    out = mask.copy()
    h, w = mask.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            shifted = np.zeros_like(mask)
            ys, yd = slice(max(0, dy), h + min(0, dy)), slice(max(0, -dy), h - max(0, dy))
            xs, xd = slice(max(0, dx), w + min(0, dx)), slice(max(0, -dx), w - max(0, dx))
            shifted[yd, xd] = mask[ys, xs]
            out &= shifted
    return out


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference in 0..255 units, the scale people think in."""
    return float(np.abs(a - b).mean() * 255.0)


def crop_common(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Crop two panes to their common centred size, so the same pixel shows the same point.

    Each pane projects about its own centre, so an odd 1 px width difference leaves a
    half-pixel offset; comparisons across panes need a tolerance for that.
    """
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])

    def centre(img):
        y0, x0 = (img.shape[0] - h) // 2, (img.shape[1] - w) // 2
        return img[y0 : y0 + h, x0 : x0 + w]

    return centre(a), centre(b)


def disc(shape, center, radius: float) -> np.ndarray:
    h, w = shape
    rows, cols = np.mgrid[0:h, 0:w]
    return (cols + 0.5 - center[0]) ** 2 + (rows + 0.5 - center[1]) ** 2 <= radius**2


def angle_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Angle between unit vectors along the last axis, in degrees."""
    an = a / np.linalg.norm(a, axis=-1, keepdims=True)
    bn = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(np.arccos(np.clip(np.sum(an * bn, axis=-1), -1.0, 1.0)))
