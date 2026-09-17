"""Normalisation pipeline: extraction Project -> NormalizedProject."""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from ..diagnostics import DiagnosticsCollector
from ..geometry import classify_polygon, rectangle_polygon
from ..schema import Point2, Project
from .geometry import (Support, box_centre, fit_arcs, fit_text_height, lattice_panels, poly_from_points,
                       representative_point, ring_points, text_fits)
from ..tags import parse_depth, parse_tag
from .model import (MarkMap, NBeam, NColumn, NFloor, NFold, NFooting, NGrid, NJoint, NLevel, NOpening, NPanel, NPile, NStair, NWall, NormalizedProject)
from .naming import normalise_floor_name, split_mark_size, title_from_level_name
from .spans import runs_for_floor, split_runs
from .spec import TemplateSpec
from .stacks import build_stacks


def _pt(p) -> Point2:
    return Point2(x=round(p[0], 2), y=round(p[1], 2))


def _pts(ring) -> list[Point2]:
    return [Point2(x=x, y=y) for x, y in ring]


def _fmt(fmt: str, **kw) -> str:
    class _Safe(dict):
        def __missing__(self, k):
            return "?"
    try:
        return fmt.format_map(_Safe(**kw))
    except (ValueError, TypeError):
        return fmt


def parse_pcc_safe(text: str):
    from ..tags import parse_pcc
    try:
        return parse_pcc(text or "")
    except Exception:
        return None


def _tagged_size(c) -> tuple[float, float] | None:
    """Size in the order the client's tag states it, else (short, long) from the resolved size."""
    from ..tags import parse_tag
    for t in c.tags:
        pt = parse_tag(t.text)
        if pt.width_mm and pt.depth_mm:
            return (pt.width_mm, pt.depth_mm)
    if c.width_mm and c.depth_mm:
        if c.size_source == "schedule":
            return (c.width_mm, c.depth_mm)
        return (min(c.width_mm, c.depth_mm), max(c.width_mm, c.depth_mm))
    return None


class LevelRow:
    def __init__(self, floor_id, name, order, elevation, f2f, revit_name):
        self.floor_id, self.name, self.order, self.elevation, self.f2f, self.revit_name = floor_id, name, order, elevation, f2f, revit_name


