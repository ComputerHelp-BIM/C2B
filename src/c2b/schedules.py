"""Schedule table parsing.

Many drawings give member sizes in a table (Mark | b | h | Thk) rather than on
the plan. The table is just text entities laid out on a grid, so this module
rebuilds rows and columns from text positions. Two layouts are supported:

* classic grids: a header row with ``Mark`` and size columns, data rows below;
* "size -> marks" lists: ``BEAM SIZE`` / ``BEAM NO.`` columns with comma
  separated marks per size row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .diagnostics import DiagnosticsCollector
from .dxfio import Prim
from .tags import parse_length_mm, parse_size_from_name, parse_symbolic_size, parse_tag

_HEADER_ALIASES: dict[str, str] = {
    "mark": "mark", "marks": "mark", "no": "mark", "no.": "mark", "beam no": "mark", "beam no.": "mark", "column no": "mark",
    "column no.": "mark", "col no": "mark", "col. no.": "mark", "footing no": "mark", "member": "mark", "type": "mark",
    "b": "width", "width": "width", "w": "width", "breadth": "width",
    "h": "depth", "d": "depth", "depth": "depth", "dp": "depth", "height": "depth",
    "thk": "thickness", "thk.": "thickness", "t": "thickness", "thickness": "thickness",
    "size": "size", "beam size": "size", "column size": "size", "sizes": "size", "section": "size",
    "dia": "diameter", "dia.": "diameter", "diameter": "diameter",
    "l": "length", "length": "length",
}
_TITLE_RE = re.compile(r"schedule", re.I)
_CATEGORY_WORDS = [("footing", "footing"), ("foundation", "footing"), ("column", "column"), ("shear", "wall"),
                   ("wall", "wall"), ("beam", "beam"), ("slab", "slab")]
_MARK_RE = re.compile(r"^[A-Z]{1,4}\d{0,4}[A-Za-z]{0,2}$")


@dataclass
class ScheduleTable:
    id: str
    title: str | None
    category: str | None
    columns: list[str]
    rows: list[dict]
    layer: str
    lookup: dict[str, dict] = field(default_factory=dict)


def _norm_header(text: str) -> str | None:
    key = text.strip().lower().rstrip(":")
    return _HEADER_ALIASES.get(key)


def _category_from_title(title: str | None) -> str | None:
    if not title:
        return None
    low = title.lower()
    for word, cat in _CATEGORY_WORDS:
        if word in low:
            return cat
    return None


def _cluster_rows(items: list[Prim], tol: float) -> list[list[Prim]]:
    items = sorted(items, key=lambda p: -p.rep_point()[1])
    rows: list[list[Prim]] = []
    for p in items:
        y = p.rep_point()[1]
        if rows and abs(rows[-1][0].rep_point()[1] - y) <= tol:
            rows[-1].append(p)
        else:
            rows.append([p])
    for r in rows:
        r.sort(key=lambda p: p.rep_point()[0])
    return rows


def parse_schedules(texts: list[Prim], diag: DiagnosticsCollector, row_tol_factor: float = 0.6) -> list[ScheduleTable]:
    """Parse all schedule tables found among ``texts`` (schedule-role text prims)."""
    texts = [t for t in texts if t.text and t.text.strip()]
    if not texts:
        return []
    height = sorted(t.text_height for t in texts)[len(texts) // 2] or 1.0
    tol = max(height * row_tol_factor, 1.0)
    rows = _cluster_rows(texts, tol)

    tables: list[ScheduleTable] = []
    counter = 0
    used: set[int] = set()
    for ri, row in enumerate(rows):
        header_cells = [(p, _norm_header(p.text)) for p in row]
        if not any(h == "mark" for _, h in header_cells):
            continue
        # split the row into tables at every "mark" header
        starts = [i for i, (_, h) in enumerate(header_cells) if h == "mark"]
        for si, start in enumerate(starts):
            end = starts[si + 1] if si + 1 < len(starts) else len(header_cells)
            cells = [(p, h) for p, h in header_cells[start:end] if h]
            if len(cells) < 2:
                continue
            col_x = [(h, p.rep_point()[0]) for p, h in cells]
            x_min = min(x for _, x in col_x) - height * 2
            x_max = max(x for _, x in col_x) + height * 8
            if si + 1 < len(starts):
                x_max = min(x_max, header_cells[starts[si + 1]][0].rep_point()[0] - height)
            header_y = row[0].rep_point()[1]
            # title: text above the header within 3 rows containing "schedule"
            title = None
            for prev in rows[max(0, ri - 3):ri]:
                for p in prev:
                    x = p.rep_point()[0]
                    if x_min - height * 6 <= x <= x_max and _TITLE_RE.search(p.text):
                        title = p.text.strip()
            data_rows: list[dict] = []
            for nxt in rows[ri + 1:]:
                cells_in = [p for p in nxt if x_min <= p.rep_point()[0] <= x_max]
                if not cells_in:
                    continue
                if any(_norm_header(p.text) == "mark" or _TITLE_RE.search(p.text) for p in cells_in):
                    break
                if nxt[0].rep_point()[1] < header_y - height * 400:
                    break
                record: dict = {}
                for p in cells_in:
                    x = p.rep_point()[0]
                    col = min(col_x, key=lambda c: abs(c[1] - x))[0]
                    record[col] = p.text.strip()
                    used.add(id(p))
                if "mark" in record:
                    data_rows.append(record)
            if not data_rows:
                continue
            counter += 1
            table = _build_table(f"SCH{counter:02d}", title, [h for h, _ in col_x], data_rows, row[0].layer)
            tables.append(table)

    # size -> marks lists (header "BEAM SIZE" | "BEAM NO.")
    for ri, row in enumerate(rows):
        cells = [(p, p.text.strip().lower()) for p in row]
        size_cols = [p for p, t in cells if t in ("beam size", "column size", "size", "sizes")]
        mark_cols = [p for p, t in cells if t in ("beam no.", "beam no", "column no.", "column no", "mark", "marks", "beam mark", "beams")]
        if not size_cols or not mark_cols or any(id(p) in used for p in row):
            continue
        sx, mx = size_cols[0].rep_point()[0], mark_cols[0].rep_point()[0]
        half = abs(mx - sx) / 2 or height * 5
        header_y = row[0].rep_point()[1]
        title = None
        for prev in rows[max(0, ri - 3):ri]:
            for p in prev:
                if _TITLE_RE.search(p.text) and abs(p.rep_point()[0] - (sx + mx) / 2) < half * 4:
                    title = p.text.strip()
        data_rows = []
        for nxt in rows[ri + 1:]:
            size_txt = [p for p in nxt if abs(p.rep_point()[0] - sx) <= half]
            mark_txt = [p for p in nxt if abs(p.rep_point()[0] - mx) <= half]
            if not size_txt and not mark_txt:
                continue
            if any(_TITLE_RE.search(p.text) for p in nxt):
                break
            if not size_txt or not mark_txt:
                continue
            raw_size = size_txt[0].text.strip()
            size = parse_size_from_name(raw_size)
            symbolic = None if size else parse_symbolic_size(raw_size)
            marks = [m.strip() for m in re.split(r"[,/;&]| and ", mark_txt[0].text) if m.strip()]
            if not (size or symbolic) or not marks:
                continue
            for m in marks:
                if size:
                    data_rows.append({"mark": m, "width": size[0], "depth": size[1], "size": raw_size})
                else:
                    # the table states a rule where a number will not fit ("300XSLB THK."); the
                    # width is still real, and the rule is resolved where the answer is known
                    data_rows.append({"mark": m, "width": symbolic[0], "depth": None, "size": raw_size,
                                      "depth_rule": symbolic[1]})
        if data_rows:
            counter += 1
            tables.append(_build_table(f"SCH{counter:02d}", title or size_cols[0].text, ["mark", "width", "depth", "depth_rule"], data_rows, row[0].layer))

    return tables


def _build_table(tid: str, title: str | None, columns: list[str], data_rows: list[dict], layer: str) -> ScheduleTable:
    category = _category_from_title(title)
    rows: list[dict] = []
    lookup: dict[str, dict] = {}
    for rec in data_rows:
        mark = str(rec.get("mark", "")).strip()
        if not mark:
            continue
        vals: dict = {"mark": mark}
        for col, raw in rec.items():
            if col == "mark":
                continue
            if isinstance(raw, (int, float)):
                vals[col] = float(raw)
                continue
            if col == "size":
                size = parse_size_from_name(str(raw))
                if size:
                    vals["width"], vals["depth"] = size
                vals["size"] = raw
                continue
            num = parse_length_mm(str(raw))
            vals[col] = num if num is not None else raw
        if category is None:
            tag = parse_tag(mark)
            category = tag.category_hint
        rows.append(vals)
        lookup[mark.upper()] = vals
    return ScheduleTable(tid, title, category, columns, rows, layer, lookup)


class ScheduleIndex:
    """Mark -> size lookup across all tables, with category awareness."""

    def __init__(self, tables: list[ScheduleTable]):
        self.tables = tables
        self.by_mark: dict[str, list[tuple[ScheduleTable, dict]]] = {}
        for t in tables:
            for mark, vals in t.lookup.items():
                self.by_mark.setdefault(mark, []).append((t, vals))

    def find(self, mark: str | None, category: str | None = None) -> dict | None:
        if not mark:
            return None
        hits = self.by_mark.get(mark.upper())
        if not hits:
            return None
        if category:
            for t, vals in hits:
                if t.category == category:
                    return vals
        return hits[0][1]

    def __len__(self) -> int:
        return len(self.by_mark)
