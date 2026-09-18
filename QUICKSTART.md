# C2B quickstart — running it on your own machine

Everything up to utility 4 (client drawing → template DXF → verified round trip)
runs on one
Windows machine with nothing but Python. No AutoCAD licence, no Revit, no
internet access
after installation.

---

## 1. Install (once per machine, about five minutes)

1. **Install Python 3.11 or newer** from
  [https://www.python.org/downloads/](https://www.python.org/downloads/).
   During setup tick **“Add python.exe to PATH”**.
2. **Get the code.** Either download the repository as a ZIP from GitHub and
  unzip it, or:

   ```bash
   git clone https://github.com/ComputerHelp-BIM/C2B.git
   cd C2B
   ```

3. **Double-click `windows\install.bat`.** It creates a private Python
  environment in
   `.venv`, installs C2B, and runs a self-check.

The self-check ends with `READY`. If it does not, the line in red says what is
missing.

**macOS / Linux, or if you prefer the command line:**

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,render]"
c2b doctor
```text

## 2. Prove the installation works

```bash
c2b doctor
```

It prints the versions it found and then runs the entire pipeline on a built-in
demo drawing:
extract → normalise → template DXF → read back → compare. The last line must say
`READY`.

```Text
Self-test: demo drawing -> extract -> normalize -> verify
  extract        24 columns, 8 beams
  normalize      24 columns, 18 spans, 8 panels
  template dxf   103 KB
  round trip     identical
READY
```text

## 3. Try the demo drawing yourself

```bash
c2b demo -o demo
c2b run demo\demo.dxf
```

Open `demo\out\demo\demo.template.dxf` in AutoCAD. It is a two-floor structural
layout drawn
in the CH template conventions, produced from a drawing the tool had never seen
before.

## 4. The window (what drafters use)

Double-click `windows\C2B.bat`, or run `c2b gui`. **The whole job is three
things:**

1. Pick the client drawing, press **Run**.
2. Press **Set floor heights…**, type a height per floor, press **Save and run
  again**.
3. In Revit: **C2B → Import C2B model**, and pick the file the window names.

The window says which of the three you are on, in one line at the bottom:
**Next: …**. The four
steps appear as they happen, anything unclear is listed in plain language
underneath, and the
buttons along the bottom open the template DXF, the workbooks, what Revit will
build, or the
folder. **Re-check an edited template DXF** lists every change a drafter made
after the drawing
was generated.

Step 2 exists because a drawing cannot say how high each floor is. It is the one
thing you have
to supply, and it is asked for in the window — no spreadsheet.

See [docs/revit-run.md](docs/revit-run.md) for the Revit half in full.

## 5. Run your own drawing from the command line

Put your template at `templates\CH-TEMPLATE.dxf` first, then **drag a client DXF
onto
`windows\C2B-run.bat`**. On the command line that is:

```bash
c2b run "C:\Projects\Tower A\STR-PLANS.dxf" --seed templates\CH-TEMPLATE.dxf
```text

It writes everything into `C:\Projects\Tower A\out\STR-PLANS\`:

| File | What to do with it |
| --- | --- |
| `STR-PLANS.template.dxf` | **the deliverable** — open it in AutoCAD next to the client drawing |
| `STR-PLANS.review.xlsx` | what was read from the client drawing; the **Diagnostics** sheet lists everything unclear |
| `STR-PLANS.review.dxf` | overlay this on the client drawing to see what was recognised and what was missed |
| `STR-PLANS.schedules.xlsx` | column schedule per stack and floor, beams, slabs, footings, mark map |
| `STR-PLANS.levels.xlsx` | **fill in the floor elevations**, then run the same command again |
| `STR-PLANS.verify.md` | round-trip check: the template DXF read back and compared |
| `STR-PLANS.profile.yaml` | the layer roles that were guessed; edit and reuse for that client |
| `STR-PLANS.normalized.json` | the data the Revit importer will consume (utility 5) |

**DWG input.** C2B reads DXF. Save the DXF from AutoCAD (Save As → *AutoCAD 2018
DXF*), or
install the free [ODA File
Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
and C2B will convert DWG files itself.

## 6. The normal working loop

1. `c2b run <drawing>` — first pass.
2. Open `*.review.xlsx` → **Diagnostics**. Errors block, warnings need a
  decision.
3. Open `*.profile.yaml`. Any layer with confidence `low` or role `UNKNOWN` that
  carries
   structural geometry gets a proper role. Re-run with `--profile`.
4. Fill `*.levels.xlsx` with the floor elevations (top of structural slab).
  Re-run.
5. Open `*.template.dxf`, let the drafter fix what is left.
6. Drag the edited file onto `windows\C2B-verify.bat` — every change against the
  model is
   listed, and `*.reread.json` becomes the corrected data for Revit.

## 7. What to expect on a real drawing

From the five client drawings used to build this, a first pass with no profile
editing:

| Drawing | Floors | Columns | Beam spans | Slab panels | Time |
| --- | --- | --- | --- | --- | --- |
| Test10 | 7 | 330 | 401 | 194 | 7 s |
| Test14 | 3 | 363 | 663 | 384 | 11 s |
| Test16 | 5 | 328 | 444 | 213 | 6 s |
| Test17 | 13 | 2094 | 4714 | 2345 | 93 s |
| Test18 | 1 | 335 | 972 | 772 | 43 s |

Nothing is guessed silently: anything the tool could not resolve is a diagnostic
with a code,
a floor, a location and an element id, in both the workbook and the report.

## 8. Into Revit (utility 5)

**There is nothing to run.** A Run with floor heights filled in has already prepared the Revit
model: the window names the file, and the button **What Revit will build** opens the workbook
listing every family type it will use and whether your template already has it.

In Revit, open a project from the structural template and press **C2B → Import C2B model**.
It builds the model, reads it back, and reports anything that does not match the plan.

**[docs/revit-run.md](docs/revit-run.md) is the guide** — the one-time pyRevit setup, what the
import reports, and what to send when something breaks. The Revit script has not yet been run
against a live model, so expect to adjust one or two API calls on the first project.

## 9. When something looks wrong

| Symptom | Cause and fix |
| --- | --- |
| Very few columns or beams found | Layer roles were not recognised. Check the **Layers** sheet, fix `*.profile.yaml`, re-run with `--profile` |
| Everything is 25.4 times too big or small | Units. Re-run with `--units mm` (or `ft`, `in`, `m`) |
| One floor only, called “Floor 1” | The drawing has no `Boundary` rectangles and `Origin` points. Add them, or accept one floor per file |
| No elevation frame | `*.levels.xlsx` has no elevations filled in |
| Beams missing on one layer | They are drawn as single centrelines, not as edge pairs. `BEAM_UNPAIRED_LINES` in the report lists them |
| `c2b` is not recognised | The environment is not active: `\.venv\Scripts\activate`, or use the batch files |

Run `c2b --help`, or `c2b run --help`, for every option. `docs\` holds the
schema, the layer
profiles, the template spec and the round trip in detail.
