"""Floor detection.

Client drawings put several floor plans side by side in model space. The
firm's convention marks each plan with a closed polyline on the ``Boundary``
layer and a POINT on the ``Origin`` layer. This module finds those, names each
floor from a title block or level text, assigns every primitive to a floor and
converts coordinates to the floor-local system (origin = 0,0).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import shapely
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

from .diagnostics import DiagnosticsCollector
from .dxfio import Prim
from .profile import Profile
from .tags import clean_text

_RE_SCALE = re.compile(r"\bSCALE\b|^\s*1\s*:\s*\d+\s*$", re.I)


@dataclass
class FloorFrame:
    id: str
    index: int
    name: str
    name_source: str
    origin: tuple[float, float]
    boundary: Polygon | None
    boundary_handle: str | None = None
    prims: list[Prim] = field(default_factory=list)
    default_beam_depth: float | None = None
    default_slab_thickness: float | None = None


def _is_floor_label(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    if _RE_SCALE.search(text) and "level" not in low and "floor" not in low:
        return False
    return any(k in low for k in keywords)


def _pick_label(candidates: list[tuple[int, float, str, str]]) -> tuple[str, str] | None:
    """candidates: (priority, text_height, text, source). Highest priority, then tallest text."""
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], -c[1]))
    return candidates[0][2], candidates[0][3]


def detect_floors(prims: list[Prim], roles: dict[str, tuple[str, str]], profile: Profile, diag: DiagnosticsCollector, layouts: list[str]) -> list[FloorFrame]:
    """Find floors. ``roles`` maps layer -> (geometry_role, text_role)."""
    fs = profile.floor
    boundaries = [p for p in prims if p.kind == "polygon" and roles.get(p.layer, ("", ""))[0] == "BOUNDARY"]
    open_boundaries = [p for p in prims if p.kind == "polyline" and roles.get(p.layer, ("", ""))[0] == "BOUNDARY"]
    for p in open_boundaries:
        diag.warning("BOUNDARY_NOT_CLOSED", f"Boundary polyline {p.handle} on layer {p.layer} is not closed and was ignored", layer=p.layer, handle=p.handle, location=p.rep_point())
    boundaries = [b for b in boundaries if b.geom.area >= fs.min_boundary_area_m2 * 1e6]
    origins = [p for p in prims if p.kind == "point" and roles.get(p.layer, ("", ""))[0] == "ORIGIN"]

    frames: list[FloorFrame] = []
    if not boundaries:
        diag.warning("NO_BOUNDARY", f"No closed polylines on layer '{fs.boundary_layer}'; the whole drawing is treated as one floor. Add a Boundary rectangle and Origin point per floor for multi-floor drawings.")
        origin = (origins[0].geom.x, origins[0].geom.y) if origins else (0.0, 0.0)
        name, source = _fallback_name(prims, roles, fs, layouts)
        if source == "fallback":
            diag.warning("FLOOR_NO_LABEL", "Floor name not found; using 'Floor 1'")
        frame = FloorFrame("L01", 1, name, source, origin, None)
        frame.prims = list(prims)
        return [frame]

    # order floors left to right, then bottom to top
    boundaries.sort(key=lambda b: (round(b.geom.bounds[0] / 1000.0), b.geom.bounds[1]))
    origin_pts = [(o, Point(o.geom.x, o.geom.y)) for o in origins]
    texts = [p for p in prims if p.kind == "text" and p.text]

    for i, b in enumerate(boundaries, start=1):
        poly: Polygon = b.geom
        inside_origins = [o for o, pt in origin_pts if poly.contains(pt)]
        if inside_origins:
            origin = (inside_origins[0].geom.x, inside_origins[0].geom.y)
        else:
            origin = (poly.bounds[0], poly.bounds[1])
            diag.warning("FLOOR_NO_ORIGIN", f"Boundary {b.handle} has no Origin point inside it; lower-left corner used as origin", handle=b.handle, location=origin)

        candidates: list[tuple[int, float, str, str]] = []
        for t in texts:
            if not poly.contains(Point(t.rep_point())):
                continue
            role = roles.get(t.layer, ("", "NOTE"))[1]
            txt = clean_text(t.text)
            if not txt:
                continue
            if t.dxftype == "ATTRIB" and _is_floor_label(txt, fs.label_keywords):
                candidates.append((3, t.text_height, txt, "title_block"))
            elif role in ("TITLE", "NOTE") and _is_floor_label(txt, fs.label_keywords):
                candidates.append((2, t.text_height, txt, "text"))
            elif _is_floor_label(txt, fs.label_keywords) and len(txt) <= 60:
                candidates.append((1, t.text_height, txt, "text"))
        picked = _pick_label(candidates)
        if picked:
            name, source = picked
        else:
            name, source = f"Floor {i}", "fallback"
            diag.warning("FLOOR_NO_LABEL", f"No floor name found inside boundary {b.handle}; using '{name}'", handle=b.handle, location=origin)
        frames.append(FloorFrame(f"L{i:02d}", i, name, source, origin, poly, b.handle))

    # assign prims to floors by representative point
    tree = STRtree([f.boundary for f in frames])
    unassigned = 0
    for p in prims:
        if p is b:
            continue
        pt = Point(p.rep_point())
        hits = tree.query(pt, predicate="within")
        if len(hits) == 0:
            unassigned += 1
            continue
        frames[int(hits[0])].prims.append(p)
    if unassigned:
        diag.info("ELEMENT_OUTSIDE_FLOORS", f"{unassigned} entities lie outside every floor boundary (schedules, legends, stray geometry)")
    return frames


def _fallback_name(prims: list[Prim], roles, fs, layouts: list[str]) -> tuple[str, str]:
    candidates: list[tuple[int, float, str, str]] = []
    for t in prims:
        if t.kind != "text" or not t.text:
            continue
        txt = clean_text(t.text)
        if t.dxftype == "ATTRIB" and _is_floor_label(txt, fs.label_keywords):
            candidates.append((3, t.text_height, txt, "title_block"))
        elif _is_floor_label(txt, fs.label_keywords) and len(txt) <= 60:
            candidates.append((1, t.text_height, txt, "text"))
    picked = _pick_label(candidates)
    if picked:
        return picked
    named = [l for l in layouts if l.lower() not in ("model",)]
    if len(named) == 1:
        return named[0], "layout"
    return "Floor 1", "fallback"


def localise(frame: FloorFrame) -> None:
    """Translate all prims of a floor so the floor origin becomes (0, 0)."""
    dx, dy = -frame.origin[0], -frame.origin[1]
    for p in frame.prims:
        p.geom = shapely.affinity.translate(p.geom, xoff=dx, yoff=dy)
        if p.text_center:
            p.text_center = (p.text_center[0] + dx, p.text_center[1] + dy)
        if "anchor" in p.extra:
            a = p.extra["anchor"]
            p.extra["anchor"] = (a[0] + dx, a[1] + dy)
        if "center" in p.extra:
            c = p.extra["center"]
            p.extra["center"] = (c[0] + dx, c[1] + dy)
