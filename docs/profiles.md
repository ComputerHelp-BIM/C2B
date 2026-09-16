# Layer profiles

A profile tells the extractor what each client layer means. Without one, roles are
suggested from layer names and entity statistics and every guess carries a confidence.
`c2b profile suggest drawing.dxf -o profiles/client.yaml` writes the suggestion; edit it
and pass it with `-p`.

```yaml
name: client-x
units_override: null          # mm | cm | m | in | ft, when $INSUNITS is wrong
explode_blocks: true
max_block_depth: 4
floor:
  boundary_layer: Boundary
  origin_layer: Origin
  label_keywords: [level, lvl, floor, plan, terrace, foundation, ...]
layers:
  S-COLS:        {geometry: COLUMN, confidence: high}
  COL. SIZE:     {geometry: COLUMN}                # text on it becomes COLUMN_TAG automatically
  S-BEAM-HDLN:   {geometry: BEAM, modifiers: [hidden]}   # skipped, reported
  HAT:           {geometry: HATCH_GENERIC}         # hatches only confirm outlines, never create members
  OTHER:         {geometry: IGNORE}
  MYSTERY-LAYER: {geometry: BEAM, text: NOTE}      # explicit text role
tolerances:
  beam_max_width_mm: 1500
  column_tag_radius_min_mm: 600
  ...
```

## Roles

| Role | Geometry on the layer becomes | Text on the layer becomes |
|---|---|---|
| `BOUNDARY`, `ORIGIN` | floor frames / origins | — |
| `GRID` | grid lines | grid labels |
| `COLUMN` | column outlines (polylines, hatches, circles, line loops, blocks) | column tags |
| `BEAM` | beam edges (lines, polylines) or thin outlines | beam tags |
| `SLAB` | slab outlines (≥ 1 m²) | slab thickness tags |
| `FOOTING` | footing outlines | footing tags |
| `OPENING` | cut-outs / shafts | opening labels |
| `WALL` | wall outlines | wall marks (also offered to wall-like columns) |
| `STAIR` | ignored for now | — |
| `SCHEDULE` | — | schedule table cells |
| `NOTE` | — | general notes (defaults such as "ALL BEAMS ARE 750MM") and floor names |
| `TITLE` | — | title block attributes (floor names) |
| `DIMENSION`, `HATCH_GENERIC`, `IGNORE`, `UNKNOWN` | see above | — |

## Modifiers

`hidden` (skip), `stop`/`start`/`stub`/`podium` (columns), `fold`/`sunk`/`drop`/`projection`
(slabs, footings), `non_structural`/`retaining` (walls), `hatch`.

## Which witness wins: tag or outline

When the client's tag and their own outline disagree about a size, `size_sources` decides which
is believed. `tag` (the default) takes the tag or schedule and falls back to the outline; `outline`
measures the drawing and keeps the tag for the mark alone. Neither is right for every client --
a firm that dimensions carefully wants the outline, one that keeps a maintained schedule wants
the tag -- and the disagreement is reported either way, as `COLUMN_SIZE_MISMATCH`.

```yaml
size_sources:
  column: tag        # or: outline
  beam: tag
  slab: tag
  footing: tag
```

In the drafter's window this is the **Column size from** box; only columns act on it so far.

## Tolerances worth knowing

| Key | Default | Meaning |
|---|---|---|
| `snap_mm` | 1 | end-point snapping when closing line loops |
| `ring_close_tol_mm` | 50 | close nearly-closed outline polylines up to this gap |
| `column_min_side_mm` / `column_max_side_mm` | 100 / 20000 | outline size window for columns |
| `beam_min_width_mm` / `beam_max_width_mm` | 100 / 1500 | edge-pair distance window |
| `beam_merge_gap_mm` | 800 | merge collinear edge pieces across crossing beams |
| `beam_min_length_mm` | 500 | shorter pairs are dropped |
| `grid_label_radius_mm` | 2500 | label search radius from grid line ends |
| `size_mismatch_tol_mm` | 26 | tag vs drawn comparison tolerance |
| `wall_like_min_side_ratio` / `wall_like_min_length_mm` | 4 / 1000 | what counts as a wall-like column |
