# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

The canonical JSON schema carries its own version (`schema_version` in every output).
A MAJOR bump of the schema means downstream utilities (DXF writer, Revit importer)
must be updated; a MINOR bump adds fields or element types; a PATCH bump fixes values.

## [0.11.0] - 2026-09-16

Each leg of a shaped wall is now its own element, and only the outlines that belong to a floor
are read from it. Normalised schema `0.7.0` → `0.8.0` (new field, no breaking change).

### Added

- **Shaped walls are cut into their legs** (answer 2). The client marks and sizes every leg of
  an L, T, C or F separately, so a wall kept whole could only hold one of those marks and the
  rest landed nowhere. The legs **overlap at the corner**, because both run to the outside face
  -- that is how the client dimensions them and how the walls meet in the model. Partitioning
  instead leaves one leg short of its own tag. Shapes that are not rectilinear are left whole.
  Test17: `COLUMN_MULTI_SIZE` 174 → 62, `MARK_FIT` 104 → 0.
- **A column's life is read from the layer** (answer 4). The template models the column below a
  floor level, so of the outlines drawn on one plan only some belong to that floor: a `start`
  outline is a column beginning here with nothing under this floor, and where a `stop` outline
  and a plain one are drawn over each other the plain one is the floor above's column.
  Reported as `COLUMN_STARTS_ABOVE` and `COLUMN_ABOVE_FLOOR`.
- **Untagged stub columns are `ST1`, `ST2`, …** (answer 2), sized from their own outline. Test17
  has 45 of them and the client tags none. `numbering.stub_prefix` sets the letter.

### Fixed

- **A wall drawn a fraction off square split into legs no one drew.** A client polyline is
  rarely exactly axis-aligned; squared up, a wall drawn 0.0003 degrees off leaves its two faces
  a few microns apart, and cutting on both made sliver cells that broke a leg into pieces. One
  Test17 wall came out as three legs, the third a 200 x 1620 ghost no mark could ever match.
  Cut lines closer together than a millimetre are now one line.

### Confirmed, not changed

- An untagged column already takes its stack's mark from whichever floor the client *did* tag,
  falling back to the next number free in the client's own numbering (answer 3). Its size
  already comes from the outline. Both now have tests.

## [0.10.0] - 2026-09-16

Columns and their marks, from the answers to the column questions. Extraction schema
`0.5.0` → `0.6.0`, normalised schema `0.6.0` → `0.7.0` (new fields, no breaking change).

### Fixed

- **Marks swapped between two legs of a wall.** Both marks are written in the gap between the
  legs, each sitting a few millimetres nearer the leg it does *not* name, and nearest-outline-
  wins takes them at face value. Nothing later notices: neither leg is bare and neither holds
  two, so there is nothing to rebalance. The size the client wrote on the tag now decides which
  member it names -- a far better witness than which outline the text happens to sit nearer.
  Test17 round trip: 531 → 485 warnings.
- **A leg left with no mark when freeing its tag takes a chain of moves.** Where a leg's only
  candidate is held by a neighbour that holds just the one, and that neighbour's own second
  candidate is held by a third element with two, feeding the first leg means moving the spare
  along the chain. A single rebalance pass cannot see that far. This is the augmenting step of
  bipartite matching, run only for the starved so every assignment the greedy got right is left
  alone; a tag written inside an element is never taken from it.

### Changed

- **Column marks go back inside, on the bounding-box centre** (answer 7), and step down a
  ladder of standard heights -- 100, 75, 50 mm -- until they fit. Heights come from a ladder,
  never a freely computed size: a drawing whose every mark is slightly different cannot be
  re-styled or edited as a set. A mark too long even at the smallest height shows its base
  alone, as a short beam span already did, with the size kept in the schedule and in the XDATA
  utility 4 reads back. Test17: 1760 marks at 100 mm, 17 at 75, 189 at 50, 52 showing the base
  alone; `MARK_FIT` 969 → 104.
- `placement.wall_mark` now defaults to `inside`; `beside` remains available.

### Added

- **Which witness wins is a setting** (answer 5): `size_sources.column` is `tag` (the client's
  stated size, the default) or `outline` (measure the drawing, keeping the tag for the mark).
  Exposed in the drafter's window as **Column size from**, and remembered between runs. The
  same setting exists for beams, slabs and footings; only columns act on it so far.
- `NColumn.mark_height_mm` -- the height the mark is drawn at, so the workbook, the drawing and
  Revit agree on it.

## [0.9.0] - 2026-09-16

Stabilising grids, columns, beams, slabs and their marks on Test17 before going further.
Normalised schema `0.5.0` → `0.6.0` (new field, no breaking change).

