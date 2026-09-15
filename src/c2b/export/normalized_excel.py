"""Schedules workbook for the normalised model."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from ..normalize.model import NormalizedProject
from .excel import _sheet, _SEV_FILL


def write_normalized_workbook(np_: NormalizedProject, path: str | Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    s = np_.summary
    _sheet(wb, "Summary", ["Item", "Value"], [["Source", np_.source_file], ["Generator", np_.generator], ["Normalised schema", np_.schema_version], ["Spec", np_.spec_name], ["Level reference", np_.level_reference], [],
                                              ["Floors", s.floors], ["Levels", s.levels], ["Column stacks", s.stacks], ["Columns", s.columns], ["Beam spans", s.beams],
                                              ["Slab panels", s.panels], ["Footings", s.footings], ["Grids", s.grids], ["Openings", s.openings], ["Walls", s.walls], ["Stairs", s.stairs], [],
                                              ["Errors", s.errors], ["Warnings", s.warnings], ["Infos", s.infos]])
    _sheet(wb, "Levels", ["Level id", "Index", "Name", "Elevation (mm)", "Floor-to-floor (mm)", "Plan floor", "Revit level name"],
           [[l.id, l.index, l.name, l.elevation_mm, l.floor_to_floor_mm, l.plan_floor_id, l.revit_level_name] for l in np_.levels])
    _sheet(wb, "Floors", ["Floor id", "Index", "Name", "Title", "Source name", "Elevation (mm)", "Levels", "Columns", "Beams", "Panels", "Footings", "Grids"],
           [[f.id, f.index, f.name, f.title, f.source_name, f.elevation_mm, f.levels, f.counts.get("columns"), f.counts.get("beams"), f.counts.get("panels"), f.counts.get("footings"), f.counts.get("grids")] for f in np_.floors])
    floors = [f.id for f in np_.floors]
    col_by = {(c.floor_id, c.stack_id): c for c in np_.columns}
    rows = []
    for st in np_.stacks:
        row = [st.id, st.mark_base, st.grid_ref, st.centre.x, st.centre.y, ", ".join(st.client_marks)]
        for fid in floors:
            c = col_by.get((fid, st.id))
            row.append("" if c is None else (f"D{c.diameter_mm:.0f}" if c.shape == "circle" and c.diameter_mm else f"{(c.width_mm or 0):.0f}x{(c.depth_mm or 0):.0f}") + (" STOP" if c.stops_here else ""))
        rows.append(row)
    _sheet(wb, "Column schedule", ["Stack", "Mark", "Grid", "X", "Y", "Client marks"] + floors, rows)
    _sheet(wb, "Columns", ["Id", "Floor", "Stack", "Mark", "Client mark", "Shape", "X", "Y", "Width", "Depth", "Dia", "Rotation", "Stops", "Starts", "Wall-like", "Size source", "Source ids"],
           [[c.id, c.floor_id, c.stack_id, c.mark, c.client_mark, c.shape, c.center.x, c.center.y, c.width_mm, c.depth_mm, c.diameter_mm, c.rotation_deg, "yes" if c.stops_here else "", "yes" if c.starts_here else "", "yes" if c.wall_like else "", c.size_source, c.source_ids] for c in np_.columns])
    _sheet(wb, "Beams", ["Id", "Floor", "Mark", "Client mark", "Run", "Span", "Start X", "Start Y", "End X", "End Y", "Length", "Width", "Depth", "Tip depth", "Cantilever", "Inverted", "Top offset (mm)", "Support start", "Support end", "Depth source"],
           [[b.id, b.floor_id, b.mark, b.client_mark, b.run_id, b.span_index, b.start.x, b.start.y, b.end.x, b.end.y, b.length_mm, b.width_mm, b.depth_mm, b.depth_tip_mm, "yes" if b.cantilever else "", "yes" if b.inverted else "", b.top_offset_mm, b.support_start, b.support_end, b.depth_source] for b in np_.beams])
    _sheet(wb, "Slabs", ["Id", "Floor", "Kind", "Mark", "Thickness", "Source", "Area (m2)", "Centroid X", "Centroid Y", "Top offset (mm)", "Offset rule", "Support depth", "Sunk", "Sunk source", "Slope", "Direction", "Holes", "Folds", "Openings", "Tags used"],
           [[p.id, p.floor_id, p.kind, p.mark, p.thickness_mm, p.thickness_source, p.area_m2, p.centroid.x, p.centroid.y, p.top_offset_mm, p.top_offset_rule, p.support_depth_mm, p.sunk_mm, p.sunk_source, p.slope_ratio, p.direction, len(p.holes), p.fold_ids, p.opening_ids, p.tag_ids] for p in np_.panels])
    _sheet(wb, "Footings", ["Id", "Floor", "Kind", "Mark", "Client mark", "Shape", "X", "Y", "Width", "Depth", "Thickness", "Fold", "Pit depth", "PCC thk", "PCC proj", "Piles", "Stacks over"],
           [[x.id, x.floor_id, x.kind, x.mark, x.client_mark, x.shape, x.center.x, x.center.y, x.width_mm, x.depth_mm, x.thickness_mm, x.fold_mm, x.pit_depth_mm, x.pcc_thickness_mm, x.pcc_projection_mm, len(x.pile_ids), x.stack_ids] for x in np_.footings])
    _sheet(wb, "Walls", ["Id", "Floor", "Mark", "Structural", "X", "Y", "Length", "Thickness", "Top offset (mm)", "Beam above"],
           [[w.id, w.floor_id, w.mark, "yes" if w.structural else "no", w.center.x, w.center.y, w.length_mm, w.thickness_mm, w.top_offset_mm, w.beam_above_id] for w in np_.walls])
    _sheet(wb, "Stairs", ["Id", "Floor", "Mark", "Waist", "Direction", "Treads", "Risers (est)", "Landing (est mm)", "Estimated"],
           [[st.id, st.floor_id, st.mark, st.waist_mm, st.direction, st.tread_count, st.riser_count_est, st.landing_level_est_mm, "yes" if st.estimated else ""] for st in np_.stairs if st.outline or st.mark])
    _sheet(wb, "Folds", ["Id", "Floor", "Panel", "Fold (mm)", "Vertical thk", "Mark"], [[fd.id, fd.floor_id, fd.panel_id, fd.fold_mm, fd.vertical_thickness_mm, fd.mark] for fd in np_.folds])
    _sheet(wb, "Grids", ["Id", "Floor", "Label", "Axis", "Offset", "Start X", "Start Y", "End X", "End Y"],
           [[g.id, g.floor_id, g.label, g.axis, g.offset_mm, g.start.x, g.start.y, g.end.x, g.end.y] for g in np_.grids])
    _sheet(wb, "Mark map", ["Element", "Floor", "Kind", "C2B mark", "Client mark", "Client tag texts"],
           [[m.element_id, m.floor_id, m.kind, m.mark, m.client_mark, [t.text for t in m.client_tags]] for m in np_.mark_map])
    ws = _sheet(wb, "Diagnostics", ["Severity", "Code", "Floor", "Element", "X", "Y", "Message"],
                [[d.severity, d.code, d.floor_id, d.element_id, d.location.x if d.location else None, d.location.y if d.location else None, d.message]
                 for d in sorted(np_.diagnostics, key=lambda d: ({"ERROR": 0, "WARNING": 1, "INFO": 2}[d.severity], d.code))])
    for row in ws.iter_rows(min_row=2):
        fill = _SEV_FILL.get(row[0].value)
        if fill:
            row[0].fill = fill
    wb.save(str(path))
    return Path(path)
