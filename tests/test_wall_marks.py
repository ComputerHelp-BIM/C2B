"""How a column carries its mark, end to end.

Answer 7: the mark sits on the bounding-box centre of its own member, text along the longer
side, and it shrinks rather than overflow -- a smaller mark that reads is worth more than a
full-height one lying across the beams alongside. The rules that keep that honest:

* the mark never leaves its member, at any length of mark or size of member;
* a mark broken onto two lines (the optional ``wall_mark: beside``) still reads back as the one
  mark, so utility 4 loses nothing;
* the size shown is the size the *mark* states, never the size measured off the polyline, so a
  client tag that disagrees with their own geometry is reported once rather than drawn as a
  third number.
"""
from __future__ import annotations

import ezdxf
import pytest
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import Point, Polygon

from c2b.export.template_dxf import write_template_dxf
from c2b.normalize.geometry import box_centre, fit_text_height
from c2b.normalize.naming import split_mark_size
from c2b.normalize.pipeline import LevelRow, normalize
from c2b.normalize.spec import TemplateSpec
from c2b.pipeline import extract
from c2b.roundtrip.reader import TemplateReader

#: a tall wall: 200 wide, 2950 deep, tagged 200X2500 -- the client's own numbers disagree
TALL = [(4000.0, 1000.0), (4200.0, 1000.0), (4200.0, 3950.0), (4000.0, 3950.0)]
TALL_TAG = "T1SW136c-200X2500"
#: a short member: the full mark cannot be drawn at the top of the ladder inside 450 mm
SHORT = [(8000.0, 1000.0), (8200.0, 1000.0), (8200.0, 1450.0), (8000.0, 1450.0)]
SHORT_TAG = "T1SW44a-200X450"


def _build(tmp_path, spec: TemplateSpec):
    path = tmp_path / "wall.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-COLS", "S-COLS-IDEN", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-3000, -3000), (27000, -3000), (27000, 17000), (-3000, 17000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((8000, -2500))
    for ring, tag in ((TALL, TALL_TAG), (SHORT, SHORT_TAG)):
        msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "S-COLS"})
        cx = sum(p[0] for p in ring) / 4
        cy = sum(p[1] for p in ring) / 4
        msp.add_text(tag, dxfattribs={"layer": "S-COLS-IDEN", "height": 200}).set_placement((cx, cy))
    # an ordinary column, to prove only the marks that need to are treated differently
    msp.add_lwpolyline([(14000, 1000), (14300, 1000), (14300, 1450), (14000, 1450)],
                       close=True, dxfattribs={"layer": "S-COLS"})
    msp.add_text("C1-300X450", dxfattribs={"layer": "S-COLS-IDEN", "height": 200}).set_placement((14150, 1225))
    doc.saveas(str(path))
    levels = [LevelRow("L01", "GROUND FLOOR LEVEL", 0, 0.0, None, "GROUND FLOOR LVL.")]
    return path, normalize(extract(path).project, spec, levels, source_file="wall.dxf")


@pytest.fixture(scope="module")
def normalized(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("inside"), TemplateSpec())


@pytest.fixture(scope="module")
def beside(tmp_path_factory):
    spec = TemplateSpec()
    spec.placement.wall_mark = "beside"
    return _build(tmp_path_factory.mktemp("beside"), spec)


def _by_mark(np_, needle: str):
    hits = [c for c in np_.columns if needle in c.mark]
    assert len(hits) == 1, f"expected one {needle}, got {[c.mark for c in np_.columns]}"
    return hits[0]


def test_split_mark_size():
    assert split_mark_size("T1SW136c-200X2500") == ("T1SW136c", "200X2500")
    assert split_mark_size("C12-300x450") == ("C12", "300x450")
    assert split_mark_size("T1SW18a") == ("T1SW18a", "")       # no size stated
    assert split_mark_size("") == ("", "")


def test_box_centre_stays_inside_an_L_shape():
    """A rectangle takes its box centre; an L shape's box centre is out in the notch."""
    rect = Polygon([(0, 0), (200, 0), (200, 1000), (0, 1000)])
    assert box_centre(rect) == (100.0, 500.0)
    ell = Polygon([(0, 0), (1000, 0), (1000, 200), (200, 200), (200, 1000), (0, 1000)])
    assert ell.contains(Point(box_centre(ell)))


