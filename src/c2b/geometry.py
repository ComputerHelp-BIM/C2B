"""Geometry helpers built on Shapely.

All functions work in millimetres in the XY plane. They are pure functions so
they can be unit tested without a DXF file.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

Pt = tuple[float, float]


# ---------------------------------------------------------------------------
# Polygons
# ---------------------------------------------------------------------------

def polygon_from_points(points: list[Pt], close_tol: float = 0.0) -> Polygon | None:
    """Build a valid polygon from a vertex list.

    If the ring is open but its end points are within ``close_tol`` the ring is
    closed. Degenerate or self-intersecting rings are repaired with a zero
    buffer; if that fails ``None`` is returned.
    """
    pts = [(float(x), float(y)) for x, y in points]
    # drop consecutive duplicates
    dedup: list[Pt] = []
    for p in pts:
        if not dedup or math.dist(dedup[-1], p) > 1e-6:
            dedup.append(p)
    if len(dedup) > 1 and math.dist(dedup[0], dedup[-1]) <= 1e-6:
        dedup.pop()
    if len(dedup) < 3:
        return None
    if close_tol > 0 and math.dist(dedup[0], dedup[-1]) > close_tol:
        return None
    try:
        poly = Polygon(dedup)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            return None
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        return poly
    except Exception:
        return None


def ring_gap(points: list[Pt]) -> float:
    """Distance between the first and last vertex of a ring."""
    if len(points) < 2:
        return 0.0
    return math.dist(points[0], points[-1])


@dataclass
class ShapeInfo:
    """Result of classifying a closed outline."""

    shape: str                 # "rect" | "circle" | "polygon"
    center: Pt
    width: float               # extent along the local x axis (mm)
    depth: float               # extent along the local y axis (mm)
    rotation_deg: float        # rotation of the local x axis, in (-45, 45]
    diameter: float | None = None
    area: float = 0.0


def classify_polygon(poly: Polygon, rect_tol: float = 0.03, circle_tol: float = 0.06) -> ShapeInfo:
    """Classify a polygon as rectangle, circle or general polygon and measure it."""
    area = poly.area
    minx, miny, maxx, maxy = poly.bounds
    bw, bh = maxx - minx, maxy - miny
    n_vertices = len(poly.exterior.coords) - 1

    # circle test: near-square bbox, area close to pi r^2 and many vertices
    if bw > 0 and bh > 0 and abs(bw - bh) / max(bw, bh) <= 0.03 and n_vertices >= 8:
        r = (bw + bh) / 4.0
        if abs(area - math.pi * r * r) / (math.pi * r * r) <= circle_tol:
            return ShapeInfo("circle", (poly.centroid.x, poly.centroid.y), bw, bh, 0.0, diameter=2 * r, area=area)

    mrr = poly.minimum_rotated_rectangle
    if mrr.geom_type == "Polygon" and mrr.area > 0 and abs(area - mrr.area) / mrr.area <= rect_tol:
        coords = list(mrr.exterior.coords)[:4]
        e0 = math.dist(coords[0], coords[1])
        e1 = math.dist(coords[1], coords[2])
        ang = math.degrees(math.atan2(coords[1][1] - coords[0][1], coords[1][0] - coords[0][0]))
        # normalise so the local x axis is within (-45, 45]
        w, d = e0, e1
        ang = ((ang + 90) % 180) - 90          # -> (-90, 90]
        if ang > 45:
            ang -= 90
            w, d = e1, e0
        elif ang <= -45:
            ang += 90
            w, d = e1, e0
        if abs(ang) < 1e-6:
            ang = 0.0
        cx, cy = mrr.centroid.x, mrr.centroid.y
        return ShapeInfo("rect", (cx, cy), w, d, ang, area=area)

    return ShapeInfo("polygon", (poly.centroid.x, poly.centroid.y), bw, bh, 0.0, area=area)


def iou(a: Polygon, b: Polygon) -> float:
    """Intersection over union of two polygons."""
    try:
        inter = a.intersection(b).area
    except Exception:
        return 0.0
    if inter <= 0:
        return 0.0
    return inter / (a.area + b.area - inter)


def snap_endpoints(lines: list[LineString], tol: float) -> list[LineString]:
    """Move line end points that lie within ``tol`` of each other onto one shared point.

    This closes the small gaps drafters leave at corners, which plain grid
    snapping cannot do reliably (a gap of half the grid still survives rounding).
    """
    if tol <= 0 or not lines:
        return lines
    ends: list[Pt] = []
    for l in lines:
        c = list(l.coords)
        ends.append((c[0][0], c[0][1]))
        ends.append((c[-1][0], c[-1][1]))
    tree = shapely.STRtree([Point(e) for e in ends])
    parent = list(range(len(ends)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, e in enumerate(ends):
        for j in tree.query(Point(e).buffer(tol), predicate="intersects"):
            j = int(j)
            if j > i and math.dist(e, ends[j]) <= tol:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(ends)):
        groups.setdefault(find(i), []).append(i)
    target: dict[int, Pt] = {}
    for members in groups.values():
        cx = sum(ends[m][0] for m in members) / len(members)
        cy = sum(ends[m][1] for m in members) / len(members)
        for m in members:
            target[m] = (cx, cy)
    out: list[LineString] = []
    for k, l in enumerate(lines):
        c = [(x, y) for x, y, *_ in l.coords]
        c[0] = target[2 * k]
        c[-1] = target[2 * k + 1]
        if len(c) >= 2 and math.dist(c[0], c[-1]) > 1e-9 or len(c) > 2:
            out.append(LineString(c))
    return out


def polygonize_lines(lines: list[LineString], grid_size: float = 1.0) -> list[Polygon]:
    """Turn a soup of line segments (and arcs) into the closed faces they form.

    End points within ``grid_size`` of each other are snapped together first so
    small drafting gaps close.
    """
    lines = [l for l in lines if not l.is_empty]
    if not lines:
        return []
    # 1. end points within the tolerance become one point (closes corner gaps),
    # 2. all coordinates are rounded to the grid so nearly-collinear overlaps become exactly collinear,
    # 3. the union nodes every crossing and polygonize collects the faces.
    snapped = [shapely.set_precision(l, grid_size) for l in snap_endpoints(lines, grid_size)]
    merged = unary_union([l for l in snapped if not l.is_empty])
    return [p for p in polygonize(merged) if p.area > 0]


def rectangle_polygon(center: Pt, width: float, depth: float, rotation_deg: float) -> Polygon:
    """Axis-aligned rectangle rotated about its centre."""
    hw, hd = width / 2.0, depth / 2.0
    c, s = math.cos(math.radians(rotation_deg)), math.sin(math.radians(rotation_deg))
    pts = []
    for dx, dy in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        pts.append((center[0] + dx * c - dy * s, center[1] + dx * s + dy * c))
    return Polygon(pts)


# ---------------------------------------------------------------------------
# Segments: merging and pairing (beams)
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """A straight segment with provenance."""

    p1: Pt
    p2: Pt
    handles: list[str] = field(default_factory=list)
    layer: str = ""
    n_parts: int = 1

    @property
    def length(self) -> float:
        return math.dist(self.p1, self.p2)

    @property
    def angle_deg(self) -> float:
        """Direction in [0, 180)."""
        a = math.degrees(math.atan2(self.p2[1] - self.p1[1], self.p2[0] - self.p1[0]))
        return a % 180.0

    def unit(self) -> tuple[Pt, Pt]:
        a = math.radians(self.angle_deg)
        u = (math.cos(a), math.sin(a))
        n = (-u[1], u[0])
        return u, n

    def linestring(self) -> LineString:
        return LineString([self.p1, self.p2])


def _angle_bucket(angle_deg: float, tol: float) -> int:
    n = int(round(180.0 / tol))
    return int(round(angle_deg / tol)) % n


def _frame(angle_deg: float) -> tuple[Pt, Pt]:
    a = math.radians(angle_deg)
    u = (math.cos(a), math.sin(a))
    return u, (-u[1], u[0])


def _project(p: Pt, u: Pt, n: Pt) -> tuple[float, float]:
    return p[0] * u[0] + p[1] * u[1], p[0] * n[0] + p[1] * n[1]


def _unproject(t: float, o: float, u: Pt, n: Pt) -> Pt:
    return (u[0] * t + n[0] * o, u[1] * t + n[1] * o)


def merge_collinear(segments: list[Segment], angle_tol: float = 0.5, offset_tol: float = 2.0, gap_tol: float = 0.0) -> list[Segment]:
    """Merge collinear segments that overlap or lie within ``gap_tol`` of each other."""
    buckets: dict[int, list[Segment]] = {}
    for s in segments:
        if s.length <= 1e-6:
            continue
        buckets.setdefault(_angle_bucket(s.angle_deg, angle_tol), []).append(s)

    out: list[Segment] = []
    for bucket, segs in buckets.items():
        angle = bucket * angle_tol
        u, n = _frame(angle)
        rows = []
        for s in segs:
            t1, o1 = _project(s.p1, u, n)
            t2, o2 = _project(s.p2, u, n)
            rows.append((0.5 * (o1 + o2), min(t1, t2), max(t1, t2), s))
        rows.sort(key=lambda r: (r[0], r[1]))
        # cluster by offset
        clusters: list[list] = []
        for r in rows:
            if clusters and abs(r[0] - clusters[-1][-1][0]) <= offset_tol:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        for cl in clusters:
            cl.sort(key=lambda r: r[1])
            cur = None
            for o, t1, t2, s in cl:
                if cur is None:
                    cur = [o, t1, t2, [s]]
                    continue
                if t1 <= cur[2] + gap_tol:
                    cur[2] = max(cur[2], t2)
                    cur[3].append(s)
                    cur[0] = (cur[0] * (len(cur[3]) - 1) + o) / len(cur[3])
                else:
                    out.append(_make_merged(cur, u, n))
                    cur = [o, t1, t2, [s]]
            if cur is not None:
                out.append(_make_merged(cur, u, n))
    return out


def _make_merged(cur, u, n) -> Segment:
    o, t1, t2, parts = cur
    handles = [h for s in parts for h in s.handles]
    return Segment(_unproject(t1, o, u, n), _unproject(t2, o, u, n), handles, parts[0].layer, n_parts=len(parts))


@dataclass
class PairedRect:
    """Two parallel edges paired into a centreline with a width."""

    start: Pt
    end: Pt
    width: float
    angle_deg: float
    edges: tuple[Segment, Segment]
    score: float

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    def outline(self) -> Polygon:
        cx, cy = (self.start[0] + self.end[0]) / 2, (self.start[1] + self.end[1]) / 2
        return rectangle_polygon((cx, cy), self.length, self.width, self.angle_deg)


def pair_parallel(
    segments: list[Segment],
    min_width: float,
    max_width: float,
    min_overlap: float,
    angle_tol: float = 1.0,
) -> tuple[list[PairedRect], list[Segment]]:
    """Pair parallel segments into rectangles (beam plan outlines).

    Candidate pairs are scored by width and by how well the two edges cover
    each other, then accepted greedily while tracking which parts of each edge
    have already been used. Returns the rectangles and the segments that were
    never used (for diagnostics).
    """
    buckets: dict[int, list[Segment]] = {}
    for s in segments:
        if s.length <= 1e-6:
            continue
        buckets.setdefault(_angle_bucket(s.angle_deg, angle_tol), []).append(s)

    candidates = []
    for bucket, segs in buckets.items():
        u, n = _frame(bucket * angle_tol)
        rows = []
        for s in segs:
            t1, o1 = _project(s.p1, u, n)
            t2, o2 = _project(s.p2, u, n)
            rows.append([0.5 * (o1 + o2), min(t1, t2), max(t1, t2), s])
        rows.sort(key=lambda r: r[0])
        for i in range(len(rows)):
            oi, si, ei, a = rows[i]
            for j in range(i + 1, len(rows)):
                oj, sj, ej, b = rows[j]
                w = oj - oi
                if w > max_width:
                    break
                if w < min_width:
                    continue
                overlap = min(ei, ej) - max(si, sj)
                if overlap < max(min_overlap, 0.0):
                    continue
                cover = min(overlap / (ei - si), overlap / (ej - sj))
                score = w / (0.5 + cover)
                candidates.append((score, w, max(si, sj), min(ei, ej), (oi + oj) / 2, a, b, u, n, bucket * angle_tol, cover))

    candidates.sort(key=lambda c: c[0])
    consumed: dict[int, list[tuple[float, float]]] = {}
    used: set[int] = set()
    rects: list[PairedRect] = []

    def free_fraction(seg: Segment, t1: float, t2: float) -> float:
        total = t2 - t1
        if total <= 0:
            return 0.0
        taken = 0.0
        for a, b in consumed.get(id(seg), []):
            taken += max(0.0, min(b, t2) - max(a, t1))
        return 1.0 - taken / total

    for score, w, t1, t2, o, a, b, u, n, ang, cover in candidates:
        if free_fraction(a, t1, t2) < 0.5 or free_fraction(b, t1, t2) < 0.5:
            continue
        consumed.setdefault(id(a), []).append((t1, t2))
        consumed.setdefault(id(b), []).append((t1, t2))
        used.add(id(a))
        used.add(id(b))
        rects.append(PairedRect(_unproject(t1, o, u, n), _unproject(t2, o, u, n), w, ang, (a, b), score))

    unpaired = [s for s in segments if id(s) not in used and s.length > 1e-6]
    return rects, unpaired


# ---------------------------------------------------------------------------
# Text boxes
# ---------------------------------------------------------------------------

def text_box(center: Pt, width: float, height: float, rotation_deg: float) -> Polygon:
    return rectangle_polygon(center, max(width, 1e-3), max(height, 1e-3), rotation_deg)


def angle_diff_deg(a: float, b: float) -> float:
    """Smallest difference between two directions in degrees, modulo 180."""
    d = abs((a - b) % 180.0)
    return min(d, 180.0 - d)


def nearest_grid_intersection_label(point: Pt, grids_x: list[tuple[str, float]], grids_y: list[tuple[str, float]], tol: float) -> str | None:
    """Return "X/Y" label of the closest grid intersection within ``tol``, else None."""
    if not grids_x or not grids_y:
        return None
    gx = min(grids_x, key=lambda g: abs(g[1] - point[0]))
    gy = min(grids_y, key=lambda g: abs(g[1] - point[1]))
    if abs(gx[1] - point[0]) <= tol and abs(gy[1] - point[1]) <= tol:
        return f"{gx[0]}/{gy[0]}"
    return None


def as_point(p: Pt) -> Point:
    return Point(p[0], p[1])


#: Defaults for :func:`is_wall_like`. ``Tolerances`` seeds its profile fields from these, so the
#: numbers live in one place whether the caller has a profile (extraction) or not (round trip).
WALL_LIKE_MIN_SIDE_RATIO = 4.0
WALL_LIKE_MIN_LENGTH_MM = 1000.0


def is_wall_like(
    shape: str,
    width: float,
    depth: float,
    min_side_ratio: float = WALL_LIKE_MIN_SIDE_RATIO,
    min_length_mm: float = WALL_LIKE_MIN_LENGTH_MM,
) -> bool:
    """Is this column really a shear wall?

    Long and thin, or an irregular polygon long enough to be a wall leg. It decides how the
    element is marked and how it is built, so extraction and the round trip must answer it the
    same way -- including for entities a drafter added by hand, which carry no XDATA to consult.
    """
    long_side, short_side = max(width, depth), min(width, depth)
    if shape == "polygon" and long_side >= min_length_mm:
        return True
    return shape != "circle" and short_side > 0 and long_side / short_side >= min_side_ratio and long_side >= min_length_mm
