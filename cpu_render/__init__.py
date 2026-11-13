"""NumPy CPU reference renderer for 3DGS scenes, in the same frame and camera as the WebGL viewer.

``render_splats.py`` is the command-line entry point and the ``/render`` backend; this
package holds the renderer itself:

* ``plyio``    binary PLY vertex table, read by the header's property types
* ``frame``    export frame -> viewer frame, quaternions (rot_0 = w), normals
* ``scene``    ``load_ply``: per-splat arrays the renderer uses
* ``lighting`` Retinex albedo/irradiance split, Cook-Torrance relighting
* ``camera``   the viewer's orbit camera
* ``project``  full 3D covariance -> 2D screen-space Gaussian (EWA splatting)
* ``raster``   tile-based front-to-back compositing
* ``render``   ``render_rgba``: the above for one image
"""

from .camera import OrbitCamera
from .frame import quat_to_matrix
from .lighting import LightRig, Material, separate_lighting
from .plyio import PlyFormatError
from .render import MODES, over_background, render_rgba
from .scene import load_ply

__all__ = [
    "MODES",
    "LightRig",
    "Material",
    "OrbitCamera",
    "PlyFormatError",
    "load_ply",
    "over_background",
    "quat_to_matrix",
    "render_rgba",
    "separate_lighting",
]
