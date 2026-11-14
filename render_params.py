"""Validation of the query string of ``GET /render``. Stdlib only.

Every setting has a type and bounds. Anything outside them is rejected with a message
that says what was wrong and what is allowed; nothing is silently clamped or guessed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl

MAX_QUERY_FIELDS = 40
_MAX_ECHO = 30  # characters of a bad value repeated back to the person

_INT_RE = re.compile(r"[+-]?[0-9]{1,9}", re.ASCII)
_FLOAT_RE = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]{1,3})?", re.ASCII)

MODES = ("relit", "neutral", "albedo", "normals")


class RenderParamError(ValueError):
    """The request had unusable settings. ``str(exc)`` is plain language, safe to show."""


@dataclass(frozen=True)
class Setting:
    query: str  # name in the URL
    kwarg: str  # argument of render_png
    label: str  # how the message names it
    kind: str  # "int", "float" or "choice"
    default: object
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()


SETTINGS: tuple[Setting, ...] = (
    Setting("mode", "mode", "Mode", "choice", "relit", choices=MODES),
    Setting("w", "width", "Image width", "int", 1600, 16, 2048),
    Setting("h", "height", "Image height", "int", 1600, 16, 2048),
    Setting("stride", "stride", "Stride (use every Nth splat)", "int", 1, 1, 64),
    Setting("ambient", "ambient", "Ambient light", "float", 0.20, 0, 5),
    Setting("dirInt", "dir_intensity", "Directional light intensity", "float", 1.5, 0, 20),
    Setting("dirX", "dir_x", "Directional light X", "float", 0.5, -10, 10),
    Setting("dirY", "dir_y", "Directional light Y", "float", 0.7, -10, 10),
    Setting("dirZ", "dir_z", "Directional light Z", "float", 0.5, -10, 10),
    Setting("pointInt", "point_intensity", "Point light intensity", "float", 1.0, 0, 20),
    Setting("pointX", "point_x", "Point light X", "float", 1.2, -50, 50),
    Setting("pointY", "point_y", "Point light Y", "float", 1.5, -50, 50),
    Setting("pointZ", "point_z", "Point light Z", "float", 0.8, -50, 50),
    Setting("roughness", "roughness", "Roughness", "float", 0.30, 0, 1),
    Setting("metallic", "metallic", "Metallic", "float", 0.10, 0, 1),
    Setting("sep", "separation", "Lighting separation", "float", 1.0, 0, 1),
    Setting("keepAO", "keep_ao", "Keep AO", "float", 0.0, 0, 1),
    # The viewer's orbit camera (?cam=yaw,pitch,zoom); defaults are its DEFAULT_VIEW.
    Setting("yaw", "yaw", "Camera yaw in radians", "float", 0.4, -10, 10),
    Setting("pitch", "pitch", "Camera pitch in radians", "float", 0.25, -1.56, 1.56),
    Setting("zoom", "zoom", "Camera distance", "float", 10.0, 1, 50),
)
_BY_QUERY = {s.query: s for s in SETTINGS}


def _shown(value: str) -> str:
    text = value if len(value) <= _MAX_ECHO else value[:_MAX_ECHO] + "..."
    return f"'{text}'"


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _parse(setting: Setting, raw: str):
    name = f"{setting.label} ({setting.query})"
    if setting.kind == "choice":
        if raw not in setting.choices:
            options = ", ".join(setting.choices)
            raise RenderParamError(f"{name} must be one of: {options}. You sent {_shown(raw)}.")
        return raw
    bounds = f"between {_fmt(setting.lo)} and {_fmt(setting.hi)}"
    if setting.kind == "int":
        if not _INT_RE.fullmatch(raw):
            raise RenderParamError(f"{name} must be a whole number {bounds}. You sent {_shown(raw)}.")
        value = int(raw)
    else:
        value = float(raw) if _FLOAT_RE.fullmatch(raw) else math.nan
        if not math.isfinite(value):
            raise RenderParamError(f"{name} must be a number {bounds}. You sent {_shown(raw)}.")
    if not setting.lo <= value <= setting.hi:
        kind = "whole number" if setting.kind == "int" else "number"
        raise RenderParamError(f"{name} must be a {kind} {bounds}. You sent {_shown(raw)}.")
    return value


def _collect(query: str) -> dict[str, str]:
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=MAX_QUERY_FIELDS)
    except ValueError as exc:
        raise RenderParamError(
            f"Too many settings in the address. Send at most {MAX_QUERY_FIELDS}, each one once."
        ) from exc
    found: dict[str, str] = {}
    problems: list[str] = []
    for key, value in pairs:
        if key.startswith("_"):  # cache-busting parameters such as _=123 are ignored
            continue
        if key not in _BY_QUERY:
            allowed = ", ".join(_BY_QUERY)
            problems.append(f"Unknown setting {_shown(key)}. The settings you can use are: {allowed}.")
        elif key in found:
            problems.append(f"{key} was sent more than once. Send each setting only once.")
        else:
            found[key] = value
    if problems:
        raise RenderParamError(" ".join(problems))
    return found


def parse_render_query(query: str) -> dict:
    """Turn a raw query string into keyword arguments for ``render_png``.

    Raises RenderParamError listing every problem found, in plain language.
    """
    raw = _collect(query)
    kwargs: dict = {}
    problems: list[str] = []
    for setting in SETTINGS:
        if setting.query not in raw:
            kwargs[setting.kwarg] = setting.default
            continue
        try:
            kwargs[setting.kwarg] = _parse(setting, raw[setting.query])
        except RenderParamError as exc:
            problems.append(str(exc))
    if problems:
        raise RenderParamError(" ".join(problems))
    return kwargs
