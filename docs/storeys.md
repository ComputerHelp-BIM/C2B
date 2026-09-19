# Storeys — the building's levels

A drawing shows **floor plans**. A building has **storeys**. They are not the same list, and
the gap between them is where a CAD-to-BIM job usually goes wrong:

| The drawing has | The building has |
| --- | --- |
| One plan labelled *3rd to 7th Floor Typical Level* | Five storeys, 3 m apart |
| No elevation anywhere on the sheet | A datum every level is measured from |
| A foundation plan drawn beside the others | A level 2.5 m below the ground floor |

The **Storey Editor** is where that gap is closed. Everything Revit is given — the levels, the
elevations, which plan is built on which storey — is decided here, and `levels.xlsx` is written
from it.

---

## 1. Opening it

Run a drawing, then press **Storeys…** beside *Next:* in the C2B window.

You do not have to open it. C2B seeds a stack from the drawing on the first run: one storey per
floor plan, ordered by elevation where the drawing gives one, 3000 mm apart where it does not.
That stack is enough to build a Revit model, so the first run already produces one. Open the
editor to correct it — which, on a real job, you will.

---

## 2. What you are looking at

The highest storey is at the top, the way a section is drawn.

```
 Build  No.  Storey                Height mm  Elevation mm  Built from      Repeat  Note
  [x]    6   Terrace Floor Level        3000         30000  L07 TERRACE          1  drawn
  [x]    4   3rd Floor Level            3000         12000  L05 TYPICAL          7  drawn
  [x]    1   Ground Floor Level         2500          2500  L02 GROUND           1  drawn
  [x]    0   Foundation Level                            0  L01 FOUNDATION       1  drawn
        Move up   Move down   Add storey   Add at the bottom   Remove
```

**One row is one entry in the schedule, not always one level.** The *Repeat* column is how
many levels that one row builds — the drawing above has thirteen levels from four rows, because
the typical floor is drawn once and built seven times. That is how a drawing says it
(`TYPICAL FLOOR PLAN (2ND TO 8TH FLOOR)`) and how the rest of the suite shows it.

**Untick Build to leave a storey out.** The row stays in the table, so a storey dropped by
mistake is one tick away from coming back, and nothing about an unticked storey is reported —
it is not in the model, so it cannot be wrong.

Click a row and the buttons under the table act on it. Columns can be dragged wider.

The **Note** column is one word: `drawn`, `level text`, `repeat`, `assumed`, `check`, `fix this`.

**Height** is the rise from the storey *below* — the same thing an ETABS story table or a level
schedule means by it. **Elevation** is those heights added up from the lowest storey.

The lowest storey has no height, because there is nothing under it to rise from. Set its
**elevation** instead: that is the datum, and it moves the whole building.

> Type a height *or* an elevation — the other follows. Typing a height moves everything above
> it. Typing an elevation puts that storey where you said and leaves the storeys above the same
> distance away. Neither is silently corrected: type something impossible and the storey goes
> where you typed it, with the reason listed at the bottom of the window.

---

## 3. The five things it does

### Add

**Add on top** puts a storey above everything and makes the building that much taller — nothing
already in the stack is squashed. **Add at the bottom** puts one underneath: that is how a
foundation level gets under a ground floor without moving the ground floor.

New storeys take the height in the **New storeys are ___ mm tall** box, which is remembered.

### Remove

Deletes the selected storey and brings everything above it down by its height — the building gets
shorter, which is what deleting a floor means.

Deleting the *lowest* storey is the exception: everything else stays exactly where it is.
Removing a foundation level does not drag the ground floor down to where the foundation was.

### Move up / Move down

Reorders the selected storey, carrying its height with it.

### Repeat — the typical floor

The important one, and it is a **column**, not a button. Type how many levels that one row
builds.

Each copy keeps the original's height *and its floor plan*, so one drawn layout builds all of
them. `3rd Floor Level` repeated four times becomes `4th`, `5th`, `6th`, `7th` — the numbering
follows the name, ordinals included.

This is how *3rd to 7th Floor Typical Level* becomes five storeys in Revit from one plan.

### Height and elevation

Covered above. Both columns are editable on every storey except the base's height.

---

## 4. Built from

Which floor plan is built on this storey. Several storeys can name the same plan — that is what
a repeat does, and you can set it by hand too.

A storey with **(nothing drawn)** is created in Revit as a level with no columns, beams or slab
on it. That is a warning, not an error: a level marking a parapet or a plinth is a real thing to
want.

A floor plan that *no* storey names is also a warning — everything drawn on it is left out of
the model, so it is worth knowing before Revit is opened.

---

## 5. What stops a save

The footer badge says where the stack stands, and the panel above it lists everything wrong.

| Reported as | What it is |
| --- | --- |
| **ERROR** — two storeys called the same thing | Revit will not hold two levels of one name, so one would simply be lost |
| **ERROR** — a storey level with or below the one under it | Columns between them have no height to be built with, and Revit refuses a column of zero height with an error that cannot be ignored — it rolls back the whole import |
| **WARNING** — a storey with nothing drawn | It becomes a bare level |
| **WARNING** — a plan no storey builds | Everything on it is left out |

**Save** is disabled while there is an error. That is deliberate: the alternative is finding out
in Revit, an hour later, with 2000 elements rolled back.

---

## 6. Where it is kept

| File | What it is |
| --- | --- |
| `<drawing>.storeys.json` | **The source of truth.** What the editor saved. |
| `<drawing>.levels.xlsx` | Written *from* it on every run, for Revit and for the record. |

`levels.xlsx` is an **output** now. Type into it and the next run replaces what you typed — the
workbook's `Settings` sheet says so on the sheet itself. To work in Excel instead, delete the
`.storeys.json` beside it and C2B will read the workbook again.

One exception: a workbook named on purpose wins. `c2b run drawing.dxf --levels mine.xlsx`, or
picking one in **Level heights** in the window, is a deliberate instruction and is honoured. The
window clears that box when you save storeys, so the two can never quietly contradict each other.

---

## 7. If the window looks different to this

C2B's windows — this one and the main window — are **WPF**, the branded ones. They need
Windows and **pythonnet**, which installs with C2B from 0.24.1 onward. On an installation from
before that, or one where it did not install:

```bat
.venv\Scripts\pip install pythonnet
```

**To check which window you are getting**, run `windows\C2B-debug.bat`. It prints the
installation check — including a `window` line saying `branded (WPF)` or
`plain (Tkinter)` and why — and then opens C2B with a console behind it, so anything the tool
says stays on screen. `C2B.bat` starts C2B with `pythonw.exe`, which has no console at all.

The plain window also says so on itself: an amber banner across the top naming the reason.

Without it C2B falls back to a plain Tkinter window with the same columns, the same buttons and
exactly the same behaviour. Nothing is lost but the styling, and no drawing is treated
differently.
