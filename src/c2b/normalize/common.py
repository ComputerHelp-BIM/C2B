"""Small helpers shared by the normalisation phases.

Kept in one place so a phase can be lifted into its own module without dragging the whole
pipeline behind it.
"""
from __future__ import annotations

from ..schema import Point2


def to_pt(p) -> Point2:
    return Point2(x=round(p[0], 2), y=round(p[1], 2))


def to_pts(ring) -> list[Point2]:
    return [Point2(x=x, y=y) for x, y in ring]


def format_mark(template: str, **kw) -> str:
    class _Safe(dict):
        def __missing__(self, k):
            return "?"
    try:
        return template.format_map(_Safe(**kw))
    except (ValueError, TypeError):
        return template


def parse_pcc_safe(text: str):
    from ..tags import parse_pcc
    try:
        return parse_pcc(text or "")
    except Exception:
        return None


def tagged_size(c) -> tuple[float, float] | None:
    """Size in the order the client's tag states it, else (short, long) from the resolved size."""
    from ..tags import parse_tag
    if c.size_source == "geometry" and c.width_mm and c.depth_mm:
        # the drawing is the authority here -- a leg cut back to butt against a larger one, or a
        # member the client never tagged -- so the mark states what is built, not what the tag
        # said before the cut
        return (min(c.width_mm, c.depth_mm), max(c.width_mm, c.depth_mm))
    for t in c.tags:
        pt = parse_tag(t.text)
        if pt.width_mm and pt.depth_mm:
            return (pt.width_mm, pt.depth_mm)
    if c.width_mm and c.depth_mm:
        if c.size_source == "schedule":
            return (c.width_mm, c.depth_mm)
        return (min(c.width_mm, c.depth_mm), max(c.width_mm, c.depth_mm))
    return None


