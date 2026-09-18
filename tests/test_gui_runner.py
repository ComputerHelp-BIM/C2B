"""The window's worker: the whole pipeline without any display toolkit."""
import re
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
    msp.delete_entity(next(iter(msp.query('LWPOLYLINE[layer=="CH-S-COLUMN"]'))))
    doc.saveas(str(first.template_dxf))
    res2 = run_verify(first.template_dxf, None, progress)
    assert not res2.ok and res2.counts["changes"] >= 1
    assert any(code == "RT_MISSING" for _sev, code, _n, _meaning in res2.issues)


def test_column_size_choice_survives_a_relabelling():
    """The window stores the label it showed; the mapping is what keeps that honest.

    An earlier build offered "tag or schedule (client's intent)". If a saved label that no longer
    exists were compared against the current first option, it would quietly come back meaning the
    *other* setting -- sizing every column off the drawing instead of the client's tag.
    """
    from c2b.gui.runner import COLUMN_SIZE_DEFAULT, COLUMN_SIZE_FROM, column_size_label, column_size_value

    assert set(COLUMN_SIZE_FROM.values()) == {"tag", "outline"}
    assert column_size_value(COLUMN_SIZE_DEFAULT) == "tag"
    assert column_size_value("drawn outline") == "outline"
    stale = "tag or schedule (client's intent)"
    assert column_size_label(stale) is None, "a label we no longer offer is not restored"
    assert column_size_value(stale) == "tag", "and it falls back to the default, not the other option"
    assert column_size_value(None) == "tag"


def test_the_run_button_is_not_inside_the_settings_grid():
    """The Run button disappeared once, and this is how.

    It was built into the frame that holds Units and Column size from, which sits in one cell of
    the entry grid. Widening the option box pushed the button past the window edge with nothing
    to scroll or wrap it back into view. Its frame must be packed on the window itself.
    """
    import ast
    from pathlib import Path

    src = Path("src/c2b/gui/app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    parent = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and any(isinstance(t, ast.Attribute) and t.attr == "run_btn" for t in node.targets)):
            parent = node.value.args[0].id
    assert parent, "could not find where self.run_btn is built"

    # that frame must be created on the window and laid out with pack, never gridded into a cell
    made_on_window = re.search(rf"\b{parent}\s*=\s*ttk\.Frame\(\s*self\b", src)
    assert made_on_window, f"{parent} is not a frame on the window"
    assert re.search(rf"\b{parent}\.pack\(", src), f"{parent} must be packed, not gridded"
    assert not re.search(rf"\b{parent}\.grid\(", src), f"{parent} is gridded and can be clipped"


# ----------------------------------------------------------- the last step, in the window
def test_the_run_prepares_the_revit_model_too(tmp_path):
    """A drafter should never open a terminal to reach the last step of the pipeline."""
    from c2b.export.levels import level_rows_for_editing, write_level_elevations

    dxf = build_demo_drawing(tmp_path / "demo.dxf")
    lines, progress = _collect()
    first = run_job(JobSettings(drawing=dxf, out_dir=tmp_path / "out"), progress)

    # no elevations yet: there is nothing to place, and the window says exactly that
    assert first.revit_json is None
    assert "elevation" in first.next_step.lower() and "run again" in first.next_step.lower()

    rows = level_rows_for_editing(first.levels_xlsx)
    write_level_elevations(first.levels_xlsx, {r["excel_row"]: 3000.0 * i for i, r in enumerate(rows)})

    lines, progress = _collect()
    second = run_job(JobSettings(drawing=dxf, out_dir=tmp_path / "out", levels=first.levels_xlsx), progress)
    assert second.revit_json and Path(second.revit_json).exists()
    assert second.revit_xlsx and Path(second.revit_xlsx).exists()
    assert "Revit" in second.next_step and Path(second.revit_json).name in second.next_step
    assert [m for level, m in lines if m.startswith("4 of 4")], "the Revit step has to be visible as a step"


def test_the_template_description_is_found_not_asked_for(tmp_path):
    """Nobody should type a path to a file that only ever sits in one place."""
    from c2b.gui.runner import REVIT_TEMPLATE_NAMES, SHARED_PARAM_NAMES, _find_beside

    repo = Path(__file__).resolve().parent.parent
    found = _find_beside(tmp_path, tmp_path / "x.dxf", REVIT_TEMPLATE_NAMES)
    assert found is not None and found.name.endswith(".template.md"), "the shipped template was not found"
    assert _find_beside(tmp_path, tmp_path / "x.dxf", SHARED_PARAM_NAMES) is not None

    # one sitting beside the drawing wins over the shipped one
    beside = tmp_path / "templates"
    beside.mkdir()
    mine = beside / "MINE.template.md"
    mine.write_text("# MINE\n", encoding="utf-8")
    assert _find_beside(tmp_path / "out", tmp_path / "x.dxf", REVIT_TEMPLATE_NAMES) == mine
    assert repo.exists()


def test_floor_heights_round_trip_without_excel(tmp_path):
    from c2b.export.levels import level_rows_for_editing, write_level_elevations

    dxf = build_demo_drawing(tmp_path / "demo.dxf")
    _lines, progress = _collect()
    res = run_job(JobSettings(drawing=dxf, out_dir=tmp_path / "out"), progress)

    rows = level_rows_for_editing(res.levels_xlsx)
    assert rows and all(r["elevation_mm"] is None for r in rows)
    assert all(r["floor_id"] and r["excel_row"] >= 2 for r in rows)

    write_level_elevations(res.levels_xlsx, {rows[0]["excel_row"]: -1500.0, rows[-1]["excel_row"]: None})
    back = level_rows_for_editing(res.levels_xlsx)
    assert back[0]["elevation_mm"] == -1500.0
    assert back[-1]["elevation_mm"] is None
    assert back[0]["floor_name"] == rows[0]["floor_name"], "editing heights must not disturb the rest"


def test_the_window_shows_the_next_step_and_offers_the_heights_editor():
    """A log of forty lines does not tell a drafter which line is addressed to them."""
    import ast

    source = (Path(__file__).resolve().parent.parent / "src" / "c2b" / "gui" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_edit_levels" in names

    finish = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_finish")
    body = ast.unparse(finish)
    assert "next_step" in body, "the window never shows the next step"
    assert "levels_btn.pack" in body, "the heights editor is never offered"
    # it is offered when the heights are what is missing, not always
    assert "not result.revit_json" in body
