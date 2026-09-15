# Utility 5 — the Revit importer

C2B does the thinking outside Revit. `c2b revit-plan` turns the normalised model into a
**build plan**: an ordered list of "create this family type, on this level, at this point,
with this offset". The script inside Revit only executes that list, so the part that runs in
Revit is short, readable and easy for your team to adjust.

```
 <name>.normalized.json   (or <name>.reread.json after the drafter's edits)
          |  c2b revit-plan --mapping <name>.revit-mapping.yaml
          v
 <name>.revit.json        the build plan
 <name>.revit.xlsx        every family and type it will use, and how many of each
          |  pyRevit button "Import C2B model"
          v
 native Revit columns, beams, floors, foundations, walls, shafts
```

## One-time setup

1. Install [pyRevit](https://github.com/eirannejad/pyRevit/releases) on the Revit seat.
2. In pyRevit's settings, add this repository's `revit` folder as a **custom extension
   directory**, then Reload. A **C2B** tab appears with one button.

## Every project

```
c2b revit-plan out\TowerA\TowerA.normalized.json --write-mapping     # first time only
```

Open `TowerA.revit-mapping.yaml` and set the family and type names to match your Revit
template. The defaults are Autodesk's metric sample families, which are almost certainly not
yours:

```yaml
column:
  family: M_Concrete-Rectangular-Column     # your column family
  type_name: "{w:.0f} x {d:.0f}mm"          # how your types are named
  width_param: b                            # the type parameter holding the width
  depth_param: h
beam:
  family: M_Concrete-Rectangular Beam
floor:
  type_name: "RCC {thk:.0f}mm"
  base_type: "Generic 150mm"                # duplicated when a thickness is missing
```

Then:

```
c2b revit-plan out\TowerA\TowerA.normalized.json
```

Open `TowerA.revit.xlsx`, sheet **Types to create**. That is exactly what the import will
place. Fix the mapping until that sheet reads the way your model should.

In Revit: open the project from your structural template, press **C2B → Import C2B model**,
pick `TowerA.revit.json`, confirm the summary.

## What it creates

| Plan action | Revit |
|---|---|
| `level` | Levels at the elevations from the level workbook |
| `grid` | Grids with the client's labels |
| `column` | Structural column per stack per level, base and top level, rotation, mark |
| `beam` | Structural framing on the level, with the top offset (inverted beams sit above) |
| `floor` | Floor with the panel outline and cut-outs as holes, offset for sunk and chajja panels |
| `footing` | Isolated footing family, or a foundation slab for rafts, pile caps and pits |
| `pcc` | Lean concrete slab under the foundation |
| `pile` | Round column at the pile position |
| `wall` | RCC wall between levels, top under the beam above |
| `shaft` | Shaft opening through the floor for lifts and stairs |

Stairs are not built: the plan carries the outlines and the estimated riser count, but a
Revit stair needs a section to be correct. Model those by hand.

## Honest limits

This script has been written against the Revit 2021 to 2025 API but **has not been run
against a live Revit model** — there is no Revit in the environment where C2B was built.
Expect to adjust family names, parameter names and one or two API calls on the first run.
Everything it does is in one transaction group, so undo removes it cleanly.

Run it first on a copy of a small project, compare against the client drawing, and tell me
what breaks. The fixes belong in the mapping file or in this one script, not in the rest of
the pipeline.
