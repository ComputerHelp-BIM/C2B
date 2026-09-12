"""Footing extraction."""
from __future__ import annotations

from ..geometry import classify_polygon
from ..schema import Footing
from .associate import TagCand, associate_tags, make_tag_cands, merge_parsed
from .context import FloorContext, outline_points, pt, tag_ref
from .outlines import collect_outlines


def extract_footings(ctx: FloorContext) -> list[Footing]:
    tol = ctx.tol
    outlines = collect_outlines(ctx, "FOOTING", tol.footing_min_side_mm, tol.footing_min_side_mm ** 2, 1e10, 1e6)
    if not outlines:
        return []
    polys = [o.poly for o in outlines]
    shapes = [classify_polygon(p) for p in polys]
    tags: list[TagCand] = make_tag_cands(ctx.texts("FOOTING_TAG"))

    def radius(i: int, tag: TagCand) -> float:
        s = shapes[i]
        return max(800.0, 0.75 * max(s.width, s.depth), 3 * tag.height)

    assigned, _ = associate_tags(polys, tags, radius)
    out: list[Footing] = []
    for i, o in enumerate(outlines):
        s = shapes[i]
        fid = ctx.ids.next("F")
        my = [tags[k] for k in assigned.get(i, [])]
        for t in my:
            ctx.assigned_tag_handles.update(pr.handle for pr in t.prims)
        merged, _sizes = merge_parsed(my)
        width = depth = thickness = None
        size_source = "unknown"
        if merged.width_mm is not None:
            width, depth, size_source = merged.width_mm, merged.depth_mm, "tag"
        if merged.thickness_mm is not None:
            thickness = merged.thickness_mm
            size_source = "tag" if size_source == "unknown" else size_source
        if width is None or thickness is None:
            sched = ctx.schedules.find(merged.mark, "footing") or ctx.schedules.find(merged.mark)
            if sched:
                if width is None and isinstance(sched.get("width"), (int, float)) and isinstance(sched.get("depth"), (int, float)):
                    width, depth = float(sched["width"]), float(sched["depth"])
                    size_source = "schedule" if size_source == "unknown" else size_source
                if thickness is None and isinstance(sched.get("thickness"), (int, float)):
                    thickness = float(sched["thickness"])
                    size_source = "schedule" if size_source == "unknown" else size_source
            elif merged.mark and len(ctx.schedules):
                ctx.diag.warning("SCHEDULE_MARK_MISSING", f"Footing mark '{merged.mark}' not found in any schedule", floor_id=ctx.floor_id, element_id=fid, location=s.center)
        if width is None:
            width, depth = round(s.width, 1), round(s.depth, 1)
            size_source = "geometry" if size_source == "unknown" else size_source
        if thickness is None:
            ctx.diag.warning("FOOTING_NO_SIZE", f"Footing {fid} ({s.width:.0f}x{s.depth:.0f}) has no thickness from tag or schedule", floor_id=ctx.floor_id, element_id=fid, layer=o.layer, location=s.center)
        out.append(Footing(
            id=fid, floor_id=ctx.floor_id, mark=merged.mark, shape=s.shape, center=pt(s.center), width_mm=width, depth_mm=depth,
            rotation_deg=round(s.rotation_deg, 3), thickness_mm=thickness, fold_mm=merged.fold_mm, outline=outline_points(o.poly),
            area_mm2=round(o.poly.area, 1), drawn_width_mm=round(s.width, 1), drawn_depth_mm=round(s.depth, 1), size_source=size_source,
            modifier=ctx.modifier_for(o.layer), tags=[tag_ref(pr) for t in my for pr in t.prims], source_layer=o.layer,
            source_handles=o.handles + o.merged_handles, confidence="high" if o.source_kind == "polyline" else "medium",
        ))
    return out
