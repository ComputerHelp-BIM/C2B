"""Slab extraction: thickness tags and (where drawn) slab outlines."""
from __future__ import annotations

from shapely.geometry import Point
from shapely.strtree import STRtree

from ..schema import Slab
from .associate import make_tag_cands
from .context import FloorContext, outline_points, pt, tag_ref


def extract_slabs(ctx: FloorContext) -> list[Slab]:
    tol = ctx.tol
    outlines = [p for p in ctx.geoms("SLAB", "polygon") if p.geom.area >= tol.slab_min_area_mm2]
    tags = make_tag_cands(ctx.texts("SLAB_TAG"), group_factor=0.0)
    slabs: list[Slab] = []

    def resolve_thickness(parsed):
        if parsed.thickness_mm is not None:
            return parsed.thickness_mm, "tag"
        sched = ctx.schedules.find(parsed.mark, "slab") or (ctx.schedules.find(parsed.mark) if parsed.category_hint == "slab" else None)
        if sched and isinstance(sched.get("thickness"), (int, float)):
            return float(sched["thickness"]), "schedule"
        if parsed.mark and parsed.category_hint == "slab" and len(ctx.schedules):
            return None, "missing_in_schedule"
        return None, "unknown"

    tree = STRtree([o.geom for o in outlines]) if outlines else None
    used_tags: set[int] = set()
    for oi, o in enumerate(outlines):
        sid = ctx.ids.next("S")
        inside = [ti for ti, t in enumerate(tags) if o.geom.contains(Point(t.center))]
        used_tags.update(inside)
        my = [tags[ti] for ti in inside]
        thickness, source = None, "unknown"
        mark = None
        for t in my:
            th, src = resolve_thickness(t.parsed)
            if th is not None:
                thickness, source = th, src
            if mark is None and t.parsed.mark:
                mark = t.parsed.mark
            ctx.assigned_tag_handles.add(t.prim.handle)
        c = o.geom.centroid
        modifier = ctx.modifier_for(o.layer)
        if thickness is None and ctx.frame.default_slab_thickness and modifier is None:
            thickness, source = ctx.frame.default_slab_thickness, "default"
        slabs.append(Slab(id=sid, floor_id=ctx.floor_id, mark=mark, thickness_mm=thickness, thickness_source=source if source in ("tag", "schedule", "default") else "unknown",
                          position=pt((c.x, c.y)), outline=outline_points(o.geom), modifier=modifier, tags=[tag_ref(t.prim) for t in my],
                          source_layer=o.layer, source_kind="polyline", source_handles=[o.handle]))
        if thickness is None and modifier is None:
            ctx.diag.warning("SLAB_NO_THICKNESS", f"Slab outline {sid} has no thickness tag", floor_id=ctx.floor_id, element_id=sid, layer=o.layer, location=(c.x, c.y))

    for ti, t in enumerate(tags):
        if ti in used_tags:
            continue
        p = t.parsed
        if p.unparsed or (p.thickness_mm is None and not p.mark and p.sunk_mm is None):
            continue   # left for the unassigned-tag report
        sid = ctx.ids.next("S")
        thickness, source = resolve_thickness(p)
        if thickness is None and ctx.frame.default_slab_thickness and p.sunk_mm is not None:
            thickness, source = ctx.frame.default_slab_thickness, "default"
        if source == "missing_in_schedule":
            ctx.diag.warning("SCHEDULE_MARK_MISSING", f"Slab mark '{p.mark}' not found in any schedule", floor_id=ctx.floor_id, element_id=sid, location=t.center)
        ctx.assigned_tag_handles.add(t.prim.handle)
        slabs.append(Slab(id=sid, floor_id=ctx.floor_id, mark=p.mark, thickness_mm=thickness, thickness_source=source if source in ("tag", "schedule", "default") else "unknown",
                          position=pt(t.center), outline=[], sunk_mm=p.sunk_mm, tags=[tag_ref(t.prim)], source_layer=t.prim.layer,
                          source_kind="tag", source_handles=[t.prim.handle]))
        if thickness is None:
            ctx.diag.warning("SLAB_NO_THICKNESS", f"Slab tag '{p.text}' has no thickness", floor_id=ctx.floor_id, element_id=sid, layer=t.prim.layer, location=t.center)

    if not [x for x in slabs if x.modifier is None] and (ctx.by_geom_role.get("BEAM") or ctx.by_geom_role.get("COLUMN")):
        if ctx.frame.default_slab_thickness:
            ctx.diag.info("SLAB_DEFAULT_THICKNESS", f"No slab tags on floor; general note gives {ctx.frame.default_slab_thickness:.0f} mm", floor_id=ctx.floor_id)
        else:
            ctx.diag.warning("SLAB_NONE_ON_FLOOR", "No slab thickness information found on this floor", floor_id=ctx.floor_id)
    return slabs
