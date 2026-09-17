"""Slab panels: the bays the beams and columns close, and what is inside them.

Split out of the normalisation pipeline. This phase builds the lattice of panels from the
members around them, decides which of those holes are really cut-outs or stairs and which are
cantilevers hanging past the grid, then gives each panel its thickness, its level relative to
the floor, and any sunk pocket or fold inside it.
"""
from __future__ import annotations

import math
from collections import Counter

from shapely.geometry import LineString, Point, Polygon

from ..diagnostics import DiagnosticsCollector
from ..geometry import rectangle_polygon
from ..schema import Project
from ..tags import parse_tag
from .common import format_mark, to_pt, to_pts
from .geometry import fit_arcs, lattice_panels, poly_from_points, representative_point, ring_points
from .model import MarkMap, NBeam, NFold, NormalizedProject, NPanel
from .spec import TemplateSpec


def build_panels(project: Project, np_: NormalizedProject, spec: TemplateSpec,
                 diag: DiagnosticsCollector, floors_sorted: list) -> None:
    """Add this project's slab panels, cut-outs, stairs and folds to ``np_``."""
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
            _ux, _uy = math.cos(ang), math.sin(ang)
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

        def region_cover(poly, meaning, regions_f=regions_f):
            tot = 0.0
            val = None
            for r, rp in regions_f:
                if r.meaning == meaning and rp.intersects(poly):
                    a = rp.intersection(poly).area
                    if a > 0:
                        tot += a
                        val = r.value_mm if val is None else val
            return tot / poly.area, val

        def adjacent_beams(poly, beam_polys=beam_polys):
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
                np_.panels.append(NPanel(id=pid, floor_id=f.id, kind="opening", mark="", outline=to_pts(ring_points(poly)), area_m2=round(poly.area / 1e6, 3),
                                         centroid=to_pt((c.x, c.y)), mark_position=to_pt((c.x, c.y)), opening_ids=[o.id for o, op in openings_f if op is not None and op.intersects(poly)]))
                continue
            if stair_cover >= spec.stair_panel_cover:
                pid = f"{f.id}-X{len([x for x in np_.panels if x.floor_id == f.id and x.kind != 'slab']) + 1:03d}"
                c = poly.centroid
                np_.panels.append(NPanel(id=pid, floor_id=f.id, kind="stair", mark="", outline=to_pts(ring_points(poly)), area_m2=round(poly.area / 1e6, 3),
                                         centroid=to_pt((c.x, c.y)), mark_position=to_pt((c.x, c.y))))
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
                        sunk_rings = [to_pts(ring_points(c)) for c in clipped if c.geom_type == "Polygon" and not c.is_empty]
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
                        holes.append(to_pts(ring_points(opoly)))     # inner loop of the slab sketch (answer 9C)
            if poly in oversized:
                diag.warning("PANEL_LARGE", f"Panel {pid} is {poly.area / 1e6:.0f} m2; a beam may be missing", floor_id=f.id, element_id=pid, location=representative_point(poly))
            # ramps: a ramp note inside the hole (answer 18B); slope and direction from the note and its arrow
            ramp = next((h for h in project.ramp_hints if h.floor_id == f.id and poly.contains(Point(h.position.x, h.position.y))), None)
            if ramp is not None:
                mark = format_mark(spec.marks.ramp if thickness is not None else spec.marks.ramp_no_thickness, n=i, thk=thickness, slope=ramp.slope_ratio or "1:?")
            elif is_cant:
                mark = format_mark(spec.marks.slab_cantilever, n=i, thk=thickness) if thickness is not None else format_mark(spec.marks.slab_no_thickness.replace("S{n}", "CS{n}"), n=i)
            else:
                mark = format_mark(spec.marks.slab, n=i, thk=thickness) if thickness is not None else format_mark(spec.marks.slab_no_thickness, n=i)
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
                                     outline=to_pts(ring), bulges=bulges, holes=holes, area_m2=round(poly.area / 1e6, 3), centroid=to_pt((c.x, c.y)), mark_position=to_pt(mp),
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
                np_.folds.append(NFold(id=fid_, floor_id=f.id, panel_id=pid, outline=to_pts(ring_points(fp)), fold_mm=fold_val, vertical_thickness_mm=vert,
                                       mark=format_mark(spec.marks.fold_line, fold=fold_val) if fold_val else "FOLD", mark_position=to_pt((fc.x, fc.y)), source_ids=r.source_handles))
                np_.panels[-1].fold_ids.append(fid_)
            np_.mark_map.append(MarkMap(element_id=pid, floor_id=f.id, kind="slab", mark=mark, client_mark=inside[0].mark if inside else None, client_tags=[t for s in inside for t in s.tags]))
        stray = [s for s in tags if s.id not in used_tags]
        if stray:
            diag.info("PANEL_TAG_OUTSIDE", f"{len(stray)} slab tag(s) lie in no panel (edge strips, cantilevers or stairs), e.g. {', '.join(s.tags[0].text for s in stray[:4] if s.tags)}", floor_id=f.id)
