# Canonical schema v0.6.0

Written by `c2b extract` as `<stem>.c2b.json`. All lengths are millimetres, all angles
degrees, all element coordinates are **floor-local** (the floor `Origin` point is 0,0).
Every element keeps `source_handles` (DXF entity handles) so it can be traced back.

```
Project
├─ schema_version, generator, generated_at, units ("mm"), profile_name
├─ drawing        file, dxf_version, insunits, unit_name, unit_scale_to_mm, unit_source, unit_confidence, layouts, extents
├─ layer_map[]    layer, geometry_role, text_role, modifiers, confidence, source (auto|profile), entity_counts, layer_size
├─ floors[]       id (L01..), index, name, name_source, origin (drawing coords), boundary[], elevation_mm, floor_to_floor_mm,
│                 default_beam_depth_mm, default_slab_thickness_mm, counts{}
├─ grids[]        id, floor_id, label, axis (X|Y|other), start, end, angle_deg, offset_mm
├─ columns[]      id, floor_id, mark, shape (rect|circle|polygon), center, width_mm, depth_mm, rotation_deg, diameter_mm,
│                 outline[], area_mm2, drawn_width_mm, drawn_depth_mm, size_source, wall_like, modifier, grid_ref, tags[]
├─ beams[]        id, floor_id, mark, start, end, length_mm, width_mm, depth_mm, depth_alt_mm, drawn_width_mm, angle_deg,
│                 inverted, sunk_mm, outline[], size_source, depth_source, tags[], n_edge_parts
├─ slabs[]        id, floor_id, mark, thickness_mm, thickness_source, position, outline[] (may be empty), sunk_mm, modifier, tags[]
├─ footings[]     id, floor_id, mark, shape, center, width_mm, depth_mm, rotation_deg, thickness_mm, fold_mm, outline[], ...
├─ openings[]     id, floor_id, label, center, outline[], area_mm2
├─ walls[]        id, floor_id, mark, center, outline[], length_mm, thickness_mm, rotation_deg, structural
├─ schedules[]    id, title, category, columns[], rows[{mark, values{width, depth, thickness, ...}}]
├─ tags_unassigned[]  handle, layer, text, role, floor_id, position, parsed{}
├─ diagnostics[]  severity (ERROR|WARNING|INFO), code, message, floor_id, layer, handle, element_id, location
└─ summary        counts per element type and per severity
```

## Field conventions

- `size_source` / `depth_source` / `thickness_source`: `tag`, `schedule`, `layer`, `block`,
  `geometry`, `default`, `unknown`. Anything other than `tag`/`schedule` deserves a look.
- `width_mm` × `depth_mm` for rectangles follow the drawn orientation: `width_mm` is the
  extent along the element's local x axis, `rotation_deg` (−45, 45] rotates that axis.
  `drawn_*` are what the geometry measures; `width_mm`/`depth_mm` are what the tag or
  schedule says (drawn values when nothing else exists).
- `wall_like` on a column: long/short ratio ≥ 4 and long side ≥ 1 m. Such elements are
  kept as columns (that is how the drawings tag them) and flagged for the Revit step,
  where they will become structural walls.
- `modifier` on columns: `start`, `stop`, `stub`, `podium` (from layer names).
  On slabs: `drop`, `fold`, `projection`, `sunk`.
- `grid_ref`: nearest grid intersection ("3/B") within 600 mm, when both axes have grids.
- Beams: `start`/`end` are the centreline over the paired length; `outline` is the plan
  rectangle; `n_edge_parts` says how many line pieces were merged (high numbers = beam
  crossed many others = check it).

## Versioning rules

- **MAJOR**: a field is removed or its meaning changes.
- **MINOR**: a field or element type is added.
- **PATCH**: value corrections without structural change.

The tool version (`c2b.__version__`) and the schema version move independently.
