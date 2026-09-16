"""Parsing the template's own marks back into values."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..tags import clean_text, parse_depth, parse_pcc, parse_tag

_RE_PILES = re.compile(r"(\d+)\s*PILES?\s*(\d+(?:\.\d+)?)\s*(?:MM)?\s*DIA", re.I)
_RE_FOLD = re.compile(r"(\d+(?:\.\d+)?)\s*(?:MM)?\s*FOLD", re.I)
_RE_BASE = re.compile(r"^\s*([A-Za-z]{1,4}\d{1,4}[A-Za-z0-9]{0,4})\b")
_RE_SLOPE = re.compile(r"\b1\s*:\s*(\d{1,3})\b")
_RE_DIR = re.compile(r"\b(UP|DN|DOWN)\b", re.I)


@dataclass
class TemplateMark:
    """Everything a template mark carries. All lengths in millimetres."""

    text: str
    base: str | None = None
    width_mm: float | None = None
    depth_mm: float | None = None
    depth_tip_mm: float | None = None
    diameter_mm: float | None = None
    thickness_mm: float | None = None
    fold_mm: float | None = None
    pcc_thickness_mm: float | None = None
    pile_count: int | None = None
    pile_diameter_mm: float | None = None
    pit_depth_mm: float | None = None
    slope_ratio: str | None = None
    direction: str | None = None
    inverted: bool = False
    lines: list[str] = field(default_factory=list)

    @property
    def size(self) -> tuple[float, float] | None:
        return (self.width_mm, self.depth_mm) if self.width_mm and self.depth_mm else None


def parse_template_mark(text: str) -> TemplateMark:
    """Parse a mark written by the template writer (``C12-300X900``, ``B5-200X900/600-INV``,
    ``S16-200THK``, ``RP1-150THK 1:8``, ``1500 FOLD``, ``PCC 100THK``, ``4 PILES 500DIA``)."""
    raw = clean_text(text or "")
    tm = TemplateMark(text=raw, lines=[l for l in raw.split("\n") if l.strip()])
    parsed = parse_tag(raw.replace("\n", " "))
    m = _RE_BASE.match(raw)
    tm.base = m.group(1).upper() if m else parsed.mark
    tm.width_mm, tm.depth_mm, tm.depth_tip_mm = parsed.width_mm, parsed.depth_mm, parsed.depth_alt_mm
    tm.diameter_mm, tm.thickness_mm = parsed.diameter_mm, parsed.thickness_mm
    tm.inverted = parsed.inverted or "-INV" in raw.upper()
    f = _RE_FOLD.search(raw)
    if f:
        tm.fold_mm = float(f.group(1))
    pl = _RE_PILES.search(raw)
    if pl:
        tm.pile_count, tm.pile_diameter_mm = int(pl.group(1)), float(pl.group(2))
    for line in tm.lines:
        pc = parse_pcc(line)
        if pc and pc[0]:
            tm.pcc_thickness_mm = pc[0]
        d = parse_depth(line)
        if d:
            tm.pit_depth_mm = d
    sl = _RE_SLOPE.search(raw)
    if sl:
        tm.slope_ratio = f"1:{sl.group(1)}"
    d = _RE_DIR.search(raw)
    if d:
        tm.direction = "DN" if d.group(1).upper() in ("DN", "DOWN") else "UP"
    return tm
