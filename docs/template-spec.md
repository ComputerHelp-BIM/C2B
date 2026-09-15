# Template spec (utility 3)

`c2b normalize` turns an extraction JSON into the firm's template conventions and writes
the template DXF. Every convention is a field of `TemplateSpec`
(`src/c2b/normalize/spec.py`), saved next to the output as `<stem>.template-spec.yaml`.
Defaults reproduce `CH-TEMPLATE-REMARKED.dxf`.

## What the normaliser does

| Step | Rule (default) | Spec field |
|---|---|---|
| Column stacks | columns matched floor to floor by overlap / centre distance (300 mm), numbered once for the whole building; client marks win, generated numbers fill the gaps, row by row from the bottom row (`row-major`) | `numbering.columns`, `numbering.keep_client_marks`, `stack_match_tol_mm` |
| Column marks | `C{n}-{w}X{d}` / `C{n}-{dia}DIA` in the client's b x D order, inside the column, text along the longer side | `marks.column`, `placement.column_mark`, `placement.column_mark_rotate` |
| Column stop | column present on this floor but not the next gets the `column_stop` hatch | `hatch.column_stop`, `hatch.hatch_all_columns` |
| Beam spans | runs cut at the faces of axis-aligned rectangular columns and at the centre of round / rotated / odd columns; a beam ending on another beam stops at its face; at an X crossing the shallower beam is split | `split.*`, `split.irregular_support_to_centre` |
| Beam marks | client mark kept (`MB-300X750`), else `B{n}-{w}X{d}` per floor; at the span centroid, text along the beam; centreline on `CH-S-BEAM-CL` | `marks.beam`, `numbering.keep_client_beam_marks`, `placement.beam_mark_rotate`, `beam_centreline` |
| Slab panels | holes of the union of beams, columns and walls with true arcs at round columns; thickness from the tag inside, else the floor note default | `panels.*` |
| Cut-outs / stairs | lattice holes covered ≥ 60 % by an opening become cut-outs (outline + X), ≥ 50 % by stair geometry become stairs | `opening_panel_cover`, `stair_panel_cover` |
| Footings | `F{n}-{thk}THK`; a raft `RF{n}-{thk}THK` is what the client calls RF / RAFT / MAT; folds and sunk areas inside a raft go to the raft layers with the raft mark | `raft_by_client`, `raft_min_area_m2`, `marks.footing*` |
| Grids | lines extended 1500 mm past the outermost member, bubble r=300 at the start end | `placement.grid_*` |
| Frames | client Boundary kept, extended 5000 mm downward for title, client notes (verbatim), generator note, legend | `frame.*`, `client_notes` |
| Levels | elevation frame left of the plans: level lines, `NN NAME LVL.` marks, dimensions between levels | `frame.level_*`, `marks.level` |
| Legend | copied from the seed template into every plan frame | `legend_from_seed` |

## Levels workbook

`<stem>.levels.xlsx` (written by `extract`) lists the plan floors. Fill `elevation_mm`
(or `floor_to_floor_mm`) and optionally `revit_level_name`. When the client drawing has a
section or elevation with level texts ("GROUND FLOOR LVL. +2.500"), the matching
elevations are pre-filled and marked "please confirm"; every hint is listed on the
"Level hints" sheet. A typical-floor plan that
represents several levels gets one row per level with the same `floor_id`:

| floor_id | floor_name | order | elevation_mm | revit_level_name |
|---|---|---|---|---|
| L05 | 3rd to 7th Floor Typical Level | 4 | 12450 | 3RD FLOOR LVL. |
| L05 | 3rd to 7th Floor Typical Level | 5 | 15400 | 4TH FLOOR LVL. |

## Outputs of `c2b normalize`

| File | Purpose |
|---|---|
| `<stem>.template.dxf` | the template drawing; every entity carries XDATA `C2B` with `id=`, `mark=`, `client=` for the round trip (utility 4) |
| `<stem>.normalized.json` | normalised model, schema 0.2.0 (stacks, spans, panels, footings, grids, levels, mark map) |
| `<stem>.schedules.xlsx` | column schedule (stack × floor), beams, slabs, footings, grids, mark map, diagnostics |
| `<stem>.template-spec.yaml` | the spec used, ready to edit |

## Validating against the reference template

```bash
python tools/compare_with_template.py out/Test10/Test10.template.dxf samples/CH-TEMPLATE-REMARKED.dxf
```

reports, frame by frame, entity counts per layer and the share of reference outlines
(columns, beams, slabs, footings, raft) that have a generated outline with IoU ≥ 0.6.
