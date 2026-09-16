"""Column extraction."""
from __future__ import annotations

from ..geometry import classify_polygon, is_wall_like, nearest_grid_intersection_label
from ..schema import Column
from .associate import TagCand, associate_tags, make_tag_cands, merge_parsed
from .context import FloorContext, outline_points, pt, tag_ref
from .outlines import collect_outlines


def _sizes_match(a: tuple[float, float], b: tuple[float, float], tol: float) -> bool:
    sa, sb = sorted(a), sorted(b)
    return abs(sa[0] - sb[0]) <= tol and abs(sa[1] - sb[1]) <= tol


def extract_columns(ctx: FloorContext) -> list[Column]:
    tol = ctx.tol
    outlines = collect_outlines(
        ctx, "COLUMN", tol.column_min_side_mm, tol.column_min_area_mm2, tol.column_max_area_mm2, tol.column_max_side_mm,
        include_generic_hatch=True,
    )
    if not outlines:
        return []

    # shear walls are routinely drawn on column layers and tagged on wall layers, so both tag roles apply
    tags: list[TagCand] = make_tag_cands(ctx.texts("COLUMN_TAG") + ctx.texts("WALL_TAG"))
    polys = [o.poly for o in outlines]
    shapes = [classify_polygon(p) for p in polys]

    def radius(i: int, tag: TagCand) -> float:
        # distance is measured to the outline, so the short side governs (a 250x2750 wall must not
        # collect tags of walls 2 m away)
        s = shapes[i]
        return max(tol.column_tag_radius_min_mm, tol.column_tag_radius_factor * min(s.width, s.depth), 0.5 * max(s.width, s.depth), 4 * tag.height)

    def size_matches(i: int, tag: TagCand) -> bool | None:
        """Does the size on this tag describe this column as drawn?"""
        w, d = tag.parsed.width_mm, tag.parsed.depth_mm
        if not (w and d):
            return None
        s_ = shapes[i]
        return _sizes_match((w, d), (s_.width, s_.depth), tol.size_mismatch_tol_mm)

    assigned, unassigned = associate_tags(polys, tags, radius, size_match_fn=size_matches)
    columns: list[Column] = []
    no_size_ids: list[str] = []
    for i, o in enumerate(outlines):
        s = shapes[i]
        cid = ctx.ids.next("C")
        my_tags = [tags[k] for k in assigned.get(i, [])]
        for t in my_tags:
            ctx.assigned_tag_handles.update(pr.handle for pr in t.prims)
        merged, sizes = merge_parsed(my_tags)

        drawn_w, drawn_d = round(s.width, 1), round(s.depth, 1)
        long_side, short_side = max(s.width, s.depth), min(s.width, s.depth)
        wall_like = is_wall_like(s.shape, s.width, s.depth, tol.wall_like_min_side_ratio, tol.wall_like_min_length_mm)
        width = depth = dia = None
        size_source = "unknown"
        if len(sizes) > 1:
            same_thickness = wall_like and len({min(w or 0, d or 0) for w, d, _ in sizes if w and d}) == 1
            if same_thickness:
                # legs of one wall tagged separately: keep the leg whose length matches the drawn one
                best = min((sz for sz in sizes if sz[0] and sz[1]), key=lambda sz: abs(max(sz[0], sz[1]) - long_side))
                merged.width_mm, merged.depth_mm = best[0], best[1]
                ctx.diag.info("COLUMN_MULTI_SIZE", f"Wall {cid} carries {len(sizes)} size tags of equal thickness {sizes}; leg matching the drawn length used", floor_id=ctx.floor_id, element_id=cid, location=s.center)
            else:
                ctx.diag.warning("COLUMN_MULTI_SIZE", f"Column {cid} has conflicting size tags: {sizes}", floor_id=ctx.floor_id, element_id=cid, location=s.center)
        if merged.diameter_mm is not None:
            dia, size_source = merged.diameter_mm, "tag"
        elif merged.width_mm is not None:
            width, depth, size_source = merged.width_mm, merged.depth_mm, "tag"
        else:
            sched = ctx.schedules.find(merged.mark, "column") or ctx.schedules.find(merged.mark, "wall") or ctx.schedules.find(merged.mark)
            if sched and isinstance(sched.get("width"), (int, float)) and isinstance(sched.get("depth"), (int, float)):
                width, depth, size_source = float(sched["width"]), float(sched["depth"]), "schedule"
            elif sched and isinstance(sched.get("diameter"), (int, float)):
                dia, size_source = float(sched["diameter"]), "schedule"
            elif merged.mark and len(ctx.schedules):
                ctx.note_missing_mark("column", merged.mark, cid)
            if size_source == "unknown" and o.block_size:
                width, depth, size_source = o.block_size[0], o.block_size[1], "block"
            elif size_source == "unknown" and ctx.layer_size(o.layer):
                width, depth = ctx.layer_size(o.layer)  # type: ignore[misc]
                size_source = "layer"

        if ctx.size_sources.column == "outline" and size_source in ("tag", "schedule", "block", "layer"):
            # answer 5: the drawing wins, and the tag is kept for the mark alone. The size the
            # client stated is still reported where it differs, so neither reading is lost.
            if s.shape == "circle":
                dia = round(s.diameter or 0, 1)
            else:
                width, depth = drawn_w, drawn_d
            size_source = "geometry"
        if size_source == "unknown":
            if s.shape == "circle":
                dia = round(s.diameter or 0, 1)
            else:
                width, depth = drawn_w, drawn_d
            size_source = "geometry"
            no_size_ids.append(cid)
        elif s.shape == "rect" and width is not None and depth is not None and not _sizes_match((width, depth), (drawn_w, drawn_d), tol.size_mismatch_tol_mm):
            code = "SCHEDULE_PLAN_MISMATCH" if size_source == "schedule" else "COLUMN_SIZE_MISMATCH"
            src = "schedule" if size_source == "schedule" else "tag"
            thickness_ok = abs(min(width, depth) - short_side) <= tol.size_mismatch_tol_mm
            if wall_like and thickness_ok:
                # wall legs are routinely drawn shorter/longer than scheduled (overlaps at corners): information only
                ctx.diag.info(code, f"Wall {cid} {src} says {width:.0f}x{depth:.0f}, drawn {drawn_w:.0f}x{drawn_d:.0f} (thickness matches, length differs)", floor_id=ctx.floor_id, element_id=cid, location=s.center)
            else:
                ctx.diag.warning(code, f"Column {cid} {src} says {width:.0f}x{depth:.0f} but drawn {drawn_w:.0f}x{drawn_d:.0f}", floor_id=ctx.floor_id, element_id=cid, location=s.center)
        elif s.shape == "circle" and dia is not None and s.diameter and abs(dia - s.diameter) > tol.size_mismatch_tol_mm:
            ctx.diag.warning("COLUMN_SIZE_MISMATCH", f"Column {cid} tagged dia {dia:.0f} but drawn dia {s.diameter:.0f}", floor_id=ctx.floor_id, element_id=cid, location=s.center)

        # rectangle drawn with a tag in the other orientation: align tag size to drawn axes
        if s.shape == "rect" and width is not None and depth is not None and size_source in ("tag", "schedule"):
            if abs(width - drawn_d) + abs(depth - drawn_w) < abs(width - drawn_w) + abs(depth - drawn_d):
                width, depth = depth, width

        if merged.category_hint not in (None, "column", "wall"):
            ctx.diag.info("TAG_CATEGORY_MISMATCH", f"Column {cid} tag '{merged.text}' looks like a {merged.category_hint} mark", floor_id=ctx.floor_id, element_id=cid, location=s.center)

        if wall_like:
            ctx.diag.info("COLUMN_WALL_LIKE", f"Column {cid} ({long_side:.0f}x{short_side:.0f}) looks like a shear wall", floor_id=ctx.floor_id, element_id=cid, location=s.center)
        if not wall_like and (short_side < 150 or long_side > 3000):
            ctx.diag.warning("COLUMN_ODD_SIZE", f"Column {cid} drawn size {drawn_w:.0f}x{drawn_d:.0f} is unusual", floor_id=ctx.floor_id, element_id=cid, location=s.center)

        columns.append(Column(
            id=cid, floor_id=ctx.floor_id, mark=merged.mark, shape=s.shape, center=pt(s.center),
            width_mm=width, depth_mm=depth, rotation_deg=round(s.rotation_deg, 3), diameter_mm=dia,
            outline=outline_points(o.poly), area_mm2=round(o.poly.area, 1),
            drawn_width_mm=drawn_w, drawn_depth_mm=drawn_d, size_source=size_source, wall_like=wall_like,
            modifier=ctx.modifier_for(o.layer), grid_ref=nearest_grid_intersection_label(s.center, ctx.grids_x, ctx.grids_y, tol.grid_ref_tol_mm),
            tags=[tag_ref(pr) for t in my_tags for pr in t.prims], source_layer=o.layer, source_kind=o.source_kind,
            source_handles=o.handles + o.merged_handles, confidence="high" if o.source_kind in ("polyline", "circle", "hatch") else "medium",
        ))

    # missing sizes: one element-level entry each, escalated to a floor-level warning when it is the norm
    if no_size_ids:
        widespread = len(no_size_ids) > 0.5 * len(columns)
        by_id = {c.id: c for c in columns}
        for cid in no_size_ids:
            c = by_id[cid]
            (ctx.diag.info if widespread else ctx.diag.warning)("COLUMN_NO_SIZE", f"Column {cid} has no size tag; drawn size {c.drawn_width_mm:.0f}x{c.drawn_depth_mm:.0f} used", floor_id=ctx.floor_id, element_id=cid, layer=c.source_layer, location=(c.center.x, c.center.y))
        if widespread:
            ctx.diag.warning("COLUMN_NO_SIZE", f"{len(no_size_ids)} of {len(columns)} columns on this floor have no size tag or schedule entry; drawn sizes used", floor_id=ctx.floor_id)
    return columns
