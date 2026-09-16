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


def complement(intervals: list[tuple[float, float]], length: float, start: float = 0.0) -> list[tuple[float, float]]:
    """Free intervals within [start, length] after removing ``intervals`` (zero-length cuts split without a gap)."""
    spans: list[tuple[float, float]] = []
    t = start
    for a, b in merge_intervals(intervals):
        a, b = max(a, start), min(b, length)
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


@dataclass
class Support:
    id: str
    poly: Polygon
    shape: str = "rect"          # rect | circle | polygon
    rotation_deg: float = 0.0

    def is_irregular_for(self, run_angle: float, tol_deg: float) -> bool:
        if self.shape != "rect":
            return True
        d = angle_diff_deg(self.rotation_deg, run_angle)
        return not (d <= tol_deg or abs(d - 90.0) <= tol_deg)


def support_cuts(run: Run, supports: list[Support], cover_ratio: float, to_centre: bool = True, angle_tol: float = 3.0) -> tuple[list[Cut], float, float]:
    """Intervals along the run covered by columns/walls.

    Axis-aligned rectangular supports cut the beam at their faces. Round, rotated or
    odd-shaped supports cut it at their centre (zero-width cut) so adjacent spans meet
    at the column centre; a run ending inside such a support is extended to the centre.
    Returns (cuts, t_min, t_max) with the possibly extended run domain.
    """
    cuts: list[Cut] = []
    t_min, t_max = 0.0, run.axis.length
    w = run.width
    for sup in supports:
        poly = sup.poly
        irregular = to_centre and sup.is_irregular_for(run.axis.angle, angle_tol)
        probe = span_rectangle(run, -w, run.axis.length + w) if irregular else run.outline
        if not poly.intersects(probe):
            continue
        inter = poly.intersection(probe)
        if inter.is_empty or inter.area < 1.0:
            continue
        iv = run.axis.interval_of(inter)
        if iv is None:
            continue
        t1, t2 = iv
        if t2 - t1 <= 0:
            continue
        if inter.area / max(1.0, (t2 - t1) * w) < cover_ratio:
            continue   # merely touches the beam edge
        if irregular:
            c = poly.centroid
            tc = run.axis.t_of((c.x, c.y))
            cuts.append(Cut(tc, tc, sup.id))
            if tc > run.axis.length:
                t_max = max(t_max, tc)
            if tc < 0.0:
                t_min = min(t_min, tc)
        else:
            cuts.append(Cut(t1, t2, sup.id))
    return cuts, t_min, t_max


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


def text_fits(text: str, height: float, width_factor: float, poly: Polygon, rotation_deg: float = 0.0,
              centre: Pt | None = None) -> bool:
    w = len(text) * height * width_factor
    c = centre if centre is not None else representative_point(poly)
    box = rectangle_polygon(c, w * 1.1, height * 1.3, rotation_deg)
    return poly.contains(box)


def fit_text_height(text: str, heights: list[float], width_factor: float, poly: Polygon,
                    rotation_deg: float = 0.0, centre: Pt | None = None) -> float:
    """The largest of the drawing's standard text heights at which this mark fits inside ``poly``.

    Heights are chosen from a ladder, not computed freely: a drawing whose every mark is a
    slightly different size looks wrong and cannot be edited or re-styled as a set. Falls back to
    the smallest height when even that overflows -- the mark is still drawn, because a drafter
    needs to see it to correct it.
    """
    ladder = sorted((h for h in heights if h > 0), reverse=True) or [1.0]
    for h in ladder:
        if text_fits(text, h, width_factor, poly, rotation_deg, centre):
            return h
    return ladder[-1]


def box_centre(poly: Polygon) -> Pt:
    """The centre of the bounding box, or a point inside the shape when that centre is not.

    A rectangular column or wall leg wants its mark on the box centre. An L or T shape has a box
    centre out in the notch, where the text would sit on nothing.
    """
    minx, miny, maxx, maxy = poly.bounds
    c = ((minx + maxx) / 2, (miny + maxy) / 2)
    return c if poly.contains(Point(c)) else representative_point(poly)


def fit_arcs(ring: list[Pt], circles: list[tuple[Pt, float]], tol: float) -> tuple[list[Pt], list[float]]:
    """Replace runs of vertices lying on a known circle by one arc segment (DXF bulge).

    Returns the reduced vertex list and, per vertex, the bulge of the segment to the next
    vertex (0 = straight). Bulge = tan(sweep / 4), positive for counter-clockwise arcs.
    """
    n = len(ring)
    if n < 3 or not circles:
        return list(ring), [0.0] * n
    on: list[int | None] = [None] * n
    for i, v in enumerate(ring):
        for k, (c, r) in enumerate(circles):
            if abs(math.dist(v, c) - r) <= tol:
                on[i] = k
                break
    start = next((i for i in range(n) if on[i] is None), None)
    if start is None:
        return list(ring), [0.0] * n
    order = list(range(start, n)) + list(range(0, start))
    pts: list[Pt] = []
    bulges: list[float] = []
    i = 0
    while i < n:
        k = on[order[i]]
        if k is None:
            pts.append(ring[order[i]])
            bulges.append(0.0)
            i += 1
            continue
        j = i
        while j + 1 < n and on[order[j + 1]] == k:
            j += 1
        if j == i:
            pts.append(ring[order[i]])
            bulges.append(0.0)
            i += 1
            continue
        c, r = circles[k]
        p0, p1 = ring[order[i]], ring[order[j]]
        a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
        a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
        ccw = (a1 - a0) % (2 * math.pi)
        if j - i >= 2:
            pm = ring[order[(i + j) // 2]]
            am = math.atan2(pm[1] - c[1], pm[0] - c[0])
            mid_on_ccw = (am - a0) % (2 * math.pi) <= ccw
            sweep = ccw if mid_on_ccw else ccw - 2 * math.pi
        else:
            sweep = ccw if ccw <= math.pi else ccw - 2 * math.pi
        pts.append(p0)
        bulges.append(math.tan(sweep / 4.0))
        pts.append(p1)
        bulges.append(0.0)
        i = j + 1
    return pts, bulges
