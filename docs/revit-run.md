# Running C2B inside Revit (utility 5)

From a client DXF to a native Revit model, and back out again to prove it worked. Everything
here runs on one Windows machine with Revit and pyRevit; nothing needs internet after the
install.

The loop is the same one utilities 3 and 4 use. C2B writes a plan, Revit builds it, and the
model is read back and compared with the plan. Nothing is trusted because it looked right on
screen.

```text
 client DXF ──► c2b run ──► <name>.normalized.json
                                    │
                    c2b revit-plan  │  --template <your template>.md
                                    ▼
                          <name>.revit.json      the build plan
                          <name>.revit.xlsx      read this before you open Revit
                                    │
                    pyRevit ► C2B ► │ Import C2B model
                                    ▼
                            the Revit model
                                    │
                  Extract Template  │  (your own tool, on the project)
                                    ▼
                          <project>-template.md
                                    │
                  c2b revit-verify  │
                                    ▼
                          <name>.revit-check.md   what was built vs what was planned
```

---

## 1. Once per machine

1. **Install pyRevit** from [github.com/eirannejad/pyRevit/releases](https://github.com/eirannejad/pyRevit/releases).
   Take the installer, not the zip.
2. Open Revit once so pyRevit registers, then close it.
3. **Add the C2B extension.** In Revit: **pyRevit → Settings → Custom Extension Directories →
   Add folder**, and pick the `revit` folder of this repository (the one holding
   `C2B.extension`). Press **Save Settings and Reload**.
4. A **C2B** tab appears with one button, **Import C2B model**. If it does not, use
   **pyRevit → Reload**, and check the extension path points at `revit`, not at
   `revit\C2B.extension`.

You only do this once. Updating C2B is `git pull`; pyRevit picks up the new script on the next
**Reload**.

---

## 2. Once per template — describe it, and check it

This is the step that makes everything after it safe. A `.rvt` is a compound binary, so
nothing outside Revit can read it; your **Extract Template** tool writes it out as markdown,
and C2B reads that.

1. Open the structural template (`R25_TEMPLATE.rvt`) in Revit.
2. Run **Extract Template**. It writes `R25_TEMPLATE-template.md`.
3. Copy that file into the repository as `templates/R25_TEMPLATE.template.md`, replacing the
   one already there, and commit it. It is text: git will show you exactly what changed in the
   template since last time, which is worth having on its own.

Re-do this **whenever the template changes** — a family loaded, a type added, a parameter
bound. C2B checks every plan against this file, so a stale copy means the check is answering
about a template that no longer exists.

---

## 3. Every project — plan it, and read the plan

```bat
c2b run "C:\Projects\Tower A\STR-PLANS.dxf" --seed templates\CH-TEMPLATE.dxf
```

Fill `STR-PLANS.levels.xlsx` with the floor elevations and run it again — **without
elevations there are no levels, and with no levels nothing can be placed.** Then:

```bat
c2b revit-plan "C:\Projects\Tower A\out\STR-PLANS\STR-PLANS.normalized.json" ^
    --template templates\R25_TEMPLATE.template.md ^
    --shared-params templates\CH-shared-parameters.txt
```

It prints a summary and writes two files:

| File | What it is |
| --- | --- |
| `STR-PLANS.revit.json` | the build plan — what the Revit button reads |
| `STR-PLANS.revit.xlsx` | what it will create, checked against your template |

**Open the workbook before you open Revit.** Three sheets decide whether the import is worth
running:

- **Types to create** — every family type the plan needs. `in template` means it is already
  there; `create` means Revit will duplicate the base type named beside it and set its
  dimensions; `FAMILY MISSING` means the family is not loaded and **everything using it will
  fail**. The last column flags types that are legitimate but odd — a 12 m "column" that is
  really a shear wall leg, a 450 m² "footing" the client never marked as a raft.
- **Template check** — where the marks will go. A row saying *Mark would vanish* means Revit
  will accept the write and drop the value, which you cannot see afterwards by looking at the
  model. Fix it before importing, not after.
- **Diagnostics** — anything C2B could not place, with the element id and the reason.

Fix what that workbook tells you, re-run, and only then open Revit.

---

## 4. Import

1. Open Revit and **start a project from your structural template** — or open the project you
   are adding to.
2. **Save it.** The import is one transaction group and undo removes it cleanly, but a save
   costs nothing and an undo of nine thousand elements is slow.
3. **C2B tab → Import C2B model.** Pick `STR-PLANS.revit.json`.
4. It shows what it is about to create and asks. Say yes.
5. When it finishes, pyRevit's output window reports:
   - how many of each kind were created,
   - every type it created and the thickness it set,
   - **where the marks went** — each parameter name with how many elements it was written on.
     A name reading *not in this model* is one nobody bound: nothing C2B meant for it arrived.
   - anything that failed, with the element id and the Revit error.

**Keep that output window.** Copy it out (pyRevit's output has a copy button) — it is the only
record of what happened, and it is the first thing to look at when something is wrong.

A large project takes a while. Test17 is about nine thousand elements; expect minutes, not
seconds, and do not touch Revit while it runs.

---

## 5. Prove it — read the model back

Do not trust the model because the import said it finished. Read it back:

1. With the imported project open, run **Extract Template** on it. It writes
   `<project>-template.md` — the same format as the template description, but now describing
   what was actually built.
2. Compare it with the plan:

```bat
c2b revit-verify "...\STR-PLANS.revit.json" "...\Tower A-template.md"
```

It writes `STR-PLANS.revit-check.md` and answers three questions:

| Check | The failure it catches |
| --- | --- |
| Element counts per category | Revit created 2 of 3 columns and said nothing |
| Every planned type exists | A type was never created, so everything needing it failed |
| Every created type is the right size | A `175 THK. RCC SLAB` duplicated from the 150 and kept its thickness — it looks completely normal in the project browser |
| Levels are at their planned height | The level already existed at a different elevation and was kept, so everything on it is at the wrong height |
| Every grid label is there | A grid label collided with an existing one |

If it reports nothing, the model matches the plan. That is the point at which the import is
finished.

---

## 6. When something breaks

This script has been written against the Revit 2021–2025 API but has **not yet been run
against a live model**, so the first run on a real project is the one that finds what is
wrong. What the template check already guarantees is that every family, type and parameter
name is real; what it cannot guarantee is the API calls themselves.

Start small: run it on **Test10** rather than Test17 — 404 columns, 9 levels, and it exercises
round columns, rafts and shaft openings without taking minutes.

To get a problem fixed, send these four things:

1. **The pyRevit output window**, copied out in full. The `failed` lines carry the element id
   and Revit's own error text, which is usually enough on its own.
2. **`<name>.revit.json`** — the plan that was run.
3. **`<project>-template.md`** — Extract Template on the project after the import.
4. **Your Revit version** (2021 … 2025), since a few API calls differ.

With those four, the failure can be reproduced and fixed without a Revit seat: the plan says
what was asked for, the model description says what came out, and the log says what Revit
objected to. That is the whole loop, and none of it needs anyone watching Revit.

**Nothing is deleted, ever.** Running the import twice creates a second set of elements. Undo,
or work in a fresh file.

---

## The settings you are most likely to change

They live in `<name>.revit-mapping.yaml`, written next to the plan the first time you run
`revit-plan`. Edit it and re-run; the defaults already match R25_TEMPLATE.

| Setting | What it decides |
| --- | --- |
| `wall_like_as` | `column` (default) makes each tagged shear wall leg a Structural Column, one to one with the drawing and the schedule. `wall` makes them Basic Walls instead |
| `wall_like_min_thickness_mm` | with `wall_like_as: wall`, legs thinner than this stay columns |
| `two_depth_beam` | whether a mark like `B5-200X900/600` is a `step` beam (default) or a `taper` on this client's drawings |
| `mark_params`, `id_params` | every parameter name the mark and the C2B id are written to. All of them are tried, and the run reports which existed |
| `build` | switch whole categories off — useful for importing columns first, checking them, then the rest |
| `structural_only` | skip non-structural walls |
| `round_sizes_to_mm` | sizes are rounded to this before a type is named, so 299.6 and 300.2 do not make two types |
