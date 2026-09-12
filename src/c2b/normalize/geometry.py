"""Geometry for the normaliser: beam splitting, panel lattice, mark fitting."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from ..geometry import angle_diff_deg, rectangle_polygon

Pt = tuple[float, float]


def poly_from_points(points) -> Polygon | None:
    pts = [(p.x, p.y) if hasattr(p, "x") else (p[0], p[1]) for p in points]
    if len(pts) < 3:
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly


def ring_points(poly: Polygon, simplify_mm: float = 0.5) -> list[Pt]:
    """Exterior ring as a list of points without the closing duplicate."""
    if simplify_mm > 0:
        poly = poly.simplify(simplify_mm, preserve_topology=True)
    coords = list(poly.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    # ensure counter-clockwise orientation
    if shapely.is_ccw(poly.exterior) is False:
        coords = coords[::-1]
    return [(round(x, 2), round(y, 2)) for x, y in coords]


@dataclass
class Axis:
    start: Pt
    end: Pt

    def __post_init__(self) -> None:
        dx, dy = self.end[0] - self.start[0], self.end[1] - self.start[1]
        self.length = math.hypot(dx, dy)
        self.u = (dx / self.length, dy / self.length) if self.length else (1.0, 0.0)
        self.n = (-self.u[1], self.u[0])
        self.angle = math.degrees(math.atan2(dy, dx)) % 180.0

    def t_of(self, p: Pt) -> float:
        return (p[0] - self.start[0]) * self.u[0] + (p[1] - self.start[1]) * self.u[1]

    def point_at(self, t: float) -> Pt:
        return (self.start[0] + self.u[0] * t, self.start[1] + self.u[1] * t)

    def interval_of(self, geom) -> tuple[float, float] | None:
        """Projection of a geometry onto the axis as an interval."""
        if geom.is_empty:
            return None
        ts = [self.t_of((x, y)) for x, y in _all_coords(geom)]
        if not ts:
            return None
        return (min(ts), max(ts))


def _all_coords(geom):
    if geom.geom_type == "Polygon":
        return list(geom.exterior.coords)
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        out = []
        for g in geom.geoms:
            out.extend(_all_coords(g))
        return out
    if geom.geom_type in ("LineString", "LinearRing"):
        return list(geom.coords)
    if geom.geom_type == "Point":
        return [(geom.x, geom.y)]
    if geom.geom_type == "MultiLineString":
        return [c for g in geom.geoms for c in g.coords]
    return []


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def complement(intervals: list[tuple[float, float]], length: float) -> list[tuple[float, float]]:
    """Free intervals within [0, length] after removing ``intervals``."""
    spans: list[tuple[float, float]] = []
    t = 0.0
    for a, b in merge_intervals(intervals):
        a, b = max(a, 0.0), min(b, length)
        if a > t:
            spans.append((t, a))
        t = max(t, b)
    if t < length:
        spans.append((t, length))
    return spans


@dataclass
class Run:
    """A continuous beam run from extraction, with its plan rectangle."""

    id: str
    axis: Axis
    width: float
    depth: float | None
    outline: Polygon
    payload: object = None


@dataclass
class Cut:
    t1: float
    t2: float
    by: str            # support id


def support_cuts(run: Run, supports: list[tuple[str, Polygon]], cover_ratio: float) -> list[Cut]:
    """Intervals along the run covered by columns/walls that cross the beam width."""
    cuts: list[Cut] = []
    for sid, poly in supports:
        if not poly.intersects(run.outline):
            continue
        inter = poly.intersection(run.outline)
        if inter.is_empty or inter.area < 1.0:
            continue
        iv = run.axis.interval_of(inter)
        if iv is None:
            continue
        t1, t2 = iv
        if t2 - t1 <= 0:
            continue
        # a support must cover most of the beam width, otherwise it merely touches the beam
        if inter.area / max(1.0, (t2 - t1) * run.width) < cover_ratio:
            continue
        cuts.append(Cut(t1, t2, sid))
    return cuts


def crossing_cuts(run: Run, others: list[Run], end_tol: float, trim_at_faces: bool, split_crossing_by: str) -> list[Cut]:
    """Intervals along ``run`` occupied by other beams that dominate it.

    - ``run`` terminates inside another beam -> trimmed to that beam's face,
    - the other beam terminates inside ``run`` -> ``run`` stays continuous,
    - both continue (an X crossing) -> the shallower beam is split; ties go to the longer run.
    """
    cuts: list[Cut] = []
    for other in others:
        if other.id == run.id or angle_diff_deg(run.axis.angle, other.axis.angle) < 20.0:
            continue
        if not run.outline.intersects(other.outline):
            continue
        inter = run.outline.intersection(other.outline)
        if inter.is_empty or inter.area < 1.0:
            continue
        iv = run.axis.interval_of(inter)
        if iv is None:
            continue
        t1, t2 = iv
        a_ends_here = t1 <= end_tol or t2 >= run.axis.length - end_tol
        o_iv = other.axis.interval_of(inter)
        o_ends_here = o_iv is not None and (o_iv[0] <= end_tol or o_iv[1] >= other.axis.length - end_tol)
        if a_ends_here and not o_ends_here:
            if trim_at_faces:
                cuts.append(Cut(t1, t2, other.id))
        elif o_ends_here and not a_ends_here:
            continue
        elif a_ends_here and o_ends_here:
            # corner: both end in each other; the longer run keeps the corner
            if other.axis.length > run.axis.length and trim_at_faces:
                cuts.append(Cut(t1, t2, other.id))
        else:
            if split_crossing_by == "none":
                continue
            da, do = run.depth or 0.0, other.depth or 0.0
            other_dominates = do > da or (do == da and other.axis.length > run.axis.length) or (
                do == da and other.axis.length == run.axis.length and other.axis.angle < run.axis.angle)
            if other_dominates:
                cuts.append(Cut(t1, t2, other.id))
    return cuts


def span_rectangle(run: Run, t1: float, t2: float) -> Polygon:
    c = run.axis.point_at((t1 + t2) / 2)
    return rectangle_polygon(c, t2 - t1, run.width, run.axis.angle)


def lattice_panels(structure_polys: list[Polygon], min_area: float, max_area: float) -> tuple[list[Polygon], list[Polygon]]:
    """Slab panels are the holes of the union of beams, columns and walls.

    Returns (panels, oversized) with oversized panels kept separately for diagnostics.
    """
    if not structure_polys:
        return [], []
    union = unary_union([p.buffer(0) for p in structure_polys if not p.is_empty])
    parts = list(union.geoms) if isinstance(union, MultiPolygon) else [union]
    panels: list[Polygon] = []
    oversized: list[Polygon] = []
    for part in parts:
        for ring in part.interiors:
            poly = Polygon(ring)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            if poly.area < min_area:
                continue
            if poly.area > max_area:
                oversized.append(poly)
            panels.append(poly)
    return panels, oversized


def representative_point(poly: Polygon) -> Pt:
    """A point inside the polygon suitable for a mark: the centroid when it is inside, else the pole of inaccessibility."""
    c = poly.centroid
    if poly.contains(c):
        return (c.x, c.y)
    p = shapely.maximum_inscribed_circle(poly, tolerance=10.0) if hasattr(shapely, "maximum_inscribed_circle") else None
    if p is not None and not p.is_empty:
        q = list(p.coords)[0]
        return (q[0], q[1])
    q = poly.representative_point()
    return (q.x, q.y)


def text_fits(text: str, height: float, width_factor: float, poly: Polygon, rotation_deg: float = 0.0) -> bool:
    w = len(text) * height * width_factor
    c = representative_point(poly)
    box = rectangle_polygon(c, w * 1.1, height * 1.3, rotation_deg)
    return poly.contains(box)
