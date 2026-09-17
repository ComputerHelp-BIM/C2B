"""What gets hatched, and what is left clear.

Three faults seen on Test17's plans, all in the drawing rather than the data:

* the north chajjas came out as bare outlines -- a chajja sits at beam bottom level by its own
  rule, and the client hatches it like any other slab at that level, but only the two rules
  named ``beam_bottom`` and ``projection`` were being hatched;
* the hatch ran straight across the cut-outs, burying the drafter's own cut-out symbol;
* a sunk area far smaller than the panel it sits in was dropped entirely, because sinking the
  whole bay for it would have been wrong and there was nothing else to do with it.
"""
from __future__ import annotations

import ezdxf
import pytest

from c2b.export.template_dxf import TemplateWriter, write_template_dxf
from c2b.normalize.model import NFloor, NormalizedProject, NPanel
from c2b.normalize.spec import TemplateSpec
from c2b.schema import Point2


def _pts(ring):
    return [Point2(x=x, y=y) for x, y in ring]


def _project(panel: NPanel) -> NormalizedProject:
    np_ = NormalizedProject(source_file="t.dxf", source_schema_version="0.6.0", spec_name="CH")
    np_.floors.append(NFloor(id="L01", index=0, name="GROUND FLOOR LVL.", title="PLAN", source_name="GROUND",
                             origin=Point2(x=0.0, y=0.0),
                             frame=_pts([(-1000, -1000), (9000, -1000), (9000, 9000), (-1000, 9000)]),
                             plan_bottom_y=0.0))
    np_.panels.append(panel)
    return np_


def _panel(**kw) -> NPanel:
    ring = kw.pop("outline", [(0, 0), (4000, 0), (4000, 3000), (0, 3000)])
    return NPanel(id="L01-S001", floor_id="L01", mark="S1-125THK", thickness_mm=125.0,
                  outline=_pts(ring), area_m2=12.0, centroid=Point2(x=2000.0, y=1500.0),
                  mark_position=Point2(x=2000.0, y=1500.0), **kw)


def _hatches(path, layer: str | None = None, element: str | None = "L01-S001"):
    """Hatches belonging to an element; the writer also draws swatches for its own legend."""
    doc = ezdxf.readfile(str(path))
    out = []
    for h in doc.modelspace().query("HATCH"):
        if layer is not None and h.dxf.layer != layer:
            continue
        if element is not None:
            try:
                tags = {t[1].split("=", 1)[0]: t[1].split("=", 1)[1] for t in h.get_xdata("C2B")}
            except Exception:
                continue
            if tags.get("id") != element:
                continue
        out.append(h)
    return out


def test_a_chajja_is_hatched_like_any_other_slab_at_beam_bottom(tmp_path):
    spec = TemplateSpec()
    np_ = _project(_panel(kind="cantilever", cantilever=True, top_offset_rule="cantilever_bottom_align"))
    out = write_template_dxf(np_, tmp_path / "chajja.dxf", spec)
    hs = _hatches(out, spec.layer(spec.beam_bottom_hatch_layer))
    assert len(hs) == 1, "the chajja came out as a bare outline"
    assert hs[0].dxf.pattern_name == spec.hatch.slab_at_beam_bottom


def test_a_plain_slab_is_not_hatched(tmp_path):
    out = write_template_dxf(_project(_panel()), tmp_path / "plain.dxf", TemplateSpec())
    assert not _hatches(out), "a slab at its own level needs no hatch"


def test_the_hatch_leaves_a_cut_out_clear(tmp_path):
    spec = TemplateSpec()
    hole = [(1000, 1000), (2000, 1000), (2000, 2000), (1000, 2000)]
    np_ = _project(_panel(sunk_mm=200.0, sunk_source="legend", holes=[_pts(hole)]))
    out = write_template_dxf(np_, tmp_path / "hole.dxf", spec)
    hs = _hatches(out, spec.layer("slab_sunk"))
    assert len(hs) == 1
    assert len(hs[0].paths) == 2, "the cut-out is not a hole in the hatch"
    outer, inner = hs[0].paths
    assert outer.path_type_flags & ezdxf.const.BOUNDARY_PATH_EXTERNAL
    assert not (inner.path_type_flags & ezdxf.const.BOUNDARY_PATH_EXTERNAL)


def test_a_sunk_pocket_is_hatched_over_itself_not_the_whole_bay(tmp_path):
    spec = TemplateSpec()
    pocket = [(200, 200), (800, 200), (800, 700), (200, 700)]
    np_ = _project(_panel(sunk_mm=250.0, sunk_source="legend", sunk_outlines=[_pts(pocket)]))
    out = write_template_dxf(np_, tmp_path / "pocket.dxf", spec)
    hs = _hatches(out, spec.layer("slab_sunk"))
    assert len(hs) == 1
    vs = list(hs[0].paths[0].vertices)
    xs, ys = [v[0] for v in vs], [v[1] for v in vs]
    assert max(xs) - min(xs) == pytest.approx(600, abs=1), "the hatch covers the bay, not the pocket"
    assert max(ys) - min(ys) == pytest.approx(500, abs=1)


def test_the_hatch_scale_is_the_spec_not_the_template(tmp_path):
    """Neither the scale nor the text heights are read from the seed DXF."""
    spec = TemplateSpec()
    assert spec.hatch.scale == 10.0
    spec.hatch.scale = 3.0
    np_ = _project(_panel(sunk_mm=200.0, sunk_source="legend"))
    out = write_template_dxf(np_, tmp_path / "scale.dxf", spec)
    assert _hatches(out)[0].dxf.pattern_scale == pytest.approx(3.0)
