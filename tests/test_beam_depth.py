"""Where a beam's depth comes from when the schedule does not give a number.

Two of this client's schedule rows state a rule instead: ``300XSLB THK.`` (a concealed beam, as
deep as the slab it sits in) and ``200XAS/LAYOUT`` (the plan says). The plan says it in the text
override on a dimension -- ``{\\H0.666667x;200x400}`` across the beam -- which is also how a
stepped beam gets its two depths.
"""
from __future__ import annotations

import ezdxf
import pytest
from ezdxf.enums import TextEntityAlignment

from c2b.normalize.pipeline import LevelRow, normalize
from c2b.normalize.spec import TemplateSpec
from c2b.pipeline import extract
from c2b.tags import strip_mtext_codes


def _bay(msp, x0, y0, x1, y1, width=200.0):
    """Four beams round a bay, each drawn as its two edge lines."""
    h = width / 2
    for a, b in (((x0, y0), (x1, y0)), ((x0, y1), (x1, y1))):
        for dy in (-h, h):
            msp.add_line((a[0], a[1] + dy), (b[0], b[1] + dy), dxfattribs={"layer": "S-BEAM"})
    for a, b in (((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))):
        for dx in (-h, h):
            msp.add_line((a[0] + dx, a[1]), (b[0] + dx, b[1]), dxfattribs={"layer": "S-BEAM"})


def _base(msp):
    msp.add_lwpolyline([(-4000, -4000), (16000, -4000), (16000, 14000), (-4000, 14000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((6000, -3000))


def _levels():
    return [LevelRow("L01", "GROUND FLOOR LEVEL", 0, 0.0, None, "GROUND FLOOR LVL.")]


def test_strip_mtext_codes():
    assert strip_mtext_codes("{\\H0.666667x;200x400}") == "200x400"
    assert strip_mtext_codes("(200x650)") == "200x650"
    assert strip_mtext_codes("175mm\\XEXPANSION JOINT") == "175mm EXPANSION JOINT"
    assert strip_mtext_codes("") == ""


def test_a_dimension_override_gives_a_beam_its_size(tmp_path):
    """The override is the client stating the section; the measurement itself is not a size."""
    path = tmp_path / "dim.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-BEAM", "S-BEAM NO.", "DIM", "G-ANNO-TEXT"):
        doc.layers.add(name)
    _base(msp)
    _bay(msp, 0, 0, 8000, 6000)
    # the client writes the override over the beam it describes
    dim = msp.add_linear_dim(base=(4000, 0), p1=(3000, 0), p2=(5000, 0),
                             text="{\\H0.666667x;200x400}", dxfattribs={"layer": "DIM"})
    dim.render()
    doc.saveas(str(path))

    beams = extract(path).project.beams
    sized = [b for b in beams if b.depth_mm == 400.0]
    assert sized, f"no beam took the override's depth: {[(b.width_mm, b.depth_mm, b.depth_source) for b in beams]}"
    assert all(b.width_mm == 200.0 for b in sized)
    assert sized[0].depth_source == "tag"


def test_a_hidden_beam_is_as_deep_as_the_slab_and_flush_with_it(tmp_path):
    """``300XSLB THK.``: the depth is a rule, settled once the slabs around the beam are known."""
    path = tmp_path / "slb.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-BEAM", "S-BEAM NO.", "SLAB THK.", "G-ANNO-SCHD", "G-ANNO-TEXT"):
        doc.layers.add(name)
    _base(msp)
    _bay(msp, 0, 0, 8000, 6000, width=300.0)
    msp.add_text("SB", dxfattribs={"layer": "S-BEAM NO.", "height": 150}).set_placement(
        (4000, 0), align=TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text("S1-175THK", dxfattribs={"layer": "SLAB THK.", "height": 150}).set_placement(
        (4000, 3000), align=TextEntityAlignment.MIDDLE_CENTER)
    # the schedule row that states the rule rather than a number
    msp.add_text("BEAM SIZE", dxfattribs={"layer": "G-ANNO-SCHD", "height": 150}).set_placement((0, 12000))
    msp.add_text("BEAM NO.", dxfattribs={"layer": "G-ANNO-SCHD", "height": 150}).set_placement((3000, 12000))
    msp.add_text("300XSLB THK.", dxfattribs={"layer": "G-ANNO-SCHD", "height": 150}).set_placement((0, 11500))
    msp.add_text("SB", dxfattribs={"layer": "G-ANNO-SCHD", "height": 150}).set_placement((3000, 11500))
    doc.saveas(str(path))

    project = extract(path).project
    sb = [b for b in project.beams if b.mark == "SB"]
    assert sb, "the SB beam was not found"
    assert all(b.depth_mm is None and b.depth_rule == "slab_thickness" for b in sb), \
        "extraction should carry the rule, not guess a depth"

    np_ = normalize(project, TemplateSpec(), _levels(), source_file="slb.dxf")
    spans = [b for b in np_.beams if b.mark.startswith("SB")]
    assert spans, "the SB span disappeared"
    assert all(b.depth_mm == 175.0 for b in spans), [(b.mark, b.depth_mm) for b in spans]
    assert all(b.depth_source == "slab" for b in spans)
    assert all(b.top_offset_mm == 0.0 for b in spans), "a concealed beam is flush with the slab"
    assert not any("X?" in b.mark for b in spans), "the mark still says the depth is unknown"
