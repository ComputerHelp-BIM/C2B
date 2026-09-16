"""A tag must reach the member it names, even when a neighbour is marginally nearer.

Two failures the client's drawings produce, both from marks written in the gap between two legs
of a wall:

* the marks are *swapped*, because each sits a few millimetres nearer the other leg;
* a leg is left with **no mark at all**, because the tag that was its only candidate went to a
  neighbour, and freeing it takes a chain of moves rather than one.

The size the client wrote on the tag settles the first. Re-homing along a chain settles the
second. Neither is covered by simply rebalancing an over-tagged element onto a bare neighbour.
"""
from __future__ import annotations

import ezdxf
import pytest
from ezdxf.enums import TextEntityAlignment

from c2b.pipeline import extract


def _extract(path, legs, tags):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-COLS", "S-COLS-IDEN", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-3000, -3000), (9000, -3000), (9000, 9000), (-3000, 9000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((3000, -2500))
    for x0, x1, y1 in legs:
        msp.add_lwpolyline([(x0, 0), (x1, 0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "S-COLS"})
    for x, y, txt in tags:
        # centred, so the tag sits where the test says rather than a text-width to its right
        msp.add_text(txt, dxfattribs={"layer": "S-COLS-IDEN", "height": 100}).set_placement(
            (x, y), align=TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(str(path))
    return extract(path).project


def _leg(project, x_min: float):
    hits = [c for c in project.columns if abs(min(p.x for p in c.outline) - x_min) < 1]
    assert len(hits) == 1, f"expected one leg at x={x_min}, got {len(hits)}"
    return hits[0]


def test_the_stated_size_decides_which_leg_a_tag_names(tmp_path):
    """Both marks are written in the gap, each nearer the leg it does *not* name.

    Nearest-outline-wins swaps them, and nothing later notices: neither leg is bare and neither
    holds two, so there is nothing to rebalance. Only the size on the tag tells them apart.
    """
    project = _extract(tmp_path / "swap.dxf",
                       legs=[(0, 200, 600), (500, 700, 1400)],
                       tags=[(360, 200, "SW1-200X600"),      # 160 from A, 140 from B
                             (340, 500, "SW2-200X1400")])    # 140 from A, 160 from B
    a, b = _leg(project, 0), _leg(project, 500)
    assert a.mark == "SW1", "the 200x600 tag names the 200x600 leg, not the nearer one"
    assert b.mark == "SW2"
    assert (a.width_mm, a.depth_mm) == (200.0, 600.0)
    assert (b.width_mm, b.depth_mm) == (200.0, 1400.0)


def test_no_leg_is_left_blank_when_freeing_its_tag_takes_a_chain(tmp_path):
    """Three legs of one section, so the sizes cannot tell them apart.

    A's only candidate is held by B, and B holds just the one, so there is nothing for B to
    spare; B's own second candidate is held by C, which has two. Feeding A means moving C's
    spare to B first. A single rebalance pass cannot see that far and leaves A bare.
    """
    project = _extract(tmp_path / "chain.dxf",
                       legs=[(0, 200, 600), (500, 700, 600), (1000, 1200, 600)],
                       tags=[(360, 500, "SW1-200X600"),      # 160 from A, 140 from B
                             (860, 500, "SW2-200X600"),      # 160 from B, 140 from C
                             (1600, 300, "SW3-200X600")])    # 400 from C, out of B's reach
    a, b, c = _leg(project, 0), _leg(project, 500), _leg(project, 1000)
    assert a.mark and b.mark and c.mark, f"a leg lost its mark: {a.mark!r} {b.mark!r} {c.mark!r}"
    assert {a.mark, b.mark, c.mark} == {"SW1", "SW2", "SW3"}, "a tag was used twice while another went nowhere"


def test_size_source_outline_measures_the_drawing_instead(tmp_path):
    """Answer 5: which witness wins is a setting, defaulting to the tag.

    The leg is drawn 200 x 640 but tagged 200X600. With the default the mark's size is taken;
    with ``size_sources.column = "outline"`` the drawing is measured and the tag keeps the mark.
    """
    from c2b.pipeline import extract
    from c2b.profile import Profile

    def build(path):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        msp = doc.modelspace()
        for name in ("Boundary", "Origin", "S-COLS", "S-COLS-IDEN", "G-ANNO-TEXT"):
            doc.layers.add(name)
        msp.add_lwpolyline([(-3000, -3000), (9000, -3000), (9000, 9000), (-3000, 9000)],
                           close=True, dxfattribs={"layer": "Boundary"})
        msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
        msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((3000, -2500))
        msp.add_lwpolyline([(0, 0), (200, 0), (200, 640), (0, 640)], close=True, dxfattribs={"layer": "S-COLS"})
        msp.add_text("SW1-200X600", dxfattribs={"layer": "S-COLS-IDEN", "height": 100}).set_placement(
            (100, 320), align=TextEntityAlignment.MIDDLE_CENTER)
        doc.saveas(str(path))
        return path

    path = build(tmp_path / "source.dxf")
    by_tag = extract(path).project.columns[0]
    assert (by_tag.width_mm, by_tag.depth_mm) == (200.0, 600.0) and by_tag.size_source == "tag"

    profile = Profile()
    profile.size_sources.column = "outline"
    by_outline = extract(path, user_profile=profile).project.columns[0]
    assert (by_outline.width_mm, by_outline.depth_mm) == (200.0, 640.0)
    assert by_outline.size_source == "geometry"
    assert by_outline.mark == "SW1", "the tag still names the column even when the drawing sizes it"
