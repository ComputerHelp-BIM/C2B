# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the
project follows [Semantic Versioning](https://semver.org/)
(`MAJOR.MINOR.PATCH`).

The canonical JSON schema carries its own version (`schema_version` in every
output).
A MAJOR bump of the schema means downstream utilities (DXF writer, Revit
importer)
must be updated; a MINOR bump adds fields or element types; a PATCH bump fixes
values.

## [0.18.1] - 2026-09-18

### Changed (0.18.1)

- **The CAD files are on Git LFS.** Every `.dxf`, `.dwg`, `.rvt`, `.rfa` and `.rte` is a pointer
  in the commit and a file on the LFS server. A DXF is text, so git *can* store it -- the
  problem is the next version of it: a structural drawing is tens of megabytes and an edit
  rewrites most of the file, so successive revisions cannot be packed against each other and
  each one adds its whole self to the history, for everyone, forever. A revision now costs a
  pointer, and a clone fetches only what it checks out.
- The client drawings and the firm's `CH-TEMPLATE.dxf` are committed, so a clone can run the
  tests and the demo without hunting for files. About 36 MB across seven files.
- **`docs/git-lfs.md`** -- installing it, cloning, fetching, pushing, adding a drawing, what it
  costs against GitHub's allowance, and what to do when a DXF turns out to be 130 bytes of text
  because LFS was not installed before the clone.

### Fixed (0.18.1)

- The sample drawings went into 0.18.0 as ordinary git blobs. Their `.gitignore` change had
  stopped excluding them and a `git add -A` swept them in, the same commit in which the decision
  was supposed to be left open. They are on LFS from here on; the blobs already in the branch
  pack to about 4 MB in total, which is less than a history rewrite would cost anyone holding a
  clone, so they stay.

## [0.18.0] - 2026-09-18

The second live run. The grids and the stacking were right; the beams were not, and the check
said the model matched the plan while they were not.

### Fixed (0.18.0)

- **Every floor's beams were built on top of each other at the ground.** Revit reads a beam's
  reference level off the curve it is drawn on, and the curve was drawn at elevation zero --
  `point()` defaults its height to nothing, and nobody had passed one. So 363 beams from seven
  floors landed in one place: 779 *"identical instances in the same place, this will result in
  double counting in schedules"* warnings, and a beam reporting `01 GROUND LVL.` as its
  reference level while its own `CH-LEVEL`, written from the plan, said the fifth floor.
  Everything placed by a point, a curve or a loop is now built at its level's elevation, and a
  beam's reference level is stated rather than left to Revit to infer.
- **A beam's offset was applied twice.** Its start and end level offsets carried the element's
  offset *and* so did the z offset, which places the section about that line. The reference line
  now sits on the level and the z offset does the placing, once.
- **The check called that model a match.** It counted elements, checked every type's size and
  every level's height, and never asked where an element actually ended up -- which is the one
  thing that was wrong. It now reads back the level each created element landed on and compares
  it with the level the plan gave it. The plan being right is not evidence that the model is.
- The `-1500` was the beam family's own default, not C2B's: setting the z justification and
  offset explicitly (0.17.0) was the right fix, and the screenshot confirms it now reads 0.

### Added (0.18.0)

- **The firm's template DXF is found rather than asked for**, the same way the Revit template
  description already was. It is in the repository now, so the window's *Our template* box can
  stay empty.
- A test that no function in the Revit script reads a name only `main()` defines. IronPython
  finds that halfway through building a model, or never.

## [0.17.0] - 2026-09-18

The first run against a live Revit model, on Test10. It built 852 elements and found four
things, three of them ours.

### Fixed (0.17.0)

- **The building came out as a staircase of floors marching across the site.** Every element is
  stored relative to the `Origin` point the firm draws inside each boundary -- that is what the
  point is for, and it is what says which spot of each plan is the same spot of the building.
  The planner added that origin back, putting every floor where its plan happens to sit on the
  client's sheet. Coordinates now stay floor-local, which is what stacks them: on Test10 a
  column stack went from seven plan positions to one, and the model from spread across the site
  to a 28 m footprint.
- **Every beam sat 1500 mm below its level, on every floor.** C2B set a beam's start and end
  level offsets and never touched its z justification or z offset, so the family's own defaults
  decided where it sat -- and `CH-Concrete-Rectangular-Beam` carries Top / -1500. The plan now
  states both: the top face flush with the level (the top of the structural slab), moved by the
  element's own offset, which is what carries an inverted beam up and a sunk one down.
  `beam_z_justification` and `beam_top_at_level` change it.
- **Thirteen of seventeen grids were lost: "Name must be unique".** A project started from the
  firm's template already holds its sample grids (1, 2, 3, A-E), and Revit will not have two
  grids of one name, so the client's were refused outright. The template's placeholder is now
  renamed out of the way and the client's grid created in its place; `grid_name_clash` can
  `reuse` or `skip` instead. The clash is also reported **before** the import, by name, since
  the template description already lists the grids the template carries.
- **The import's own check called 320 created columns none of them.** Its tally wrote
  `made["column"]` while the check read `columns`; half the call sites were singular and half
  plural. One rule now normalises the key where it is counted, and a test refuses a call site
  that spells it by hand.

### Changed (0.17.0)

- **The template now binds the firm's own names**, so the mapping stops carrying the pair that
  was there while the template and the shared parameter file disagreed. Marks go to
  `CH-ScheduleMark` and Revit's built-in `Mark`; the C2B id goes to `CH-ID`. On Test10 both were
  written on all 852 elements.
- **The level name is written to `CH-LEVEL`** on every element. The template binds it, their
  schedules read it, and C2B is the only thing in the chain that knows which level an element
  was built on.
- Build plan version `0.3.0`: an action carries `z_justification` and `z_offset_mm`, and the
  plan carries `grid_name_clash`, so where a member sits across its own section is decided in
  the place it can be tested rather than by whatever a family happens to carry.
- The template check reports grid-name clashes, and the window, the workbook and the CLI all
  name them.

## [0.16.0] - 2026-09-18

Three steps instead of eight, and no terminal. The pipeline was right and the way into it was
not: reaching a Revit model meant a spreadsheet, two command lines, a second tool and reading
three sheets to know what to do next. A drafter should pick a file and press a button.

### Changed (0.16.0)

- **The Run prepares the Revit model too.** Step 4 of 4 writes the build plan and checks it
  against the firm's Revit template, which it finds rather than asks for: beside the output,
  beside the drawing, or the one shipped with C2B. The command line still exists; nobody has to
  reach it.
- **Floor heights are typed in the window.** *Set floor heights…* lists the floors the drawing
  found, takes a height for each and runs again. It was the one thing the drawing cannot supply
  and the one thing that sent a drafter out to Excel, which is what turned one run into three.
  The button appears only when the heights are what is missing.
- **The window says what to do next, in one line.** A log of forty lines does not tell anyone
  which line is addressed to them, so the next step is said once, on its own strip: fill the
  heights, or open Revit and pick this file.
- **The import checks its own work.** It reads the model back before it reports, so Extract
  Template and a second command are no longer part of a normal run. It catches the three
  failures that look completely normal in the project browser: elements that failed while the
  rest carried on, a type duplicated that kept the size it was copied from, and a level that
  already existed at another height so everything on it sits wrong. `c2b revit-verify` stays,
  for looking at a model someone else imported.
- The import opens the file dialog where the last plan was picked, and names the project's
  display unit in the confirmation.
- `docs/revit-run.md` now opens with the three steps and a table of what you do and what you
  get. The detail is still there, below.

### Fixed (0.16.0)

- **A unit trap in the Revit script.** Revit stores every length in decimal feet whatever the
  project's units say, so a millimetre value handed straight to it is read as feet -- 300 mm
  becomes 91 m, and nothing complains. Every length was converted except one: `point(xy, z)`
  converted x and y and left z raw, half a function in two unit systems. It now takes
  millimetres for every axis, `to_mm()` exists for reading lengths back, and a test walks the
  script's syntax tree and fails if any bare number or `*_mm` value reaches a Revit call
  unconverted. Reverting the conversion on the level elevation makes that test fail, which is
  the point of it.

## [0.15.0] - 2026-09-18

Utility 5 closes its loop. The plan went into Revit and nothing came back out; now the model
is read back and compared with what was asked for, the same way utility 4 reads the template
DXF back.

### Added (0.15.0)

- **`c2b revit-verify <plan>.revit.json <project>-template.md`.** The firm's *Extract Template*
  tool describes any model, not only a template, so running it on the project after an import
  gives a description of what was actually built. Comparing that with the plan answers what
  nothing else can: whether every element was built, whether every type exists, whether each
  created type is the size the plan asked for, whether the levels are at their planned height
  and whether every grid label is there. It writes `<name>.revit-check.md`.
  Nothing in it talks to Revit -- it compares two files, so a fault can be diagnosed away from
  the Revit seat.
- The check that matters most is the type sizes. A `175 THK. RCC SLAB` duplicated from the 150
  and left 150 thick looks entirely normal in the project browser, and every floor of that type
  is wrong. Same for a level that already existed at a different elevation: the import keeps it,
  and everything hosted on it is built at the wrong height.
- **`docs/revit-run.md`** -- the guide to follow at a Revit seat. The one-time pyRevit setup,
  describing the template and keeping that description current, what to read in the workbook
  before importing, what the import reports (including where the marks went), reading the model
  back, and the four things to send when something breaks.

### Changed (0.15.0)

- The template description now also carries the **Categories** table, so a digest knows how many
  elements of each category a model holds. That is what makes a re-export of an imported project
  worth comparing against.
- `mark_params` and `id_params` lead with `CH-ScheduleMark` and `CH-ID`, the names the firm
  settled on. The older `S_ScheduleMark` and `ID` stay behind them, because a model built before
  that change still carries them and every name that exists is written either way.
- **The Revit tests no longer assert the contents of the firm's own template.** They are pinned
  against `tests/data/mini-template.md` instead, written by hand. The firm edits their template
  -- they moved the mark parameters to the `CH-` names -- and a template edit should not be a
  failing test. The real file keeps one smoke test: every family the mapping names must still
  be in it, which is the part that would actually break a project.

## [0.14.0] - 2026-09-17

Utility 5 against the firm's real Revit template. Every family name, type-name pattern and
dimension parameter in the mapping now exists in **R25_TEMPLATE**, and a plan can be checked
against that template before Revit is opened.

### Added (0.14.0)

- **The Revit template is read outside Revit.** A `.rvt` is a compound binary, so the mapping
  used to be names typed from memory. `c2b revit-plan --template <template>.md` reads the
  markdown the firm's *Extract Template* tool writes -- 260 families, 654 types, every type's
  driving dimensions, the levels, the grids and every parameter the model binds -- and answers
  three questions that otherwise surface halfway through a Revit run: which types the template
  already carries, whether every family the plan names is actually loaded, and whether the
  marks will survive.
- **Where a mark goes is now checked, not assumed.** R25_TEMPLATE binds `ID` and
  `S_ScheduleMark`; the firm's shared parameter file defines `CH-ID` and `CH-ScheduleMark`.
  They are not the same names. Revit accepts a write to a parameter nobody bound, drops the
  value and leaves a model that looks finished, so C2B writes every name that exists on the
  element and the Revit run reports which ones took. `--shared-params` reads the shared
  parameter file as well, because "not bound in this template" and "does not exist anywhere"
  look identical in Revit and have different fixes.
- **Types the template does not carry are created by duplication** -- and a duplicated system
  type is now given its thickness. A floor type named `175 THK. RCC SLAB` duplicated from
  `150 THK. RCC SLAB` was 150 thick, and nothing said so.
- **Two-depth beams reach the right family.** A mark like `B5-200X900/600` goes to
  `CH-Concrete-Step-Beam-Bottom` with `W`/`H`/`H1` set; inverted, it goes to the `-Top` family;
  a tapered cantilever goes to the tapered pair. Rectangular beams are unaffected.
- **Shear wall legs: `wall_like_as`.** A leg is a column in the drawing and in the schedule and
  C2B split it as one, so it stays a Structural Column by default, one Revit element per tagged
  leg. `wall_like_as: wall` models them as Basic Walls instead, along the leg's own longer side,
  and `wall_like_min_thickness_mm` keeps the thin ones as columns.
- **A type that is legitimate but odd is flagged rather than changed.** Test10's `CH-12300 X 300`
  is a 12 m shear wall leg modelled as a column, and its `CH-14700 X 30750 X 750` is a 452 m2
  raft the client never marked RF/RAFT/MAT. Both follow the firm's own rules; both are worth a
  glance before Revit makes the type.

### Fixed (0.14.0)

- **A mark read as a diameter.** `T1SW136d` is tower 1, shear wall 136, leg d. The tag parser
  read `136d` as a 136 mm diameter, gave the leg no width and no depth, and dropped it: thirteen
  of Test17's shear wall legs, on every floor they appear. `C_600D` is still a 600 dia column --
  the difference is that its digits do not run on from letters. A drawn rectangle now also
  refuses a tag diameter outright, whatever the tag says. **Test17 columns with no size: 13 → 0**,
  and 148 Revit actions that were being skipped are back.

### Changed (0.14.0)

- The mapping defaults are R25_TEMPLATE's names, not Autodesk's sample families, so on that
  template nothing needs editing before a first run.
- `templates/` now holds the template description and the shared parameter file. They are text,
  they are the contract the plan is checked against, and they belong in the repository; the DXF
  template itself still does not.
- Build plan version `0.2.0`: the plan carries the mark and id parameter names and the template
  check. Extraction schema `0.7.1` and normalised schema `0.10.1`: no field changed, but the
  thirteen columns above now carry the sizes their tags always stated.

## [0.13.2] - 2026-09-17

No change to what the tool produces: Test17 re-extracts and re-normalises to
the same JSON
down to the generator's version stamp, and rounds trips to the same 0 errors /
504 warnings.
This release is the code and the documentation catching up with 0.12 and 0.13.

### Changed (0.13.2)

- **`normalize/pipeline.py` split into one module per phase**: `columns.py`,
  `beams.py`,
  `panels.py`, `footings.py` and a shared `common.py`, leaving `pipeline.py`
  with the phase
  order and the frame (801 → 257 lines). It had grown into a single 726-line
  function where
  a slab rule and a footing rule sat twenty lines apart, which is how the
  floor-local
  coordinate bug in 0.12.1 survived two runs. Each extraction was verified by
  re-running
  Test17 and diffing the output field by field; the only difference across the
  whole file
  is the generator's version stamp.
- Every phase now takes the project, the model, the spec and the diagnostics
  list
  explicitly instead of closing over the pipeline's locals, so a phase can be
  read — and
  tested — on its own.

### Added (0.13.2)

- **ruff** configured in `pyproject.toml` (none had been). The ignores are
  listed with the
  reason for each: `B008` is typer's argument idiom, `E741` covers the `l`/`o`
  names in the
  geometry module where they mean line and offset, `RUF001` the en dashes in
  the drawing
  notes, `SIM108` an if/else whose branches each carry a comment.
  `ruff check src tests tools` is clean.
- What it found, none of which changes a result: three closures reading a
  variable from the
  loop around them (the row in the level reader, the regions and beam outlines
  in the panel
  builder) now bind it as a default argument, so a later edit cannot move the
  call out of
  the iteration and read the wrong floor's geometry — which is exactly the
  shape of the bug
  0.12.1 shipped; six loop variables that are never read, renamed; two pairs of
  nested `if`s
  merged; and `c2b run` raises its exit `from None`, since it has already
  printed the
  message and the traceback only hides it.

### Documentation (0.13.2)

- `docs/schema.md`: `Beam.depth_rule` was added to the schema in 0.13.0 but
  never written
  down; `source_layer` and `source_kind` were on every element and in no
  document.
- `docs/profiles.md`: the shaped-wall section still said the legs **overlap at
  the corner**,
  which 0.13.1 stopped being true two sections further down. A reader had two
  contradictory
  rules and no way to tell which was current.
- `README.md`: the package layout predated `roundtrip/`, `revit/` and `gui/`
  and described
  `normalize/` as one module; the versioning note described two version numbers
  where there
  are three (tool, extraction schema, normalised schema) and did not say which
  one a
  downstream step should pin. Two limits worth knowing were missing: a beam mark
  in no
  schedule row keeps no depth, and members crossing at their middles are left
  overlapping.
  Its pipeline table also numbered the steps 1 to 5 while every other page
  numbers the
  utilities as the firm does, so the round trip was step 3 in one table and
  utility 4 six
  lines below it. The table now carries the firm's numbers, and says outright
  that utility 2
  folded into utility 1.
- `QUICKSTART.md`: the "what to expect" figures were three releases old and
  listed three of
  the five client drawings. All five re-run: Test10, Test14, Test16, Test17,
  Test18. Install
  step 2 no longer checks out the working branch after cloning, since this
  release is on
  `main`.

## [0.13.1] - 2026-09-17

### Fixed

- **Slab panels overlapping completely.** A box the client draws round a slab tag is a closed
  polyline that looks exactly like a small slab, and read as one it closed a little panel of its
  own inside the bay it labels -- 50 pairs of panels sitting on top of each other on Test17, all
  of them 845 x 496 boxes round a `300THK. SLAB` tag. An outline that fits the text inside it
  that tightly is a box round that text, not a member. **Overlapping panel pairs: 50 → 0.**
- **Wall legs overlapping at their junctions.** Each leg runs the full width of the wall, so at
  a corner or a T the two shared that square and the smaller pushed into the larger by its own
  width. The larger member now keeps its full length and the smaller is cut back to meet its
  face. Test17's `T1SW135` wall comes out 200X5700, 200X2100 and 200X2300, against the client's
  own dimensions. **Overlapping column pairs: 71 → 9**, the nine being members crossing at their
  middles rather than meeting at an end, which are left for a human.
- A cut member takes its size from the drawing rather than its tag, since the tag states the
  length before the cut; it keeps its name. Test17 round trip: 535 → 504 warnings.

### Changed

- Junction trimming shortens a member along its own axis instead of subtracting one shape from
  the other. The client's rectangles are a fraction of a degree off square, so a boolean
  difference leaves a hairline sliver along the shared face and the remainder stops being a
  rectangle at all -- which is why the first attempt cut only some of the legs.

## [0.13.0] - 2026-09-17

Beam depths. Extraction schema `0.6.0` → `0.7.0`, normalised schema `0.9.0` →
`0.10.0`
(new fields, no breaking change). **Test17 spans with no depth: 575 → 136.**

### Added (0.13.0)

- **A size written on a dimension is a size.** A drafter who overrides a
- dimension's text with a
  section -- `{\H0.666667x;200x400}` across the beam -- is stating that member's
  size, and it is
  how this client gives a stepped beam its two depths. Those overrides are now
  read as beam size
  tags at the dimension's text position. An override with no size in it
  (`175mm\XEXPANSION JOINT`) is an ordinary annotation and is left alone. Test17
  has 512 of
  them, every one previously discarded; beams sized from a tag went 475 → 896.
- **`300XSLB THK.` is resolved.** A concealed beam is as deep as the slab it
- sits in, flush top
  and bottom. Which slab can only be answered once the panels exist, so the
  schedule carries the
  rule that far and the normaliser settles it; where the slabs either side
  differ, the thicker
  wins. Test17: 229 hidden beams sized from their slab, none left unresolved.

### Fixed (0.13.0)

- **Beams straddling an expansion joint.** A joint is 175 mm wide, beams merge
- across gaps up to
  800 mm, and two 200 mm beams either side of one present their outer faces 575
  mm apart -- a
  perfectly plausible beam width. So the client's two beams came out as a single
  wrong beam
  through the joint, and the B6s beside it were replaced by a B1 running across.
  Lines on a
  `JOINT` layer are now barriers: nothing is merged along one or paired across
  one, and a pair
  whose two faces are both joint lines (the gap itself) is rejected too.
- **A dimension's tag sat at its definition point and carried no text height**,
- so an overridden
  dimension read as a size tag had no reach at all. It now uses the text
  mid-point and the height
  from its own style, falling back to `dimension_tag_height_mm`.

## [0.12.1] - 2026-09-17

Hatching, from a look at the generated plans. Normalised schema `0.8.0` →
`0.9.0`
(new field, no breaking change).

### Fixed (0.12.1)

- **Chajjas came out as bare outlines.** A chajja sits at beam bottom level by
- its own rule
  (`cantilever_bottom_align`) and the client hatches it like any other slab at
  that level, but
  only `beam_bottom` and `projection` were being hatched. Test17: 243 → 967
  beam-bottom hatches.
- **The hatch ran straight across cut-outs**, burying the drafter's own cut-out
- symbol under the
  pattern. A panel's openings are now holes in its hatch. Test17: 76 hatches
  carry a hole.
- **Sunk areas far smaller than their panel were dropped.** A 250 mm sunk box
- covering under a
  hundredth of the bay it sits in failed the "half the panel" rule, and sinking
  the whole bay
  for it would have been wrong, so it went missing from the plan entirely. Such
  a region is now
  a *pocket*: it keeps its own outline, and only a panel sunk as a whole takes
  the full ring.
  All 480 of Test17's sunk regions now reach a panel that is drawn sunk (was
  432).

