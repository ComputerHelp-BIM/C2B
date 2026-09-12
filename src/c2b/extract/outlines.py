"""Shared outline collection for column-like elements (columns, footings, openings, walls).

Gathers closed shapes from polylines, hatches, circles, solids and line loops,
closes nearly-closed rings, filters by size and removes duplicates.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon
from shapely.strtree import STRtree

from ..dxfio import Prim
from ..geometry import iou, polygon_from_points, polygonize_lines
from ..tags import parse_size_from_name
from .context import FloorContext

PRIORITY = {"polyline": 0, "circle": 0, "solid": 1, "hatch": 2, "lines": 3, "generic_hatch": 4}


@dataclass
class Outline:
    poly: Polygon
    source_kind: str
    layer: str
    handles: list[str] = field(default_factory=list)
    block_size: tuple[float, float] | None = None
    block_path: tuple[str, ...] = ()
    priority: int = 0
    merged_handles: list[str] = field(default_factory=list)


def _block_size(prim: Prim) -> tuple[float, float] | None:
    for name in reversed(prim.block_path):
        s = parse_size_from_name(name)
        if s:
            return s
    return None


def collect_outlines(ctx: FloorContext, role: str, min_side: float, min_area: float, max_area: float, max_side: float,
                     include_generic_hatch: bool = False, close_tol: float | None = None) -> list[Outline]:
    tol = ctx.tol
    close_tol = tol.ring_close_tol_mm if close_tol is None else close_tol
    cands: list[Outline] = []
    soup: dict[str, list[LineString]] = {}
    soup_handles: dict[str, list[str]] = {}

    for p in ctx.geoms(role):
        if p.kind in ("polygon", "solid"):
            cands.append(Outline(p.geom, "polyline" if p.kind == "polygon" else "solid", p.layer, [p.handle], _block_size(p), p.block_path, PRIORITY[p.kind if p.kind == "solid" else "polyline"]))
        elif p.kind == "circle":
            cands.append(Outline(p.geom, "circle", p.layer, [p.handle], _block_size(p), p.block_path, PRIORITY["circle"]))
        elif p.kind == "hatch":
            cands.append(Outline(p.geom, "hatch", p.layer, [p.handle], _block_size(p), p.block_path, PRIORITY["hatch"]))
        elif p.kind == "polyline":
            coords = [(c[0], c[1]) for c in p.geom.coords]
            poly = polygon_from_points(coords, close_tol=close_tol) if len(coords) >= 3 and p.ring_gap <= close_tol else None
            if poly is not None:
                if p.ring_gap > tol.snap_mm:
                    ctx.diag.info("POLYLINE_NOT_CLOSED", f"Polyline {p.handle} on {p.layer} closed automatically (gap {p.ring_gap:.0f} mm)", floor_id=ctx.floor_id, layer=p.layer, handle=p.handle, location=p.rep_point())
                cands.append(Outline(poly, "polyline", p.layer, [p.handle], _block_size(p), p.block_path, PRIORITY["polyline"]))
            else:
                soup.setdefault(p.layer, []).append(p.geom)
                soup_handles.setdefault(p.layer, []).append(p.handle)
        elif p.kind in ("line", "arc", "curve"):
            soup.setdefault(p.layer, []).append(p.geom)
            soup_handles.setdefault(p.layer, []).append(p.handle)

    for layer, lines in soup.items():
        for poly in polygonize_lines(lines, grid_size=tol.snap_mm):
            cands.append(Outline(poly, "lines", layer, [], None, (), PRIORITY["lines"]))
    # attach handles of the lines that touch each polygonised face
    line_faces = [c for c in cands if c.source_kind == "lines"]
    if line_faces:
        all_lines = [(h, l) for layer in soup for h, l in zip(soup_handles[layer], soup[layer])]
        tree = STRtree([l for _, l in all_lines])
        for c in line_faces:
            hits = tree.query(c.poly.exterior.buffer(tol.snap_mm * 2), predicate="intersects")
            c.handles = sorted({all_lines[int(i)][0] for i in hits})

    if include_generic_hatch:
        for p in ctx.geoms("HATCH_GENERIC", "hatch"):
            cands.append(Outline(p.geom, "generic_hatch", p.layer, [p.handle], _block_size(p), p.block_path, PRIORITY["generic_hatch"]))

    # size filter
    kept: list[Outline] = []
    for c in cands:
        minx, miny, maxx, maxy = c.poly.bounds
        w, h = maxx - minx, maxy - miny
        if c.poly.area < min_area or c.poly.area > max_area:
            continue
        if min(w, h) < min_side or max(w, h) > max_side:
            continue
        kept.append(c)

    # dedupe: highest priority first, larger first within a priority
    kept.sort(key=lambda c: (c.priority, -c.poly.area))
    accepted: list[Outline] = []
    acc_polys: list[Polygon] = []
    for c in kept:
        dup = None
        if acc_polys:
            tree = STRtree(acc_polys)
            for i in (int(k) for k in tree.query(c.poly, predicate="intersects")):
                a = accepted[i]
                ratio = iou(a.poly, c.poly)
                inter = a.poly.intersection(c.poly).area
                if ratio >= tol.column_iou_dedupe or inter >= 0.8 * c.poly.area:
                    dup = a
                    break
        if dup is not None:
            dup.merged_handles.extend(c.handles)
            if dup.block_size is None and c.block_size:
                dup.block_size = c.block_size
            continue
        if c.source_kind == "generic_hatch":
            # generic hatches only confirm existing outlines; they never create elements
            continue
        accepted.append(c)
        acc_polys.append(c.poly)

    # containers: a face that holds two or more accepted outlines is an enclosure, not a member
    if len(accepted) > 2:
        tree = STRtree(acc_polys)
        result = []
        for i, c in enumerate(accepted):
            inner = [int(k) for k in tree.query(c.poly, predicate="contains") if int(k) != i]
            if len(inner) >= 2 and c.source_kind in ("lines", "polyline"):
                continue
            result.append(c)
        accepted = result
    return accepted
