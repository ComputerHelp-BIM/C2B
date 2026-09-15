"""Utility 3 on the synthetic drawing: stacks, spans, panels, marks, template DXF."""
from pathlib import Path

import ezdxf
import pytest

from c2b.export.template_dxf import write_template_dxf
from c2b.normalize.geometry import complement, lattice_panels, merge_intervals
from c2b.normalize.naming import normalise_floor_name, title_from_level_name
from c2b.normalize.pipeline import LevelRow, normalize
from c2b.normalize.spec import TemplateSpec


@pytest.fixture(scope="module")
def normalized(synthetic_result):
    levels = [LevelRow("L01", "FOUNDATION LEVEL", 0, -1500.0, None, "FOUNDATION LVL."), LevelRow("L02", "GROUND FLOOR LEVEL", 1, 0.0, None, "GROUND FLOOR LVL.")]
    return normalize(synthetic_result.project, TemplateSpec(), levels, source_file="synthetic.dxf")


def test_intervals():
    assert merge_intervals([(0, 10), (5, 20), (30, 40)]) == [(0, 20), (30, 40)]
    assert complement([(10, 20), (50, 60)], 100) == [(0, 10), (20, 50), (60, 100)]
    assert complement([], 100) == [(0, 100)]


def test_lattice_panels():
    from shapely.geometry import Polygon
    beams = [Polygon([(0, 0), (6000, 0), (6000, 230), (0, 230)]), Polygon([(0, 5000), (6000, 5000), (6000, 5230), (0, 5230)]),
             Polygon([(0, 0), (230, 0), (230, 5230), (0, 5230)]), Polygon([(5770, 0), (6000, 0), (6000, 5230), (5770, 5230)])]
    panels, oversized = lattice_panels(beams, 1e5, 1e9)
    assert len(panels) == 1 and abs(panels[0].area - (6000 - 460) * (5000 - 230)) < 1
    assert not oversized


def test_names():
    assert normalise_floor_name("LAYOUT AT 1ST FLOOR LVL. (T1)") == "1ST FLOOR LVL."
    assert normalise_floor_name("Ground Floor Level") == "GROUND FLOOR LVL."
    assert normalise_floor_name("(TOWER 1)- 3RD  FLOOR ROOF SLAB") == "3RD FLOOR ROOF SLAB"
    assert title_from_level_name("GROUND FLOOR LVL.") == "GROUND FLOOR LEVEL"


def test_levels_and_floors(normalized):
    assert [l.name for l in normalized.levels] == ["00 FOUNDATION LVL.", "01 GROUND FLOOR LVL."]
    assert normalized.levels[0].floor_to_floor_mm == 1500.0
    f = {f.id: f for f in normalized.floors}
    assert f["L02"].title == "LAYOUT PLAN - GROUND FLOOR LEVEL" and f["L02"].elevation_mm == 0.0
    assert min(p.y for p in f["L02"].frame) == f["L02"].plan_bottom_y - TemplateSpec().frame.bottom_band_mm


def test_stacks_and_column_marks(normalized):
    assert len(normalized.stacks) == 12
    # every stack exists on both floors; row-major numbering starts at grid 1/A, the client's "C1" at 1/C keeps its mark
    assert all(s.floors == ["L01", "L02"] for s in normalized.stacks)
    first = normalized.stacks[0]
    assert first.grid_ref == "1/A" and first.mark_base == "C2"        # C1 is taken by the client mark
    client = next(s for s in normalized.stacks if s.client_marks == ["C1"])
    assert client.grid_ref == "1/C" and client.mark_base == "C1"
    assert normalized.stacks[1].grid_ref == "2/A"                        # along the row, then the next row
    cols = [c for c in normalized.columns if c.floor_id == "L02"]
    assert len(cols) == 12
    marks = {c.mark for c in cols}
    assert "C1-300X450" in marks and "C2-300X450" in marks and any(m.endswith("600DIA") for m in marks)
    c2 = next(c for c in cols if c.mark == "C2-300X450")
    assert abs(c2.mark_position.y - c2.center.y) < 1 and abs(c2.mark_position.x - c2.center.x) < 1   # inside, at the centre
    assert c2.mark_rotation_deg == 90.0                                  # text along the 450 side
    assert not any(c.stops_here for c in cols) and not any(c.starts_here for c in cols)


def test_spans(normalized):
    spans = [b for b in normalized.beams if b.floor_id == "L02"]
    # 3 horizontal runs x 3 bays + 4 vertical runs x 2 bays + 1 untagged beam between grids 2 and 4 (2 pieces cut by the vertical beams? no: it ends at them)
    assert len(spans) >= 17
    assert all(s.length_mm < 6000 for s in spans)          # nothing spans across a column
    assert all(s.width_mm == 230 for s in spans)
    supported = [s for s in spans if s.support_start and s.support_end]
    assert len(supported) >= 15
    assert any(s.mark.startswith("B1-230X") for s in spans)
    assert any(s.mark.startswith("MB-230X600") for s in spans)          # client mark kept
    assert all(s.depth_mm in (450, 600) for s in spans)
    vertical = [s for s in spans if abs(s.angle_deg - 90) < 1]
    assert all(s.mark_rotation_deg == 90.0 for s in vertical)


