# Utility 5 — the Revit importer

C2B does the thinking outside Revit. `c2b revit-plan` turns the normalised model
into a
**build plan**: an ordered list of "create this family type, on this level, at
this point,
with this offset". The script inside Revit only executes that list, so the part
that runs in
Revit is short, readable and easy for your team to adjust.

```text
 <name>.normalized.json   (or <name>.reread.json after the drafter's edits)
          |  c2b revit-plan --mapping <name>.revit-mapping.yaml
          |               --template templates/R25_TEMPLATE.template.md
          v
 <name>.revit.json        the build plan, checked against the template
 <name>.revit.xlsx        every family and type it will use, whether the template
          |               already has it, and where the marks will go
          |  pyRevit button "Import C2B model"
          v
 native Revit columns, beams, floors, foundations, walls, shafts
```

## Checking the plan against the template first

A `.rvt` is a compound binary, so nothing outside Revit can read it. What can be read is the
markdown the firm's *Extract Template* tool writes from it. `templates/R25_TEMPLATE.template.md`
is that file for the structural template, and `--template` checks the plan against it before
anyone opens Revit:

```bash
c2b revit-plan out\TowerA\TowerA.normalized.json ^
   --template templates/R25_TEMPLATE.template.md ^
   --shared-params templates/CH-shared-parameters.txt
```

It answers three questions that otherwise only surface halfway through a Revit run:

| Question | Why it matters |
| --- | --- |
| Which types does the template already carry, and which will be created by duplicating one? | A type created from the wrong base is the wrong thickness, and nothing says so |
| Is every family the plan names actually in the template? | A type cannot be duplicated inside a family that is not loaded, so every element needing it is unbuildable |
| Will the marks survive? | Revit accepts a write to a parameter nobody bound, drops the value, and the model looks finished |

That last one is why `--shared-params` exists. "Not bound in the template" and "does not exist
anywhere" look the same in Revit and have different fixes, so C2B reads the shared parameter
file and says which it is.

The check also flags types that are legitimate but worth a glance -- a 12 m "column" that is
really a shear wall leg, or a 450 m2 "footing" the client never marked as a raft.

## One-time setup

1. Install [pyRevit](https://github.com/eirannejad/pyRevit/releases) on the
  Revit seat.
2. In pyRevit's settings, add this repository's `revit` folder as a **custom
  extension
   directory**, then Reload. A **C2B** tab appears with one button.

## Every project

```text
c2b revit-plan out\TowerA\TowerA.normalized.json --write-mapping     # first time only
```

Open `TowerA.revit-mapping.yaml` and set the family and type names to match your
Revit
template. The defaults are Autodesk's metric sample families, which are almost
certainly not
yours:

The defaults are read off **R25_TEMPLATE**, so on that template they need no editing:

```yaml
column:
  family: CH-Concrete-Rectangular-Column    # your column family
  type_name: "CH-{w:.0f} X {d:.0f}"         # how your types are named
  width_param: b                            # the type parameter holding the width
  depth_param: h
  fallback_type: "CH-300 X 600"             # duplicated to make a size the template lacks
beam_step:
  family: CH-Concrete-Step-Beam-Bottom      # a mark like B5-200X900/600
  width_param: W
  depth_param: H
  depth_alt_param: H1
floor:
  type_name: "{thk:.0f} THK. RCC SLAB"
  base_type: "150 THK. RCC SLAB"            # duplicated when a thickness is missing
mark_params: [S_ScheduleMark, CH-ScheduleMark, Mark]   # every one that exists is written
id_params: [ID, CH-ID]
wall_like_as: column                        # or "wall" to model shear wall legs as walls
```

**Shear wall legs.** A leg is a column in the drawing and in the schedule, and C2B split it as
one, so it is a Structural Column by default -- one Revit element per tagged leg, which keeps
the model one-to-one with the drawing. Set `wall_like_as: wall` to model them as Basic Walls
instead; `wall_like_min_thickness_mm` then keeps the thin ones as columns.

**Marks.** R25_TEMPLATE binds `ID` and `S_ScheduleMark`; the firm's shared parameter file
defines `CH-ID` and `CH-ScheduleMark`. Until those agree, C2B writes every name that exists on
the element and the Revit run reports which ones took -- a name with no writes at all is one
nobody bound.

Then:

```bash
c2b revit-plan out\TowerA\TowerA.normalized.json
```

Open `TowerA.revit.xlsx`, sheet **Types to create**. That is exactly what the
import will
place. Fix the mapping until that sheet reads the way your model should.

In Revit: open the project from your structural template, press **C2B → Import
C2B model**,
pick `TowerA.revit.json`, confirm the summary.

## What it creates

| Plan action | Revit |
| --- | --- |
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

Stairs are not built: the plan carries the outlines and the estimated riser
count, but a
Revit stair needs a section to be correct. Model those by hand.

## Honest limits

This script has been written against the Revit 2021 to 2025 API but **has not
been run
against a live Revit model** — there is no Revit in the environment where C2B
was built.
Expect to adjust family names, parameter names and one or two API calls on the
first run.
Everything it does is in one transaction group, so undo removes it cleanly.

Run it first on a copy of a small project, compare against the client drawing,
and tell me
what breaks. The fixes belong in the mapping file or in this one script, not in
the rest of
the pipeline.
