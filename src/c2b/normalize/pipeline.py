"""Normalisation pipeline: extraction Project -> NormalizedProject."""
from __future__ import annotations

import math
from collections import Counter

from shapely.geometry import LineString
from shapely.strtree import STRtree

from ..diagnostics import DiagnosticsCollector
from ..schema import Project
from .beams import build_beams
from .columns import build_columns
from .common import format_mark, to_pt, to_pts
from .footings import build_footings
from .geometry import (
    poly_from_points,
    ring_points,
)
from .model import (
    NFloor,
    NGrid,
    NJoint,
    NLevel,
    NOpening,
    NormalizedProject,
    NStair,
)
from .naming import normalise_floor_name, title_from_level_name
from .panels import build_panels
from .spec import TemplateSpec


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
            name = format_mark(spec.marks.level, n=i, name=normalise_floor_name(base) if base else f"LEVEL {i}")
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
        title = format_mark(spec.marks.plan_title, name=title_from_level_name(level_name))
        if level_name != f.name.strip().upper():
            diag.info("NAME_NORMALISED", f"Floor '{f.name}' written as '{level_name}'", floor_id=f.id)
        elevation = next((l.elevation_mm for l in np_.levels if l.id in plan_levels.get(f.id, [])), None)
        np_.floors.append(NFloor(id=f.id, index=f.index, name=level_name, title=title, source_name=f.name, origin=f.origin,
                                 frame=[to_pt((left, frame_bottom)), to_pt((right, frame_bottom)), to_pt((right, top)), to_pt((left, top))],
                                 plan_bottom_y=plan_bottom, elevation_mm=elevation, levels=plan_levels.get(f.id, []),
                                 default_beam_depth_mm=f.default_beam_depth_mm, default_slab_thickness_mm=f.default_slab_thickness_mm,
                                 notes=list(f.notes) if spec.client_notes else []))

    build_columns(project, np_, spec, diag, floors_sorted, floor_ids)
    build_beams(project, np_, spec, diag, floors_sorted)

    # ---- openings -----------------------------------------------------------
    for o in project.openings:
        outline = poly_from_points(o.outline)
        if outline is None:
            continue
        n = len([x for x in np_.openings if x.floor_id == o.floor_id]) + 1
        np_.openings.append(NOpening(id=f"{o.floor_id}-O{n:03d}", floor_id=o.floor_id, label=o.label, outline=to_pts(ring_points(outline)), center=o.center, source_id=o.id))

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
            mark = format_mark(spec.marks.stair.replace("ST{n}", "{base}"), base=base, n=n, thk=waist) if waist else base
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
                                 outline=to_pts(ring_points(outline)) if outline else [], lines=st.lines, center=st.center, source_id=st.id))

    # ---- joints (as drawn) ----------------------------------------------------
    for j in project.joints:
        n = len([x for x in np_.joints if x.floor_id == j.floor_id]) + 1
        np_.joints.append(NJoint(id=f"{j.floor_id}-J{n:03d}", floor_id=j.floor_id, start=j.start, end=j.end, source_id=j.id))

    build_panels(project, np_, spec, diag, floors_sorted)

    # ---- hidden beams: "300XSLB THK." is as deep as the slab it sits in -----------------
    # A concealed beam is buried in the slab, flush top and bottom, so its depth is the slab's.
    # Which slab can only be answered once the panels exist, so the schedule carries the rule
    # this far and it is settled here. Where the slabs either side differ, the thicker wins.
    for f in floors_sorted:
        panels_f = [(p_, poly_from_points(p_.outline)) for p_ in np_.panels
                    if p_.floor_id == f.id and p_.kind in ("slab", "cantilever") and p_.thickness_mm]
        panels_f = [(p_, pp) for p_, pp in panels_f if pp is not None]
        tree = STRtree([pp for _p, pp in panels_f]) if panels_f else None
        for b in np_.beams:
            if b.floor_id != f.id or b.depth_mm or b.depth_rule != "slab_thickness":
                continue
            bp = poly_from_points(b.outline)
            if bp is None or tree is None:
                continue
            touching = bp.buffer(spec.panels.hidden_beam_reach_mm)
            thick = [panels_f[int(k)][0].thickness_mm for k in tree.query(touching, predicate="intersects")
                     if panels_f[int(k)][1].intersects(touching)]
            if not thick:
                diag.warning("BEAM_NO_SLAB", f"Hidden beam {b.id} ({b.mark}) takes the slab thickness, but no slab around it has one", floor_id=f.id, element_id=b.id, location=(b.start.x, b.start.y))
                continue
            b.depth_mm = float(max(thick))
            b.depth_source = "slab"
            b.top_offset_mm = 0.0            # flush with the slab, top and bottom
            if "X?" in b.mark:
                b.mark = b.mark.replace("X?", f"X{b.depth_mm:.0f}")

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

    build_footings(project, np_, spec, diag, floors_sorted)

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
                                   offset_mm=g.offset_mm, start=to_pt(start), end=to_pt(end), bubble_centres=[to_pt(b) for b in bubbles], source_id=g.id))

    if spec.write_generator_note:
        np_.notes.append(f"GENERATED BY C2B {np_.generator.split()[-1]} FROM {np_.source_file} | NORMALISED SCHEMA {np_.schema_version}")
    np_.notes.extend(spec.notes)
    np_.diagnostics = diag.items
    np_.recompute_summary()
    return np_