### Fixed

- **Grids: `T1` was being read as a grid.** This client writes the tower prefix on every grid
  bubble, so "T1" sat beside all 38 of them and won two lines as a label. A text written on
  most of a floor's bubbles names nothing and is now struck from the label pool before any
  line is named (`GRID_LABEL_QUALIFIER`, informational). Counting how often the text is
  *written* is what distinguishes it: counting the lines it merely sits beside also catches
  real labels, which are surrounded by their own leader, dimension and ticks.
- **Grids: dimension strings were being drawn as grids.** A dimension string down the margin
  is long enough to pass for a grid and borrows the nearest bubble's text, so grid `B` ran
  down the left margin instead of across the plan. A label names one line, so the lines
  claiming it are now arbitrated: a bubble off a line's own end beats a nearer one sitting
  across it, and the loser, having nothing else to be, is dropped.
- **Grids: `B` and `G` went missing on every floor.** Their real grid lines are 800 mm stubs,
  and short lines were being discarded *before* labels were settled — so a stub lost its
  bubble to any long line that happened to run past it. Length is now only consulted for a
  line that owns no bubble at all.
  Test17: 38 grids per floor with all 38 client labels and no spurious ones (was 31, then 41).
- **Shear wall marks ran over their neighbours.** `T1SW17-200X1500` rotated inside a 200 mm
  wall overflows it and collides with the beam marks alongside. Wall marks now go beside the
  wall on two lines, as the client draws them, and utility 4 recovers the whole mark from the
  two lines via XDATA. Test17: `MARK_FIT` 969 → 68.
- **A wall mark could show a third size.** The second line was built from the measured
  polyline while the mark stated the client's tagged size; where a client tag disagrees with
  their own geometry the drawing showed neither. The line now repeats the size the mark
  states, verbatim, and the disagreement is reported once as `RT_MARK_MISMATCH` rather than
  twice. Test17 round trip: 645 → 531 warnings, all of them genuine client inconsistencies.
- **Beam marks no longer overflow short spans.** A span too short for the full mark shows the
  mark alone; the size stays in the schedule and in the data.
- **Step lines are no longer slab edges**, which was over-classifying panels as cantilevers.
  Test17: 2485 → 1722 panels, every one of them carrying a thickness.
- **`wall_like` survived the round trip.** The re-read model had every shear wall back as an
  ordinary column. The rule now lives in one place (`geometry.is_wall_like`) and is applied
  to the drawing rather than read from XDATA, so entities added by hand are judged too.

### Changed

- Wall mark placement is decided in the normaliser, not the DXF writer, so the workbook, the
  drawing and Revit all place it identically. `NColumn` gains `mark_lines` (the lines as
  drawn), matching what `NFooting` already carried.
- New template spec settings: `placement.wall_mark` (`beside` | `inside`),
  `placement.wall_mark_gap_mm`, `placement.beam_mark_shorten`, and the `marks.column_wall` /
  `marks.beam_short` formats.

### Added

- `tools/audit_client.py` — coverage audit of the output against the client drawing, per
  floor, reading the client through the same code path as the extractor.
- `tools/compare_floor.py` — side-by-side render of the same bay from client and template.

## [0.8.0] - 2026-09-15

### Fixed (found by running Test17-clean in the firm)
- **Sunk hatches were never drawn.** An earlier edit had stranded the hatch code inside the
  fold loop, so a drawing without folds got no sunk hatching at all. Test17 now carries 480
  sunk regions on `CH-S-SLAB-SUNK`.
- **The legend was missing** unless a seed template was given, and then it was the seed's.
  The legend is now built from what the drawing actually uses (each sunk depth, slab at beam
  bottom, column stop, fold), one hatch pattern per depth from a palette, in the template's
  layout. `legend_from_seed: true` restores the old behaviour.
- **Staircases were thinned out.** Stair geometry went through the member de-duplication used
  for columns, so treads inside a flight outline were swallowed. Stairs are now carried
  through exactly as drawn: Test17 keeps all 44 flight outlines and every tread line.
- **Bracket beams were dropped.** A bracket is wider than it is long (200 wide, 50 long), so
  it failed both the minimum-span and the width tests. Short rectangles on a beam layer whose
  long side is a plausible beam width are now brackets, with the mark deciding which side is
  the width on the way back in. Test17 gains 310 bracket beams.
- Marked spans shorter than the minimum are kept (a 50 mm corbel is a real member); spans of
  zero length are always dropped.
- "Projection at beam bottom lvl." is treated as "slab at beam bottom".

