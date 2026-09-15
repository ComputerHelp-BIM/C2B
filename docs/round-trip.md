# Round trip (utility 4)

```bash
c2b verify out/client/client.template.dxf            # --against <normalized.json>, --spec, -o
```

`c2b verify` does two jobs in one pass.

1. **Read the template DXF back into the normalised model.** Geometry and mark text come from
   the drawing, never from the JSON, so anything a drafter changed in AutoCAD is picked up. The
   `C2B` XDATA (application id `C2B`) supplies identity (`id=`, `stack=`, `client=`) and the few
   values a drawing cannot carry (level elevations, panel top offsets, the floor origin).
   Outputs `<stem>.reread.json` and `<stem>.reread.xlsx` in the same shape as `c2b normalize`,
   so the Revit importer can consume the edited drawing directly.
2. **Compare it with the normalised model** (`<stem>.normalized.json` next to the DXF, or
   `--against`). Outputs `<stem>.verify.xlsx` and `<stem>.verify.md`. The command exits 0 when
   the drawing matches the model and 1 when it does not, so it can gate a pipeline.

## What is compared

Only elements the writer actually draws: slab, cantilever and ramp panels (not the bookkeeping
records for cut-outs and stairs), structural walls, piles with a diameter, stairs with an
outline. Matching is by `id` first, then by geometry overlap, so an element that was moved is
recognised as the same element rather than reported as deleted and added.

| Code | Meaning | Severity |
|---|---|---|
| `RT_MISSING` | in the model, not in the drawing (deleted) | error |
| `RT_ADDED` | in the drawing, not in the model (drawn by hand) | error |
| `RT_MOVED` | centre moved more than 2 mm | warning |
| `RT_RESIZED` | size changed more than 2 mm | warning |
| `RT_MARK_CHANGED` / `RT_MARK_MISSING` | mark text edited or deleted | warning |
| `RT_MARK_MISMATCH` | the mark disagrees with the drawn geometry | warning |
| `RT_DUP_MARK` | one mark names two different sections on a floor | warning |
| `RT_COUNT` | element count per floor differs | warning |
| `RT_LEVEL_CHANGED` | a level elevation or name changed | warning |
| `RT_NO_ID` | entity on a `CH-` layer without a `C2B` id | warning |
| `RT_ORPHAN_MARK` | mark text belonging to no element | info |

Sizes are measured on the minimum rotated rectangle, so a column drawn at 45 degrees is not
reported as bigger than it is. Beam marks describe a cross-section, so spans sharing a mark are
compared on width alone, never on length.

## Results on the sample drawings

| Drawing | Errors | Warnings | What the warnings are |
|---|---|---|---|
| Test10 | 0 | 0 | clean round trip |
| Test14 | 0 | 18 | the client uses `MB` for both 350 and 300 wide beams |
| Test16 | 0 | 10 | terrace columns whose schedule size differs from the plan |
| Test18 | 0 | 38 | client column tags that disagree with the drawn outline |

None of these are tool defects: they are inconsistencies in the client drawings that the mark
now makes visible.

## Using it after the drafter edits the DXF

The template DXF is the working copy. When a drafter moves a beam or retypes a mark, run
`c2b verify` again: the report lists every change, and `<stem>.reread.json` is the corrected
model for Revit. Entities added by hand carry no `C2B` id, so they are listed as `RT_NO_ID` and
`RT_ADDED` rather than silently entering the model with a colliding id.
