"""Grid line extraction."""
from __future__ import annotations

import itertools
import math
import re

from ..geometry import Segment, merge_collinear
from ..schema import Grid
from .context import FloorContext, pt

_RE_GOOD_LABEL = re.compile(r"^(?:[A-Z]{1,2}\d?|\d{1,3}[A-Z]?|[A-Z]\d{1,2})$")

#: A real grid label is written once, or twice when the client bubbles both ends of its line.
#: These bound what counts as "written on every bubble instead of naming one line": a qualifier
#: has to clear both, so a small floor with only a handful of grids cannot trip the rule.
_QUALIFIER_MIN_COUNT = 5
_QUALIFIER_MIN_SHARE = 0.25

#: How far off a line's own axis a bubble may sit and still be read as belonging to it, as
#: cos(37 deg). ``_BUBBLE_ON_AXIS_MM`` only guards the division when a bubble sits on an endpoint.
_BUBBLE_AXIS_COS = 0.8
_BUBBLE_ON_AXIS_MM = 1.0


def _on_axis(seg: Segment, c: tuple[float, float]) -> bool:
    """Does this bubble sit beyond an end of the line, on the line's own axis?

    A grid bubble is drawn off the end of its grid line, pointing back along it. A dimension
    string or a section line that happens to run past the same bubble has it off to one side
    instead. That is what tells the two apart when both are within reach of the text, and it is
    the difference between grid B running across the plan and running down its left margin.
    """
    for end, other in ((seg.p1, seg.p2), (seg.p2, seg.p1)):
        vx, vy = c[0] - end[0], c[1] - end[1]
        d = math.hypot(vx, vy)
        if d <= _BUBBLE_ON_AXIS_MM:
            return True
        ux, uy = end[0] - other[0], end[1] - other[1]
        length = math.hypot(ux, uy) or 1.0
        if (vx * ux + vy * uy) / (d * length) >= _BUBBLE_AXIS_COS:
            return True
    return False


def _label_priority(text: str) -> int:
    t = text.strip()
    if _RE_GOOD_LABEL.match(t):
        return 0
    if len(t) <= 4:
        return 1
    return 2


