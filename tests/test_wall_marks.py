"""How a shear wall carries its mark, end to end.

A 200 mm wall cannot hold "T1SW136c-200X2500" inside it, and rotating the text into the wall
runs it over the beams alongside -- which is what the client's own drawings avoid by writing the
mark beside the wall on two lines. The rules that keep that honest:

* the two lines must still read back as the one mark, so utility 4 loses nothing;
* the size shown is the size the *mark* states, never the size measured off the polyline, so a
  client tag that disagrees with their own geometry is reported once rather than drawn as a
  third number;
* the decision is the normaliser's, so the workbook, the DXF and Revit all place it identically.
"""
from __future__ import annotations

import ezdxf
import pytest

from c2b.export.template_dxf import write_template_dxf
from c2b.normalize.naming import split_mark_size
from c2b.normalize.pipeline import LevelRow, normalize
from c2b.normalize.spec import TemplateSpec
from c2b.pipeline import extract
from c2b.roundtrip.reader import TemplateReader

#: the wall as drawn: 200 wide, 2950 deep, tagged 200X2500 -- the client's own numbers disagree
WALL = [(4000.0, 1000.0), (4200.0, 1000.0), (4200.0, 3950.0), (4000.0, 3950.0)]
WALL_TAG = "T1SW136c-200X2500"


@pytest.fixture(scope="module")
def normalized(tmp_path_factory):
    path = tmp_path_factory.mktemp("wall") / "wall.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-COLS", "S-COLS-IDEN", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-3000, -3000), (27000, -3000), (27000, 17000), (-3000, 17000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((8000, -2500))
    msp.add_lwpolyline(WALL, close=True, dxfattribs={"layer": "S-COLS"})
    msp.add_text(WALL_TAG, dxfattribs={"layer": "S-COLS-IDEN", "height": 200}).set_placement((4100, 2475))
    # an ordinary column, to prove only the wall is treated specially
    msp.add_lwpolyline([(10000, 1000), (10300, 1000), (10300, 1450), (10000, 1450)],
                       close=True, dxfattribs={"layer": "S-COLS"})
    msp.add_text("C1-300X450", dxfattribs={"layer": "S-COLS-IDEN", "height": 200}).set_placement((10150, 1225))
    doc.saveas(str(path))
    project = extract(path).project
    levels = [LevelRow("L01", "GROUND FLOOR LEVEL", 0, 0.0, None, "GROUND FLOOR LVL.")]
    return path, normalize(project, TemplateSpec(), levels, source_file="wall.dxf")


def _wall(np_):
    walls = [c for c in np_.columns if c.wall_like]
    assert len(walls) == 1, f"expected one shear wall, got {[c.mark for c in walls]}"
    return walls[0]


def test_split_mark_size():
    assert split_mark_size("T1SW136c-200X2500") == ("T1SW136c", "200X2500")
    assert split_mark_size("C12-300x450") == ("C12", "300x450")
    assert split_mark_size("T1SW18a") == ("T1SW18a", "")       # no size stated
    assert split_mark_size("") == ("", "")


def test_wall_mark_is_split_beside_the_wall(normalized):
    _path, np_ = normalized
    w = _wall(np_)
    assert w.mark_lines == ["T1SW136c", "200X2500"]
    assert "2950" not in "".join(w.mark_lines), "the mark states the size; the polyline does not get a vote"
    assert w.mark_rotation_deg == 0.0                           # upright, not rotated into the wall
    assert w.mark_position.x > max(p[0] for p in WALL)          # clear of the wall, to its right
    assert min(p[1] for p in WALL) <= w.mark_position.y <= max(p[1] for p in WALL)


def test_ordinary_column_keeps_its_mark_inside(normalized):
    _path, np_ = normalized
    col = [c for c in np_.columns if not c.wall_like]
    assert len(col) == 1 and col[0].mark_lines == [col[0].mark]
    minx, maxx = 10000.0, 10300.0
    assert minx <= col[0].mark_position.x <= maxx               # inside its own outline


def test_two_lines_read_back_as_one_mark(normalized, tmp_path):
    """Utility 4 must recover the whole mark from the two drawn lines."""
    _path, np_ = normalized
    spec = TemplateSpec()
    dxf = write_template_dxf(np_, tmp_path / "wall.template.dxf", spec)
    reread = TemplateReader(spec).read(dxf)
    w = _wall(reread)
    assert w.mark == WALL_TAG                                   # the whole mark, not one line of it
    assert w.mark_lines == ["T1SW136c", "200X2500"]             # and what the drawing shows
    assert (w.width_mm, w.depth_mm) == (200.0, 2500.0)          # sizes come from the mark it states