### Added
- **The C2B window** (`c2b gui`, or `windows\C2B.bat`): pick a drawing, press Run, watch the
  three steps, read the issues in plain language, then open the template DXF, the workbooks or
  the folder. Settings are remembered. The worker is Tk-free and tested.
- **Utility 5, the Revit importer.** `c2b revit-plan` turns the normalised model into a build
  plan (`<name>.revit.json`) plus a workbook listing every family and type it will use, driven
  by an editable mapping file. A pyRevit button (`revit/C2B.extension`) executes that plan:
  levels, grids, columns, beams, floors with holes, foundations, PCC, piles, RCC walls and
  shaft openings. The script has not yet been run against a live Revit model.

## [0.7.0] - 2026-09-15

Everything needed to run utilities 1 to 4 on a firm machine without help.

### Added
- `c2b run <drawing>`: the whole pipeline in one command (extract, normalise, verify), with the
  level workbook picked up automatically on the second run.
- `c2b doctor`: checks Python, dependencies and DWG converters, then runs the entire pipeline on
  a built-in demo drawing and reports READY or the exact problem.
- `c2b demo`: writes a demo client drawing so the pipeline can be tried without client data;
  the same drawing backs the test suite (`c2b.demo`).
- Optional DWG input: ODA File Converter or AutoCAD `accoreconsole` is used when installed,
  otherwise a clear message says what to install or to save the DXF by hand.
- `windows\install.bat`, `windows\C2B-run.bat` (drag and drop a drawing), `windows\C2B-verify.bat`.
- `QUICKSTART.md`: install, prove the install, run the demo, run a client drawing, the working
  loop, what to expect, and a troubleshooting table.

## [0.6.0] - 2026-09-15

### Added
- Utility 4 (`c2b verify`): reads a template DXF back into the normalised model and verifies the
  round trip. Geometry and mark text are read from the drawing itself, so a drafter's edits are
  detected; the `C2B` XDATA supplies identity and the values a drawing cannot carry.
  Outputs `<stem>.reread.json`, `<stem>.reread.xlsx`, `<stem>.verify.xlsx` and `<stem>.verify.md`,
  and exits non-zero when differences are found.
- Round-trip findings: `RT_MISSING`, `RT_ADDED`, `RT_MOVED`, `RT_RESIZED`, `RT_MARK_CHANGED`,
  `RT_MARK_MISSING`, `RT_MARK_MISMATCH` (mark versus drawn geometry), `RT_DUP_MARK` (one mark
  naming two sections), `RT_COUNT`, `RT_LEVEL_CHANGED`, plus `RT_NO_ID` and `RT_ORPHAN_MARK`
  raised while reading.
- The floor origin is carried on the frame's XDATA, so a drawing whose origin falls outside its
  frame still reads back exactly.

### Changed
- Fold vertical slab thickness is taken only from the client's fold tag; nothing is assumed
  (`FOLD_THICKNESS_UNKNOWN` otherwise).
- Piles are never invented: only the ones the client drew, with the diameter they drew.
- Lift pit depth is measured from the floor's structural slab level.

## [0.5.0] - 2026-09-15

Third round of template answers (special elements):

### Added
- PCC (lean concrete) under footings, combined footings, rafts, pile caps and pits when the
  client mentions PCC: outline on `CH-S-PCC` offset by the projection, `PCC 100THK` line in the
  foundation mark; thickness and projection read from the client note.
- Slab folds like raft folds: legend "fold" regions inside a panel become hatched outlines on
  `CH-S-SLAB-FOLD` with a `1500 FOLD` mark; lower side inside; the fold record carries the
  vertical slab thickness for Revit.
- Lift pits (`LP`) with depth from a `... DEEP` text or a level text; pile caps on
  `CH-S-PILECAP` with a `n PILES dDIA` line; piles as circles on `CH-S-PILE` (round columns in Revit).
- Ramps: a `RAMP 1:8 UP` note inside a panel makes it a ramp on `CH-S-RAMP` with the slope and
  direction in the mark and the client's arrow line redrawn.
- RCC walls only are drawn; a wall under a beam gets its top at the beam bottom.
- Stairs: direction from DN/UP texts, tread lines counted (risers = treads + 1), landing assumed
  at half the floor height, all flagged `STAIR_ESTIMATED`.
- Level workbook gains a Settings sheet (`level_reference`) that wins over the spec.

