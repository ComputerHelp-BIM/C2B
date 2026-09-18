# From a client drawing to a Revit model

## The whole thing is three steps

| | You do | You get |
| --- | --- | --- |
| **1** | Open **C2B**, pick the client drawing, press **Run** | The drawing in the firm's template, plus a list of anything unclear |
| **2** | Press **Set floor heights…**, type a height per floor, press **Save and run again** | The same, now with levels — and the Revit model prepared |
| **3** | In Revit, open a project from the structural template, press **C2B → Import C2B model**, pick the file the window named | The native model, checked against the plan, with a report of anything that did not match |

That is all of it. The window tells you which of the three you are on, in one line, at the
bottom: **Next: …**. If you only read one thing on the screen, read that line.

Step 2 exists because a plan cannot tell anyone how high each floor is. It is the only thing
you have to supply by hand, and it is asked for in the window — no spreadsheet.

---

## Step 1 — Run

Double-click `windows\C2B.bat`, or drag the client DXF onto `windows\C2B-run.bat`.

Pick the **client drawing**. Pick **our template** once (it is remembered). Press **Run**.

Four steps go past in the Progress panel. When it stops, look at:

- the **Next:** line at the bottom — the one thing to do now;
- **Things to check** — anything C2B could not resolve, in plain language, worst first.

The buttons along the bottom open what was produced. The ones worth opening on a first run are
**Open the template DXF** (the drawing) and **Overlay on the client drawing** (what was
recognised, drawn over the original).

## Step 2 — Floor heights

Press **Set floor heights…**. Every floor found in the drawing is listed. Type the top of the
structural slab for each, in millimetres; below ground is negative. Leave a floor blank to skip
it.

Press **Save and run again**. That is the whole of step 2.

## Step 3 — Revit

1. Open Revit. **Start a project from your structural template**, or open the project you are
   adding to. **Save it.**
2. **C2B tab → Import C2B model.** It opens in the folder you used last. Pick the
   `…revit.json` the window named.
3. It shows what it is about to create and which units the project displays. Say yes.
4. When it finishes it reports, in this order:
   - **anything that does not match the plan** — and nothing at all if everything does;
   - what was created, by kind;
   - every type it created, with the size it set;
   - where the marks went — each parameter name and how many elements carry it. A name reading
     *not in this model* is one nobody bound in your template, so nothing C2B wrote to it
     arrived;
   - anything that failed, with the element and Revit's own error.

**Copy that report out** (pyRevit's output window has a copy button) before closing it. It is
the record of what happened.

Nothing is deleted, ever. Running the import twice creates a second set of elements. Undo, or
work in a fresh file.

---

## What the import checks by itself

The import saying "finished" is not evidence, so it reads the model back before it reports.
Three things go wrong quietly, and none of them look wrong in the project browser:

| What | Why you would never notice |
| --- | --- |
| Some elements failed while the rest carried on | The model looks complete until someone counts |
| A type was created by duplication and kept the size it was copied from | A `175 THK. RCC SLAB` that is 150 thick is named correctly and looks right |
| A level already existed at a different height | Everything hosted on it is at the wrong elevation, consistently, so nothing looks odd |

You do not have to do anything to get this — it is part of pressing the button.

---

## Once per template

Do this when the Revit template changes — a family loaded, a type added, a parameter bound.

1. Open the structural template in Revit, run **Extract Template**. It writes a `.md` file.
2. Put it in the `templates` folder of this repository, replacing the one there.

C2B finds it by itself after that. It uses it to tell you, before Revit is ever opened, which
family types already exist, which it will have to create, and whether the marks it writes will
survive. If it is a stale copy, that check is answering about a template that no longer exists.

You can also drop it in a `templates` folder beside the client drawing, and that one wins.

---

## When something breaks

This script has been written against the Revit 2021–2025 API but has **not yet been run
against a live model**, so the first run on a real project is the one that finds what is wrong.

Start on a small job. **Test10** is a good first run — 404 columns, 9 levels, and it exercises
round columns, rafts and shaft openings without taking minutes.

Send three things and the failure can be reproduced and fixed without a Revit seat:

1. the **pyRevit output**, copied out in full;
2. **`<name>.revit.json`** — the plan that was run;
3. your **Revit version** (2021 … 2025).

---

## A note on units, if you are wondering

Revit stores every length internally in **decimal feet**, whatever the project's units are set
to. A millimetre value handed straight to it is read as feet — 300 becomes 91 metres — and
nothing complains.

Every length crossing into Revit goes through one conversion, every length read back out goes
through its opposite, and a test refuses to let a raw number past. The project's own unit
setting changes only what you see on screen: an imperial project imports exactly the same
model. The import prints the setting anyway, so the log is never ambiguous about it.

---

## The settings you might change

In the window: **Units** (leave it alone unless the drawing has none) and **Column size from**
(the client's stated size, or the drawing measured).

Everything else lives in `<name>.revit-mapping.yaml`, written beside the results. Edit it and
press Run again; the defaults already match the firm's template.

| Setting | What it decides |
| --- | --- |
| `wall_like_as` | `column` (default) makes each tagged shear wall leg a Structural Column, one to one with the drawing and the schedule. `wall` makes them Basic Walls |
| `two_depth_beam` | whether a mark like `B5-200X900/600` is a `step` beam (default) or a `taper` |
| `build` | switch whole categories off — import columns first, check them, then the rest |
| `mark_params`, `id_params` | the parameter names the mark and the C2B id are written to |

## Running it from a terminal instead

The window does all of this, but every step is a command if you want one:

```bash
c2b run client.dxf --seed templates\CH-TEMPLATE.dxf   # steps 1 and 2, including the Revit plan
c2b revit-plan out\client\client.normalized.json --template templates\R25_TEMPLATE.template.md
c2b revit-verify out\client\client.revit.json "project-template.md"
```

`c2b revit-verify` is the same check the import already does, run from outside Revit against an
Extract Template description of the finished project. It is there for looking at a model
someone else imported.
