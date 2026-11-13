"""The viewer's orbit camera (src/camera.js), so a CPU render and a viewer pane can share a view."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# src/camera.js DEFAULT_VIEW: the view the viewer opens with.
DEFAULT_YAW, DEFAULT_PITCH, DEFAULT_ZOOM = 0.4, 0.25, 10.0


@dataclass(frozen=True)
class OrbitCamera:
    """At spherical position (yaw, pitch, zoom) around the origin, looking at the origin."""

    yaw: float = DEFAULT_YAW
    pitch: float = DEFAULT_PITCH
    zoom: float = DEFAULT_ZOOM

    @property
    def position(self) -> np.ndarray:
        cy, sy, cp, sp = np.cos(self.yaw), np.sin(self.yaw), np.cos(self.pitch), np.sin(self.pitch)
        return np.array([sy * cp, sp, cy * cp]) * self.zoom

    @property
    def rotation(self) -> np.ndarray:
        """World -> view rotation. Rows: right, up, back; the camera looks down view -Z."""
        cy, sy, cp, sp = np.cos(self.yaw), np.sin(self.yaw), np.cos(self.pitch), np.sin(self.pitch)
        return np.array([[cy, 0.0, -sy], [-sy * sp, cp, -cy * sp], [sy * cp, sp, cy * cp]])

    @staticmethod
    def focal(width: int, height: int) -> float:
        """Focal length in pixels (focalFor)."""
        return min(width, height) * 0.8
