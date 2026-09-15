"""Utility 4: the template DXF read back must reproduce the model, and drafter edits must show up."""
from pathlib import Path

import ezdxf
import pytest

from c2b.export.template_dxf import write_template_dxf
from c2b.normalize.pipeline import LevelRow, normalize
from c2b.normalize.spec import TemplateSpec
from c2b.roundtrip.diff import compare
from c2b.roundtrip.marks import parse_template_mark
from c2b.roundtrip.reader import read_template

SPEC = TemplateSpec()


@pytest.fixture(scope="module")
def model(synthetic_result):
    levels = [LevelRow("L01", "FOUNDATION LEVEL", 0, -1500.0, None, "FOUNDATION LVL."), LevelRow("L02", "GROUND FLOOR LEVEL", 1, 0.0, None, "GROUND FLOOR LVL.")]
    return normalize(synthetic_result.project, SPEC, levels, source_file="synthetic.dxf")


@pytest.fixture(scope="module")
def template(model, tmp_path_factory) -> Path:
    return write_template_dxf(model, tmp_path_factory.mktemp("rt") / "synthetic.template.dxf", SPEC)


@pytest.mark.parametrize("text,expect", [
    ("C12-300X900", {"base": "C12", "width_mm": 300, "depth_mm": 900}),
    ("C5-600DIA", {"base": "C5", "diameter_mm": 600}),
    ("B13-300X750-INV", {"base": "B13", "width_mm": 300, "depth_mm": 750, "inverted": True}),
    ("B5-200X900/600", {"base": "B5", "width_mm": 200, "depth_mm": 900, "depth_tip_mm": 600}),
    ("S16-200THK", {"base": "S16", "thickness_mm": 200}),
    ("CS1-100THK", {"base": "CS1", "thickness_mm": 100}),
    ("RP1-150THK 1:8", {"base": "RP1", "thickness_mm": 150, "slope_ratio": "1:8"}),
    ("1500 FOLD", {"fold_mm": 1500}),
    ("PCC 100THK", {"pcc_thickness_mm": 100}),
    ("4 PILES 500DIA", {"pile_count": 4, "pile_diameter_mm": 500}),
])
def test_parse_template_mark(text, expect):
    tm = parse_template_mark(text)
    for key, value in expect.items():
        assert getattr(tm, key) == value, (text, key, getattr(tm, key))


def test_reread_reproduces_the_model(model, template):
    drawing = read_template(template, SPEC)
    assert [f.id for f in drawing.floors] == [f.id for f in model.floors]
    assert drawing.summary.columns == model.summary.columns
    assert drawing.summary.beams == model.summary.beams
    assert drawing.summary.grids == model.summary.grids
    assert [l.name for l in drawing.levels] == [l.name for l in model.levels]
    assert [round(l.elevation_mm) for l in drawing.levels] == [round(l.elevation_mm) for l in model.levels]
    # geometry comes back in floor-local coordinates
    c_model = {c.id: c for c in model.columns}
    for c in drawing.columns:
        ref = c_model[c.id]
        assert abs(c.center.x - ref.center.x) < 1 and abs(c.center.y - ref.center.y) < 1
        assert c.mark == ref.mark


def test_round_trip_passes(model, template):
    res = compare(model, read_template(template, SPEC))
    assert res.ok(), [f"{d.code}: {d.message}" for d in res.findings][:10]


def _edit(template: Path, tmp_path: Path, fn) -> Path:
    doc = ezdxf.readfile(str(template))
    fn(doc, doc.modelspace())
    out = tmp_path / "edited.dxf"
    doc.saveas(str(out))
    return out


def _codes(model, path) -> set[str]:
    return {d.code for d in compare(model, read_template(path, SPEC)).findings}


def test_detects_moved_column(model, template, tmp_path):
    def move(doc, msp):
        e = list(msp.query(f'LWPOLYLINE[layer=="{SPEC.layer("column")}"]'))[0]
        e.translate(500, 0, 0)
    assert "RT_MOVED" in _codes(model, _edit(template, tmp_path, move))


def test_detects_deleted_beam(model, template, tmp_path):
    def delete(doc, msp):
        msp.delete_entity(list(msp.query(f'LWPOLYLINE[layer=="{SPEC.layer("beam")}"]'))[0])
    codes = _codes(model, _edit(template, tmp_path, delete))
    assert "RT_MISSING" in codes and "RT_COUNT" in codes


def test_detects_retyped_mark(model, template, tmp_path):
    def retype(doc, msp):
        t = list(msp.query(f'MTEXT[layer=="{SPEC.layer("beam_mark")}"]'))[0]
        t.text = "B99-230X1200"
    codes = _codes(model, _edit(template, tmp_path, retype))
    assert "RT_MARK_CHANGED" in codes


def test_detects_hand_added_column(model, template, tmp_path):
    def add(doc, msp):
        msp.add_lwpolyline([(1000, 1000), (1300, 1000), (1300, 1450), (1000, 1450)], close=True, dxfattribs={"layer": SPEC.layer("column")})
    path = _edit(template, tmp_path, add)
    drawing = read_template(path, SPEC)
    assert "RT_NO_ID" in {d.code for d in drawing.diagnostics}
    assert "RT_ADDED" in {d.code for d in compare(model, drawing).findings}


def test_detects_resized_column(model, template, tmp_path):
    def resize(doc, msp):
        e = list(msp.query(f'LWPOLYLINE[layer=="{SPEC.layer("column")}"]'))[0]
        pts = [(x, y * 1.0) for x, y in e.get_points("xy")]
        minx = min(p[0] for p in pts)
        e.set_points([(minx + (p[0] - minx) * 1.5, p[1]) for p in pts], format="xy")
    codes = _codes(model, _edit(template, tmp_path, resize))
    assert "RT_RESIZED" in codes and "RT_MARK_MISMATCH" in codes


def test_doctor_selftest_pipeline(tmp_path):
    """What `c2b doctor --selftest` runs: demo drawing straight through to a clean round trip."""
    from c2b.demo import build_demo_drawing
    from c2b.pipeline import extract

    dxf = build_demo_drawing(tmp_path / "demo.dxf")
    result = extract(dxf)
    assert result.project.summary.errors == 0 and result.project.summary.columns == 24
    np_ = normalize(result.project, SPEC, None, source_file=dxf.name)
    tpl = write_template_dxf(np_, tmp_path / "demo.template.dxf", SPEC)
    assert compare(np_, read_template(tpl, SPEC)).ok()