def test_panels(normalized):
    panels = [p for p in normalized.panels if p.floor_id == "L02" and p.kind in ("slab", "ramp")]
    # 3 x 2 bays, one split by the extra beam at y=2500 -> 7 panels (one of them the ramp bay; the opening sits inside another bay)
    assert len(panels) == 7, [p.area_m2 for p in panels]
    tagged = [p for p in panels if p.thickness_mm == 150]
    assert len(tagged) >= 4
    assert all(p.mark.startswith(("S", "RP")) for p in panels)
    with_opening = [p for p in panels if p.opening_ids]
    assert with_opening and with_opening[0].holes, "interior cut-out must become a hole of the panel"
    # legend region: the bay hatched with the sunk pattern is sunk by 75
    sunk = [p for p in panels if p.sunk_mm == 75]
    assert len(sunk) == 1 and sunk[0].sunk_source == "legend"


def test_cantilever_panel(normalized):
    cs = [p for p in normalized.panels if p.floor_id == "L02" and p.kind == "cantilever"]
    assert len(cs) == 1, [(p.kind, p.area_m2) for p in normalized.panels if p.floor_id == "L02"]
    chajja = cs[0]
    assert chajja.mark == "CS1-100THK" and chajja.thickness_mm == 100
    assert abs(chajja.area_m2 - 6.0 * 0.9) < 0.3
    # bottom aligned with the supporting beam; the 450 horizontal beam and the 600 verticals touch it, the smaller depth governs
    assert chajja.support_depth_mm == 450
    assert chajja.top_offset_mm == -350 and chajja.top_offset_rule == "cantilever_bottom_align"


def test_ramp_pcc_and_settings(normalized):
    ramps = [p for p in normalized.panels if p.floor_id == "L02" and p.kind == "ramp"]
    assert len(ramps) == 1 and ramps[0].slope_ratio == "1:8" and ramps[0].direction == "UP" and ramps[0].mark.startswith("RP1-") and ramps[0].mark.endswith("1:8")
    assert len(ramps[0].arrow) == 2
    ftg = [x for x in normalized.footings if x.floor_id == "L01"]
    assert all(x.pcc_thickness_mm == 100 and x.pcc_projection_mm == 100 and x.pcc_outline for x in ftg)
    assert all(x.kind == "footing" for x in ftg)                # CF only when the client says so
    assert any("PCC 100THK" in x.mark_lines for x in ftg)
    assert normalized.level_reference == "SSL"


def test_inverted_beam(normalized):
    inv = [b for b in normalized.beams if b.floor_id == "L02" and b.inverted]
    assert inv and all(b.mark.endswith("-INV") for b in inv)
    assert all(b.top_offset_mm > 0 for b in inv)


def test_footings_and_grids(normalized):
    ftg = [x for x in normalized.footings if x.floor_id == "L01"]
    assert len(ftg) == 12 and all(x.kind == "footing" and x.thickness_mm == 500 for x in ftg)
    assert all(len(x.stack_ids) == 1 for x in ftg)
    assert ftg[0].mark == "F1-500THK" and ftg[0].mark_lines[0] == "F1-500THK"
    grids = [g for g in normalized.grids if g.floor_id == "L02"]
    assert len(grids) == 7 and all(g.bubble_centres for g in grids)


def test_template_dxf(normalized, tmp_path):
    spec = TemplateSpec()
    out = write_template_dxf(normalized, tmp_path / "t.dxf", spec)
    doc = ezdxf.readfile(str(out))
    msp = doc.modelspace()
    layers = {e.dxf.layer for e in msp}
    for key in ("column", "column_mark", "beam", "beam_mark", "slab", "slab_mark", "footing", "grid", "grid_mark", "level", "boundary", "origin", "text", "pcc", "ramp"):
        assert spec.layer(key) in layers, key
    cols = list(msp.query(f'LWPOLYLINE[layer=="{spec.layer("column")}"]')) + list(msp.query(f'CIRCLE[layer=="{spec.layer("column")}"]'))
    assert len(cols) == normalized.summary.columns
    assert all(e.closed for e in msp.query(f'LWPOLYLINE[layer=="{spec.layer("beam")}"]'))
    # XDATA round trip
    c = list(msp.query(f'LWPOLYLINE[layer=="{spec.layer("column")}"]'))[0]
    xd = {t[1].split("=", 1)[0]: t[1].split("=", 1)[1] for t in c.get_xdata(spec.xdata_appid)}
    assert xd["id"].startswith("L0") and xd["mark"].startswith("C")
    assert len(list(msp.query(f'LINE[layer=="{spec.layer("level")}"]'))) == 2
    assert len(list(msp.query("DIMENSION"))) == 1
    assert len(list(msp.query(f'LINE[layer=="{spec.layer("beam_cl")}"]'))) == normalized.summary.beams
    # the circular column leaves true arcs in the adjacent panels
    arcs = [e for e in msp.query(f'LWPOLYLINE[layer=="{spec.layer("slab")}"]') if any(abs(p[4]) > 1e-9 for p in e.get_points())]
    assert arcs, "expected bulges on panels next to the round column"
    assert spec.text.style in doc.styles
