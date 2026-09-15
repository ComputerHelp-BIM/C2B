# Windows helpers

| File | What it does |
|---|---|
| `install.bat` | One-time setup: creates `.venv` next to the repository, installs C2B, runs `c2b doctor` |
| `C2B.bat` | **the window** - double-click it, or drag a drawing onto it. This is what drafters use |
| `C2B-run.bat` | Drag a client DXF or DWG onto it: extract, normalise to the template, verify |
| `C2B-verify.bat` | Drag an edited `*.template.dxf` onto it: lists every change against the model |

Put your own template at `templates\CH-TEMPLATE.dxf` and `C2B-run.bat` will use it as the
seed automatically (layers, text styles, dimension style and legend are taken from it).

Make a desktop shortcut to `C2B.bat` for each drafter: right-click it, Send to, Desktop.

These are convenience wrappers. Everything they do is available from a command prompt with
`.venv\Scripts\activate` followed by `c2b --help`.
