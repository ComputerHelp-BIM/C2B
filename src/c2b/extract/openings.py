"""Openings (cut-outs, shafts) and walls."""
from __future__ import annotations

from shapely.geometry import Point

from ..geometry import classify_polygon
from ..schema import Opening, Wall
from .associate import make_tag_cands
from .context import FloorContext, outline_points, pt, tag_ref
from .outlines import collect_outlines


def extract_openings(ctx: FloorContext) -> list[Opening]:
    tol = ctx.tol
    outlines = collect_outlines(ctx, "OPENING", 100.0, tol.opening_min_area_mm2, 1e10, 1e6)
    labels = [t for t in ctx.texts("OPENING_TAG")] + [t for t in ctx.texts("NOTE") if t.text and len(t.text) <= 20]
    out: list[Opening] = []
    for o in outlines:
        c = o.poly.centroid
        label = None
        for t in labels:
            if o.poly.contains(Point(t.rep_point())):
                label = (label + " " if label else "") + t.text.strip()
                ctx.assigned_tag_handles.add(t.handle)
        out.append(Opening(id=ctx.ids.next("O"), floor_id=ctx.floor_id, label=label, center=pt((c.x, c.y)), outline=outline_points(o.poly),
                           area_mm2=round(o.poly.area, 1), source_layer=o.layer, source_handles=o.handles + o.merged_handles))
    return out


def extract_walls(ctx: FloorContext) -> list[Wall]:
    outlines = collect_outlines(ctx, "WALL", 75.0, 5e4, 1e10, 1e6)
    tags = make_tag_cands(ctx.texts("WALL_TAG"), group_factor=0.0)
    out: list[Wall] = []
    for o in outlines:
        s = classify_polygon(o.poly)
        my = [t for t in tags if o.poly.buffer(max(600.0, 2 * t.height)).contains(Point(t.center))]
        for t in my:
            ctx.assigned_tag_handles.add(t.prim.handle)
        mark = next((t.parsed.mark for t in my if t.parsed.mark), None)
        rule_mods = ctx.rules.get(o.layer).modifiers if o.layer in ctx.rules else []
        out.append(Wall(id=ctx.ids.next("W"), floor_id=ctx.floor_id, mark=mark, center=pt(s.center), outline=outline_points(o.poly),
                        length_mm=round(max(s.width, s.depth), 1), thickness_mm=round(min(s.width, s.depth), 1) if s.shape == "rect" else None,
                        rotation_deg=round(s.rotation_deg, 3), area_mm2=round(o.poly.area, 1), structural="non_structural" not in rule_mods,
                        tags=[tag_ref(t.prim) for t in my], source_layer=o.layer, source_handles=o.handles + o.merged_handles))
    return out
