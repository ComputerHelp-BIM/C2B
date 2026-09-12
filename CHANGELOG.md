# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

The canonical JSON schema carries its own version (`schema_version` in every output).
A MAJOR bump of the schema means downstream utilities (DXF writer, Revit importer)
must be updated; a MINOR bump adds fields or element types; a PATCH bump fixes values.

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
