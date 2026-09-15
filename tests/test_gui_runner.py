"""The window's worker: the whole pipeline without any display toolkit."""
from pathlib import Path

from c2b.demo import build_demo_drawing
from c2b.gui.runner import JobSettings, run_job, run_verify


def _collect():
    lines: list[tuple[str, str]] = []
    return lines, lambda level, message: lines.append((level, message))


def test_run_job_on_the_demo_drawing(tmp_path):
    dxf = build_demo_drawing(tmp_path / "demo.dxf")
    lines, progress = _collect()
    res = run_job(JobSettings(drawing=dxf, out_dir=tmp_path / "out"), progress)
    assert res.ok and res.error is None
    for path in (res.template_dxf, res.review_xlsx, res.schedules_xlsx, res.verify_md, res.review_dxf, res.levels_xlsx):
        assert path and Path(path).exists(), path
    assert res.counts["columns"] == 24 and res.counts["beam spans"] == 18
    assert [m for level, m in lines if level == "step"], "the window needs step messages to move the progress bar"
    # every issue row carries a plain-language meaning for the drafter
    assert all(meaning for _sev, _code, _n, meaning in res.issues), res.issues


def test_run_job_reports_a_bad_file_without_raising(tmp_path):
    bad = tmp_path / "not-a-drawing.dxf"
    bad.write_text("this is not a DXF", encoding="utf-8")
    lines, progress = _collect()
    res = run_job(JobSettings(drawing=bad, out_dir=tmp_path / "out"), progress)
    assert not res.ok and res.error
    assert any(level == "bad" for level, _m in lines)


def test_verify_an_edited_template(tmp_path):
    dxf = build_demo_drawing(tmp_path / "demo.dxf")
    _lines, progress = _collect()
    first = run_job(JobSettings(drawing=dxf, out_dir=tmp_path / "out"), progress)
    res = run_verify(first.template_dxf, None, progress)
    assert res.ok and res.counts["changes"] == 0

    import ezdxf
    doc = ezdxf.readfile(str(first.template_dxf))
    msp = doc.modelspace()
    msp.delete_entity(list(msp.query('LWPOLYLINE[layer=="CH-S-COLUMN"]'))[0])
    doc.saveas(str(first.template_dxf))
    res2 = run_verify(first.template_dxf, None, progress)
    assert not res2.ok and res2.counts["changes"] >= 1
    assert any(code == "RT_MISSING" for _sev, code, _n, _meaning in res2.issues)
