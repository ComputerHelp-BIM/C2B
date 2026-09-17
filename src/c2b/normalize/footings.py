"""Footings, rafts, pile caps, pits and the PCC under them.

Split out of the normalisation pipeline: this phase reads the extraction's footing records and
decides, from the client's own marks and layers, which of them is an isolated footing, a raft, a
pile cap or a lift pit, then numbers and marks each.
"""
from __future__ import annotations

from shapely.geometry import Point

from ..diagnostics import DiagnosticsCollector
from ..schema import Project
from ..tags import parse_depth
from .common import format_mark, parse_pcc_safe, to_pts
from .geometry import poly_from_points, ring_points
from .model import MarkMap, NFooting, NormalizedProject, NPile
from .spec import TemplateSpec


def build_footings(project: Project, np_: NormalizedProject, spec: TemplateSpec,
                   diag: DiagnosticsCollector, floors_sorted: list) -> None:
    """Add this project's footings, pile caps, pits and piles to ``np_``."""
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
                mark = format_mark(spec.marks.raft, n=n, thk=x.thickness_mm) if x.thickness_mm else format_mark(spec.marks.footing_no_thickness, n=n).replace("F", "RF", 1)
            elif client_says_pit:
                n_f += 1
                n, kind = n_f, "pit"
                mark = format_mark(spec.marks.pit, n=n, thk=x.thickness_mm) if x.thickness_mm else format_mark(spec.marks.footing_no_thickness, n=n).replace("F", "LP", 1)
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
                mark = format_mark(spec.marks.pilecap, n=n, thk=x.thickness_mm) if x.thickness_mm else format_mark(spec.marks.footing_no_thickness, n=n).replace("F", "PC", 1)
            elif (client_says_combined if spec.combined_by_client else len(over) >= 2):
                n_f += 1
                n, kind = n_f, "combined"      # answer 16A / 8B: only when the client says combined
                mark = format_mark(spec.marks.footing_combined, n=n, thk=x.thickness_mm) if x.thickness_mm else format_mark(spec.marks.footing_no_thickness, n=n).replace("F", "CF", 1)
            else:
                n_f += 1
                n, kind = n_f, "footing"
                mark = format_mark(spec.marks.footing, n=n, thk=x.thickness_mm) if x.thickness_mm else format_mark(spec.marks.footing_no_thickness, n=n)
            lines = [mark] if mark else []
            if x.fold_mm:
                lines.append(format_mark(spec.marks.footing_fold_line, fold=x.fold_mm))
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
                    lines.append(format_mark(spec.marks.pit_depth_line, depth=pit_depth))
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
                    lines.append(format_mark(spec.marks.pcc_line, thk=pcc_t))
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
                    lines = [parent.mark, *lines]
            pcc_outline = to_pts(ring_points(outline.buffer(pcc_p, join_style=2))) if pcc_t else []
            np_.footings.append(NFooting(id=fid_, floor_id=f.id, kind=kind, mark=mark, mark_lines=lines, shape=x.shape, center=x.center, width_mm=x.width_mm, depth_mm=x.depth_mm,
                                         rotation_deg=x.rotation_deg, thickness_mm=x.thickness_mm, fold_mm=x.fold_mm, outline=to_pts(ring_points(outline)), stack_ids=over,
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
                ft.mark_lines.insert(1, format_mark(spec.marks.pilecap_piles_line, n=len(ft.pile_ids), dia=dia))
        covered = {sid for ft in np_.footings if ft.floor_id == f.id for sid in ft.stack_ids}
        for s, pt in stacks_on_floor:
            if s.id not in covered and f.index == min(fl.index for fl in floors_sorted):
                diag.warning("COLUMN_NO_FOOTING", f"Column stack {s.mark_base} on {f.id} has no footing under it", floor_id=f.id, element_id=s.id, location=(pt.x, pt.y))
