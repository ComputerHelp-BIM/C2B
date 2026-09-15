"""Diff a template DXF (re-read) against the normalised model it was written from.

Every difference is something a person did to the drawing after it was generated, or a
defect in the writer. Both are worth reporting, so the check is symmetric: elements only in
the model, elements only in the drawing, and elements that moved, changed size or changed
mark.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

from ..geometry import classify_polygon
from ..normalize.geometry import poly_from_points
from ..normalize.model import NormalizedProject
from ..schema import Diagnostic, Point2
from .marks import parse_template_mark

CODES: dict[str, str] = {
    "RT_MISSING": "Element of the model is not in the drawing (deleted)",
    "RT_ADDED": "Element in the drawing is not in the model (added by hand)",
    "RT_MOVED": "Element moved",
    "RT_RESIZED": "Element size changed",
    "RT_MARK_CHANGED": "Mark text changed",
    "RT_MARK_MISMATCH": "Mark disagrees with the drawn geometry",
    "RT_MARK_MISSING": "Element has no mark in the drawing",
    "RT_COUNT": "Element count per floor differs",
    "RT_DUP_MARK": "The same mark is used twice on one floor",
    "RT_LEVEL_CHANGED": "Level elevation or name changed",
    "RT_FLOOR_MISSING": "Floor of the model is not in the drawing",
}


@dataclass
class Tolerances:
    move_mm: float = 2.0
    size_mm: float = 2.0
    iou: float = 0.9


@dataclass
class DiffResult:
    findings: list[Diagnostic] = field(default_factory=list)
    counts: list[dict] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for d in self.findings if d.severity == "ERROR")

    @property
    def warnings(self) -> int:
        return sum(1 for d in self.findings if d.severity == "WARNING")

    @property
    def infos(self) -> int:
        return sum(1 for d in self.findings if d.severity == "INFO")

    def ok(self) -> bool:
        return self.errors == 0 and self.warnings == 0


_CATEGORIES = ("columns", "beams", "panels", "footings", "walls", "openings", "grids", "stairs", "folds", "piles", "joints")


def _poly(el) -> Polygon | None:
    return poly_from_points(el.outline) if getattr(el, "outline", None) else None


def _centre(el) -> tuple[float, float] | None:
    """Centre of the drawn outline; both sides are measured the same way."""
    poly = _poly(el)
    if poly is not None:
        return (poly.centroid.x, poly.centroid.y)
    for attr in ("center", "centroid", "centre"):
        p = getattr(el, attr, None)
        if isinstance(p, Point2):
            return (p.x, p.y)
    if getattr(el, "start", None) is not None and getattr(el, "end", None) is not None:
        return ((el.start.x + el.end.x) / 2, (el.start.y + el.end.y) / 2)
    return None


def _size(el) -> tuple[float, float] | None:
    """Size of the minimum rotated rectangle, so a rotated member is not measured by its bounding box."""
    poly = _poly(el)
    if poly is None:
        return None
    shape = classify_polygon(poly)
    return (round(shape.width, 1), round(shape.depth, 1))


def _drawable(el, cat: str) -> bool:
    """Only elements the template writer actually draws take part in the comparison."""
    if cat == "panels":
        return getattr(el, "kind", "slab") in ("slab", "cantilever", "ramp")
    if cat == "stairs":
        return bool(getattr(el, "outline", None))
    if cat == "piles":
        return bool(getattr(el, "diameter_mm", None))
    if cat == "walls":
        return getattr(el, "structural", True)
    return True


def _mark(el) -> str:
    m = getattr(el, "mark", None)
    return (m or "").strip()


def _iou(a: Polygon, b: Polygon) -> float:
    try:
        inter = a.intersection(b).area
    except Exception:
        return 0.0
    return inter / (a.area + b.area - inter) if inter > 0 else 0.0


def compare(model: NormalizedProject, drawing: NormalizedProject, tol: Tolerances | None = None) -> DiffResult:
    tol = tol or Tolerances()
    res = DiffResult()

    def add(sev: str, code: str, msg: str, floor_id=None, element_id=None, loc=None):
        res.findings.append(Diagnostic(severity=sev, code=code, message=msg, floor_id=floor_id, element_id=element_id,
                                       location=Point2(x=loc[0], y=loc[1]) if loc else None))

    model_floors = {f.id: f for f in model.floors}
    drawing_floors = {f.id: f for f in drawing.floors}
    for fid, f in model_floors.items():
        if fid not in drawing_floors:
            add("ERROR", "RT_FLOOR_MISSING", f"Floor {fid} '{f.name}' is not in the drawing", floor_id=fid)

    for cat in _CATEGORIES:
        a_all = [e for e in getattr(model, cat) if _drawable(e, cat)]
        b_all = [e for e in getattr(drawing, cat) if _drawable(e, cat)]
        for fid in sorted({e.floor_id for e in a_all} | {e.floor_id for e in b_all}):
            a = [e for e in a_all if e.floor_id == fid]
            b = [e for e in b_all if e.floor_id == fid]
            if len(a) != len(b):
                add("WARNING", "RT_COUNT", f"{cat}: model has {len(a)}, drawing has {len(b)}", floor_id=fid)
            res.counts.append({"floor": fid, "category": cat, "model": len(a), "drawing": len(b)})

            b_by_id = {e.id: e for e in b if e.id}
            matched_b: set[str] = set()
            b_polys = [(_poly(e), e) for e in b]
            tree_items = [(p, e) for p, e in b_polys if p is not None]
            tree = STRtree([p for p, _e in tree_items]) if tree_items else None

            for ea in a:
                eb = b_by_id.get(ea.id)
                if eb is None and tree is not None:
                    pa = _poly(ea)
                    if pa is not None:
                        best, best_iou = None, 0.0
                        for i in tree.query(pa, predicate="intersects"):
                            cand = tree_items[int(i)][1]
                            if cand.id in matched_b:
                                continue
                            v = _iou(pa, tree_items[int(i)][0])
                            if v > best_iou:
                                best, best_iou = cand, v
                        if best is not None and best_iou >= 0.5:
                            eb = best
                if eb is None:
                    add("ERROR", "RT_MISSING", f"{cat[:-1]} {ea.id} '{_mark(ea)}' is not in the drawing", floor_id=fid, element_id=ea.id, loc=_centre(ea))
                    continue
                matched_b.add(eb.id)
                ca, cb = _centre(ea), _centre(eb)
                if ca and cb:
                    d = math.dist(ca, cb)
                    if d > tol.move_mm:
                        add("WARNING", "RT_MOVED", f"{cat[:-1]} {ea.id} '{_mark(ea)}' moved {d:.0f} mm", floor_id=fid, element_id=ea.id, loc=cb)
                sa, sb = _size(ea), _size(eb)
                circleish = "circle" in (getattr(ea, "shape", ""), getattr(eb, "shape", ""))
                size_tol = max(tol.size_mm, 0.02 * max(sa or [0]) if circleish and sa else tol.size_mm)
                if sa and sb and (abs(sa[0] - sb[0]) > size_tol or abs(sa[1] - sb[1]) > size_tol):
                    add("WARNING", "RT_RESIZED", f"{cat[:-1]} {ea.id} '{_mark(ea)}' is {sb[0]:.0f}x{sb[1]:.0f} in the drawing, {sa[0]:.0f}x{sa[1]:.0f} in the model",
                        floor_id=fid, element_id=ea.id, loc=cb)
                ma, mb = _mark(ea), _mark(eb)
                if ma and not mb:
                    add("WARNING", "RT_MARK_MISSING", f"{cat[:-1]} {ea.id} lost its mark '{ma}'", floor_id=fid, element_id=ea.id, loc=cb)
                elif ma.replace(" ", "") != mb.replace(" ", ""):
                    add("WARNING", "RT_MARK_CHANGED", f"{cat[:-1]} {ea.id}: mark '{ma}' became '{mb}'", floor_id=fid, element_id=ea.id, loc=cb)

            for eb in b:
                if eb.id in matched_b:
                    continue
                add("ERROR", "RT_ADDED", f"{cat[:-1]} {eb.id} '{_mark(eb)}' is in the drawing but not in the model", floor_id=fid, element_id=eb.id, loc=_centre(eb))

    # marks versus drawn geometry, and duplicate marks, on the drawing itself
    for cat in ("columns", "beams", "footings"):
        seen: dict[tuple[str, str], tuple[str, tuple[float, float] | None]] = {}
        for e in getattr(drawing, cat):
            mk = _mark(e)
            if not mk:
                continue
            base = parse_template_mark(mk).base
            size = _size(e)
            # a beam mark describes the cross-section: spans of one mark differ in length, never in width
            section = ((getattr(e, "width_mm", None) or min(size),) if (size and cat == "beams")
                       else (tuple(sorted(size)) if size else None))
            if base:
                key = (e.floor_id, base)
                prev = seen.get(key)
                # one mark may repeat (the client's "MB" runs everywhere); it must not name two different sections
                if prev and section and prev[1] and any(abs(x - y) > 26 for x, y in zip(section, prev[1])):
                    shown = lambda t: "x".join(f"{v:.0f}" for v in t)
                    add("WARNING", "RT_DUP_MARK", f"{cat[:-1]} mark '{base}' names {shown(prev[1])} on {prev[0]} and {shown(section)} on {e.id}",
                        floor_id=e.floor_id, element_id=e.id, loc=_centre(e))
                seen[key] = (e.id, section)
            tm = parse_template_mark(mk)
            size = _size(e)
            if getattr(e, "shape", "rect") == "polygon":
                continue     # an L or T shaped member is not described by one b x D
            if tm.size and size:
                drawn = sorted(size)
                stated = sorted(tm.size)
                if cat == "beams":
                    drawn, stated = [getattr(e, "width_mm", None) or min(size)], [tm.width_mm]
                if any(abs(x - y) > 26 for x, y in zip(drawn, stated)):
                    shown = f"{tm.width_mm:.0f}x{tm.depth_mm:.0f}"
                    add("WARNING", "RT_MARK_MISMATCH", f"{cat[:-1]} {e.id}: mark says {shown} but the drawing measures {size[0]:.0f}x{size[1]:.0f}",
                        floor_id=e.floor_id, element_id=e.id, loc=_centre(e))

    m_levels = {l.name.strip(): l for l in model.levels}
    for l in drawing.levels:
        ml = m_levels.get(l.name.strip())
        if ml is not None and abs((ml.elevation_mm or 0) - (l.elevation_mm or 0)) > 1.0:
            add("WARNING", "RT_LEVEL_CHANGED", f"Level '{l.name}' is at {l.elevation_mm:.0f} in the drawing, {ml.elevation_mm:.0f} in the model", element_id=l.id)
    return res
