"""Grid line extraction."""
from __future__ import annotations

import math
import re

from ..geometry import Segment, merge_collinear
from ..schema import Grid
from .context import FloorContext, pt

_RE_GOOD_LABEL = re.compile(r"^(?:[A-Z]{1,2}\d?|\d{1,3}[A-Z]?|[A-Z]\d{1,2})$")


def _label_priority(text: str) -> int:
    t = text.strip()
    if _RE_GOOD_LABEL.match(t):
        return 0
    if len(t) <= 4:
        return 1
    return 2


def extract_grids(ctx: FloorContext) -> list[Grid]:
    tol = ctx.tol
    segs: list[Segment] = []
    for p in ctx.geoms("GRID", "line", "polyline"):
        coords = list(p.geom.coords)
        for a, b in zip(coords[:-1], coords[1:]):
            s = Segment((a[0], a[1]), (b[0], b[1]), [p.handle], p.layer)
            if s.length >= tol.grid_min_length_mm * 0.25:
                segs.append(s)
    if not segs:
        if ctx.by_geom_role.get("COLUMN") or ctx.by_geom_role.get("BEAM"):
            ctx.diag.warning("NO_GRIDS", "No grid lines found on this floor", floor_id=ctx.floor_id)
        return []
    merged = [s for s in merge_collinear(segs, angle_tol=0.5, offset_tol=5.0, gap_tol=tol.grid_label_radius_mm) if s.length >= tol.grid_min_length_mm]

    labels = [t for t in ctx.texts("GRID_TAG") if len((t.text or "").strip()) <= 6]
    label_pts = [(t, t.rep_point()) for t in labels]

    grids: list[Grid] = []
    seen: dict[tuple[str, str], list[Grid]] = {}
    unlabeled = 0
    for s in merged:
        best = None
        for t, c in label_pts:
            d = min(math.dist(c, s.p1), math.dist(c, s.p2))
            if d > tol.grid_label_radius_mm:
                continue
            key = (_label_priority(t.text), d)
            if best is None or key < best[0]:
                best = (key, t)
        label = best[1].text.strip() if best else None
        if best:
            ctx.assigned_tag_handles.add(best[1].prim_handle if hasattr(best[1], "prim_handle") else best[1].handle)
        ang = s.angle_deg
        if abs(ang - 90) <= 1.0:
            axis, offset = "X", 0.5 * (s.p1[0] + s.p2[0])
        elif ang <= 1.0 or ang >= 179.0:
            axis, offset = "Y", 0.5 * (s.p1[1] + s.p2[1])
        else:
            axis, offset = "other", 0.0
        if label is None:
            unlabeled += 1
        g = Grid(id=ctx.ids.next("G"), floor_id=ctx.floor_id, label=label, axis=axis, start=pt(s.p1), end=pt(s.p2),
                 angle_deg=round(ang, 3), offset_mm=round(offset, 1), source_layer=s.layer, source_handles=s.handles)
        if label:
            dup = seen.setdefault((label, axis), [])
            same = [d for d in dup if abs(d.offset_mm - g.offset_mm) <= 50]
            if same:
                # same grid drawn twice (e.g. both floors' copies or split segments): extend and skip
                continue
            if dup:
                ctx.diag.warning("GRID_DUPLICATE_LABEL", f"Grid label '{label}' appears on two different {axis} lines ({dup[0].offset_mm:.0f} and {g.offset_mm:.0f})", floor_id=ctx.floor_id, element_id=g.id, location=s.p1)
            dup.append(g)
        grids.append(g)
    if unlabeled:
        ctx.diag.warning("GRID_NO_LABEL", f"{unlabeled} grid line(s) have no label within {tol.grid_label_radius_mm:.0f} mm of their ends", floor_id=ctx.floor_id)
    ctx.grids_x = [(g.label, g.offset_mm) for g in grids if g.axis == "X" and g.label]
    ctx.grids_y = [(g.label, g.offset_mm) for g in grids if g.axis == "Y" and g.label]
    return grids