### Added (0.12.1)

- `NPanel.sunk_outlines` -- the rings of the sunk pockets in a panel; empty
- means the whole
  panel is sunk. `panels.pocket_inside` (0.6) sets how much of a region must lie
  in a panel to
  count as a pocket in it, and `PANEL_MULTI_SUNK` reports a panel holding
  pockets of more than
  one depth.

## [0.12.0] - 2026-09-17

### Fixed (0.12.0)

- **The client's legend was being read as structure.** The legend sits under the
- plan, inside
  the floor's own frame, and its swatches are drawn exactly like the thing they
  explain -- so
  the "COLUMN/SHEAR WALL END" swatch became a stub column (`SC1-581X1436`) and
  the "CUT-OUT"
  swatch became an opening, on every plan. The band each legend line occupies is
  now ruled out
  before anything is read as a member. Built from the legend *text*, because a
  cut-out swatch
  is a plain rectangle with no hatch to match it by. Test17: 3 phantom columns
  and 13 phantom
  openings gone.
- **The "projection at beam bottom" hatch was never drawn.** The panel
- registered the legend
  entry and then drew nothing, unlike the sunk hatch beside it, so those areas
  came out blank.
  Test17 now carries 243 of them (on `CH-HATCH`; the template has no layer of
  its own for it --
  `beam_bottom_hatch_layer` moves them when it gets one).
