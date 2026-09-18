# C2B — CAD to BIM

Automates the path from a client's 2D structural AutoCAD drawing to a native
Revit model.
This repository contains **steps 1 to 3 of the pipeline**: reading a client DXF,
classifying what is on it, extracting the structural elements into a canonical
JSON
schema with diagnostics, and normalising them into the firm's template drawing
(`CH-` layers, `C12-300X900` marks, spans between supports, slab panels, level
frame).

Version `0.17.0` (tool) — extraction schema `0.7.1`, normalised schema `0.10.1`.
See [CHANGELOG.md](CHANGELOG.md).

## Using it

Three steps, all of them in the window (`windows\C2B.bat`, or `c2b gui`):

1. Pick the client drawing, press **Run**.
2. Press **Set floor heights…**, type a height per floor, press **Save and run again**.
3. In Revit: **C2B → Import C2B model**, and pick the file the window names.

The window says which step you are on in one line at the bottom. Everything below is what
happens inside those three, and every part of it is also a command for anyone who wants one.
See [QUICKSTART.md](QUICKSTART.md) to install, and [docs/revit-run.md](docs/revit-run.md) for
the Revit half.

## Pipeline

| Utility | What it does | Command |
| --- | --- | --- |
| 1 + 2 | **Extract + check**: client DXF → canonical JSON, Excel review workbook, review DXF, diagnostics | `c2b extract`, since v0.1.0 |
| 3 | **Normalise**: column stacks, beam spans at supports, slab panels, template marks → template DXF + schedules | `c2b normalize`, since v0.5.0 |
| 4 | **Round trip**: template DXF → JSON + Excel again, verified against the normalised model | `c2b verify`, since v0.6.0 |
| 5 | **Revit importer**: JSON → build plan, checked against the Revit template → native columns, beams, floors, foundations → the model read back and compared | `c2b revit-plan`, pyRevit, `c2b revit-verify`, since v0.8.0 |
| 6 | Cross-check: quantities, supports, continuity | next |

The original plan had utility 2 as a separate "drawing checker" before
conversion. Checking a
drawing *is* parsing it, so utility 1 does both: the same run that extracts the
data produces
the error list, and the two can never disagree. The numbering is kept as the
firm knows it,
which is why there is no utility 2 of its own.

## What step 1 handles

Five real client drawings with five different conventions were used to build it:

