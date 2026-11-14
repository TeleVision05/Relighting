"""The viewer's orbit camera, mirrored in NumPy so tests can say where geometry lands on screen.

It follows getCamPos, viewRot and focalFor in src/camera.js, and the projection in the splat
vertex shader. Pixel coordinates here are (column, row) with row 0 at the top, which is
how ``imagestats.decode_pane`` orders the captured image.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Camera:
    yaw: float
    pitch: float
    zoom: float

    @property
    def param(self) -> str:
        """The value of the viewer's ``?cam=`` URL parameter for this camera."""
        return f"{self.yaw},{self.pitch},{self.zoom}"

    @property
    def position(self) -> np.ndarray:
        cy, sy, cp, sp = np.cos(self.yaw), np.sin(self.yaw), np.cos(self.pitch), np.sin(self.pitch)
        return np.array([sy * cp, sp, cy * cp]) * self.zoom

    @property
    def rotation(self) -> np.ndarray:
        """Rows are the view-space right, up and back vectors in world coordinates."""
        cy, sy, cp, sp = np.cos(self.yaw), np.sin(self.yaw), np.cos(self.pitch), np.sin(self.pitch)
        return np.array([[cy, 0, -sy], [-sy * sp, cp, -cy * sp], [sy * cp, sp, cy * cp]])

    @staticmethod
    def focal(w: int, h: int) -> float:
        return min(w, h) * 0.8

    def project(self, points, w: int, h: int) -> np.ndarray:
        """World points (N, 3) to pixel (column, row), shape (N, 2)."""
        v = (np.atleast_2d(points) - self.position) @ self.rotation.T
        depth = -v[:, 2]
        f = self.focal(w, h)
        return np.stack([w / 2 + f * v[:, 0] / depth, h / 2 - f * v[:, 1] / depth], axis=1)

    def pixel_rays(self, w: int, h: int) -> np.ndarray:
        """Unit world-space ray direction through every pixel centre, shape (h, w, 3)."""
        f = self.focal(w, h)
        cols, rows = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
        view = np.stack([(cols - w / 2) / f, -(rows - h / 2) / f, -np.ones_like(cols)], axis=-1)
        world = view @ self.rotation  # R is orthonormal: view -> world is R transposed
        return world / np.linalg.norm(world, axis=-1, keepdims=True)


# The camera each fixture scene is viewed from in the tests.
VIEWS = {
    "plane": Camera(yaw=0.4, pitch=0.35, zoom=4.5),
    "sphere": Camera(yaw=0.0, pitch=0.15, zoom=4.0),
    "shadow": Camera(yaw=0.0, pitch=0.9, zoom=6.0),
}
