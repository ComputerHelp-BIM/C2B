"""Level schedule (Excel) template and reader.

Plans do not carry floor elevations. The extractor writes a template listing the
floors it found; the engineer fills in elevations; ``--levels`` feeds them back.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook

from ..schema import Project

HEADERS = ["floor_id", "floor_name", "order", "elevation_mm", "floor_to_floor_mm", "revit_level_name", "notes"]


def _match_hint(floor_name: str, hints) -> tuple[float, str] | None:
    """Pick the level hint whose name shares the most words with the floor name."""
    words = {w for w in floor_name.upper().replace(".", " ").split() if w not in ("LEVEL", "LVL", "FLOOR", "AT", "LAYOUT", "PLAN", "-")}
    best, score = None, 0
    for h in hints:
        hw = {w for w in h.name.upper().replace(".", " ").split() if w not in ("LEVEL", "LVL", "FLOOR")}
        common = len(words & hw)
        if common > score:
            best, score = h, common
    return (best.elevation_mm, best.text) if best and score else None


def write_levels_template(project: Project, path: str | Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Levels"
    ws.append(HEADERS)
    for f in project.floors:
        hint = _match_hint(f.name, project.level_hints) if f.elevation_mm is None else None
        elev = f.elevation_mm if f.elevation_mm is not None else (hint[0] if hint else None)
        note = "fill elevation_mm (top of structural slab) in mm" if elev is None else (f"from client text '{hint[1]}', please confirm" if hint else "")
        ws.append([f.id, f.name, f.index, elev, f.floor_to_floor_mm, None, note])
    ws.freeze_panes = "A2"
    for col, width in zip("ABCDEFG", (10, 36, 8, 16, 18, 24, 50)):
        ws.column_dimensions[col].width = width
    if project.level_hints:
        hs = wb.create_sheet("Level hints")
        hs.append(["name", "elevation_mm", "client text", "handle", "layer", "floor"])
        for h in sorted(project.level_hints, key=lambda h: h.elevation_mm):
            hs.append([h.name, h.elevation_mm, h.text, h.handle, h.layer, h.floor_id])
        for col, width in zip("ABCDEF", (30, 14, 60, 10, 24, 8)):
            hs.column_dimensions[col].width = width
    wb.save(str(path))
    return Path(path)


def apply_levels(project: Project, path: str | Path) -> list[str]:
    """Read a filled level schedule into the project floors. Returns a list of problems."""
    problems: list[str] = []
    wb = load_workbook(str(path), data_only=True)
    ws = wb["Levels"] if "Levels" in wb.sheetnames else wb.active
    header = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    idx = {h: i for i, h in enumerate(header)}
    if "floor_id" not in idx:
        return ["level schedule has no 'floor_id' column"]
    by_id = {f.id: f for f in project.floors}
    by_name = {f.name.strip().lower(): f for f in project.floors}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or all(v is None for v in row):
            continue
        fid = str(row[idx["floor_id"]]).strip() if row[idx["floor_id"]] is not None else ""
        floor = by_id.get(fid) or by_name.get(str(row[idx.get("floor_name", 0)] or "").strip().lower())
        if floor is None:
            problems.append(f"level row '{fid}' does not match any floor in the drawing")
            continue
        for key, attr in (("elevation_mm", "elevation_mm"), ("floor_to_floor_mm", "floor_to_floor_mm")):
            if key in idx and row[idx[key]] is not None:
                try:
                    setattr(floor, attr, float(row[idx[key]]))
                except (TypeError, ValueError):
                    problems.append(f"{fid}: {key} '{row[idx[key]]}' is not a number")
        if "order" in idx and row[idx["order"]] is not None:
            try:
                floor.index = int(row[idx["order"]])
            except (TypeError, ValueError):
                problems.append(f"{fid}: order '{row[idx['order']]}' is not an integer")
    project.floors.sort(key=lambda f: f.index)
    return problems


def read_levels(path: str | Path) -> list:
    """Read the level schedule as rows (a plan floor may own several levels, e.g. a typical floor)."""
    from ..normalize.pipeline import LevelRow

    wb = load_workbook(str(path), data_only=True)
    ws = wb["Levels"] if "Levels" in wb.sheetnames else wb.active
    header = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    idx = {h: i for i, h in enumerate(header)}
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or all(v is None for v in row):
            continue

        def val(key):
            i = idx.get(key)
            return row[i] if i is not None and i < len(row) else None

        def num(key):
            v = val(key)
            try:
                return float(v) if v is not None and str(v).strip() != "" else None
            except (TypeError, ValueError):
                return None

        fid = str(val("floor_id")).strip() if val("floor_id") not in (None, "") else None
        rows.append(LevelRow(fid, str(val("floor_name") or "").strip() or None, int(num("order") or 0) if num("order") is not None else None,
                             num("elevation_mm"), num("floor_to_floor_mm"), str(val("revit_level_name") or "").strip() or None))
    return rows