- **North-side chajjas were missing.** 0.9.0 stopped reading step lines as slab
- edges, which
  fixed whole bays being classified as cantilevers, but it also dropped the
  closed rings on the
  projection layer -- and a chajja hanging past the beam grid has no other edge
  to close
  against, so it was never built. What the modifier *means* now decides: a
  `projection` ring is
  an edge, a `drop`, `fold` or `sunk` ring is a level change inside a bay the
  beams already
  close, and an open line is a step whatever the layer. Test17: 55 → 724
  cantilever panels,
  panels 1722 → 2404, and `beam_bottom` offsets are back.

### Changed (0.12.0)

- **Mark heights: 50 mm, stepping down to 10 mm, for every mark** -- column,
- beam, slab, fold,
  footing, stair and wall, not just columns. Height is settled in the writer,
  once, since unlike
  position it is a drawing concern Revit does not read. Test17: 2080 marks at
  50, 12 at 40,
  2 at 20.
- **Hatch scale 20 → 10.** Both this and the text heights are the tool's
- defaults, not read
  from the seed template: the template supplies layers, text styles, dimension
  styles,
  linetypes and the legend.
- `text.column_mark_heights` is now `text.mark_heights`, since it is no longer
- column-only.

## [0.11.1] - 2026-09-17

### Fixed (0.11.1)

