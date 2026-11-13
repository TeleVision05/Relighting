"""Tile-based rasteriser with front-to-back alpha compositing, in NumPy.

Splats are sorted near to far once, then binned into square tiles by their footprint.
Each tile composites its splats in blocks: a (splats x pixels) matrix of Gaussian
alphas, an exclusive cumulative product for the transmittance in front of each splat,
and a matrix product for the colour. A tile stops as soon as every pixel in it is opaque.

Front-to-back "under" with transmittance gives the same image as the viewer's
back-to-front "over" blending (src/renderer.js), up to rounding:
``C = sum_i c_i a_i prod_{j<i} (1 - a_j)``, with i running near to far.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .project import MIN_OPACITY, SIGMA_CUTOFF, Projected

TILE = 16
BLOCK = 256  # splats composited at once per tile
T_EPSILON = 1e-4  # a pixel whose remaining transmittance is below this is finished
_MAHA_MAX = SIGMA_CUTOFF * SIGMA_CUTOFF


def _bin(proj: Projected, width: int, height: int, tile: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(tile id, splat) pairs for every tile a splat's footprint overlaps.

    Returns splat ids grouped by tile, the tile id of each group, and the group boundaries.
    Splats must already be in front-to-back order: a stable sort keeps that order in a tile.
    """
    tiles_x, tiles_y = -(-width // tile), -(-height // tile)
    lo = np.floor((proj.mean - proj.radius[:, None]) / tile).astype(np.int64)
    hi = np.floor((proj.mean + proj.radius[:, None]) / tile).astype(np.int64)
    lo = np.maximum(lo, 0)
    hi = np.minimum(hi, [tiles_x - 1, tiles_y - 1])
    span = np.maximum(hi - lo + 1, 0)
    counts = span[:, 0] * span[:, 1]
    splat = np.repeat(np.arange(len(counts)), counts)
    k = np.arange(len(splat)) - np.repeat(np.cumsum(counts) - counts, counts)
    cols = lo[splat, 0] + k % np.maximum(span[splat, 0], 1)
    rows = lo[splat, 1] + k // np.maximum(span[splat, 0], 1)
    tile_id = rows * tiles_x + cols
    order = np.argsort(tile_id, kind="stable")
    splat, tile_id = splat[order], tile_id[order]
    starts = np.flatnonzero(np.r_[True, tile_id[1:] != tile_id[:-1]]) if len(tile_id) else np.zeros(0, int)
    return splat, tile_id[starts], np.r_[starts, len(splat)]


def _composite_tile(ids, proj, colors, opacity, px, py):
    """Composite one tile's splats (front to back). Returns premultiplied rgb (P, 3) and T (P,)."""
    rgb = np.zeros((len(px), 3), dtype=np.float32)
    trans = np.ones(len(px), dtype=np.float32)
    for b in range(0, len(ids), BLOCK):
        s = ids[b : b + BLOCK]
        dx = px[None, :] - proj.mean[s, 0:1].astype(np.float32)
        dy = py[None, :] - proj.mean[s, 1:2].astype(np.float32)
        a, bb, c = (proj.conic[s, i : i + 1].astype(np.float32) for i in range(3))
        maha = a * dx * dx + 2.0 * bb * dx * dy + c * dy * dy
        alpha = opacity[s, None] * np.exp(-0.5 * np.minimum(maha, _MAHA_MAX))
        alpha[(maha > _MAHA_MAX) | (alpha < MIN_OPACITY)] = 0.0
        keep = 1.0 - alpha
        before = np.cumprod(np.vstack([trans[None, :], keep[:-1]]), axis=0)  # T in front of each splat
        rgb += (alpha * before).T @ colors[s]
        trans = before[-1] * keep[-1]
        if trans.max() < T_EPSILON:
            break
    return rgb, trans


def rasterize(
    proj: Projected,
    colors: np.ndarray,
    opacity: np.ndarray,
    width: int,
    height: int,
    tile: int = TILE,
    check: Callable[[], None] | None = None,
) -> np.ndarray:
    """Composite projected splats into a (height, width, 4) float RGBA image, straight alpha.

    ``colors`` (M, 3) and ``opacity`` (M,) are per projected splat. ``check`` is called
    between tiles, so a caller can abort a render that runs too long by raising from it.
    """
    order = np.argsort(proj.depth, kind="stable")
    proj = Projected(proj.index[order], proj.mean[order], proj.conic[order], proj.radius[order], proj.depth[order])
    colors = np.asarray(colors, dtype=np.float32)[order]
    opacity = np.asarray(opacity, dtype=np.float32)[order]

    image = np.zeros((height, width, 4), dtype=np.float32)
    tiles_x = -(-width // tile)
    ty, tx = np.mgrid[0:tile, 0:tile]
    splat, tile_ids, bounds = _bin(proj, width, height, tile)
    for t, tile_id in enumerate(tile_ids):
        if check is not None and t % 64 == 0:
            check()
        x0, y0 = int(tile_id % tiles_x) * tile, int(tile_id // tiles_x) * tile
        x1, y1 = min(x0 + tile, width), min(y0 + tile, height)
        px = (tx[: y1 - y0, : x1 - x0] + x0 + 0.5).astype(np.float32).ravel()
        py = (ty[: y1 - y0, : x1 - x0] + y0 + 0.5).astype(np.float32).ravel()
        rgb, trans = _composite_tile(splat[bounds[t] : bounds[t + 1]], proj, colors, opacity, px, py)
        alpha = 1.0 - trans
        straight = rgb / np.maximum(alpha, 1e-8)[:, None]
        image[y0:y1, x0:x1, :3] = straight.reshape(y1 - y0, x1 - x0, 3)
        image[y0:y1, x0:x1, 3] = alpha.reshape(y1 - y0, x1 - x0)
    return image