### Changed
- Chajja / cantilever slab bottom aligns with the *smaller* adjacent beam depth (correction).
- Combined footings `CF` only when the client says combined (answer 8B).
- Cantilever slab thickness without a tag: neighbouring slab thickness, else 100 mm default.
- Extraction schema 0.5.0 (`ramp_hints`, `pcc_hints`, `stairs[].labels`), normalised schema
  0.5.0 (`folds`, `piles`, `level_reference`, PCC / pit / ramp / stair fields).

## [0.4.0] - 2026-09-15

### Added
- Cantilever / chajja panels closed by client slab edge lines (`CS` marks, bottom aligned with
  the supporting beam); client legend parsed into hatch-pattern meanings; sunk depth,
  slab-at-beam-bottom offset, column stop and cut-outs from hatched regions (tags win);
  interior cut-outs as panel holes; inverted beams (`-INV`, top offset); tapered cantilevers;
  footing kinds; stairs with waist mark; joints on `CH-JOINT`; SSL level reference.

## [0.3.0] - 2026-09-15

Conventions settled with the firm (twenty answers on the template):

### Changed
- Column marks sit inside the column, text along the longer side; beam marks run along the beam.
- Client column and beam marks are kept (`C32-400X750`, `T1SW51a-200X2850`, `MB-300X750`);
  generated numbers fill the gaps left by the client's numbering. Columns without client
  marks are numbered row by row from the bottom row (A1, A2 ... B1, B2 ...).
- Column marks quote the size in the client's order (b x D), not the plan orientation.
- Beams end at the centre of round, rotated or odd-shaped columns (zero-width cut, the two
  spans meet at the centre); axis-aligned rectangular columns still cut at their faces.
- Slab panels carry true arcs (bulges) around circular columns.
- A raft is one the client calls RF / RAFT / MAT (layer, tag or mark); the size rule is off.
- Client general notes are carried verbatim under each plan, followed by the generator note.

### Added
- `CH-S-BEAM-CL` centreline on every span.
- Level hints: level texts in client sections ("GROUND FLOOR LVL. +2.500", "FFL +3.000") are
  read into `level_hints` and pre-fill the level workbook (flagged "please confirm").
- Extraction schema 0.3.0 (`floors[].notes`, `level_hints`), normalised schema 0.3.0
  (`panels[].bulges`, `columns[].mark_rotation_deg`, `floors[].notes`).

## [0.2.0] - 2026-09-12

### Added
- Utility 3 (`c2b normalize`): normalises an extraction JSON to the firm's template.
  Column stacks across floors with one C-number per stack, beams split into spans at
  column faces and beam faces (shallower beam split at X crossings), slab panels as the
  holes of the beam/column lattice with thickness from the tags inside, footings and
  rafts with folds/sunk areas, grids with bubbles, cut-outs with X crosses, stairs carried
  through, level frame with dimensions, titles, notes and the legend copied from the seed.
- Template DXF writer that reuses the seed template's layers, styles, dimension style and
  legend; every entity carries XDATA `C2B` (`id=`, `mark=`, `client=`) for the round trip.
- `TemplateSpec` YAML with every template convention (layer names, mark formats, mark
  placement, numbering order, split rules, hatch legend, frame layout).
- Normalised schema 0.2.0 (`<stem>.normalized.json`) and schedules workbook.
- `tools/compare_with_template.py`: frame-by-frame IoU comparison against the reference
  template; `tools/render_dxf.py`.
- Extraction: cut-outs drawn as X crosses, stair geometry (`stairs` in the schema),
  polygonisation rounds coordinates to the snap grid (rafts drawn from open polylines).

### Changed
- Extraction schema 0.1.0 -> 0.2.0 (added `stairs`; backward compatible).
- Levels workbook may hold several level rows per plan floor (typical floors).

## [0.1.0] - 2026-09-12

### Added
- Step 1 of the C2B pipeline: DXF extraction with diagnostics (merged "checker" and "converter").
- Canonical JSON schema v0.1.0 (`floors`, `grids`, `columns`, `beams`, `slabs`, `footings`, `openings`, `walls`, `schedules`, `diagnostics`).
- Layer-role profiles with automatic suggestion from layer names and entity statistics (`c2b profile suggest`).
- Floor detection from `Boundary` polylines and `Origin` points, with floor-name detection from title blocks and level texts.
- Column extraction from closed polylines, hatches, circles, line loops and block references.
- Beam extraction by pairing parallel edge lines into centerline + width, with tag, schedule, layer-name and note-default size resolution.
- Grid, footing, slab-tag and opening extraction.
- Tag parser for metric and imperial sizes, marks, thickness, fold, sunk and inverted notation.
- Schedule table parser for text-grid schedules (Mark / b / h / Thk).
- Excel review workbook, review DXF overlay, diagnostics report and level-schedule template.