- **Floors** side by side in model space, marked by a closed polyline on layer
  `Boundary`
  and a POINT on layer `Origin` (the firm's convention). Floor names are read
  from title
  block attributes or level texts. Without boundaries the whole drawing is one
  floor.
- **Layers** mapped to roles automatically from their names (`S-COLS`,
  `COL. SIZE`,
  `BEAM SIZES`, `01-STR-SLAB THK`, `B-200x400` …) with a confidence; a YAML
  profile can
  override any layer. Hidden-line layers (`-HDLN`) are recognised and skipped.
- **Columns** from closed polylines, hatches, circles, four-line loops and block
  references (blocks are exploded recursively; a block named `500X750` supplies
  its size).
- **Beams** from pairs of parallel edge lines merged across crossing beams,
  giving a
  centreline, drawn width and plan outline.
- **Grids** with labels from text, circles-plus-text or block attributes.
- **Footings, openings (cut-outs, shafts), walls** from closed outlines.
- **Slabs** as thickness tags (most drawings never draw slab panels) plus drawn
  outlines
  where they exist; drop panels, folds and projections are kept with a modifier.
- **Sizes** resolved in order: tag text → schedule table (Mark / b / h / Thk, or
  "size → marks" lists) → layer or block name → general note ("ALL BEAMS ARE
  750MM IN
  DEPTH U.N.O.") → drawn geometry. The source is recorded on every element.
- **Tags** in metric and imperial (`C_300 X 900`, `B6 (200X900/600)`, `C_600D`,
  `F3_750MM THK / 1500MM FOLD`, `1'-6" x 2'-0"`, `B6(INV.)`, `SUNK BY 75MM`). A
  mark
  text and a size text stacked on separate layers are paired into one tag before
  assignment.
- **Units**: `$INSUNITS` when present, otherwise a low-confidence guess that is
  reported;
  `--units mm|cm|m|in|ft` overrides.

## Install

**Windows:** double-click `windows\install.bat`, then `windows\C2B.bat` for the
window, or drag
a client DXF onto `windows\C2B-run.bat`. See [QUICKSTART.md](QUICKSTART.md).

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,render]"
c2b doctor          # checks the install and runs the whole pipeline on a demo drawing
```text

Requires Python 3.11+. Dependencies: ezdxf, shapely, pydantic, openpyxl, typer,
pyyaml
(matplotlib only for `c2b render`). DWG input needs the free ODA File Converter
or AutoCAD's
`accoreconsole`; otherwise save the DXF by hand.

## Usage

```bash
# everything in one command: extract, normalise to the template, verify the round trip
c2b run client.dxf --seed templates/CH-TEMPLATE.dxf

# or step by step:
# 1. look at the drawing: units, layers and the roles guessed for them
c2b inspect client.dxf

# 2. optional: write the guessed layer profile, edit it, reuse it for that client
c2b profile suggest client.dxf -o profiles/client-x.yaml

# 3. extract
c2b extract client.dxf -o out/client        # add -p profiles/client-x.yaml, -u ft, --levels levels.xlsx

# 4. optional: quick PNG per floor for a visual check
c2b render out/client/client.c2b.json

# 5. utility 3: fill out/client/client.levels.xlsx (elevations), then normalise to the template
c2b normalize out/client/client.c2b.json --seed templates/CH-TEMPLATE.dxf --levels out/client/client.levels.xlsx -o out/client
#    -> client.template.dxf, client.normalized.json, client.schedules.xlsx, client.template-spec.yaml
#    compare with the reference template:
python tools/compare_with_template.py out/client/client.template.dxf templates/CH-TEMPLATE.dxf
```

```bash
# 6. utility 4: read the template DXF back and verify it against the model
#    (run it again after the drafter has edited the DXF: every change is listed)
c2b verify out/client/client.template.dxf
#    -> client.reread.json, client.reread.xlsx, client.verify.xlsx, client.verify.md
```text

See `docs/template-spec.md` for what the normaliser does and how every template
convention is configured, `docs/round-trip.md` for the verification, and
[docs/revit-run.md](docs/revit-run.md) for the whole Revit round trip step by step.

`c2b extract` writes, for `client.dxf`:

| File | Purpose |
| --- | --- |
| `client.c2b.json` | canonical data, schema-versioned; input for every later step |
| `client.review.xlsx` | review workbook: Summary, Floors, Layers, Grids, Columns, Beams, Slabs, Footings, Openings, Walls, Schedules, Unassigned tags, Diagnostics |
| `client.review.dxf` | the extracted elements drawn back in the client's coordinates on `C2B-*` layers with element ids; overlay it on the original |
| `client.report.md` | diagnostics report grouped by code |
| `client.levels.xlsx` | level schedule template: fill `elevation_mm` and pass it back with `--levels` |
| `client.profile.yaml` | the layer profile actually used (auto + overrides), ready to edit |

## Human review after step 1

1. Open `client.review.xlsx` → **Diagnostics**. Errors block; warnings need a
  decision;
   infos are for awareness.
2. Open **Layers**. Anything with confidence `low`/`none` or role `UNKNOWN` that
  carries
   structural geometry gets a role in the profile YAML, then re-run.
3. Overlay `client.review.dxf` on the client drawing to spot missed or invented
  members.
4. Fill `client.levels.xlsx` (top-of-slab elevations) and re-run with
  `--levels`.

## Diagnostics codes

All codes are listed in `src/c2b/diagnostics.py` with their meaning. The most
common:

| Code | Meaning |
| --- | --- |
| `UNITS_GUESSED` | no `$INSUNITS`; confirm with `--units` |
| `LAYER_UNMAPPED` | a layer with geometry but no role |
| `COLUMN_NO_SIZE` / `BEAM_NO_DEPTH` / `FOOTING_NO_SIZE` / `SLAB_NO_THICKNESS` | missing data |
| `COLUMN_SIZE_MISMATCH` / `BEAM_WIDTH_MISMATCH` | tag disagrees with drawn geometry |
| `SCHEDULE_MARK_MISSING` / `SCHEDULE_PLAN_MISMATCH` | plan versus schedule |
| `TAG_UNASSIGNED` / `TAG_UNPARSED` | text nobody claimed or nobody understood |
| `BEAM_UNPAIRED_LINES` | beam-layer lines that did not form a beam |
| `NO_BOUNDARY` / `FLOOR_NO_ORIGIN` / `FLOOR_NO_LABEL` | floor conventions missing |

## Repository layout

```Text
src/c2b/
  schema.py        canonical models (pydantic)         docs/schema.md
  profile.py       layer roles, tolerances, YAML       docs/profiles.md
  diagnostics.py   every code with its meaning
  units.py         drawing units → mm
  tags.py          tag text parser
  geometry.py      shapely helpers: outlines, line pairing, snapping, leg splitting
  dxfio.py         ezdxf → primitives (blocks exploded, Z flattened)
  dwg.py           DWG → DXF via ODA File Converter / accoreconsole
  floors.py        Boundary/Origin floor detection, floor names
  schedules.py     text-grid schedule tables
  extract/         grids, columns, beams, slabs, footings, openings/walls, plus:
                     context.py    per-floor tag pool, legend zones, dimension overrides
                     associate.py  tag → element matching (bipartite, with augmenting)
                     legend.py     the client's hatch legend → meanings
                     outlines.py   closed shapes out of polylines, hatches, line loops
  pipeline.py      utility 1 orchestration
  normalize/       utility 3: spec, stacks, spans, naming, geometry, model    docs/template-spec.md
                     pipeline.py   phase order and the floor/level frame
                     columns.py    stacks → template columns and their marks
                     beams.py      spans → template beams, depths, marks
                     panels.py     slab panels, sunk areas, cut-outs, cantilevers
                     footings.py   footings, rafts, PCC, pile caps, lift pits
                     common.py     shared conversions and mark formatting
  roundtrip/       utility 4: read the template DXF back, diff it     docs/round-trip.md
  revit/           utility 5: element → family mapping, build plan, template check    docs/revit-run.md
                     template.py   the Revit template description and shared parameter file, read
                     verify.py     what Revit built, against what the plan asked for
  export/          JSON, Excel, review DXF, report, level schedule, template DXF, schedules workbook
  gui/             Tk window (app.py) over a Tk-free runner (runner.py)
  cli.py           typer CLI
tools/             compare_with_template.py (IoU check against the reference), compare_floor.py,
                   audit_client.py, render_dxf.py
tests/             unit tests + synthetic end-to-end drawing + sample integration
templates/         the firm's Revit template described in markdown, and its shared parameters
                   (the DXF template itself is not committed)
profiles/          client profiles (YAML)
samples/           client drawings (git-ignored)
```

## Known limits of v0.17.0

- Cantilever slabs, chajjas and balconies need the client's slab edge lines;
  without them a
  panel with a free edge cannot be closed.
- Sunk, beam-bottom, fold and column-stop meanings come from the client's
  legend; a drawing
  without a legend yields none of them.
- Folds, lift pits, pile caps, piles and ramps are built from tag and note
  recognition only
  and have not yet been validated on a client drawing that contains them.
- Stair riser counts and landing levels are estimates flagged for review.
- Column stacks are matched by plan overlap; a column that shifts more than 300
  mm
  between floors starts a new stack (reported as `STACK_ORPHAN`).
- Beams drawn as single centrelines (no edges) are not paired; they show up as
  `BEAM_UNPAIRED_LINES`.
- A beam mark the client's schedule does not carry, and that no tag or dimension
  sizes, keeps
  no depth (`BEAM_NO_DEPTH`): on Test17 that is marks B8 to B23 and LB1, 136
  spans.
- Two members that cross at their *middles* are left overlapping and reported.
  Only members
  meeting at an end — a corner or a T — are trimmed, because there the client's
  intent is
  unambiguous; a crossing is not.
- The Revit importer has still not been run against a live model. Both ends are checked
  against
  the template — the plan before it runs (`c2b revit-plan --template`) and the model after
  (`c2b revit-verify`) — so family, type and parameter names are known to be right and a
  quiet
  failure is caught, but the API calls themselves are unproven. See
  [docs/revit-run.md](docs/revit-run.md).
- Rotated floor plans (true north) are read as drawn; no per-floor rotation yet.
- Schedule tables drawn as real `TABLE` entities are not read (text grids are).
- Everything is rule based. Ambiguous cases are reported, not guessed.

## Versioning

Semantic versioning (`MAJOR.MINOR.PATCH`) on three things that move
independently:

| Version | Where | Bumped when |
| --- | --- | --- |
| tool | `c2b.__version__` | any release |
| extraction schema | `c2b.SCHEMA_VERSION`, `schema_version` in `<stem>.c2b.json` | a field is added (MINOR), removed or redefined (MAJOR), or its values corrected (PATCH) |
| normalised schema | `c2b.normalize.model.NORMALIZED_SCHEMA_VERSION`, `schema_version` in `<stem>.normalized.json` | same rules, for the template model |

Downstream steps pin the MAJOR of the schema they read, not the tool version:
the Revit
importer reads the normalised schema, the round trip reads both.