def extract_grids(ctx: FloorContext) -> list[Grid]:
    tol = ctx.tol
    segs: list[Segment] = []
    for p in ctx.geoms("GRID", "line", "polyline"):
        coords = list(p.geom.coords)
        for a, b in itertools.pairwise(coords):
            s = Segment((a[0], a[1]), (b[0], b[1]), [p.handle], p.layer)
            if s.length >= tol.grid_min_length_mm * 0.25:
                segs.append(s)
    if not segs:
        if ctx.by_geom_role.get("COLUMN") or ctx.by_geom_role.get("BEAM"):
            ctx.diag.warning("NO_GRIDS", "No grid lines found on this floor", floor_id=ctx.floor_id)
        return []
    labels = [t for t in ctx.texts("GRID_TAG") if len((t.text or "").strip()) <= 6]
    label_pts = [(t, t.rep_point()) for t in labels]
    candidates = merge_collinear(segs, angle_tol=0.5, offset_tol=5.0, gap_tol=tol.grid_label_radius_mm)

    # A grid label names one line on a floor -- that is what it is for, so the client writes it
    # once, or twice if they bubble both ends. A text written on nearly every bubble is a
    # qualifier they repeat throughout (a tower prefix such as "T1", a sheet code); it identifies
    # nothing, so it is struck from the pool before any line is named. Counting how often the
    # text is *written* is what separates the two: counting the lines it happens to sit beside
    # would also catch a real label, which is surrounded by its own leader, dimension and ticks.
    counts: dict[str, int] = {}
    for t in labels:
        txt = (t.text or "").strip()
        counts[txt] = counts.get(txt, 0) + 1
    threshold = max(_QUALIFIER_MIN_COUNT, _QUALIFIER_MIN_SHARE * len(labels))
    qualifiers = {txt for txt, n in counts.items() if n > threshold}
    if qualifiers:
        ctx.diag.info("GRID_LABEL_QUALIFIER", f"Ignored grid bubble text repeated on most bubbles: {', '.join(sorted(qualifiers))}", floor_id=ctx.floor_id)
        label_pts = [(t, c) for t, c in label_pts if (t.text or "").strip() not in qualifiers]

    # --- pass 1: the best bubble for each candidate line ------------------------------------
    # Every candidate is considered, short ones included: which lines are furniture is settled by
    # which of them owns a bubble, not by length. Settling it by length first throws away the
    # client's own 800 mm grid stub whenever a dimension string runs past the same bubble.
    def axis_of(seg: Segment) -> tuple[str, float]:
        ang = seg.angle_deg
        if abs(ang - 90) <= 1.0:
            return "X", 0.5 * (seg.p1[0] + seg.p2[0])
        if ang <= 1.0 or ang >= 179.0:
            return "Y", 0.5 * (seg.p1[1] + seg.p2[1])
        return "other", 0.0

    picks: list[tuple[str | None, tuple, object]] = []
    for s in candidates:
        best = None
        for t, c in label_pts:
            d = min(math.dist(c, s.p1), math.dist(c, s.p2))
            if d > tol.grid_label_radius_mm:
                continue
            # a bubble off the end of this line beats a nearer one sitting across it
            key = (_label_priority(t.text), 0 if _on_axis(s, c) else 1, d)
            if best is None or key < best[0]:
                best = (key, t)
        picks.append(((best[1].text or "").strip() if best else None, best[0] if best else (9, 9, math.inf), best[1] if best else None))

    # --- pass 2: a label names one line, so the best-placed bubble wins it -------------------
    # Furniture within reach of a bubble -- a dimension string down the margin, a section line --
    # borrows its text, and would otherwise be drawn as a grid running the wrong way across the
    # plan. It cannot own the text: the line the client actually bubbled is either off that
    # bubble's end or nearer to it. The borrower is left unnamed, and is then dropped.
    owner: dict[str, int] = {}
    for i, (label, key, _t) in enumerate(picks):
        if label is None:
            continue
        j = owner.get(label)
        if j is None or key < picks[j][1]:
            owner[label] = i

    grids: list[Grid] = []
    unlabeled = 0
    for i, (s, (label, _key, tag)) in enumerate(zip(candidates, picks)):
        axis, offset = axis_of(s)
        if label is None and s.length < tol.grid_min_length_mm:
            continue                                  # a short line with no bubble of its own
        if label is not None and owner[label] != i:
            winner = candidates[owner[label]]
            w_axis, w_offset = axis_of(winner)
            # only a line that could have been a grid in its own right is worth reporting as a
            # clash; a tick or a leader losing a label it merely borrowed is not news
            if w_axis == axis and abs(w_offset - offset) > 50 and s.length >= tol.grid_min_length_mm:
                # two lines the same way up, both bubbled the same: the client's own clash
                ctx.diag.warning("GRID_DUPLICATE_LABEL", f"Grid label '{label}' appears on two different {axis} lines ({w_offset:.0f} and {offset:.0f}); the nearer bubble wins", floor_id=ctx.floor_id, location=s.p1)
            continue
        if tag is not None:
            ctx.assigned_tag_handles.add(tag.prim_handle if hasattr(tag, "prim_handle") else tag.handle)
        else:
            unlabeled += 1
        grids.append(Grid(id=ctx.ids.next("G"), floor_id=ctx.floor_id, label=label, axis=axis, start=pt(s.p1), end=pt(s.p2),
                          angle_deg=round(s.angle_deg, 3), offset_mm=round(offset, 1), source_layer=s.layer, source_handles=s.handles))
    if unlabeled:
        ctx.diag.warning("GRID_NO_LABEL", f"{unlabeled} grid line(s) have no label within {tol.grid_label_radius_mm:.0f} mm of their ends", floor_id=ctx.floor_id)
    ctx.grids_x = [(g.label, g.offset_mm) for g in grids if g.axis == "X" and g.label]
    ctx.grids_y = [(g.label, g.offset_mm) for g in grids if g.axis == "Y" and g.label]
    return grids