def test_fit_text_height_steps_down_a_standard_ladder():
    """Heights come from the drawing's ladder, never a freely computed size."""
    ladder = [50.0, 40.0, 30.0, 20.0, 10.0]
    poly = Polygon([(0, 0), (800, 0), (800, 300), (0, 300)])
    assert fit_text_height("SHORT", ladder, 0.6, poly) == 50.0                # already fits
    h = fit_text_height("T1SW136c-200X2500-AND-THEN-SOME-MORE-STILL", ladder, 0.6, poly)
    assert h in ladder and h < 50.0
    assert fit_text_height("X" * 400, ladder, 0.6, poly) == 10.0              # gives up at the smallest


def test_mark_sits_on_the_box_centre_inside_the_wall(normalized):
    _path, np_ = normalized
    w = _by_mark(np_, "T1SW136c")
    assert w.wall_like and w.mark_lines == [w.mark]                    # one line, not split
    assert (w.mark_position.x, w.mark_position.y) == box_centre(Polygon([(p.x, p.y) for p in w.outline]))
    assert min(p[0] for p in TALL) <= w.mark_position.x <= max(p[0] for p in TALL)
    assert "2950" not in w.mark, "the mark states the tagged size; the polyline does not get a vote"


def test_a_short_member_steps_its_mark_down_instead_of_overflowing(normalized):
    _path, np_ = normalized
    ladder = TemplateSpec().text.mark_heights
    short, tall = _by_mark(np_, "T1SW44a"), _by_mark(np_, "T1SW136c")
    assert short.mark_height_mm in ladder and tall.mark_height_mm in ladder
    assert short.mark_height_mm < max(ladder), "the full mark does not fit 450 mm at the top of the ladder"
    assert tall.mark_height_mm == max(ladder), "a wall with room keeps full-height text"
    poly = Polygon([(p.x, p.y) for p in short.outline])
    assert poly.contains(Point(short.mark_position.x, short.mark_position.y))


def test_ordinary_column_keeps_its_mark_inside(normalized):
    _path, np_ = normalized
    col = _by_mark(np_, "C1-300X450")
    assert not col.wall_like and col.mark_lines == [col.mark]
    assert 14000.0 <= col.mark_position.x <= 14300.0


def test_beside_mode_splits_the_mark_and_still_reads_back(beside, tmp_path):
    """``wall_mark: beside`` is still available, and utility 4 recovers the whole mark."""
    _path, np_ = beside
    spec = TemplateSpec()
    spec.placement.wall_mark = "beside"
    w = _by_mark(np_, "T1SW136c")
    assert w.mark_lines == ["T1SW136c", "200X2500"]
    assert w.mark_rotation_deg == 0.0
    assert w.mark_position.x > max(p[0] for p in TALL)

    dxf = write_template_dxf(np_, tmp_path / "wall.template.dxf", spec)
    reread = TemplateReader(spec).read(dxf)
    r = _by_mark(reread, "T1SW136c")
    assert r.mark == TALL_TAG                                   # the whole mark, not one line of it
    assert r.mark_lines == ["T1SW136c", "200X2500"]             # and what the drawing shows
    assert (r.width_mm, r.depth_mm) == (200.0, 2500.0)          # sizes come from the mark it states


def test_a_member_too_small_for_the_whole_mark_shows_the_base(tmp_path):
    """A mark that misses even the smallest standard height shows its base instead.

    The base alone does. The size is not lost: it stays in the schedule and in the XDATA, so
    utility 4 reads the whole mark back off the drawing.
    """
    path = tmp_path / "tiny.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-COLS", "S-COLS-IDEN", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-3000, -3000), (9000, -3000), (9000, 9000), (-3000, 9000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((3000, -2500))
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={"layer": "S-COLS"})
    msp.add_text("T1SW136c-200X100", dxfattribs={"layer": "S-COLS-IDEN", "height": 50}).set_placement(
        (50, 50), align=TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(str(path))

    spec = TemplateSpec()
    levels = [LevelRow("L01", "GROUND FLOOR LEVEL", 0, 0.0, None, "GROUND FLOOR LVL.")]
    np_ = normalize(extract(path).project, spec, levels, source_file="tiny.dxf")
    col = np_.columns[0]
    assert col.mark == "T1SW136c-200X100", "the data keeps the whole mark"
    assert col.mark_lines == ["T1SW136c"], "the drawing shows only what fits"
    assert col.mark_height_mm in spec.text.mark_heights

    dxf = write_template_dxf(np_, tmp_path / "tiny.template.dxf", spec)
    reread = TemplateReader(spec).read(dxf)
    assert reread.columns[0].mark == "T1SW136c-200X100", "utility 4 recovers the whole mark"
