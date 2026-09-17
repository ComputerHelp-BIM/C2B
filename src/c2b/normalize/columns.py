"""Column stacks, the columns on each floor, and the RCC walls beside them.

Split out of the normalisation pipeline. A stack is the same column seen on every floor it
reaches, numbered once for the whole building; this phase numbers them, decides each column's
mark and where that mark is drawn, and carries the client's structural walls through.
"""
from __future__ import annotations

import re

from ..diagnostics import DiagnosticsCollector
from ..schema import Project
from .common import format_mark, tagged_size, to_pt, to_pts
from .geometry import box_centre, fit_text_height, poly_from_points, ring_points, text_fits
from .model import MarkMap, NColumn, NormalizedProject, NWall
from .naming import split_mark_size
from .spec import TemplateSpec
from .stacks import build_stacks


def build_columns(project: Project, np_: NormalizedProject, spec: TemplateSpec,
                  diag: DiagnosticsCollector, floors_sorted: list, floor_ids: list[str]) -> None:
    """Add this project's column stacks, columns and structural walls to ``np_``."""
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
                mark = format_mark(spec.marks.column_circle.replace("C{n}", "{base}"), base=base, n=n, dia=dia)
            else:
                # the mark quotes the size as the client tagged it (b x D), not as the rectangle happens to lie in plan;
                # without a tag the shorter side comes first
                w, d = tagged_size(c) or ((c.width_mm or c.drawn_width_mm or 0), (c.depth_mm or c.drawn_depth_mm or 0))
                mark = format_mark(spec.marks.column.replace("C{n}", "{base}"), base=base, n=n, w=w, d=d)
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
                                       outline=to_pts(ring_points(outline)), stops_here=stops, starts_here=starts, wall_like=c.wall_like,
                                       size_source=c.size_source, mark_position=to_pt(mp), mark_rotation_deg=round(rot, 3), mark_height_mm=round(height, 2), client_mark=c.mark,
                                       source_ids=[c.id], source_handles=c.source_handles))
            np_.mark_map.append(MarkMap(element_id=cid, floor_id=f.id, kind="column", mark=mark, client_mark=c.mark, client_tags=c.tags))

    # ---- walls: RCC walls only are modelled (answer 6B); non-structural walls are kept as records -------------
    for w in project.walls:
        outline = poly_from_points(w.outline)
        if outline is None:
            continue
        np_.walls.append(NWall(id=f"{w.floor_id}-W{len([x for x in np_.walls if x.floor_id == w.floor_id]) + 1:03d}", floor_id=w.floor_id, mark=w.mark,
                               outline=to_pts(ring_points(outline)), center=w.center, thickness_mm=w.thickness_mm, length_mm=w.length_mm,
                               structural=w.structural, source_id=w.id))
