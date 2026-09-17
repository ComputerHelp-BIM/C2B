# Layer profiles

A profile tells the extractor what each client layer means. Without one, roles
are
suggested from layer names and entity statistics and every guess carries a
confidence.
`c2b profile suggest drawing.dxf -o profiles/client.yaml` writes the suggestion;
edit it
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
```text

## Roles

| Role | Geometry on the layer becomes | Text on the layer becomes |
| --- | --- | --- |
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

`hidden` (skip), `stop`/`start`/`stub`/`podium` (columns),
`fold`/`sunk`/`drop`/`projection`
(slabs, footings), `non_structural`/`retaining` (walls), `hatch`.

## The client's legend is not structure

The legend is drawn under the plan, inside the floor's own frame, and its
swatches are drawn
exactly like the thing they explain -- a hatch, a rectangle, a cut-out cross.
The band each
legend line occupies (`THUS MARKED ...`, `INDICATES ...`, `DENOTES ...`) is
therefore ruled out
before anything is read as a member, swatch included. Reported once per plan as
`LEGEND_ZONE`.

## Slab edges: what a layer's modifier means

| Modifier | Closed ring | Open line |
| --- | --- | --- |
| (none) | a slab edge | a slab edge |
| `projection` | a slab edge -- a chajja hanging past the beam grid has no other edge to close against | a step, ignored |
| `drop`, `fold`, `sunk`, `hidden` | a level change inside a bay the beams already close; ignored | a step, ignored |

Reading a step line as an edge cuts whole bays into cantilever fragments;
dropping a projection
ring leaves that slab with nothing to close against, so it is never built at
all.

## A column's life: start, stop and the floor below

The template models the column that sits **below** a floor level, so of the
outlines a client
draws on one plan only some belong to that floor. The `start` and `stop` layer
modifiers say
which:

| Modifier | Example layer | Meaning |
| --- | --- | --- |
| (none) | `S-COLUMN` | the column under this floor |
| `stop` | `S-COLUMN_STOP` | a column running up from below that ends here — this floor's column |
| `start` | `S-COLUMN_START` | a column beginning here, so nothing stands under this floor; not drawn on it |
| `stub` | `S.STUB COL` | a stub column; marked `SC1`, `SC2`, … and sized from its own outline when untagged |

Where a `stop` outline and a plain one are drawn over each other, the plain one
is the floor
above's column and is dropped for this floor. Reported as `COLUMN_ABOVE_FLOOR`
and
`COLUMN_STARTS_ABOVE`.

Shaped walls (L, T, C, F) are cut into their rectangular legs so each can carry
the mark and
size the client wrote on it (`COLUMN_LEGS_SPLIT`). Each leg is cut as a whole
rectangle running
to the outside face, because that is how the client dimensions it; the corner
the two legs then
share is settled by the rule below. A shape that is not rectilinear is left
whole.

## Members butt, they do not overlap

Each leg of a shaped wall runs the full width of the wall, so at a corner or a T the two share
that square and the junction comes out doubled. The larger member is the one the client
dimensions, so it keeps its full length and the smaller is cut back to meet its face -- which is
the overlap, usually the larger member's width. This runs across the whole floor, because a C or
F shaped wall is as often drawn as several polylines as one.

A cut member is no longer the length its own tag states, so it takes its size from the drawing
and keeps its name (`COLUMN_LEG_TRIMMED`). Where the overlap is in the *middle* of a member
rather than at one end, both ends stick out: that is a crossing, not a junction, and it is left
for a human.

## A box round a tag is not an outline

A drafter boxing a slab tag leaves a closed polyline that looks exactly like a small slab; read
as one it closes a little panel of its own inside the bay it labels. What gives it away is how
tightly it fits the words, which `text_box_area_ratio` sets: a real slab holding its own tag is
orders of magnitude larger than the text, a box round it only a little larger.

## Sizes written on a dimension

A drafter who overrides a dimension's text with a size is stating that member's
section:
`{\H0.666667x;200x400}` on the dimension across a beam is how this client gives
a stepped beam
its two depths. Such an override is read as a beam size tag at the dimension's
text position; an
override with no size in it (`175mm\XEXPANSION JOINT`) is an ordinary annotation
and is left
alone. Test17 carries 512 of them. `dimension_tag_height_mm` is the text height
assumed when the
dimension states none, since how far a tag may sit from its member is measured
in text heights.

## A depth the schedule states as a rule

Two of Test17's beam schedule rows give a rule rather than a number:

| Row | Meaning |
| --- | --- |
| `300XSLB THK.` | a concealed beam, as deep as the slab it sits in and flush with it top and bottom |
| `200XAS/LAYOUT` | the plan says -- usually a dimension override |

The row is kept with its width and a `depth_rule`. `slab_thickness` is settled
in the normaliser,
once the panels around the beam exist; where the slabs either side differ, the
thicker wins.
`hidden_beam_reach_mm` sets how far around the beam a slab counts as the one it
sits in, and
`BEAM_NO_SLAB` reports a hidden beam with no slab thickness around it.

## Expansion joints

Lines on a layer with the `JOINT` role are barriers: no beam is merged along one
or paired
across one. A joint is around 175 mm wide, beams merge across gaps up to 800 mm,
and two 200 mm
beams either side of a joint present their outer faces 575 mm apart -- a
perfectly plausible beam
width -- so without this the client's two beams come out as one wrong beam
straddling the joint.

## Which witness wins: tag or outline

When the client's tag and their own outline disagree about a size,
`size_sources` decides which
is believed. `tag` (the default) takes the tag or schedule and falls back to the
outline; `outline`
measures the drawing and keeps the tag for the mark alone. Neither is right for
every client --
a firm that dimensions carefully wants the outline, one that keeps a maintained
schedule wants
the tag -- and the disagreement is reported either way, as
`COLUMN_SIZE_MISMATCH`.

```yaml
size_sources:
  column: tag        # or: outline
  beam: tag
  slab: tag
  footing: tag
```

In the drafter's window this is the **Column size from** box; only columns act
on it so far.

## Tolerances worth knowing

| Key | Default | Meaning |
| --- | --- | --- |
| `snap_mm` | 1 | end-point snapping when closing line loops |
| `ring_close_tol_mm` | 50 | close nearly-closed outline polylines up to this gap |
| `column_min_side_mm` / `column_max_side_mm` | 100 / 20000 | outline size window for columns |
| `beam_min_width_mm` / `beam_max_width_mm` | 100 / 1500 | edge-pair distance window |
| `beam_merge_gap_mm` | 800 | merge collinear edge pieces across crossing beams |
| `beam_min_length_mm` | 500 | shorter pairs are dropped |
| `grid_label_radius_mm` | 2500 | label search radius from grid line ends |
| `size_mismatch_tol_mm` | 26 | tag vs drawn comparison tolerance |
| `wall_like_min_side_ratio` / `wall_like_min_length_mm` | 4 / 1000 | what counts as a wall-like column |
