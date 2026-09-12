"""Beam extraction: pair parallel edge lines into centreline + width, then resolve sizes."""
from __future__ import annotations

import math

from ..geometry import PairedRect, Segment, classify_polygon, merge_collinear, pair_parallel
from ..schema import Beam
from .associate import TagCand, associate_tags, make_tag_cands, merge_parsed
from .context import FloorContext, outline_points, pt, tag_ref
from .outlines import _block_size


def _segments_from_prim(p) -> list[Segment]:
    coords = list(p.geom.exterior.coords) if p.geom.geom_type == "Polygon" else list(p.geom.coords)
    out = []
    for a, b in zip(coords[:-1], coords[1:]):
        s = Segment((a[0], a[1]), (b[0], b[1]), [p.handle], p.layer)
        if s.length > 1e-6:
            out.append(s)
    return out


def extract_beams(ctx: FloorContext) -> list[Beam]:
    tol = ctx.tol
    segs: list[Segment] = []
    direct: list[tuple[PairedRect, str, list[str], str, tuple | None]] = []   # rect, layer, handles, kind, block size
    for p in ctx.geoms("BEAM"):
        if p.kind == "line" or (p.kind == "polyline"):
            segs.extend(_segments_from_prim(p))
        elif p.kind in ("polygon", "solid"):
            s = classify_polygon(p.geom)
            short, long_ = min(s.width, s.depth), max(s.width, s.depth)
            if s.shape == "rect" and tol.beam_min_width_mm <= short <= tol.beam_max_width_mm and long_ >= tol.beam_min_length_mm and long_ / short >= 2:
                ang = s.rotation_deg if s.width >= s.depth else s.rotation_deg + 90
                ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                half = long_ / 2
                rect = PairedRect((s.center[0] - ux * half, s.center[1] - uy * half), (s.center[0] + ux * half, s.center[1] + uy * half), short, ang % 180, (Segment(s.center, s.center), Segment(s.center, s.center)), 0.0)
                direct.append((rect, p.layer, [p.handle], "polyline" if p.kind == "polygon" else "block", _block_size(p)))
            else:
                segs.extend(_segments_from_prim(p))

    merged = merge_collinear(segs, angle_tol=0.5, offset_tol=tol.beam_merge_offset_mm, gap_tol=tol.beam_merge_gap_mm)
    rects, unpaired = pair_parallel(merged, tol.beam_min_width_mm, tol.beam_max_width_mm, tol.beam_min_overlap_mm, tol.beam_angle_tol_deg)
    rects = [r for r in rects if r.length >= tol.beam_min_length_mm]

    items: list[tuple[PairedRect, str, list[str], str, tuple | None, int]] = []
    for r in rects:
        handles = sorted(set(r.edges[0].handles + r.edges[1].handles))
        items.append((r, r.edges[0].layer, handles, "paired_lines", None, r.edges[0].n_parts + r.edges[1].n_parts))
    for r, layer, handles, kind, bsize in direct:
        items.append((r, layer, handles, kind, bsize, 1))
    if not items:
        return []

    long_unpaired = [s for s in unpaired if s.length >= tol.beam_min_length_mm]
    if long_unpaired:
        by_layer: dict[str, list[Segment]] = {}
        for s in long_unpaired:
            by_layer.setdefault(s.layer, []).append(s)
        for layer, ss in by_layer.items():
            sample = [h for s in ss[:10] for h in s.handles[:1]]
            ctx.diag.warning("BEAM_UNPAIRED_LINES", f"{len(ss)} line(s) on layer {layer} longer than {tol.beam_min_length_mm:.0f} mm could not be paired into beams (sample handles: {', '.join(sample)})", floor_id=ctx.floor_id, layer=layer, location=ss[0].p1)

    polys = [it[0].outline() for it in items]
    angles = [it[0].angle_deg for it in items]
    tags: list[TagCand] = make_tag_cands(ctx.texts("BEAM_TAG"))

    def radius(i: int, tag: TagCand) -> float:
        return max(1.5 * items[i][0].width, tol.beam_tag_buffer_factor * tag.height)

    assigned, unassigned = associate_tags(polys, tags, radius, angles=angles)

    beams: list[Beam] = []
    for i, (r, layer, handles, kind, bsize, n_parts) in enumerate(items):
        bid = ctx.ids.next("B")
        my_tags = [tags[k] for k in assigned.get(i, [])]
        for t in my_tags:
            ctx.assigned_tag_handles.update(pr.handle for pr in t.prims)
        merged_tag, sizes = merge_parsed(my_tags)
        drawn_w = round(r.width, 1)
        width = depth = depth_alt = None
        size_source = depth_source = "unknown"

        if len(sizes) > 1:
            ctx.diag.warning("BEAM_MULTI_SIZE", f"Beam {bid} has conflicting size tags along its length: {sizes}; first one used (split the beam at supports in the next step)", floor_id=ctx.floor_id, element_id=bid, location=r.start)
        if merged_tag.width_mm is not None:
            width, depth, depth_alt = merged_tag.width_mm, merged_tag.depth_mm, merged_tag.depth_alt_mm
            size_source = depth_source = "tag"
        else:
            sched = ctx.schedules.find(merged_tag.mark, "beam") or ctx.schedules.find(merged_tag.mark)
            if sched and isinstance(sched.get("width"), (int, float)) and isinstance(sched.get("depth"), (int, float)):
                width, depth = float(sched["width"]), float(sched["depth"])
                size_source = depth_source = "schedule"
            elif merged_tag.mark and len(ctx.schedules):
                ctx.note_missing_mark("beam", merged_tag.mark, bid)
            if size_source == "unknown":
                lsize = ctx.layer_size(layer)
                if lsize:
                    width, depth, size_source, depth_source = lsize[0], lsize[1], "layer", "layer"
                elif bsize:
                    width, depth, size_source, depth_source = bsize[0], bsize[1], "block", "block"

        if width is None:
            width, size_source = drawn_w, "geometry"
        elif abs(width - drawn_w) > tol.size_mismatch_tol_mm:
            code = "SCHEDULE_PLAN_MISMATCH" if size_source == "schedule" else "BEAM_WIDTH_MISMATCH"
            ctx.diag.warning(code, f"Beam {bid} {'schedule' if size_source == 'schedule' else 'tag'} says width {width:.0f} but drawn width {drawn_w:.0f}", floor_id=ctx.floor_id, element_id=bid, location=r.start)
        if depth is None:
            if ctx.frame.default_beam_depth:
                depth, depth_source = ctx.frame.default_beam_depth, "default"
                ctx.diag.info("BEAM_DEFAULT_DEPTH", f"Beam {bid} depth {depth:.0f} taken from general note", floor_id=ctx.floor_id, element_id=bid, location=r.start)
            elif merged_tag.mark:
                # root cause is the schedule (reported once per mark); keep the element entry as info
                ctx.diag.info("BEAM_NO_DEPTH", f"Beam {bid} mark '{merged_tag.mark}' has no depth because the mark is not in a schedule", floor_id=ctx.floor_id, element_id=bid, layer=layer, location=r.start)
            else:
                ctx.diag.warning("BEAM_NO_DEPTH", f"Beam {bid} ({r.length:.0f} long, {drawn_w:.0f} wide) has no tag, schedule, layer size or note default", floor_id=ctx.floor_id, element_id=bid, layer=layer, location=r.start)

        if merged_tag.category_hint not in (None, "beam"):
            ctx.diag.info("TAG_CATEGORY_MISMATCH", f"Beam {bid} tag '{merged_tag.text}' looks like a {merged_tag.category_hint} mark", floor_id=ctx.floor_id, element_id=bid, location=r.start)

        beams.append(Beam(
            id=bid, floor_id=ctx.floor_id, mark=merged_tag.mark, start=pt(r.start), end=pt(r.end), length_mm=round(r.length, 1),
            width_mm=width, depth_mm=depth, depth_alt_mm=depth_alt, drawn_width_mm=drawn_w, angle_deg=round(r.angle_deg, 3),
            inverted=merged_tag.inverted, sunk_mm=merged_tag.sunk_mm, outline=outline_points(polys[i]),
            size_source=size_source, depth_source=depth_source, tags=[tag_ref(pr) for t in my_tags for pr in t.prims],
            source_layer=layer, source_kind=kind, source_handles=handles, n_edge_parts=n_parts,
            confidence="high" if kind != "paired_lines" or n_parts <= 4 else "medium",
        ))
    return beams
