"""Client legend: which hatch pattern means what, and the hatched regions that use it.

Drawings explain their hatches in a legend ("INDICATES SLAB/BEAM SUNK BY 75MM."). The
swatch next to the text tells us the pattern; every other hatch with that pattern on the
plans is then a region with that meaning. Tags always win over regions downstream.
"""
from __future__ import annotations

import math
import re

from shapely.geometry import Polygon, box

from ..dxfio import Prim
from ..schema import LegendItem, Point2, Region
from ..tags import clean_text, parse_length_mm

_RE_LEGEND = re.compile(r"^\W*(?:INDICATES|THUS\s+MARKED|DENOTES|SHOWS|HATCH(?:ED)?\s+(?:AREA\s+)?(?:INDICATES|SHOWS|DENOTES)|LEGEND)\b", re.I)
_RE_SUNK = re.compile(r"SUNK\s*(?:BY)?\s*(\d+(?:\.\d+)?)\s*(MM|M)?|(\d+(?:\.\d+)?)\s*(MM|M)?\s*SUNK", re.I)
_RE_DEPRESS = re.compile(r"(?:DEPRESS(?:ED|ION)?|DROP(?:PED)?)\s*(?:BY)?\s*(\d+(?:\.\d+)?)\s*(MM|M)?", re.I)


def classify_meaning(text: str) -> tuple[str, float | None]:
    up = clean_text(text).upper()
    m = _RE_SUNK.search(up) or _RE_DEPRESS.search(up)
    if m and "RAFT" not in up:
        num = m.group(1) or (m.group(3) if m.lastindex and m.lastindex >= 3 else None)
        unit = (m.group(2) or (m.group(4) if m.lastindex and m.lastindex >= 4 else None) or "")
        val = parse_length_mm((num or "") + unit) if num else None
        return "sunk", val
    if "BEAM BOTTOM" in up or "BEAM BTM" in up or "BM. BOTTOM" in up:
        return ("projection" if "PROJECTION" in up else "beam_bottom"), None
    if ("COLUMN" in up or "COL." in up or "SHEAR WALL" in up) and ("STOP" in up or "END" in up or "TERMINAT" in up or "DISCONTINU" in up):
        return "column_stop", None
    if ("COLUMN" in up or "COL." in up) and ("START" in up or "BEGIN" in up):
        return "column_start", None
    if ("CUT" in up and "OUT" in up) or "OPENING" in up or "DUCT" in up:
        return "cutout", None
    if "RAFT" in up and ("SUNK" in up or "FOLD" in up):
        return "fold", None
    if "FOLD" in up:
        return "fold", None
    if "UPSTAND" in up or "UP-STAND" in up:
        return "upstand", None
    if "DROP" in up:
        return "drop", None
    return "other", None


#: How far either side of a legend line its swatch may sit, in text heights. The swatch search
#: below allows 30 to the left and 4 to the right; the zone is drawn a little wider than that.
_ZONE_LEFT_H = 36.0
_ZONE_RIGHT_H = 6.0
_ZONE_ABOVE_H = 2.0


def legend_zones(prims: list[Prim]) -> list[Polygon]:
    """The strip each legend line occupies, swatch included.

    Nothing inside it is structure. The swatches are drawn exactly like the thing they explain --
    a hatch, a rectangle, a cut-out cross -- so on a sheet where the legend sits under the plan,
    inside the floor's own frame, they are read as a stub column and an opening unless the band
    they live in is ruled out first. Built from the legend *text*, which is always found, rather
    than from the swatch, which for a cut-out is a plain rectangle with no hatch to match.
    """
    zones: list[Polygon] = []
    for t in prims:
        if t.kind != "text" or not t.text or not _RE_LEGEND.match(clean_text(t.text)):
            continue
        h = t.text_height or 125.0
        ax, ay = t.extra.get("anchor", t.rep_point())
        width = t.extra.get("box_w") or (0.7 * h * len(t.text))
        zones.append(box(ax - _ZONE_LEFT_H * h, ay - _ZONE_ABOVE_H * h,
                         ax + width + _ZONE_RIGHT_H * h, ay + _ZONE_ABOVE_H * h))
    return zones


def parse_legend(prims: list[Prim]) -> tuple[list[LegendItem], set[str]]:
    """Return legend items and the handles of the swatch hatches (so they are not treated as regions)."""
    texts = [p for p in prims if p.kind == "text" and p.text and _RE_LEGEND.match(clean_text(p.text))]
    hatches = [p for p in prims if p.kind == "hatch" and p.extra.get("pattern")]
    items: list[LegendItem] = []
    swatches: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for t in texts:
        h = t.text_height or 125.0
        anchor = t.extra.get("anchor", t.rep_point())
        best, best_d = None, None
        for hp in hatches:
            c = hp.geom.centroid
            dx, dy = anchor[0] - c.x, anchor[1] - c.y
            # swatch: a small box on the same row, to the left of the text (or just right of it)
            if abs(dy) > 2.5 * h or hp.geom.area > (40 * h) ** 2:
                continue
            if not (-4 * h <= dx <= 30 * h):
                continue
            d = math.hypot(dx, dy)
            if best_d is None or d < best_d:
                best, best_d = hp, d
        if best is None:
            continue
        meaning, val = classify_meaning(t.text)
        pattern = best.extra["pattern"]
        swatches.add(best.handle)
        key = (pattern, clean_text(t.text).upper())
        if key in seen:
            continue
        seen.add(key)
        items.append(LegendItem(pattern=pattern, meaning=meaning, value_mm=val, text=clean_text(t.text), handle=t.handle))
    return items, swatches


def regions_from_hatches(prims: list[Prim], legend: list[LegendItem], swatches: set[str], floor_id: str, ids, min_area: float = 1e5) -> list[Region]:
    by_pattern: dict[str, LegendItem] = {}
    for it in legend:
        if it.meaning != "other":
            by_pattern.setdefault(it.pattern.upper(), it)
    out: list[Region] = []
    if not by_pattern:
        return out
    for p in prims:
        if p.kind != "hatch" or p.handle in swatches:
            continue
        item = by_pattern.get((p.extra.get("pattern") or "").upper())
        if item is None or p.geom.area < min_area:
            continue
        coords = list(p.geom.exterior.coords)[:-1]
        out.append(Region(id=ids.next("R"), floor_id=floor_id, meaning=item.meaning, value_mm=item.value_mm, pattern=item.pattern,
                          outline=[Point2(x=x, y=y) for x, y in coords], area_mm2=round(p.geom.area, 1), source_layer=p.layer, source_handles=[p.handle]))
    return out
