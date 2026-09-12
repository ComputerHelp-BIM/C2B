# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

The canonical JSON schema carries its own version (`schema_version` in every output).
A MAJOR bump of the schema means downstream utilities (DXF writer, Revit importer)
must be updated; a MINOR bump adds fields or element types; a PATCH bump fixes values.

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
