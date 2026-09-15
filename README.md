# C2B — CAD to BIM

Automates the path from a client's 2D structural AutoCAD drawing to a native Revit model.
This repository contains **steps 1 to 3 of the pipeline**: reading a client DXF,
classifying what is on it, extracting the structural elements into a canonical JSON
schema with diagnostics, and normalising them into the firm's template drawing
(`CH-` layers, `C12-300X900` marks, spans between supports, slab panels, level frame).

Version `0.6.0` (tool) — extraction schema `0.5.0`, normalised schema `0.5.0`. See [CHANGELOG.md](CHANGELOG.md).

## Pipeline

| Step | Utility | Status |
|---|---|---|
| 1 | **Extract + check**: client DXF → canonical JSON, Excel review workbook, review DXF, diagnostics | `c2b extract`, v0.1.0 |
| 2 | **Normalise**: column stacks, beam spans at supports, slab panels, template marks → template DXF + schedules | `c2b normalize`, v0.5.0 |
| 3 | **Round trip**: template DXF → JSON + Excel again, verified against the normalised model | `c2b verify`, v0.6.0 |
| 4 | **Revit importer**: JSON → build plan → native columns, beams, floors, foundations | `c2b revit-plan` + pyRevit, v0.8.0 |
| 5 | Cross-check: quantities, supports, continuity | next |

The original plan had a separate "drawing checker" before conversion. Checking a drawing
*is* parsing it, so step 1 does both: the same run that extracts the data produces the
error list, and the two can never disagree.

## What step 1 handles

Five real client drawings with five different conventions were used to build it:

- **Floors** side by side in model space, marked by a closed polyline on layer `Boundary`
  and a POINT on layer `Origin` (the firm's convention). Floor names are read from title
  block attributes or level texts. Without boundaries the whole drawing is one floor.
- **Layers** mapped to roles automatically from their names (`S-COLS`, `COL. SIZE`,
  `BEAM SIZES`, `01-STR-SLAB THK`, `B-200x400` …) with a confidence; a YAML profile can
  override any layer. Hidden-line layers (`-HDLN`) are recognised and skipped.
- **Columns** from closed polylines, hatches, circles, four-line loops and block
  references (blocks are exploded recursively; a block named `500X750` supplies its size).
- **Beams** from pairs of parallel edge lines merged across crossing beams, giving a
  centreline, drawn width and plan outline.
- **Grids** with labels from text, circles-plus-text or block attributes.
- **Footings, openings (cut-outs, shafts), walls** from closed outlines.
- **Slabs** as thickness tags (most drawings never draw slab panels) plus drawn outlines
  where they exist; drop panels, folds and projections are kept with a modifier.
- **Sizes** resolved in order: tag text → schedule table (Mark / b / h / Thk, or
  "size → marks" lists) → layer or block name → general note ("ALL BEAMS ARE 750MM IN
  DEPTH U.N.O.") → drawn geometry. The source is recorded on every element.
- **Tags** in metric and imperial (`C_300 X 900`, `B6 (200X900/600)`, `C_600D`,
  `F3_750MM THK / 1500MM FOLD`, `1'-6" x 2'-0"`, `B6(INV.)`, `SUNK BY 75MM`). A mark
  text and a size text stacked on separate layers are paired into one tag before
  assignment.
- **Units**: `$INSUNITS` when present, otherwise a low-confidence guess that is reported;
  `--units mm|cm|m|in|ft` overrides.

## Install

**Windows:** double-click `windows\install.bat`, then `windows\C2B.bat` for the window, or drag
a client DXF onto `windows\C2B-run.bat`. See [QUICKSTART.md](QUICKSTART.md).

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,render]"
c2b doctor          # checks the install and runs the whole pipeline on a demo drawing
```

Requires Python 3.11+. Dependencies: ezdxf, shapely, pydantic, openpyxl, typer, pyyaml
(matplotlib only for `c2b render`). DWG input needs the free ODA File Converter or AutoCAD's
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
```

See `docs/template-spec.md` for what the normaliser does and how every template
convention is configured, and `docs/round-trip.md` for the verification.

`c2b extract` writes, for `client.dxf`:

| File | Purpose |
|---|---|
| `client.c2b.json` | canonical data, schema-versioned; input for every later step |
| `client.review.xlsx` | review workbook: Summary, Floors, Layers, Grids, Columns, Beams, Slabs, Footings, Openings, Walls, Schedules, Unassigned tags, Diagnostics |
| `client.review.dxf` | the extracted elements drawn back in the client's coordinates on `C2B-*` layers with element ids; overlay it on the original |
| `client.report.md` | diagnostics report grouped by code |
| `client.levels.xlsx` | level schedule template: fill `elevation_mm` and pass it back with `--levels` |
| `client.profile.yaml` | the layer profile actually used (auto + overrides), ready to edit |

## Human review after step 1

1. Open `client.review.xlsx` → **Diagnostics**. Errors block; warnings need a decision;
   infos are for awareness.
2. Open **Layers**. Anything with confidence `low`/`none` or role `UNKNOWN` that carries
   structural geometry gets a role in the profile YAML, then re-run.
3. Overlay `client.review.dxf` on the client drawing to spot missed or invented members.
4. Fill `client.levels.xlsx` (top-of-slab elevations) and re-run with `--levels`.

## Diagnostics codes

All codes are listed in `src/c2b/diagnostics.py` with their meaning. The most common:

| Code | Meaning |
|---|---|
| `UNITS_GUESSED` | no `$INSUNITS`; confirm with `--units` |
| `LAYER_UNMAPPED` | a layer with geometry but no role |
| `COLUMN_NO_SIZE` / `BEAM_NO_DEPTH` / `FOOTING_NO_SIZE` / `SLAB_NO_THICKNESS` | missing data |
| `COLUMN_SIZE_MISMATCH` / `BEAM_WIDTH_MISMATCH` | tag disagrees with drawn geometry |
| `SCHEDULE_MARK_MISSING` / `SCHEDULE_PLAN_MISMATCH` | plan versus schedule |
| `TAG_UNASSIGNED` / `TAG_UNPARSED` | text nobody claimed or nobody understood |
| `BEAM_UNPAIRED_LINES` | beam-layer lines that did not form a beam |
| `NO_BOUNDARY` / `FLOOR_NO_ORIGIN` / `FLOOR_NO_LABEL` | floor conventions missing |

## Repository layout

```
src/c2b/
  schema.py        canonical models (pydantic)        docs/schema.md
  profile.py       layer roles, tolerances, YAML       docs/profiles.md
  units.py         drawing units → mm
  tags.py          tag text parser
  geometry.py      shapely helpers: outlines, line pairing, snapping
  dxfio.py         ezdxf → primitives (blocks exploded, Z flattened)
  floors.py        Boundary/Origin floor detection, floor names
  schedules.py     text-grid schedule tables
  extract/         grids, columns, beams, slabs, footings, openings/walls, tag association
  pipeline.py      orchestration
  normalize/       utility 3: spec, stacks, spans, panels, naming, pipeline   docs/template-spec.md
  export/          JSON, Excel, review DXF, report, level schedule, template DXF, schedules workbook
  cli.py           typer CLI
tools/             compare_with_template.py (IoU check against the reference), render_dxf.py
tests/             unit tests + synthetic end-to-end drawing + sample integration
profiles/          client profiles (YAML)
samples/           client drawings (git-ignored)
```

## Known limits of v0.5.0

- Cantilever slabs, chajjas and balconies need the client's slab edge lines; without them a
  panel with a free edge cannot be closed.
- Sunk, beam-bottom, fold and column-stop meanings come from the client's legend; a drawing
  without a legend yields none of them.
- Folds, lift pits, pile caps, piles and ramps are built from tag and note recognition only
  and have not yet been validated on a client drawing that contains them.
- Stair riser counts and landing levels are estimates flagged for review.
- Column stacks are matched by plan overlap; a column that shifts more than 300 mm
  between floors starts a new stack (reported as `STACK_ORPHAN`).
- Beams drawn as single centrelines (no edges) are not paired; they show up as
  `BEAM_UNPAIRED_LINES`.
- Rotated floor plans (true north) are read as drawn; no per-floor rotation yet.
- Schedule tables drawn as real `TABLE` entities are not read (text grids are).
- Everything is rule based. Ambiguous cases are reported, not guessed.

## Versioning

Semantic versioning on two things: the tool (`c2b.__version__`) and the JSON schema
(`schema_version` in every output). Downstream steps pin the schema major version.