- **The Run button was off the window.** Adding the "Column size from" box in
- 0.10.0 put it in
  the same frame as the buttons, and that frame sits in one cell of the entry
  grid -- so the
  wider box pushed Run and "Re-check an edited template DXF" past the window
  edge, with nothing
  to scroll or wrap them back into view. The buttons now have their own strip on
  the window,
  where no option box can reach them, and the option labels are short enough to
  leave room.
- **Untagged stub columns are `SC1`, `SC2`, … not `ST`.** `ST` is already the
- stair mark
  (`marks.stair` is `ST{n}-{thk}THK`), so the two series would have collided.
- A "Column size from" choice saved by an older build no longer reads as the
- *opposite* setting.
  The window stores the label it showed, and an earlier build's label ("tag or
  schedule
  (client's intent)") did not match the current first option, so it fell through
  to "outline" --
  sizing every column off the drawing instead of the client's tag. Labels now
  map to values
  explicitly, and one we no longer offer falls back to the default.

## [0.11.0] - 2026-09-16

Each leg of a shaped wall is now its own element, and only the outlines that
belong to a floor
are read from it. Normalised schema `0.7.0` → `0.8.0` (new field, no breaking
change).

### Added (0.11.0)

- **Shaped walls are cut into their legs** (answer 2). The client marks and
- sizes every leg of
  an L, T, C or F separately, so a wall kept whole could only hold one of those
  marks and the
  rest landed nowhere. The legs **overlap at the corner**, because both run to
  the outside face
  -- that is how the client dimensions them and how the walls meet in the model.
  Partitioning
  instead leaves one leg short of its own tag. Shapes that are not rectilinear
  are left whole.
  Test17: `COLUMN_MULTI_SIZE` 174 → 62, `MARK_FIT` 104 → 0.
- **A column's life is read from the layer** (answer 4). The template models the
- column below a
  floor level, so of the outlines drawn on one plan only some belong to that
  floor: a `start`
  outline is a column beginning here with nothing under this floor, and where a
  `stop` outline
  and a plain one are drawn over each other the plain one is the floor above's
  column.
  Reported as `COLUMN_STARTS_ABOVE` and `COLUMN_ABOVE_FLOOR`.
- **Untagged stub columns are `ST1`, `ST2`, …** (answer 2), sized from their own
- outline. Test17
  has 45 of them and the client tags none. `numbering.stub_prefix` sets the
  letter.

### Fixed (0.11.0)

- **A wall drawn a fraction off square split into legs no one drew.** A client
- polyline is
  rarely exactly axis-aligned; squared up, a wall drawn 0.0003 degrees off
  leaves its two faces
  a few microns apart, and cutting on both made sliver cells that broke a leg
  into pieces. One
  Test17 wall came out as three legs, the third a 200 x 1620 ghost no mark could
  ever match.
  Cut lines closer together than a millimetre are now one line.

### Confirmed, not changed

- An untagged column already takes its stack's mark from whichever floor the
- client *did* tag,
  falling back to the next number free in the client's own numbering (answer 3).
  Its size
  already comes from the outline. Both now have tests.

## [0.10.0] - 2026-09-16

Columns and their marks, from the answers to the column questions. Extraction
schema
`0.5.0` → `0.6.0`, normalised schema `0.6.0` → `0.7.0` (new fields, no breaking
change).

### Fixed (0.10.0)

- **Marks swapped between two legs of a wall.** Both marks are written in the
- gap between the
  legs, each sitting a few millimetres nearer the leg it does *not* name, and
  nearest-outline-
  wins takes them at face value. Nothing later notices: neither leg is bare and
  neither holds
  two, so there is nothing to rebalance. The size the client wrote on the tag
  now decides which
  member it names -- a far better witness than which outline the text happens to
  sit nearer.
  Test17 round trip: 531 → 485 warnings.
- **A leg left with no mark when freeing its tag takes a chain of moves.** Where
- a leg's only
  candidate is held by a neighbour that holds just the one, and that neighbour's
  own second
  candidate is held by a third element with two, feeding the first leg means
  moving the spare
  along the chain. A single rebalance pass cannot see that far. This is the
  augmenting step of
  bipartite matching, run only for the starved so every assignment the greedy
  got right is left
  alone; a tag written inside an element is never taken from it.

### Changed (0.10.0)

- **Column marks go back inside, on the bounding-box centre** (answer 7), and
- step down a
  ladder of standard heights -- 100, 75, 50 mm -- until they fit. Heights come
  from a ladder,
  never a freely computed size: a drawing whose every mark is slightly different
  cannot be
  re-styled or edited as a set. A mark too long even at the smallest height
  shows its base
  alone, as a short beam span already did, with the size kept in the schedule
  and in the XDATA
  utility 4 reads back. Test17: 1760 marks at 100 mm, 17 at 75, 189 at 50, 52
  showing the base
  alone; `MARK_FIT` 969 → 104.
- `placement.wall_mark` now defaults to `inside`; `beside` remains available.

### Added (0.10.0)

- **Which witness wins is a setting** (answer 5): `size_sources.column` is `tag`
- (the client's
  stated size, the default) or `outline` (measure the drawing, keeping the tag
  for the mark).
  Exposed in the drafter's window as **Column size from**, and remembered
  between runs. The
  same setting exists for beams, slabs and footings; only columns act on it so
  far.
- `NColumn.mark_height_mm` -- the height the mark is drawn at, so the workbook,
- the drawing and
  Revit agree on it.

## [0.9.0] - 2026-09-16

Stabilising grids, columns, beams, slabs and their marks on Test17 before going
further.
Normalised schema `0.5.0` → `0.6.0` (new field, no breaking change).

### Fixed (0.9.0)

- **Grids: `T1` was being read as a grid.** This client writes the tower prefix
- on every grid
  bubble, so "T1" sat beside all 38 of them and won two lines as a label. A text
  written on
  most of a floor's bubbles names nothing and is now struck from the label pool
  before any
  line is named (`GRID_LABEL_QUALIFIER`, informational). Counting how often the
  text is
  *written* is what distinguishes it: counting the lines it merely sits beside
  also catches
  real labels, which are surrounded by their own leader, dimension and ticks.
- **Grids: dimension strings were being drawn as grids.** A dimension string
- down the margin
  is long enough to pass for a grid and borrows the nearest bubble's text, so
  grid `B` ran
  down the left margin instead of across the plan. A label names one line, so
  the lines
  claiming it are now arbitrated: a bubble off a line's own end beats a nearer
  one sitting
  across it, and the loser, having nothing else to be, is dropped.
- **Grids: `B` and `G` went missing on every floor.** Their real grid lines are
- 800 mm stubs,
  and short lines were being discarded *before* labels were settled — so a stub
  lost its
  bubble to any long line that happened to run past it. Length is now only
  consulted for a
  line that owns no bubble at all.
  Test17: 38 grids per floor with all 38 client labels and no spurious ones (was
  31, then 41).
- **Shear wall marks ran over their neighbours.** `T1SW17-200X1500` rotated
- inside a 200 mm
  wall overflows it and collides with the beam marks alongside. Wall marks now
  go beside the
  wall on two lines, as the client draws them, and utility 4 recovers the whole
  mark from the
  two lines via XDATA. Test17: `MARK_FIT` 969 → 68.
- **A wall mark could show a third size.** The second line was built from the
- measured
  polyline while the mark stated the client's tagged size; where a client tag
  disagrees with
  their own geometry the drawing showed neither. The line now repeats the size
  the mark
  states, verbatim, and the disagreement is reported once as `RT_MARK_MISMATCH`
  rather than
  twice. Test17 round trip: 645 → 531 warnings, all of them genuine client
  inconsistencies.
- **Beam marks no longer overflow short spans.** A span too short for the full
- mark shows the
  mark alone; the size stays in the schedule and in the data.
- **Step lines are no longer slab edges**, which was over-classifying panels as
- cantilevers.
  Test17: 2485 → 1722 panels, every one of them carrying a thickness.
- **`wall_like` survived the round trip.** The re-read model had every shear
- wall back as an
  ordinary column. The rule now lives in one place (`geometry.is_wall_like`) and
  is applied
  to the drawing rather than read from XDATA, so entities added by hand are
  judged too.

### Changed (0.9.0)

- Wall mark placement is decided in the normaliser, not the DXF writer, so the
- workbook, the
  drawing and Revit all place it identically. `NColumn` gains `mark_lines` (the
  lines as
  drawn), matching what `NFooting` already carried.
- New template spec settings: `placement.wall_mark` (`beside` | `inside`),
  `placement.wall_mark_gap_mm`, `placement.beam_mark_shorten`, and the
  `marks.column_wall` /
  `marks.beam_short` formats.

### Added (0.9.0)

- `tools/audit_client.py` — coverage audit of the output against the client
- drawing, per
  floor, reading the client through the same code path as the extractor.
- `tools/compare_floor.py` — side-by-side render of the same bay from client and
- template.

## [0.8.0] - 2026-09-15

### Fixed (found by running Test17-clean in the firm)

- **Sunk hatches were never drawn.** An earlier edit had stranded the hatch code
- inside the
  fold loop, so a drawing without folds got no sunk hatching at all. Test17 now
  carries 480
  sunk regions on `CH-S-SLAB-SUNK`.
- **The legend was missing** unless a seed template was given, and then it was
- the seed's.
  The legend is now built from what the drawing actually uses (each sunk depth,
  slab at beam
  bottom, column stop, fold), one hatch pattern per depth from a palette, in the
  template's
  layout. `legend_from_seed: true` restores the old behaviour.
- **Staircases were thinned out.** Stair geometry went through the member
- de-duplication used
  for columns, so treads inside a flight outline were swallowed. Stairs are now
  carried
  through exactly as drawn: Test17 keeps all 44 flight outlines and every tread
  line.
- **Bracket beams were dropped.** A bracket is wider than it is long (200 wide,
- 50 long), so
  it failed both the minimum-span and the width tests. Short rectangles on a
  beam layer whose
  long side is a plausible beam width are now brackets, with the mark deciding
  which side is
  the width on the way back in. Test17 gains 310 bracket beams.
- Marked spans shorter than the minimum are kept (a 50 mm corbel is a real
- member); spans of
  zero length are always dropped.
- "Projection at beam bottom lvl." is treated as "slab at beam bottom".

### Added (0.8.0)

- **The C2B window** (`c2b gui`, or `windows\C2B.bat`): pick a drawing, press
- Run, watch the
  three steps, read the issues in plain language, then open the template DXF,
  the workbooks or
  the folder. Settings are remembered. The worker is Tk-free and tested.
- **Utility 5, the Revit importer.** `c2b revit-plan` turns the normalised model
- into a build
  plan (`<name>.revit.json`) plus a workbook listing every family and type it
  will use, driven
  by an editable mapping file. A pyRevit button (`revit/C2B.extension`) executes
  that plan:
  levels, grids, columns, beams, floors with holes, foundations, PCC, piles, RCC
  walls and
  shaft openings. The script has not yet been run against a live Revit model.

## [0.7.0] - 2026-09-15

Everything needed to run utilities 1 to 4 on a firm machine without help.

### Added (0.7.0)

- `c2b run <drawing>`: the whole pipeline in one command (extract, normalise,
- verify), with the
  level workbook picked up automatically on the second run.
- `c2b doctor`: checks Python, dependencies and DWG converters, then runs the
- entire pipeline on
  a built-in demo drawing and reports READY or the exact problem.
- `c2b demo`: writes a demo client drawing so the pipeline can be tried without
- client data;
  the same drawing backs the test suite (`c2b.demo`).
- Optional DWG input: ODA File Converter or AutoCAD `accoreconsole` is used when
- installed,
  otherwise a clear message says what to install or to save the DXF by hand.
- `windows\install.bat`, `windows\C2B-run.bat` (drag and drop a drawing),
- `windows\C2B-verify.bat`.
- `QUICKSTART.md`: install, prove the install, run the demo, run a client
- drawing, the working
  loop, what to expect, and a troubleshooting table.

## [0.6.0] - 2026-09-15

### Added (0.6.0)

- Utility 4 (`c2b verify`): reads a template DXF back into the normalised model
- and verifies the
  round trip. Geometry and mark text are read from the drawing itself, so a
  drafter's edits are
  detected; the `C2B` XDATA supplies identity and the values a drawing cannot
  carry.
  Outputs `<stem>.reread.json`, `<stem>.reread.xlsx`, `<stem>.verify.xlsx` and
  `<stem>.verify.md`,
  and exits non-zero when differences are found.
- Round-trip findings: `RT_MISSING`, `RT_ADDED`, `RT_MOVED`, `RT_RESIZED`,
- `RT_MARK_CHANGED`,
  `RT_MARK_MISSING`, `RT_MARK_MISMATCH` (mark versus drawn geometry),
  `RT_DUP_MARK` (one mark
  naming two sections), `RT_COUNT`, `RT_LEVEL_CHANGED`, plus `RT_NO_ID` and
  `RT_ORPHAN_MARK`
  raised while reading.
- The floor origin is carried on the frame's XDATA, so a drawing whose origin
- falls outside its
  frame still reads back exactly.

### Changed (0.6.0)

- Fold vertical slab thickness is taken only from the client's fold tag; nothing
- is assumed
  (`FOLD_THICKNESS_UNKNOWN` otherwise).
- Piles are never invented: only the ones the client drew, with the diameter
- they drew.
- Lift pit depth is measured from the floor's structural slab level.

## [0.5.0] - 2026-09-15

Third round of template answers (special elements):

### Added (0.5.0)

- PCC (lean concrete) under footings, combined footings, rafts, pile caps and
- pits when the
  client mentions PCC: outline on `CH-S-PCC` offset by the projection,
  `PCC 100THK` line in the
  foundation mark; thickness and projection read from the client note.
- Slab folds like raft folds: legend "fold" regions inside a panel become
- hatched outlines on
  `CH-S-SLAB-FOLD` with a `1500 FOLD` mark; lower side inside; the fold record
  carries the
  vertical slab thickness for Revit.
- Lift pits (`LP`) with depth from a `... DEEP` text or a level text; pile caps
- on
  `CH-S-PILECAP` with a `n PILES dDIA` line; piles as circles on `CH-S-PILE`
  (round columns in Revit).
- Ramps: a `RAMP 1:8 UP` note inside a panel makes it a ramp on `CH-S-RAMP` with
- the slope and
  direction in the mark and the client's arrow line redrawn.
- RCC walls only are drawn; a wall under a beam gets its top at the beam bottom.
- Stairs: direction from DN/UP texts, tread lines counted (risers = treads + 1),
- landing assumed
  at half the floor height, all flagged `STAIR_ESTIMATED`.
- Level workbook gains a Settings sheet (`level_reference`) that wins over the
- spec.

### Changed (0.5.0)

- Chajja / cantilever slab bottom aligns with the *smaller* adjacent beam depth
- (correction).
- Combined footings `CF` only when the client says combined (answer 8B).
- Cantilever slab thickness without a tag: neighbouring slab thickness, else 100
- mm default.
- Extraction schema 0.5.0 (`ramp_hints`, `pcc_hints`, `stairs[].labels`),
- normalised schema
  0.5.0 (`folds`, `piles`, `level_reference`, PCC / pit / ramp / stair fields).

## [0.4.0] - 2026-09-15

### Added (0.4.0)

- Cantilever / chajja panels closed by client slab edge lines (`CS` marks,
- bottom aligned with
  the supporting beam); client legend parsed into hatch-pattern meanings; sunk
  depth,
  slab-at-beam-bottom offset, column stop and cut-outs from hatched regions
  (tags win);
  interior cut-outs as panel holes; inverted beams (`-INV`, top offset); tapered
  cantilevers;
  footing kinds; stairs with waist mark; joints on `CH-JOINT`; SSL level
  reference.

## [0.3.0] - 2026-09-15

Conventions settled with the firm (twenty answers on the template):

### Changed (0.3.0)

- Column marks sit inside the column, text along the longer side; beam marks run
- along the beam.
- Client column and beam marks are kept (`C32-400X750`, `T1SW51a-200X2850`,
- `MB-300X750`);
  generated numbers fill the gaps left by the client's numbering. Columns
  without client
  marks are numbered row by row from the bottom row (A1, A2 ... B1, B2 ...).
- Column marks quote the size in the client's order (b x D), not the plan
- orientation.
- Beams end at the centre of round, rotated or odd-shaped columns (zero-width
- cut, the two
  spans meet at the centre); axis-aligned rectangular columns still cut at their
  faces.
- Slab panels carry true arcs (bulges) around circular columns.
- A raft is one the client calls RF / RAFT / MAT (layer, tag or mark); the size
- rule is off.
- Client general notes are carried verbatim under each plan, followed by the
- generator note.

### Added (0.3.0)

- `CH-S-BEAM-CL` centreline on every span.
- Level hints: level texts in client sections ("GROUND FLOOR LVL. +2.500", "FFL
- +3.000") are
  read into `level_hints` and pre-fill the level workbook (flagged "please
  confirm").
- Extraction schema 0.3.0 (`floors[].notes`, `level_hints`), normalised schema
- 0.3.0
  (`panels[].bulges`, `columns[].mark_rotation_deg`, `floors[].notes`).

## [0.2.0] - 2026-09-12

### Added (0.2.0)

- Utility 3 (`c2b normalize`): normalises an extraction JSON to the firm's
- template.
  Column stacks across floors with one C-number per stack, beams split into
  spans at
  column faces and beam faces (shallower beam split at X crossings), slab panels
  as the
  holes of the beam/column lattice with thickness from the tags inside, footings
  and
  rafts with folds/sunk areas, grids with bubbles, cut-outs with X crosses,
  stairs carried
  through, level frame with dimensions, titles, notes and the legend copied from
  the seed.
- Template DXF writer that reuses the seed template's layers, styles, dimension
- style and
  legend; every entity carries XDATA `C2B` (`id=`, `mark=`, `client=`) for the
  round trip.
- `TemplateSpec` YAML with every template convention (layer names, mark formats,
- mark
  placement, numbering order, split rules, hatch legend, frame layout).
- Normalised schema 0.2.0 (`<stem>.normalized.json`) and schedules workbook.
- `tools/compare_with_template.py`: frame-by-frame IoU comparison against the
- reference
  template; `tools/render_dxf.py`.
- Extraction: cut-outs drawn as X crosses, stair geometry (`stairs` in the
- schema),
  polygonisation rounds coordinates to the snap grid (rafts drawn from open
  polylines).

### Changed (0.2.0)

- Extraction schema 0.1.0 -> 0.2.0 (added `stairs`; backward compatible).
- Levels workbook may hold several level rows per plan floor (typical floors).

## [0.1.0] - 2026-09-12

### Added (0.1.0)

- Step 1 of the C2B pipeline: DXF extraction with diagnostics (merged "checker"
- and "converter").
- Canonical JSON schema v0.1.0 (`floors`, `grids`, `columns`, `beams`, `slabs`,
- `footings`, `openings`, `walls`, `schedules`, `diagnostics`).
- Layer-role profiles with automatic suggestion from layer names and entity
- statistics (`c2b profile suggest`).
- Floor detection from `Boundary` polylines and `Origin` points, with floor-name
- detection from title blocks and level texts.
- Column extraction from closed polylines, hatches, circles, line loops and
- block references.
- Beam extraction by pairing parallel edge lines into centerline + width, with
- tag, schedule, layer-name and note-default size resolution.
- Grid, footing, slab-tag and opening extraction.
- Tag parser for metric and imperial sizes, marks, thickness, fold, sunk and
- inverted notation.
- Schedule table parser for text-grid schedules (Mark / b / h / Thk).
- Excel review workbook, review DXF overlay, diagnostics report and
- level-schedule template.
