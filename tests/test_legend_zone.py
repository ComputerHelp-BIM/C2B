"""The client's legend is drawn under the plan, inside the floor's own frame.

Its swatches are drawn exactly like the thing they explain -- a hatch, a rectangle, a cut-out
cross -- so unless the band each legend line occupies is ruled out first, the swatch for
"COLUMN/SHEAR WALL END" is read as a column and the one for "CUT-OUT" as an opening. Test17
produced three phantom stub columns and thirteen phantom openings that way.
"""
from __future__ import annotations

import ezdxf
import pytest

from c2b.extract.legend import legend_zones
from c2b.pipeline import extract

#: the plan sits above y=0; the legend goes in the band below it, as the client draws it
LEGEND_Y = -4000.0


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    path = tmp_path_factory.mktemp("legend") / "legend.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-COLUMN", "S-CUTOUT", "G-ANNO-TEXT"):
        doc.layers.add(name)
    # the frame takes in the legend band under the plan, exactly as the client's does
    msp.add_lwpolyline([(-3000, -6000), (20000, -6000), (20000, 12000), (-3000, 12000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((8000, -1500))

    # one real column on the plan
    msp.add_lwpolyline([(0, 0), (300, 0), (300, 450), (0, 450)], close=True, dxfattribs={"layer": "S-COLUMN"})
    msp.add_text("C1-300X450", dxfattribs={"layer": "S-COLUMN", "height": 100}).set_placement((150, 225))

    # the legend: a swatch on a structural layer, then the line explaining it
    msp.add_lwpolyline([(0, LEGEND_Y), (1400, LEGEND_Y), (1400, LEGEND_Y + 580), (0, LEGEND_Y + 580)],
                       close=True, dxfattribs={"layer": "S-COLUMN"})
    msp.add_text("%%U*THUS MARKED COLUMN/SHEAR WALL END",
                 dxfattribs={"layer": "G-ANNO-TEXT", "height": 280}).set_placement((2000, LEGEND_Y + 150))
    msp.add_lwpolyline([(0, LEGEND_Y - 1200), (1400, LEGEND_Y - 1200), (1400, LEGEND_Y - 620), (0, LEGEND_Y - 620)],
                       close=True, dxfattribs={"layer": "S-CUTOUT"})
    msp.add_text("%%UTHUS MARKED CUT-OUT",
                 dxfattribs={"layer": "G-ANNO-TEXT", "height": 280}).set_placement((2000, LEGEND_Y - 1050))
    doc.saveas(str(path))
    return extract(path).project


def test_legend_zones_cover_the_swatch_beside_each_line(tmp_path):
    """Built from the legend *text*: a cut-out swatch is a plain rectangle with no hatch to match.

    The zone has to reach left far enough to take in the swatch, which sits before the words.
    """
    from shapely.geometry import Point

    from c2b.dxfio import iter_prims, load_document, modelspace_extent, read_meta
    from c2b.units import resolve_units

    path = tmp_path / "one.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("G-ANNO-TEXT")
    msp.add_text("%%UTHUS MARKED CUT-OUT", dxfattribs={"layer": "G-ANNO-TEXT", "height": 280}).set_placement((2000, 0))
    doc.saveas(str(path))

    d = load_document(path)
    res = resolve_units(read_meta(d, str(path)).insunits, modelspace_extent(d))
    prims, _ = iter_prims(d, res.scale_to_mm)
    zones = legend_zones(prims)
    assert len(zones) == 1
    assert zones[0].contains(Point(700, 140)), "the swatch to the left of the words is not covered"
    assert not zones[0].contains(Point(700, 4000)), "the zone is a band, not the whole sheet"


def test_a_swatch_on_a_structural_layer_is_not_a_column(project):
    cols = project.columns
    assert len(cols) == 1, f"expected the one real column, got {[(c.width_mm, c.depth_mm) for c in cols]}"
    assert cols[0].mark == "C1"
    assert all(c.center.y > -2000 for c in cols), "a column was read out of the legend band"


def test_a_cut_out_swatch_is_not_an_opening(project):
    assert not [o for o in project.openings if o.center.y < -2000], "an opening was read out of the legend band"


def test_the_legend_band_is_reported(project):
    assert any(d.code == "LEGEND_ZONE" for d in project.diagnostics)


def test_a_box_round_a_slab_tag_is_not_a_slab_outline(tmp_path):
    """A drafter boxing a tag leaves a closed polyline that looks exactly like a small slab.

    Read as one it closes a little panel of its own inside the bay it labels, and the two overlap
    completely -- 50 such pairs on Test17. What gives the box away is how tightly it fits the
    words: a real slab holding its own tag is orders of magnitude larger than the text.
    """

    from c2b.dxfio import iter_prims, load_document, modelspace_extent, read_meta
    from c2b.geometry import wraps_a_text
    from c2b.units import resolve_units

    path = tmp_path / "tagbox.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "SLAB THK.", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-3000, -3000), (20000, -3000), (20000, 15000), (-3000, 15000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((8000, -2500))
    # the client's box: 845 x 496 round a two-line tag of height 162
    msp.add_lwpolyline([(0, 0), (845, 0), (845, 496), (0, 496)], close=True, dxfattribs={"layer": "SLAB THK."})
    msp.add_text("300THK.\nSLAB", dxfattribs={"layer": "SLAB THK.", "height": 162}).set_placement((60, 100))
    # a real slab holding the same tag, two orders of magnitude bigger
    msp.add_lwpolyline([(4000, 0), (10000, 0), (10000, 5000), (4000, 5000)], close=True, dxfattribs={"layer": "SLAB THK."})
    msp.add_text("300THK.\nSLAB", dxfattribs={"layer": "SLAB THK.", "height": 162}).set_placement((6800, 2400))
    doc.saveas(str(path))

    d = load_document(path)
    res = resolve_units(read_meta(d, str(path)).insunits, modelspace_extent(d))
    prims, _ = iter_prims(d, res.scale_to_mm)
    texts = [p for p in prims if p.text and p.layer == "SLAB THK."]
    boxes = [p for p in prims if p.kind == "polygon" and p.layer == "SLAB THK."]
    assert len(boxes) == 2 and texts

    small = min(boxes, key=lambda p: p.geom.area)
    big = max(boxes, key=lambda p: p.geom.area)
    assert wraps_a_text(small.geom, texts), "the box round the tag was not recognised"
    assert not wraps_a_text(big.geom, texts), "a real slab was mistaken for a text box"

    edges = extract(path).project.slab_edges
    from_box = [e for e in edges if max(abs(e.start.x), abs(e.end.x)) <= 900]
    assert not from_box, "the tag box was read as a slab outline"
    assert edges, "the real slab outline was lost too"
