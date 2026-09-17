"""Beam spans: each run cut at its supports, marked and placed.

Split out of the normalisation pipeline. The extraction gives beam *runs* as the client drew
them; this phase cuts each run where it meets a column or another beam, so every span between
supports is its own member, and gives each span its mark and the place that mark is drawn.
"""
from __future__ import annotations

import re

from ..diagnostics import DiagnosticsCollector
from ..schema import Project
from .common import format_mark, to_pt, to_pts
from .geometry import Support, poly_from_points, representative_point, ring_points
from .model import MarkMap, NBeam, NormalizedProject
from .spans import runs_for_floor, split_runs
from .spec import TemplateSpec


def build_beams(project: Project, np_: NormalizedProject, spec: TemplateSpec,
                diag: DiagnosticsCollector, floors_sorted: list) -> None:
    """Add this project's beam spans to ``np_``."""
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
                mark = format_mark(spec.marks.beam_taper, base=base, n=i, w=w, d=d, tip=tip)      # answer 2A: depth at support / tip
            else:
                mark_fmt = (spec.marks.beam if d else spec.marks.beam_no_depth).replace("B{n}", "{base}")
                mark = format_mark(mark_fmt, base=base, n=i, w=w, d=d)
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
            np_.beams.append(NBeam(id=bid, floor_id=f.id, run_id=r.id, span_index=i, mark=mark, start=to_pt(p1), end=to_pt(p2), length_mm=round(s["t2"] - s["t1"], 1),
                                   width_mm=w, depth_mm=d, depth_alt_mm=b.depth_alt_mm, depth_tip_mm=tip, cantilever=free_end, angle_deg=round(r.axis.angle, 3), outline=to_pts(ring_points(outline)),
                                   inverted=b.inverted, support_start=s["support_start"], support_end=s["support_end"], size_source=b.size_source,
                                   depth_source=b.depth_source, depth_rule=b.depth_rule, mark_position=to_pt(mp), mark_rotation_deg=rot, client_mark=b.mark, source_handles=b.source_handles))
            np_.mark_map.append(MarkMap(element_id=bid, floor_id=f.id, kind="beam", mark=mark, client_mark=b.mark, client_tags=b.tags))
