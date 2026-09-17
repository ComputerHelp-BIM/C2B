"""Members of one wall butt against each other; they do not overlap.

Each leg of a shaped wall runs the full width of the wall, so at a corner or a T the two share
that square. Drawn as they are, the smaller leg pushes into the larger by its width and the
junction comes out doubled. The larger member is the one the client dimensions, so it stays whole
and the smaller is cut back to meet its face.

A cut leg is no longer the length its own tag states, so it takes its size from the drawing --
which is what the client's own dimensions show once the junction is resolved.
"""
from __future__ import annotations

import ezdxf
import pytest
from ezdxf.enums import TextEntityAlignment
from shapely.affinity import rotate
from shapely.geometry import box

from c2b.geometry import shorten_to_clear
from c2b.pipeline import extract


def _size(poly):
    b = poly.bounds
    return tuple(sorted((round(b[2] - b[0]), round(b[3] - b[1]))))


def test_shorten_to_clear_pulls_a_member_back_along_its_own_axis():
    big, small = box(0, 0, 200, 5700), box(0, 0, 2500, 200)
    assert _size(shorten_to_clear(small, big)) == (200, 2300)


def test_shorten_to_clear_survives_a_wall_drawn_off_square():
    """A boolean difference leaves a hairline sliver here and stops being a rectangle at all."""
    big, small = rotate(box(0, 0, 200, 5700), 0.0003, origin=(0, 0)), rotate(box(0, 0, 2500, 200), 0.0003, origin=(0, 0))
    assert _size(shorten_to_clear(small, big)) == (200, 2300)


def test_shorten_to_clear_declines_a_crossing():
    """Both ends stick out past the other member: that is a cross, not a junction."""
    assert shorten_to_clear(box(0, 0, 450, 200), box(150, -500, 350, 500)) is None


def test_shorten_to_clear_leaves_a_member_that_touches_but_does_not_overlap():
    small = box(200, 0, 2500, 200)
    assert shorten_to_clear(small, box(0, 0, 200, 5700)) is small


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """A C-shaped wall drawn as three separate polylines, as this client draws them."""
    path = tmp_path_factory.mktemp("junc") / "junction.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-COLUMN", "S-COLS-IDEN", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-3000, -3000), (12000, -3000), (12000, 12000), (-3000, 12000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((5000, -2500))

    rings = {
        "SW1a-200X5700": [(0, 0), (200, 0), (200, 5700), (0, 5700)],        # the spine, the largest
        "SW1b-200X2300": [(0, 2550), (2300, 2550), (2300, 2750), (0, 2750)],  # a T into the spine
        "SW1c-200X2500": [(0, 0), (2500, 0), (2500, 200), (0, 200)],          # the bottom corner
    }
    for mark, ring in rings.items():
        msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "S-COLUMN"})
        cx = sum(p[0] for p in ring) / 4
        cy = sum(p[1] for p in ring) / 4
        msp.add_text(mark, dxfattribs={"layer": "S-COLS-IDEN", "height": 100}).set_placement(
            (cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(str(path))
    return extract(path).project


def _by(project, base):
    hits = [c for c in project.columns if (c.mark or "").startswith(base)]
    assert len(hits) == 1, f"expected one {base}, got {[c.mark for c in hits]}"
    return hits[0]


def test_the_largest_member_keeps_its_full_length(project):
    a = _by(project, "SW1a")
    assert sorted((a.width_mm, a.depth_mm)) == [200.0, 5700.0]
    assert a.size_source == "tag", "the spine was not cut, so its tag still states its length"


def test_the_smaller_members_are_cut_back_to_meet_it(project):
    b, c = _by(project, "SW1b"), _by(project, "SW1c")
    assert sorted((b.width_mm, b.depth_mm)) == [200.0, 2100.0], "the T leg was not cut back"
    assert sorted((c.width_mm, c.depth_mm)) == [200.0, 2300.0], "the corner leg was not cut back"
    assert b.size_source == "geometry" and c.size_source == "geometry"
    assert b.mark == "SW1b" and c.mark == "SW1c", "a cut leg keeps its own name"


def test_no_two_members_overlap(project):
    from shapely.geometry import Polygon
    polys = [Polygon([(p.x, p.y) for p in c.outline]) for c in project.columns]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            assert polys[i].intersection(polys[j]).area <= 100.0, "two members still overlap"