def normalize(project: Project, spec: TemplateSpec, levels: list[LevelRow] | None = None, source_file: str = "", level_reference: str | None = None) -> NormalizedProject:
    diag = DiagnosticsCollector()
    np_ = NormalizedProject(source_file=source_file or project.drawing.file, source_schema_version=project.schema_version, spec_name=spec.name,
                            level_reference=(level_reference or spec.level_reference).upper())

    floors_sorted = sorted(project.floors, key=lambda f: f.index)
    floor_ids = [f.id for f in floors_sorted]

    # ---- levels -------------------------------------------------------------
    level_rows = levels or []
    plan_levels: dict[str, list[str]] = {fid: [] for fid in floor_ids}
    if level_rows:
        rows = sorted(level_rows, key=lambda r: (r.elevation if r.elevation is not None else 0.0, r.order or 0))
        # derive missing elevations from floor-to-floor heights where possible
        elev = None
        for r in rows:
            if r.elevation is None and elev is not None and r.f2f is not None:
                r.elevation = elev + r.f2f
            if r.elevation is not None:
                elev = r.elevation
        rows = [r for r in rows if r.elevation is not None]
        rows.sort(key=lambda r: r.elevation)
        for i, r in enumerate(rows):
            nxt = rows[i + 1].elevation - r.elevation if i + 1 < len(rows) else None
            base = r.revit_name or r.name or (next((f.name for f in floors_sorted if f.id == r.floor_id), "") if r.floor_id else "")
            name = _fmt(spec.marks.level, n=i, name=normalise_floor_name(base) if base else f"LEVEL {i}")
            lid = f"LV{i:02d}"
            np_.levels.append(NLevel(id=lid, index=i, name=name, elevation_mm=float(r.elevation), floor_to_floor_mm=nxt, plan_floor_id=r.floor_id, revit_level_name=r.revit_name))
            if r.floor_id in plan_levels:
                plan_levels[r.floor_id].append(lid)
            elif r.floor_id:
                diag.warning("LEVEL_ROW_UNMATCHED", f"Level row '{r.name or r.floor_id}' references unknown plan floor '{r.floor_id}'")
    else:
        diag.warning("LEVELS_MISSING", "No level elevations supplied (levels.xlsx); the elevation frame is not drawn and floors have no elevation")

    # ---- floors and frames --------------------------------------------------
    fr = spec.frame
    for f in floors_sorted:
        if f.boundary and fr.keep_client_frames:
            xs = [p.x for p in f.boundary]
            ys = [p.y for p in f.boundary]
            left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
        else:
            pts = [(c.center.x + f.origin.x, c.center.y + f.origin.y) for c in project.columns if c.floor_id == f.id]
            pts += [(b.start.x + f.origin.x, b.start.y + f.origin.y) for b in project.beams if b.floor_id == f.id]
            pts += [(b.end.x + f.origin.x, b.end.y + f.origin.y) for b in project.beams if b.floor_id == f.id]
            pts += [(x.center.x + f.origin.x, x.center.y + f.origin.y) for x in project.footings if x.floor_id == f.id]
            if not pts:
                pts = [(f.origin.x, f.origin.y)]
            left, right = min(p[0] for p in pts) - fr.margin_mm, max(p[0] for p in pts) + fr.margin_mm
            bottom, top = min(p[1] for p in pts) - fr.margin_mm, max(p[1] for p in pts) + fr.margin_mm
        plan_bottom = bottom
        frame_bottom = bottom - fr.bottom_band_mm
        level_name = normalise_floor_name(f.name)
        if plan_levels.get(f.id):
            first = next(l for l in np_.levels if l.id == plan_levels[f.id][0])
            level_name = first.name.split(" ", 1)[1] if " " in first.name else first.name
        title = _fmt(spec.marks.plan_title, name=title_from_level_name(level_name))
        if level_name != f.name.strip().upper():
            diag.info("NAME_NORMALISED", f"Floor '{f.name}' written as '{level_name}'", floor_id=f.id)
        elevation = next((l.elevation_mm for l in np_.levels if l.id in plan_levels.get(f.id, [])), None)
        np_.floors.append(NFloor(id=f.id, index=f.index, name=level_name, title=title, source_name=f.name, origin=f.origin,
                                 frame=[_pt((left, frame_bottom)), _pt((right, frame_bottom)), _pt((right, top)), _pt((left, top))],
                                 plan_bottom_y=plan_bottom, elevation_mm=elevation, levels=plan_levels.get(f.id, []),
                                 default_beam_depth_mm=f.default_beam_depth_mm, default_slab_thickness_mm=f.default_slab_thickness_mm,
                                 notes=list(f.notes) if spec.client_notes else []))

    # ---- column stacks ------------------------------------------------------
    stacks, col_to_stack = build_stacks(project, floor_ids, spec.numbering.columns, spec.stack_match_tol_mm, spec.stack_match_min_iou, diag)
    np_.stacks = stacks
    stack_by_id = {s.id: s for s in stacks}
    # answer 2C / 20C: a client mark wins; generated numbers fill the gaps left by the client's numbering
    if spec.numbering.keep_client_marks:
        used: set[int] = set()
        for st in stacks:
            if st.client_marks:
                m = re.match(r"^C(\d+)$", st.client_marks[0].upper())
                if m:
                    used.add(int(m.group(1)))
        nxt, nxt_stub = 1, 1
        for st in stacks:
            if st.client_marks:
                st.mark_base = st.client_marks[0]
                continue
            if st.kind == "stub":
                # an untagged stub column is SC{n}, sized from its own outline ("ST" belongs to stairs)
                st.mark_base = f"{spec.numbering.stub_prefix}{nxt_stub}"
                nxt_stub += 1
                continue
            while nxt in used:
                nxt += 1
            st.number = nxt
            st.mark_base = f"C{nxt}"
            used.add(nxt)
            nxt += 1
    col_ids_by_floor: dict[str, dict[str, str]] = {}
    text = spec.text
    for f in floors_sorted:
        fidx = floor_ids.index(f.id)
        for c in sorted((c for c in project.columns if c.floor_id == f.id), key=lambda c: (stack_by_id[col_to_stack[c.id]].number, stack_by_id[col_to_stack[c.id]].mark_base)):
            stack = stack_by_id[col_to_stack[c.id]]
            n = stack.number
            base = stack.mark_base
            outline = poly_from_points(c.outline)
            if outline is None:
                continue
            if c.shape == "circle":
                dia = c.diameter_mm or c.drawn_width_mm or 0
                mark = _fmt(spec.marks.column_circle.replace("C{n}", "{base}"), base=base, n=n, dia=dia)
            else:
                # the mark quotes the size as the client tagged it (b x D), not as the rectangle happens to lie in plan;
                # without a tag the shorter side comes first
                w, d = _tagged_size(c) or ((c.width_mm or c.drawn_width_mm or 0), (c.depth_mm or c.drawn_depth_mm or 0))
                mark = _fmt(spec.marks.column.replace("C{n}", "{base}"), base=base, n=n, w=w, d=d)
            # rotation: text along the longer side (answer 7)
            rot = 0.0
            if spec.placement.column_mark_rotate == "long-side" and c.shape != "circle":
                minx, miny, maxx, maxy = outline.bounds
                long_is_y = (c.depth_mm or (maxy - miny)) > (c.width_mm or (maxx - minx)) if c.shape == "rect" else (maxy - miny) > (maxx - minx)
                rot = (c.rotation_deg + (90.0 if long_is_y else 0.0)) if c.shape == "rect" else (90.0 if long_is_y else 0.0)
                rot = ((rot + 90.0) % 180.0) - 90.0
                if rot <= -90.0:
                    rot += 180.0
            place = spec.placement.column_mark
            minx, miny, maxx, maxy = outline.bounds
            centre = box_centre(outline)
            # answer 7: the mark sits on the bounding-box centre, and shrinks to stay inside its
            # member rather than overflowing onto the beams alongside. A smaller mark that reads
            # is worth more than a full-height one lying across its neighbours.
            ladder = text.mark_heights or [text.mark_height]
            base_txt, size_txt = split_mark_size(mark)
            drawn, lines = mark, []
            if spec.placement.column_mark_fit == "fixed":
                height = max(ladder)
            else:
                height = fit_text_height(mark, ladder, text.width_factor, outline, rot, centre)
                if size_txt and not text_fits(mark, height, text.width_factor, outline, rot, centre):
                    # a 17-character mark will not go inside a 500 mm wall leg at any height a
                    # drafter can read. The base alone does, as it does on a short beam span; the
                    # size stays in the schedule and in the XDATA utility 4 reads back.
                    h2 = fit_text_height(base_txt, ladder, text.width_factor, outline, rot, centre)
                    if text_fits(base_txt, h2, text.width_factor, outline, rot, centre):
                        drawn, lines, height = base_txt, [base_txt], h2
            fits = text_fits(drawn, height, text.width_factor, outline, rot, centre)
            if c.wall_like and spec.placement.wall_mark == "beside" and size_txt:
                lines = [base_txt, size_txt]
                gap = spec.placement.wall_mark_gap_mm + text.mark_height
                if (maxy - miny) >= (maxx - minx):        # wall up the page: mark to its right
                    mp = (maxx + gap, (miny + maxy) / 2)
                else:                                      # wall across the page: mark above it
                    mp = ((minx + maxx) / 2, maxy + gap)
                rot, height = 0.0, max(ladder)
            elif place == "centre" or (place == "auto" and fits):
                mp = centre
                if not fits:
                    diag.info("MARK_FIT", f"Mark '{drawn}' does not fit inside column {c.id} even at {height:.0f} mm text; placed at its centre anyway", floor_id=f.id, element_id=c.id, location=mp)
            else:
                mp = ((minx + maxx) / 2, maxy + spec.placement.column_mark_gap_mm)
                rot = 0.0
                if place == "auto":
                    diag.info("MARK_FIT", f"Mark '{mark}' does not fit inside column {c.id}; placed above", floor_id=f.id, element_id=c.id, location=mp)
            above = floor_ids[fidx + 1] if fidx + 1 < len(floor_ids) else None
            below = floor_ids[fidx - 1] if fidx > 0 else None
            stops = above is not None and above not in stack.floors
            starts = below is not None and below not in stack.floors
            cid = f"{f.id}-C{len(col_ids_by_floor.get(f.id, {})) + 1:03d}"
            col_ids_by_floor.setdefault(f.id, {})[c.id] = cid
            stack.column_ids[f.id] = cid
            np_.columns.append(NColumn(id=cid, floor_id=f.id, stack_id=stack.id, mark=mark, mark_lines=lines or [mark], shape=c.shape, center=c.center,
                                       width_mm=c.width_mm, depth_mm=c.depth_mm, rotation_deg=c.rotation_deg, diameter_mm=c.diameter_mm,
                                       outline=_pts(ring_points(outline)), stops_here=stops, starts_here=starts, wall_like=c.wall_like,
                                       size_source=c.size_source, mark_position=_pt(mp), mark_rotation_deg=round(rot, 3), mark_height_mm=round(height, 2), client_mark=c.mark,
                                       source_ids=[c.id], source_handles=c.source_handles))
            np_.mark_map.append(MarkMap(element_id=cid, floor_id=f.id, kind="column", mark=mark, client_mark=c.mark, client_tags=c.tags))

    # ---- walls: RCC walls only are modelled (answer 6B); non-structural walls are kept as records -------------
    for w in project.walls:
        outline = poly_from_points(w.outline)
        if outline is None:
            continue
        np_.walls.append(NWall(id=f"{w.floor_id}-W{len([x for x in np_.walls if x.floor_id == w.floor_id]) + 1:03d}", floor_id=w.floor_id, mark=w.mark,
                               outline=_pts(ring_points(outline)), center=w.center, thickness_mm=w.thickness_mm, length_mm=w.length_mm,
                               structural=w.structural, source_id=w.id))

    # ---- beams: split into spans -------------------------------------------
    for f in floors_sorted:
        runs = runs_for_floor(project, f.id)
        supports: list[Support] = []
        col_lookup = {c.id: c for c in np_.columns if c.floor_id == f.id}
        for c in col_lookup.values():
            poly = poly_from_points(c.outline)
            if poly is not None and (spec.split.at_columns or (c.wall_like and spec.split.at_walls)):
                supports.append(Support(c.stack_id, poly, c.shape, c.rotation_deg))
        if spec.split.at_walls:
            for w in np_.walls:
                if w.floor_id == f.id:
                    poly = poly_from_points(w.outline)
                    if poly is not None:
                        supports.append(Support(w.id, poly, "polygon", 0.0))
        spans = split_runs(runs, supports, spec, diag, f.id)
        # numbering: horizontal runs first (by y descending), then vertical (by x ascending), along the run
        def span_key(s):
            r = s["run"]
            horizontal = abs(r.axis.angle) < 45 or abs(r.axis.angle - 180) < 45
            off = -r.axis.start[1] if horizontal else r.axis.start[0]
            return (0 if horizontal else 1, round(off / 50.0), round(r.axis.t_of(r.axis.start) / 50.0), s["t1"])
        spans.sort(key=span_key)
        used_b: set[int] = set()
        if spec.numbering.keep_client_beam_marks:
            for sp in spans:
                m = re.match(r"^B(\d+)$", (sp["run"].payload.mark or "").upper())
                if m:
                    used_b.add(int(m.group(1)))
        nxt_b = 1
        for i, s in enumerate(spans, start=1):
            r = s["run"]
            b = r.payload
            w = r.width
            d = r.depth
            if spec.numbering.keep_client_beam_marks and b.mark:
                base = b.mark
            else:
                while nxt_b in used_b:
                    nxt_b += 1
                base = f"B{nxt_b}"
                used_b.add(nxt_b)
                nxt_b += 1
            free_end = s["support_start"] is None or s["support_end"] is None
            tip = b.depth_alt_mm if (free_end and b.depth_alt_mm and d) else None
            if tip:
                mark = _fmt(spec.marks.beam_taper, base=base, n=i, w=w, d=d, tip=tip)      # answer 2A: depth at support / tip
            else:
                fmt = (spec.marks.beam if d else spec.marks.beam_no_depth).replace("B{n}", "{base}")
                mark = _fmt(fmt, base=base, n=i, w=w, d=d)
            if b.inverted:
                mark += spec.marks.beam_inverted_suffix
            if b.depth_alt_mm and not free_end and d:
                diag.info("BEAM_ALT_DEPTH", f"Beam {mark} carries a second depth {b.depth_alt_mm:.0f} but has no free end; treated as a note", floor_id=f.id, element_id=f"{f.id}-B{i:03d}")
            outline = s["outline"]
            p1, p2 = r.axis.point_at(s["t1"]), r.axis.point_at(s["t2"])
            mp = representative_point(outline)
            rot = 0.0
            if spec.placement.beam_mark_rotate:
                rot = r.axis.angle if r.axis.angle <= 90 else r.axis.angle - 180
            bid = f"{f.id}-B{i:03d}"
            if s["support_start"] is None or s["support_end"] is None:
                diag.info("SPAN_FREE_END", f"Beam {mark} ({bid}) has a free end", floor_id=f.id, element_id=bid, location=p1 if s["support_start"] is None else p2)
            np_.beams.append(NBeam(id=bid, floor_id=f.id, run_id=r.id, span_index=i, mark=mark, start=_pt(p1), end=_pt(p2), length_mm=round(s["t2"] - s["t1"], 1),
                                   width_mm=w, depth_mm=d, depth_alt_mm=b.depth_alt_mm, depth_tip_mm=tip, cantilever=free_end, angle_deg=round(r.axis.angle, 3), outline=_pts(ring_points(outline)),
                                   inverted=b.inverted, support_start=s["support_start"], support_end=s["support_end"], size_source=b.size_source,
                                   depth_source=b.depth_source, mark_position=_pt(mp), mark_rotation_deg=rot, client_mark=b.mark, source_handles=b.source_handles))
            np_.mark_map.append(MarkMap(element_id=bid, floor_id=f.id, kind="beam", mark=mark, client_mark=b.mark, client_tags=b.tags))

    # ---- openings -----------------------------------------------------------
    for o in project.openings:
        outline = poly_from_points(o.outline)
        if outline is None:
            continue
        n = len([x for x in np_.openings if x.floor_id == o.floor_id]) + 1
        np_.openings.append(NOpening(id=f"{o.floor_id}-O{n:03d}", floor_id=o.floor_id, label=o.label, outline=_pts(ring_points(outline)), center=o.center, source_id=o.id))

    # ---- stairs (as drawn) ----------------------------------------------------
    for st in project.stairs:
        outline = poly_from_points(st.outline) if st.outline else None
        n = len([x for x in np_.stairs if x.floor_id == st.floor_id and x.outline]) + 1
        waist = None
        mark = None
        if st.label:
            from ..tags import parse_tag as _parse_tag
            pt_ = _parse_tag(st.label)
            waist = pt_.thickness_mm
            base = pt_.mark or f"ST{n}"
            mark = _fmt(spec.marks.stair.replace("ST{n}", "{base}"), base=base, n=n, thk=waist) if waist else base
        direction = next(("DN" if l.upper().startswith(("DN", "DOWN")) else "UP") for l in st.labels if l.upper().startswith(("DN", "DOWN", "UP"))) if any(l.upper().startswith(("DN", "DOWN", "UP")) for l in st.labels) else None
        treads = risers = None
        landing = None
        estimated = False
        if spec.stair_estimate and outline is not None:
            # tread lines: the client's stair lines lying inside this outline, parallel to each other (answer 5A)
            inside_lines = []
            for other in project.stairs:
                if other.floor_id != st.floor_id or not other.lines:
                    continue
                for a, b in other.lines:
                    seg = LineString([(a.x, a.y), (b.x, b.y)])
                    if outline.buffer(5.0).contains(seg) and seg.length >= 300.0:
                        inside_lines.append(seg)
            if inside_lines:
                angs = Counter(round(math.degrees(math.atan2(l.coords[1][1] - l.coords[0][1], l.coords[1][0] - l.coords[0][0])) % 180.0 / 5.0) * 5 for l in inside_lines)
                treads = angs.most_common(1)[0][1]
                risers = treads + 1
                estimated = True
            fl = next((q for q in np_.floors if q.id == st.floor_id), None)
            lv = next((l for l in np_.levels if l.id in (fl.levels if fl else [])), None)
            if lv and lv.floor_to_floor_mm:
                landing = round(lv.floor_to_floor_mm / 2.0, 1)       # answer 5B
                estimated = True
        if estimated:
            diag.info("STAIR_ESTIMATED", f"Stair {mark or st.id}: {treads or '?'} treads counted, landing assumed at half the floor height; verify against a section", floor_id=st.floor_id, location=(st.center.x, st.center.y))
        np_.stairs.append(NStair(id=f"{st.floor_id}-ST{len([x for x in np_.stairs if x.floor_id == st.floor_id]) + 1:03d}", floor_id=st.floor_id, mark=mark, waist_mm=waist,
                                 direction=direction, tread_count=treads, riser_count_est=risers, landing_level_est_mm=landing, estimated=estimated,
                                 outline=_pts(ring_points(outline)) if outline else [], lines=st.lines, center=st.center, source_id=st.id))

    # ---- joints (as drawn) ----------------------------------------------------
    for j in project.joints:
        n = len([x for x in np_.joints if x.floor_id == j.floor_id]) + 1
        np_.joints.append(NJoint(id=f"{j.floor_id}-J{n:03d}", floor_id=j.floor_id, start=j.start, end=j.end, source_id=j.id))

    # ---- slab panels --------------------------------------------------------
    for f in floors_sorted:
        beams_f = [b for b in np_.beams if b.floor_id == f.id]
        cols_f = [c for c in np_.columns if c.floor_id == f.id]
        walls_f = [w for w in np_.walls if w.floor_id == f.id]
        if not beams_f:
            continue
        ext = spec.panels.span_extend_mm
        polys = []
        beam_polys: list[tuple[NBeam, Polygon]] = []
        for b in beams_f:
            ang = math.radians(b.angle_deg)
            ux, uy = math.cos(ang), math.sin(ang)
            cx, cy = (b.start.x + b.end.x) / 2, (b.start.y + b.end.y) / 2
            bp = rectangle_polygon((cx, cy), b.length_mm + 2 * ext, b.width_mm, b.angle_deg)
            polys.append(bp)
            beam_polys.append((b, bp))
        polys += [poly_from_points(c.outline) for c in cols_f] + [poly_from_points(w.outline) for w in walls_f]
        polys = [p for p in polys if p is not None]
        # client slab edge lines close cantilever / chajja / balcony panels (answer 3B)
        edge_geom = None
        structure_union = None
        if spec.panels.use_slab_edges:
            edges = [LineString([(e.start.x, e.start.y), (e.end.x, e.end.y)]) for e in project.slab_edges if e.floor_id == f.id]
            if edges:
                from shapely.ops import unary_union as _uu
                edge_geom = _uu(edges)
                structure_union = _uu([q for q in polys if q is not None]).buffer(6.0)
                polys.append(edge_geom.buffer(1.0, cap_style=2))
        panels, oversized = lattice_panels(polys, spec.panels.min_area_m2 * 1e6, spec.panels.max_area_m2 * 1e6)
        regions_f = [(r, poly_from_points(r.outline)) for r in project.regions if r.floor_id == f.id]
        regions_f = [(r, rp) for r, rp in regions_f if rp is not None]

        def region_cover(poly, meaning):
            tot = 0.0
            val = None
            for r, rp in regions_f:
                if r.meaning == meaning and rp.intersects(poly):
                    a = rp.intersection(poly).area
                    if a > 0:
                        tot += a
                        val = r.value_mm if val is None else val
            return tot / poly.area, val

        def adjacent_beams(poly):
            ring = poly.exterior.buffer(5.0)
            return [b for b, bp in beam_polys if bp.intersects(ring)]
        if not panels:
            diag.warning("PANEL_NO_LATTICE", "Beams exist but form no closed panels; check for missing beams or wrong widths", floor_id=f.id)
            continue
        tags = [s for s in project.slabs if s.floor_id == f.id and s.source_kind == "tag"]
        tag_pts = [Point(s.position.x, s.position.y) for s in tags]
        openings_f = [(o, poly_from_points(o.outline)) for o in np_.openings if o.floor_id == f.id]
        stairs_f = [poly_from_points(st.outline) for st in np_.stairs if st.floor_id == f.id and st.outline]
        stairs_f = [x for x in stairs_f if x is not None]
        circles: list[tuple[tuple[float, float], float]] = []
        if spec.panels.keep_arcs:
            for c in cols_f:
                if c.shape == "circle":
                    cp = poly_from_points(c.outline)
                    if cp is not None:
                        minx, miny, maxx, maxy = cp.bounds
                        circles.append(((cp.centroid.x, cp.centroid.y), ((maxx - minx) + (maxy - miny)) / 4.0))
        used_tags: set[str] = set()
        n_slab = 0
        n_cs = 0
        # numbering: top-left to bottom-right by panel representative point
        panels.sort(key=lambda p: (-round(p.bounds[3] / 500.0), p.bounds[0]))
        for poly in panels:
            # lattice holes that are really cut-outs or stairs (answer 9C: no slab where the whole area is a cut-out)
            open_cover = sum(poly.intersection(op).area for _, op in openings_f if op is not None and op.intersects(poly)) / poly.area
            open_cover = max(open_cover, region_cover(poly, "cutout")[0])
            stair_cover = sum(poly.intersection(sp).area for sp in stairs_f if sp.intersects(poly)) / poly.area
            if open_cover >= spec.opening_panel_cover:
                pid = f"{f.id}-X{len([x for x in np_.panels if x.floor_id == f.id and x.kind != 'slab']) + 1:03d}"
                c = poly.centroid
                np_.panels.append(NPanel(id=pid, floor_id=f.id, kind="opening", mark="", outline=_pts(ring_points(poly)), area_m2=round(poly.area / 1e6, 3),
                                         centroid=_pt((c.x, c.y)), mark_position=_pt((c.x, c.y)), opening_ids=[o.id for o, op in openings_f if op is not None and op.intersects(poly)]))
                continue
            if stair_cover >= spec.stair_panel_cover:
                pid = f"{f.id}-X{len([x for x in np_.panels if x.floor_id == f.id and x.kind != 'slab']) + 1:03d}"
                c = poly.centroid
                np_.panels.append(NPanel(id=pid, floor_id=f.id, kind="stair", mark="", outline=_pts(ring_points(poly)), area_m2=round(poly.area / 1e6, 3),
                                         centroid=_pt((c.x, c.y)), mark_position=_pt((c.x, c.y))))
                continue
            # cantilever / chajja: a hole whose boundary runs along a client slab edge, not a beam
            is_cant = False
            if edge_geom is not None and edge_geom.intersects(poly.exterior.buffer(3.0)):
                # free edge = the part of the panel boundary on a client slab edge that is not also a beam / column / wall face
                on_edge = edge_geom.intersection(poly.exterior.buffer(3.0))
                free_edge = on_edge.difference(structure_union) if structure_union is not None else on_edge
                is_cant = free_edge.length >= max(300.0, 0.1 * poly.exterior.length)
            if is_cant:
                n_cs += 1
                i = n_cs
            else:
                n_slab += 1
                i = n_slab
            pid = f"{f.id}-{'CS' if is_cant else 'S'}{i:03d}"
            inside = [s for s, pt in zip(tags, tag_pts) if poly.contains(pt)]
            used_tags.update(s.id for s in inside)
            thicknesses = [s.thickness_mm for s in inside if s.thickness_mm is not None]
            thickness, source = None, "unknown"
            if thicknesses:
                common = Counter(thicknesses).most_common()
                thickness = common[0][0]
                source = inside[0].thickness_source if len(common) == 1 else "tag"
                if len(common) > 1:
                    diag.warning("PANEL_MULTI_TAG", f"Panel {pid} contains tags with different thicknesses {sorted(set(thicknesses))}; {thickness:.0f} used", floor_id=f.id, element_id=pid, location=representative_point(poly))
            elif f.default_slab_thickness_mm:
                thickness, source = f.default_slab_thickness_mm, "default"
            else:
                diag.warning("PANEL_NO_TAG", f"Panel {pid} ({poly.area / 1e6:.1f} m2) has no thickness tag inside it", floor_id=f.id, element_id=pid, location=representative_point(poly))
            sunk = next((s.sunk_mm for s in inside if s.sunk_mm), None)
            sunk_source = "tag" if sunk else None
            sunk_rings: list[list] = []
            if sunk is None:
                cover, val = region_cover(poly, "sunk")
                if cover >= spec.panels.region_cover and val:
                    sunk, sunk_source = val, "legend"
                else:
                    # A sunk area far smaller than its panel is a pocket in it -- a 250 mm sunk
                    # box covering under a hundredth of the bay it sits in. Sinking the whole bay
                    # for it would be wrong, so the pocket keeps its own outline; without this it
                    # was simply dropped and the client's hatch went missing from the plan.
                    pockets = [(r, rp) for r, rp in regions_f
                               if r.meaning == "sunk" and r.value_mm
                               and rp.intersection(poly).area >= spec.panels.pocket_inside * rp.area]
                    if pockets:
                        by_depth: dict[float, list] = {}
                        for r, rp in pockets:
                            by_depth.setdefault(float(r.value_mm), []).append(rp)
                        depth = max(by_depth, key=lambda d: sum(x.area for x in by_depth[d]))
                        if len(by_depth) > 1:
                            diag.info("PANEL_MULTI_SUNK", f"Panel {pid} holds sunk pockets of {sorted(by_depth)} mm; {depth:.0f} mm drawn", floor_id=f.id, element_id=pid, location=representative_point(poly))
                        clipped = [rp.intersection(poly) for rp in by_depth[depth]]
                        sunk_rings = [_pts(ring_points(c)) for c in clipped if c.geom_type == "Polygon" and not c.is_empty]
                        if sunk_rings:
                            sunk, sunk_source = depth, "legend"
            op_ids = []
            holes: list[list] = []
            out_poly = poly
            for o, opoly in openings_f:
                if opoly is not None and poly.contains(opoly.centroid):
                    op_ids.append(o.id)
                    o.panel_id = pid
                    if spec.panels.subtract_openings and opoly.intersects(poly.exterior):
                        cut = out_poly.difference(opoly)
                        if cut.geom_type == "Polygon" and not cut.is_empty:
                            out_poly = cut
                    elif spec.panels.subtract_openings:
                        holes.append(_pts(ring_points(opoly)))     # inner loop of the slab sketch (answer 9C)
            if poly in oversized:
                diag.warning("PANEL_LARGE", f"Panel {pid} is {poly.area / 1e6:.0f} m2; a beam may be missing", floor_id=f.id, element_id=pid, location=representative_point(poly))
            # ramps: a ramp note inside the hole (answer 18B); slope and direction from the note and its arrow
            ramp = next((h for h in project.ramp_hints if h.floor_id == f.id and poly.contains(Point(h.position.x, h.position.y))), None)
            if ramp is not None:
                mark = _fmt(spec.marks.ramp if thickness is not None else spec.marks.ramp_no_thickness, n=i, thk=thickness, slope=ramp.slope_ratio or "1:?")
            elif is_cant:
                mark = _fmt(spec.marks.slab_cantilever, n=i, thk=thickness) if thickness is not None else _fmt(spec.marks.slab_no_thickness.replace("S{n}", "CS{n}"), n=i)
            else:
                mark = _fmt(spec.marks.slab, n=i, thk=thickness) if thickness is not None else _fmt(spec.marks.slab_no_thickness, n=i)
            # level rule (answers 4 / 14A / 20A): slab top at SSL; cantilever slabs and "slab at beam bottom" panels sit
            # with their bottom flush with the deepest adjacent beam; sunk panels drop by the sunk depth
            adj = [b for b in adjacent_beams(poly) if b.depth_mm]
            support_depth = (min if spec.panels.cantilever_support == "min" else max)(b.depth_mm for b in adj) if adj else None
            if is_cant and thickness is None:
                # answer 1A/1B: neighbouring slab thickness, else the firm default
                neigh = [q.thickness_mm for q in np_.panels if q.floor_id == f.id and q.kind == "slab" and q.thickness_mm and poly_from_points(q.outline) is not None and poly_from_points(q.outline).buffer(400).intersects(poly)]
                thickness = neigh[0] if neigh else spec.panels.cantilever_default_thickness_mm
                source = "adjacent" if neigh else "default"
            top_offset, rule = 0.0, None
            # "slab at beam bottom" and "projection at beam bottom lvl." mean the same thing
            bb_cover = max(region_cover(poly, "beam_bottom")[0], region_cover(poly, "projection")[0])
            if (is_cant and spec.panels.cantilever_bottom_align) or bb_cover >= spec.panels.region_cover:
                if support_depth and thickness:
                    top_offset = -(support_depth - thickness)
                    rule = "cantilever_bottom_align" if is_cant else "beam_bottom"
                else:
                    rule = "cantilever_bottom_align" if is_cant else "beam_bottom"
                    diag.warning("PANEL_OFFSET_UNKNOWN", f"Panel {pid} should sit at beam bottom but beam depth or slab thickness is unknown", floor_id=f.id, element_id=pid, location=representative_point(poly))
            elif sunk:
                top_offset, rule = -sunk, "sunk"
            c = poly.centroid
            mp = representative_point(poly) if spec.placement.slab_mark == "representative" else (c.x, c.y)
            ring = ring_points(out_poly)
            bulges = [0.0] * len(ring)
            if circles:
                ring, bulges = fit_arcs(ring, circles, spec.panels.arc_fit_tol_mm)
            kind = "ramp" if ramp is not None else ("cantilever" if is_cant else "slab")
            np_.panels.append(NPanel(id=pid, floor_id=f.id, kind=kind, mark=mark, thickness_mm=thickness, thickness_source=source,
                                     outline=_pts(ring), bulges=bulges, holes=holes, area_m2=round(poly.area / 1e6, 3), centroid=_pt((c.x, c.y)), mark_position=_pt(mp),
                                     sunk_mm=sunk, sunk_source=sunk_source, sunk_outlines=sunk_rings, top_offset_mm=round(top_offset, 1), top_offset_rule=rule, support_depth_mm=support_depth,
                                     cantilever=is_cant, slope_ratio=ramp.slope_ratio if ramp else None, direction=ramp.direction if ramp else None,
                                     arrow=[ramp.arrow_start, ramp.arrow_end] if ramp and ramp.arrow_start and ramp.arrow_end else [],
                                     opening_ids=op_ids, tag_ids=[s.id for s in inside]))
            # slab folds: legend "fold" regions or fold tags inside the panel (answers 3, 6A) -> hatched region, lower side inside
            fold_regions = [(r, rp) for r, rp in regions_f if r.meaning == "fold" and rp.intersects(poly) and rp.intersection(poly).area > 0.25 * rp.area]
            fold_tags = [s for s in inside if s.tags and any("FOLD" in (t.text or "").upper() for t in s.tags)]
            for r, rp in fold_regions:
                fp = rp.intersection(poly)
                if fp.geom_type != "Polygon" or fp.area < 1e5:
                    continue
                fold_val = next((parse_tag(t.text).fold_mm for s_ in fold_tags for t in s_.tags if parse_tag(t.text).fold_mm), None) or r.value_mm
                # answer 5A: a thickness on the fold tag belongs to the vertical piece only; without one nothing is assumed
                vert = next((parse_tag(t.text).thickness_mm for s_ in fold_tags for t in s_.tags if "FOLD" in (t.text or "").upper() and parse_tag(t.text).thickness_mm), None)
                fid_ = f"{f.id}-FD{len([x for x in np_.folds if x.floor_id == f.id]) + 1:03d}"
                fc = fp.centroid
                if vert is None:
                    diag.warning("FOLD_THICKNESS_UNKNOWN", f"Fold {fid_} has no vertical slab thickness on its tag; the engineer sets it in Revit", floor_id=f.id, element_id=fid_, location=(fc.x, fc.y))
                np_.folds.append(NFold(id=fid_, floor_id=f.id, panel_id=pid, outline=_pts(ring_points(fp)), fold_mm=fold_val, vertical_thickness_mm=vert,
                                       mark=_fmt(spec.marks.fold_line, fold=fold_val) if fold_val else "FOLD", mark_position=_pt((fc.x, fc.y)), source_ids=r.source_handles))
                np_.panels[-1].fold_ids.append(fid_)
            np_.mark_map.append(MarkMap(element_id=pid, floor_id=f.id, kind="slab", mark=mark, client_mark=inside[0].mark if inside else None, client_tags=[t for s in inside for t in s.tags]))
        stray = [s for s in tags if s.id not in used_tags]
        if stray:
            diag.info("PANEL_TAG_OUTSIDE", f"{len(stray)} slab tag(s) lie in no panel (edge strips, cantilevers or stairs), e.g. {', '.join(s.tags[0].text for s in stray[:4] if s.tags)}", floor_id=f.id)

    # ---- beam level offsets (answer 15C): inverted beams sit above the slab -------------
    for f in floors_sorted:
        panels_f = [(p, poly_from_points(p.outline)) for p in np_.panels if p.floor_id == f.id and p.kind in ("slab", "cantilever")]
        for b in np_.beams:
            if b.floor_id != f.id or not b.inverted or not b.depth_mm:
                continue
            bp = poly_from_points(b.outline)
            t_adj = [p.thickness_mm for p, pp in panels_f if pp is not None and bp is not None and pp.buffer(5.0).intersects(bp) and p.thickness_mm]
            t_slab = max(t_adj) if t_adj else (f.default_slab_thickness_mm or 0.0)
            b.top_offset_mm = round(b.depth_mm - t_slab, 1)

    # ---- wall tops (answer 6A): a wall under a beam stops at the beam bottom ---------------
    for w in np_.walls:
        wp = poly_from_points(w.outline)
        if wp is None:
            continue
        over = [b for b in np_.beams if b.floor_id == w.floor_id and b.depth_mm and poly_from_points(b.outline) is not None and poly_from_points(b.outline).intersection(wp).area >= 0.5 * wp.area]
        if over:
            b = max(over, key=lambda b: b.depth_mm)
            w.top_offset_mm = -float(b.depth_mm)
            w.beam_above_id = b.id

    # ---- footings -----------------------------------------------------------
    for f in floors_sorted:
        fts = [x for x in project.footings if x.floor_id == f.id]
        if not fts:
            continue
        stacks_on_floor = [(s, Point(s.centre.x, s.centre.y)) for s in np_.stacks if f.id in s.floors]
        n_f = n_r = 0
        for x in sorted(fts, key=lambda x: (1 if x.modifier in ('fold', 'sunk') else 0, -round(x.center.y / 500.0), x.center.x)):
            outline = poly_from_points(x.outline)
            if outline is None:
                continue
            over = [s.id for s, pt in stacks_on_floor if outline.contains(pt)]
            modifier = x.modifier
            tag_text = " ".join((t.text or "") for t in x.tags).upper() + " " + (x.mark or "").upper()
            client_says_raft = (modifier == "raft") or bool(x.mark and x.mark.upper().startswith(("RF", "RAFT", "MAT"))) or "RAFT" in tag_text
            client_says_pilecap = bool(x.mark and x.mark.upper().startswith("PC")) or "PILE" in tag_text or "PILE" in (x.source_layer or "").upper()
            client_says_pit = "PIT" in tag_text or modifier == "pit"
            client_says_combined = bool(x.mark and x.mark.upper().startswith("CF")) or "COMBINED" in tag_text or "COMB." in tag_text
            is_raft = (spec.raft_by_client and client_says_raft) or (spec.raft_min_area_m2 > 0 and outline.area >= spec.raft_min_area_m2 * 1e6) or (spec.raft_min_columns > 0 and len(over) >= spec.raft_min_columns)
            if modifier in ("fold", "sunk"):
                kind = modifier
                mark = ""
                n = 0
            elif is_raft:
                n_r += 1
                n, kind = n_r, "raft"
                mark = _fmt(spec.marks.raft, n=n, thk=x.thickness_mm) if x.thickness_mm else _fmt(spec.marks.footing_no_thickness, n=n).replace("F", "RF", 1)
            elif client_says_pit:
                n_f += 1
                n, kind = n_f, "pit"
                mark = _fmt(spec.marks.pit, n=n, thk=x.thickness_mm) if x.thickness_mm else _fmt(spec.marks.footing_no_thickness, n=n).replace("F", "LP", 1)
            elif modifier == "pile" and x.shape == "circle":
                # a pile the client drew; modelled as a round column in Revit (answer 16B). Piles are never invented.
                pid_ = f"{f.id}-P{len([q for q in np_.piles if q.floor_id == f.id]) + 1:03d}"
                dia = x.diameter_mm or x.drawn_width_mm
                if not dia:
                    diag.warning("PILE_NO_DIAMETER", f"Pile {pid_} has no diameter from the client drawing", floor_id=f.id, element_id=pid_, location=(x.center.x, x.center.y))
                np_.piles.append(NPile(id=pid_, floor_id=f.id, center=x.center, diameter_mm=dia, source_id=x.id))
                continue
            elif client_says_pilecap or modifier == "pilecap":
                n_f += 1
                n, kind = n_f, "pilecap"
                mark = _fmt(spec.marks.pilecap, n=n, thk=x.thickness_mm) if x.thickness_mm else _fmt(spec.marks.footing_no_thickness, n=n).replace("F", "PC", 1)
            elif (client_says_combined if spec.combined_by_client else len(over) >= 2):
                n_f += 1
                n, kind = n_f, "combined"      # answer 16A / 8B: only when the client says combined
                mark = _fmt(spec.marks.footing_combined, n=n, thk=x.thickness_mm) if x.thickness_mm else _fmt(spec.marks.footing_no_thickness, n=n).replace("F", "CF", 1)
            else:
                n_f += 1
                n, kind = n_f, "footing"
                mark = _fmt(spec.marks.footing, n=n, thk=x.thickness_mm) if x.thickness_mm else _fmt(spec.marks.footing_no_thickness, n=n)
            lines = [mark] if mark else []
            if x.fold_mm:
                lines.append(_fmt(spec.marks.footing_fold_line, fold=x.fold_mm))
            pit_depth = None
            if kind == "pit":
                pit_depth = next((parse_depth(t.text) for t in x.tags if parse_depth(t.text)), None)
                if pit_depth is None:
                    # answer 4A: the depth is measured from this floor's structural slab level (SSL)
                    fl = next((q for q in np_.floors if q.id == f.id), None)
                    if fl and fl.elevation_mm is not None:
                        for h in project.level_hints:
                            if h.floor_id == f.id and h.elevation_mm < fl.elevation_mm:
                                pit_depth = fl.elevation_mm - h.elevation_mm
                                break
                if pit_depth:
                    lines.append(_fmt(spec.marks.pit_depth_line, depth=pit_depth))
                else:
                    diag.warning("PIT_DEPTH_UNKNOWN", f"Lift pit {mark} has no depth text", floor_id=f.id, location=(x.center.x, x.center.y))
            # PCC (lean concrete) under foundations when the client mentions it, or always when the spec says so
            pcc_t = pcc_p = None
            if kind in ("footing", "combined", "raft", "pilecap", "pit"):
                own = next((parse_pcc_safe(t.text) for t in x.tags if parse_pcc_safe(t.text)), None)
                glob = next((h for h in project.pcc_hints if h.floor_id in (f.id, None)), None) or (project.pcc_hints[0] if project.pcc_hints else None)
                if own or glob or spec.pcc_always:
                    pcc_t = (own[0] if own and own[0] else None) or (glob.thickness_mm if glob else None) or spec.pcc_default_thickness_mm
                    pcc_p = (own[1] if own and own[1] else None) or (glob.projection_mm if glob else None) or spec.pcc_default_projection_mm
                    lines.append(_fmt(spec.marks.pcc_line, thk=pcc_t))
            if kind in ("footing", "combined", "pilecap") and not over:
                diag.warning("FOOTING_NO_COLUMN", f"Footing {mark} has no column stack over it", floor_id=f.id, location=(x.center.x, x.center.y))
            prefix = {"raft": "RF", "combined": "CF", "pilecap": "PC", "pit": "LP"}.get(kind, "F")
            fid_ = f"{f.id}-{prefix}{n:03d}" if kind not in ("fold", "sunk") else f"{f.id}-FX{len(np_.footings) + 1:03d}"
            if kind in ("fold", "sunk"):
                # a fold/sunk inside a raft belongs to the raft layers and carries the raft mark, otherwise the footing layers
                rafts = [r for r in np_.footings if r.floor_id == f.id and r.kind == "raft"]
                parent = next((r for r in rafts if poly_from_points(r.outline) is not None and poly_from_points(r.outline).contains(outline.centroid)), None)
                over = ["raft"] if parent is not None else []
                if parent is not None and parent.mark:
                    lines = [parent.mark] + lines
            pcc_outline = _pts(ring_points(outline.buffer(pcc_p, join_style=2))) if pcc_t else []
            np_.footings.append(NFooting(id=fid_, floor_id=f.id, kind=kind, mark=mark, mark_lines=lines, shape=x.shape, center=x.center, width_mm=x.width_mm, depth_mm=x.depth_mm,
                                         rotation_deg=x.rotation_deg, thickness_mm=x.thickness_mm, fold_mm=x.fold_mm, outline=_pts(ring_points(outline)), stack_ids=over,
                                         pit_depth_mm=pit_depth, pcc_thickness_mm=pcc_t, pcc_projection_mm=pcc_p, pcc_outline=pcc_outline,
                                         client_mark=x.mark, source_ids=[x.id]))
            if mark:
                np_.mark_map.append(MarkMap(element_id=fid_, floor_id=f.id, kind=kind, mark=mark, client_mark=x.mark, client_tags=x.tags))
        caps = [(ft, poly_from_points(ft.outline)) for ft in np_.footings if ft.floor_id == f.id and ft.kind == "pilecap"]
        for pl in [q for q in np_.piles if q.floor_id == f.id]:
            cap = next((ft for ft, cp in caps if cp is not None and cp.contains(Point(pl.center.x, pl.center.y))), None)
            if cap is not None:
                pl.pilecap_id = cap.id
                cap.pile_ids.append(pl.id)
        for ft, _cp in caps:
            if ft.pile_ids:
                dia = next((q.diameter_mm for q in np_.piles if q.id == ft.pile_ids[0]), None) or 0
                ft.mark_lines.insert(1, _fmt(spec.marks.pilecap_piles_line, n=len(ft.pile_ids), dia=dia))
        covered = {sid for ft in np_.footings if ft.floor_id == f.id for sid in ft.stack_ids}
        for s, pt in stacks_on_floor:
            if s.id not in covered and f.index == min(fl.index for fl in floors_sorted):
                diag.warning("COLUMN_NO_FOOTING", f"Column stack {s.mark_base} on {f.id} has no footing under it", floor_id=f.id, element_id=s.id, location=(pt.x, pt.y))

    # ---- grids --------------------------------------------------------------
    for f in floors_sorted:
        members = [poly_from_points(c.outline) for c in np_.columns if c.floor_id == f.id] + [poly_from_points(b.outline) for b in np_.beams if b.floor_id == f.id]
        members += [poly_from_points(x.outline) for x in np_.footings if x.floor_id == f.id]
        members = [m for m in members if m is not None]
        if members:
            bounds = [m.bounds for m in members]
            minx, miny = min(b[0] for b in bounds), min(b[1] for b in bounds)
            maxx, maxy = max(b[2] for b in bounds), max(b[3] for b in bounds)
        else:
            minx = miny = -1.0
            maxx = maxy = 1.0
        ext = spec.placement.grid_extension_mm
        r = spec.placement.grid_bubble_radius_mm
        seen: set[tuple[str, str]] = set()
        for g in sorted((g for g in project.grids if g.floor_id == f.id and g.label), key=lambda g: (g.axis, g.offset_mm)):
            if (g.axis, g.label) in seen:
                continue
            seen.add((g.axis, g.label))
            if g.axis == "X":
                start, end = (g.offset_mm, miny - ext), (g.offset_mm, maxy + ext)
                bubbles = [(g.offset_mm, miny - ext - r)]
                if spec.placement.grid_bubble_end == "both":
                    bubbles.append((g.offset_mm, maxy + ext + r))
            elif g.axis == "Y":
                start, end = (minx - ext, g.offset_mm), (maxx + ext, g.offset_mm)
                bubbles = [(minx - ext - r, g.offset_mm)]
                if spec.placement.grid_bubble_end == "both":
                    bubbles.append((maxx + ext + r, g.offset_mm))
            else:
                start, end = (g.start.x, g.start.y), (g.end.x, g.end.y)
                bubbles = [start]
            np_.grids.append(NGrid(id=f"{f.id}-G{len([x for x in np_.grids if x.floor_id == f.id]) + 1:03d}", floor_id=f.id, label=g.label, axis=g.axis,
                                   offset_mm=g.offset_mm, start=_pt(start), end=_pt(end), bubble_centres=[_pt(b) for b in bubbles], source_id=g.id))

    if spec.write_generator_note:
        np_.notes.append(f"GENERATED BY C2B {np_.generator.split()[-1]} FROM {np_.source_file} | NORMALISED SCHEMA {np_.schema_version}")
    np_.notes.extend(spec.notes)
    np_.diagnostics = diag.items
    np_.recompute_summary()
    return np_
