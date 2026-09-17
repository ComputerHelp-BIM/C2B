"""Which outline on a floor is that floor's column, and what each leg of a wall is.

Answers 2, 3 and 4 on columns:

* the template models the column *below* a floor level, so of the outlines the client draws on
  one plan only some belong to that floor;
* an L, T, C or F shaped wall is marked and sized leg by leg, so each leg is its own element;
* an untagged stub column is ``SC{n}`` -- not ``ST``, which is the stair mark -- and any other
  untagged column takes its stack's mark
  from whichever floor the client did tag, falling back to the next free number.
"""
from __future__ import annotations

import ezdxf
import pytest
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import Polygon
from shapely.ops import unary_union

from c2b.geometry import split_rectilinear
from c2b.normalize.pipeline import LevelRow, normalize
from c2b.normalize.spec import TemplateSpec
from c2b.pipeline import extract

LAYERS = ("Boundary", "Origin", "S-COLUMN", "S-COLUMN_START", "S-COLUM_STOP", "S.STUB COL",
          "S-COLS-IDEN", "G-ANNO-TEXT")


def _floor(msp, ox: float, name: str, draw):
    msp.add_lwpolyline([(ox - 3000, -3000), (ox + 12000, -3000), (ox + 12000, 12000), (ox - 3000, 12000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((ox, 0), dxfattribs={"layer": "Origin"})
    msp.add_text(name, dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((ox + 4000, -2500))
    draw(ox)


def _rect(msp, layer, x0, y0, x1, y1):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer})


def _tag(msp, x, y, text):
    msp.add_text(text, dxfattribs={"layer": "S-COLS-IDEN", "height": 100}).set_placement(
        (x, y), align=TextEntityAlignment.MIDDLE_CENTER)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    path = tmp_path_factory.mktemp("life") / "life.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in LAYERS:
        doc.layers.add(name)

    def ground(ox):
        # a column that runs up from below and ends here: the client draws the stop outline and,
        # over it, the smaller outline of what continues above. Only the stop one is this floor's.
        _rect(msp, "S-COLUM_STOP", ox + 0, 0, ox + 400, 900)
        _rect(msp, "S-COLUMN", ox + 100, 100, ox + 300, 800)
        _tag(msp, ox + 200, 450, "C1-400X900")
        # a column starting here: nothing stands under this floor, so it is not drawn on it
        _rect(msp, "S-COLUMN_START", ox + 2000, 0, ox + 2200, 600)
        # an L-shaped wall, each leg marked and sized by the client
        msp.add_lwpolyline([(ox + 5000, 0), (ox + 7000, 0), (ox + 7000, 200), (ox + 5200, 200),
                            (ox + 5200, 1500), (ox + 5000, 1500)], close=True, dxfattribs={"layer": "S-COLUMN"})
        _tag(msp, ox + 6200, 400, "SW1-200X2000")
        _tag(msp, ox + 5600, 1200, "SW2-200X1300")
        # a stub column the client never tags
        _rect(msp, "S.STUB COL", ox + 9000, 0, ox + 9200, 450)

    def first(ox):
        _rect(msp, "S-COLUMN", ox + 100, 100, ox + 300, 800)
        _tag(msp, ox + 200, 450, "C1-200X700")
        _rect(msp, "S-COLUMN", ox + 2000, 0, ox + 2200, 600)      # the column that started below
        _rect(msp, "S.STUB COL", ox + 9000, 0, ox + 9200, 450)

    _floor(msp, 0, "GROUND FLOOR LEVEL", ground)
    _floor(msp, 20000, "FIRST FLOOR LEVEL", first)
    doc.saveas(str(path))
    return extract(path).project


def _on(project, fid):
    return [c for c in project.columns if c.floor_id == fid]


def test_split_rectilinear_cuts_shapes_into_legs_and_leaves_others_alone():
    assert len(split_rectilinear(Polygon([(0, 0), (200, 0), (200, 2000), (0, 2000)]))) == 1
    ell = Polygon([(0, 0), (2000, 0), (2000, 200), (200, 200), (200, 1500), (0, 1500)])
    legs = split_rectilinear(ell)
    assert len(legs) == 2
    # both legs run to the outside face, as the client dimensions them, so they share the corner
    assert sorted(sorted((l.bounds[2] - l.bounds[0], l.bounds[3] - l.bounds[1])) for l in legs) == \
        [[200.0, 1500.0], [200.0, 2000.0]]
    assert unary_union(legs).equals(ell), "the legs together are the whole wall"
    tee = Polygon([(0, 0), (2000, 0), (2000, 200), (1100, 200), (1100, 1500), (900, 1500), (900, 200), (0, 200)])
    assert len(split_rectilinear(tee)) == 2
    # not rectilinear: the cells would not cover it, so it is left whole
    assert len(split_rectilinear(Polygon([(0, 0), (2000, 0), (0, 2000)]))) == 1


def test_split_survives_a_polyline_that_is_not_quite_square():
    """A real client wall, drawn 0.0003 degrees off axis with sub-millimetre coordinates.

    Squared up, its two faces land a few microns apart. Cutting on both makes sliver cells that
    break a leg into pieces no one drew -- this wall came out as three legs, one of them a
    200 x 1620 ghost that no mark could ever match.
    """
    wall = Polygon([(3880.4332219879143, 1360.0119224321097), (6180.433101610048, 1360.0005401242524),
                    (6180.433342366014, 1560.0005401233211), (4080.433462742949, 1560.011681673117),
                    (4080.4377361538354, 3180.012805201113), (3880.4377361538354, 3180.013045954518)])
    legs = split_rectilinear(wall, min_side=100.0)
    sizes = sorted(sorted((round(l.bounds[2] - l.bounds[0]), round(l.bounds[3] - l.bounds[1]))) for l in legs)
    assert sizes == [[200, 1820], [200, 2300]], sizes


def test_a_stopping_column_wins_over_the_outline_of_what_continues_above(project):
    ground = _on(project, "L01")
    at_c1 = [c for c in ground if c.center.x < 1000]
    assert len(at_c1) == 1, "both outlines were kept as separate columns"
    assert (at_c1[0].width_mm, at_c1[0].depth_mm) == (400.0, 900.0), "the stop outline is this floor's column"
    assert at_c1[0].source_layer == "S-COLUM_STOP"


def test_a_column_starting_here_is_not_on_this_floor(project):
    assert not [c for c in _on(project, "L01") if 1500 < c.center.x < 3000]
    assert [c for c in _on(project, "L02") if 1500 < c.center.x < 3000], "it appears on the floor above"


def test_each_leg_of_a_shaped_wall_is_its_own_element_with_its_own_mark(project):
    legs = sorted((c for c in _on(project, "L01") if 4500 < c.center.x < 7500), key=lambda c: -max(c.width_mm, c.depth_mm))
    assert len(legs) == 2, f"expected two legs, got {[(c.width_mm, c.depth_mm) for c in legs]}"
    assert [c.mark for c in legs] == ["SW1", "SW2"]
    # width/depth follow the plan orientation; the mark keeps the client's b x D order
    assert sorted((legs[0].width_mm, legs[0].depth_mm)) == [200.0, 2000.0]
    assert sorted((legs[1].width_mm, legs[1].depth_mm)) == [200.0, 1300.0]
    assert all(c.size_source == "tag" for c in legs), "each leg took its own tag"


def test_an_untagged_stub_column_is_numbered_in_its_own_series(project):
    """SC, not ST: ``marks.stair`` is already ``ST{n}-{thk}THK``."""
    spec = TemplateSpec()
    levels = [LevelRow("L01", "GROUND FLOOR LEVEL", 0, 0.0, None, "GROUND FLOOR LVL."),
              LevelRow("L02", "FIRST FLOOR LEVEL", 1, 3000.0, None, "FIRST FLOOR LVL.")]
    np_ = normalize(project, spec, levels, source_file="life.dxf")
    stubs = [c for c in np_.columns if c.center.x > 8000]
    assert stubs, "the stub columns were dropped"
    assert all(c.mark.startswith("SC") for c in stubs), [c.mark for c in stubs]
    assert not any(c.mark.startswith("ST") for c in stubs), "ST would collide with the stair mark"
    assert all(c.mark.endswith("200X450") for c in stubs), "sized from its own outline"


def test_an_untagged_column_takes_its_stacks_mark_from_the_floor_that_has_one(project):
    """The column that started on the ground floor is untagged on the first floor."""
    spec = TemplateSpec()
    levels = [LevelRow("L01", "GROUND FLOOR LEVEL", 0, 0.0, None, "GROUND FLOOR LVL."),
              LevelRow("L02", "FIRST FLOOR LEVEL", 1, 3000.0, None, "FIRST FLOOR LVL.")]
    np_ = normalize(project, spec, levels, source_file="life.dxf")
    upper = [c for c in np_.columns if c.floor_id == "L02" and c.center.x < 1000]
    assert len(upper) == 1 and upper[0].mark.startswith("C1-"), upper[0].mark if upper else "missing"
