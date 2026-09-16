"""Grid labelling rules against the habits of real client drawings.

Two things a drafter does that a naive "nearest text wins" rule gets wrong:
a tower prefix repeated on every bubble, and a short fragment parked beside a
bubble that already belongs to a full-length grid.
"""
from __future__ import annotations

import ezdxf
import pytest

from c2b.pipeline import extract

XS = [0, 6000, 12000, 18000]
YS = [0, 5000, 10000]


def _drawing(path, *, qualifier: bool, stub: bool, dimension: bool = False):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-GRID", "S-GRID-IDEN", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-3000, -3000), (27000, -3000), (27000, 17000), (-3000, 17000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((8000, -2500))
    for i, gx in enumerate(XS):
        msp.add_line((gx, -1500), (gx, 11500), dxfattribs={"layer": "S-GRID"})
        msp.add_text(str(i + 1), dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((gx, -2000))
        # every bubble sits in its own furniture: a leader down to it and a dimension tick across.
        # A real label is therefore beside several lines, which is why only how often the text is
        # *written* can tell it apart from a qualifier.
        msp.add_line((gx, -1600), (gx, -1900), dxfattribs={"layer": "S-GRID"})
        msp.add_line((gx - 400, -2400), (gx + 400, -2400), dxfattribs={"layer": "S-GRID"})
        if qualifier:   # the tower prefix the client repeats on every bubble
            msp.add_text("T1", dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((gx + 150, -2300))
    for j, gy in enumerate(YS):
        msp.add_line((-1500, gy), (19500, gy), dxfattribs={"layer": "S-GRID"})
        msp.add_text("ABC"[j], dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((-2000, gy))
        msp.add_line((-1600, gy), (-1900, gy), dxfattribs={"layer": "S-GRID"})
        msp.add_line((-2400, gy - 400), (-2400, gy + 400), dxfattribs={"layer": "S-GRID"})
        if qualifier:
            msp.add_text("T1", dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((-2300, gy + 150))
    if stub:   # a 1 m jog beside grid 2's bubble: furniture, not a grid line
        msp.add_line((6000, -2100), (6700, -2900), dxfattribs={"layer": "S-GRID"})
    if dimension:
        # the dimension string under the bubbles: long enough to pass for a grid, and it will
        # borrow whichever bubble it happens to end nearest. It runs across the grids it
        # dimensions, so drawing it as a grid would put a line through the plan the wrong way.
        msp.add_line((0, -2600), (18000, -2600), dxfattribs={"layer": "S-GRID"})
        msp.add_line((-2600, 0), (-2600, 10000), dxfattribs={"layer": "S-GRID"})
    doc.saveas(str(path))
    return path


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    return extract(_drawing(tmp_path_factory.mktemp("g") / "plain.dxf", qualifier=False, stub=False)).project


@pytest.fixture(scope="module")
def messy(tmp_path_factory):
    return extract(_drawing(tmp_path_factory.mktemp("g") / "messy.dxf",
                            qualifier=True, stub=True, dimension=True)).project


def _labels(project, axis):
    return sorted(g.label for g in project.grids if g.axis == axis and g.label)


def test_clean_drawing_reads_its_grids(plain):
    assert len(plain.grids) == len(XS) + len(YS)
    assert _labels(plain, "X") == ["1", "2", "3", "4"]
    assert _labels(plain, "Y") == ["A", "B", "C"]


def test_furniture_does_not_become_a_grid(messy):
    """The qualifier, the jog and the dimension strings must change nothing."""
    assert len(messy.grids) == len(XS) + len(YS)
    assert _labels(messy, "X") == ["1", "2", "3", "4"]
    assert _labels(messy, "Y") == ["A", "B", "C"]
    assert not [g for g in messy.grids if g.label == "T1"]
    assert not [g for g in messy.grids if g.axis == "other"]
    assert any(d.code == "GRID_LABEL_QUALIFIER" for d in messy.diagnostics)
    # every grid runs the way its label says: numbers up the page, letters across
    assert {g.axis for g in messy.grids if g.label.isdigit()} == {"X"}
    assert {g.axis for g in messy.grids if not g.label.isdigit()} == {"Y"}


def test_short_stub_keeps_its_bubble_from_a_dimension_string(tmp_path):
    """The client's grid geometry is often just a stub off the end of each bubble.

    Test17 draws its letter grids as 800 mm stubs and runs a dimension string down the margin
    whose ends land exactly on two of those bubbles. The dimension string is the nearer line, so
    deciding by distance hands it the label; deciding which lines are furniture by length first
    throws the stub away before it can argue. Grids B and G went missing on every floor that way.
    """
    path = tmp_path / "stubs.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-GRID", "S-GRID-IDEN", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-4000, -3000), (27000, -3000), (27000, 17000), (-4000, 17000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((8000, -2500))
    for i, gx in enumerate(XS):
        msp.add_line((gx, -1500), (gx, 11500), dxfattribs={"layer": "S-GRID"})
        msp.add_text(str(i + 1), dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((gx, -2000))
    for j, gy in enumerate(YS):
        # an 800 mm stub, shorter than the minimum a grid line has to reach on its own
        msp.add_line((-1600, gy), (-800, gy), dxfattribs={"layer": "S-GRID"})
        msp.add_text("ABC"[j], dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((-2000, gy))
    # the dimension string down the margin: nearer to bubbles A and C than their own stubs are,
    # and long enough to pass for a grid, but running across them rather than off their ends
    msp.add_line((-2300, YS[0]), (-2300, YS[-1]), dxfattribs={"layer": "S-GRID"})
    doc.saveas(str(path))

    project = extract(path).project
    assert _labels(project, "Y") == ["A", "B", "C"], "the stubs own their bubbles, not the dimension string"
    assert _labels(project, "X") == ["1", "2", "3", "4"]
    assert len(project.grids) == len(XS) + len(YS), "the dimension string is not a grid"
