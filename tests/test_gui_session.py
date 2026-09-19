"""What the C2B window does, without opening one.

Both windows -- the WPF one and the Tkinter fallback -- drive this, so what is asserted here
is what both of them do, and neither can gain a field or word a status line differently.
"""
from __future__ import annotations

import json

import pytest

from c2b.gui.runner import COLUMN_SIZE_DEFAULT, JobResult
from c2b.gui.session import FIELDS, KEYS, RESULT_ACTIONS, UNITS, MainPresenter


def test_a_new_window_starts_on_the_defaults():
    p = MainPresenter()
    assert p.values["units"] == UNITS[0]
    assert p.values["col_size"] == COLUMN_SIZE_DEFAULT
    assert set(p.values) == set(KEYS)


# ------------------------------------------------------------- the field list

def test_the_drawing_is_the_first_field_and_the_only_required_one():
    assert FIELDS[0].key == "drawing"
    assert MainPresenter().problem() == "Pick a client drawing first."


def test_the_drawing_is_the_one_field_not_remembered_between_runs():
    """Every other path is a setting; the drawing is this job."""
    assert not FIELDS[0].remembered
    assert all(f.remembered for f in FIELDS[1:])


def test_every_field_says_what_it_is_for():
    for f in FIELDS:
        assert f.label and f.hint, f"{f.key} has no label or hint"
        assert f.kind in ("open", "folder")
        assert f.filters or f.kind == "folder", f"{f.key} offers no file types"


def test_a_drawing_that_is_not_there_is_reported_with_its_path(tmp_path):
    p = MainPresenter()
    p.values["drawing"] = str(tmp_path / "gone.dxf")
    assert "gone.dxf" in p.problem()


def test_a_drawing_that_is_there_starts_the_run(tmp_path):
    drawing = tmp_path / "job.dxf"
    drawing.write_text("", encoding="utf-8")
    p = MainPresenter()
    p.values["drawing"] = str(drawing)
    assert p.problem() == ""


# ------------------------------------------------------- what the run is given

def test_the_settings_carry_what_was_typed(tmp_path):
    drawing = tmp_path / "job.dxf"
    drawing.write_text("", encoding="utf-8")
    p = MainPresenter()
    p.values.update({"drawing": str(drawing), "out": str(tmp_path), "units": "mm",
                     "beam_depth": "600", "slab_thk": "150",
                     "col_size": "drawn outline"})
    s = p.job_settings()
    assert s.drawing == drawing and s.out_dir == tmp_path
    assert s.units == "mm"
    assert s.default_beam_depth_mm == 600.0 and s.default_slab_thickness_mm == 150.0
    assert s.column_size_from == "outline"


def test_read_from_drawing_means_no_units_were_stated(tmp_path):
    drawing = tmp_path / "job.dxf"
    drawing.write_text("", encoding="utf-8")
    p = MainPresenter()
    p.values.update({"drawing": str(drawing), "units": UNITS[0]})
    assert p.job_settings().units is None


def test_a_remembered_path_that_has_since_been_deleted_is_dropped(tmp_path):
    """Last job's output folder is exactly the kind of thing that goes."""
    p = MainPresenter()
    p.values["out"] = str(tmp_path / "deleted")
    assert p.path("out") is None


@pytest.mark.parametrize("text, expected", [
    ("600", 600.0), ("1,200", 1200.0), (" 150 ", 150.0), ("", None), ("deep", None),
])
def test_a_size_is_read_the_way_it_is_typed(text, expected):
    p = MainPresenter()
    p.values["beam_depth"] = text
    assert p.number("beam_depth") == expected


# --------------------------------------------------------- what a run reported

def test_before_a_run_the_footer_says_what_to_do():
    severity, badge, line = MainPresenter().summary()
    assert (severity, badge) == ("INFO", "READY")
    assert "press Run" in line


def test_a_clean_run_counts_itself_and_flags_nothing():
    p = MainPresenter()
    p.result = JobResult(ok=True, counts={"floors": 7, "columns": 330, "beam spans": 0})
    severity, badge, line = p.summary()
    assert (severity, badge) == ("SUCCESS", "DONE")
    assert "7 floors" in line and "330 columns" in line
    assert "beam spans" not in line, "a count of nothing is noise"


def test_a_run_with_things_to_check_says_how_many_kinds():
    p = MainPresenter()
    p.result = JobResult(counts={"floors": 1}, issues=[("WARNING", "X", 3, "a thing"),
                                                      ("WARNING", "Y", 1, "another")])
    severity, badge, line = p.summary()
    assert (severity, badge) == ("WARNING", "CHECK")
    assert "2 kinds of thing to check" in line


def test_one_kind_of_thing_is_not_called_kinds():
    p = MainPresenter()
    p.result = JobResult(counts={}, issues=[("WARNING", "X", 3, "a thing")])
    assert "1 kind of thing" in p.summary()[2]


def test_a_run_that_stopped_says_so_first():
    p = MainPresenter()
    p.result = JobResult(error="ValueError: no")
    severity, badge, line = p.summary()
    assert (severity, badge) == ("ERROR", "ERROR")
    assert line.startswith("Stopped: ")


def test_only_the_result_files_that_exist_are_offered(tmp_path):
    made = tmp_path / "x.template.dxf"
    made.write_text("", encoding="utf-8")
    p = MainPresenter()
    p.result = JobResult(template_dxf=made, review_xlsx=tmp_path / "missing.xlsx", out_dir=tmp_path)
    labels = [label for label, _ in p.actions()]
    assert "Open the template DXF" in labels
    assert "Review workbook" not in labels, "a button that opens nothing is worse than no button"
    assert "Open the folder" in labels


def test_the_result_buttons_are_offered_in_a_settled_order():
    """The same button is in the same place on every run, so it can be found by muscle memory."""
    order = [a for _, a in RESULT_ACTIONS]
    assert order[0] == "template_dxf" and order[-1] == "out_dir"


def test_no_result_means_no_buttons_and_no_storey_editor():
    p = MainPresenter()
    assert p.actions() == [] and not p.can_edit_storeys() and p.next_step() == ""


def test_the_storey_editor_is_offered_on_any_run_that_read_a_drawing(tmp_path):
    sidecar = tmp_path / "x.storeys.json"
    sidecar.write_text("{}", encoding="utf-8")
    p = MainPresenter()
    p.result = JobResult(storeys_json=sidecar)
    assert p.can_edit_storeys()


def test_issue_rows_are_capped_so_one_bad_drawing_cannot_fill_the_window():
    p = MainPresenter()
    p.result = JobResult(issues=[("WARNING", f"C{n}", 1, "x") for n in range(400)])
    assert len(p.issue_rows()) == 200


def test_an_issue_with_no_plain_meaning_falls_back_to_its_code():
    p = MainPresenter()
    p.result = JobResult(issues=[("ERROR", "REVIT_NO_LEVELS", 2, "")])
    assert p.issue_rows() == [("Error", 2, "REVIT_NO_LEVELS")]


# ----------------------------------------------------------------- remembering

def test_what_was_typed_comes_back_next_time(tmp_path):
    path = tmp_path / "gui.json"
    p = MainPresenter()
    p.values.update({"seed": "C:/CH-TEMPLATE.dxf", "beam_depth": "600", "units": "mm",
                     "col_size": "drawn outline"})
    p.save(path)

    back = MainPresenter()
    back.load(path)
    assert back.values["seed"] == "C:/CH-TEMPLATE.dxf"
    assert back.values["beam_depth"] == "600"
    assert back.values["units"] == "mm"
    assert back.values["col_size"] == "drawn outline"


def test_the_drawing_is_not_remembered(tmp_path):
    path = tmp_path / "gui.json"
    p = MainPresenter()
    p.values["drawing"] = "C:/jobs/last.dxf"
    p.save(path)
    assert "drawing" not in json.loads(path.read_text(encoding="utf-8"))

    back = MainPresenter()
    back.load(path)
    assert back.values["drawing"] == ""


def test_a_settings_file_that_will_not_read_is_not_fatal(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text("{ not json", encoding="utf-8")
    p = MainPresenter()
    p.load(path)
    assert p.values["units"] == UNITS[0]


def test_a_settings_file_holding_something_else_entirely_is_ignored(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text('["a list"]', encoding="utf-8")
    p = MainPresenter()
    p.load(path)
    assert p.values["col_size"] == COLUMN_SIZE_DEFAULT


def test_a_remembered_option_that_is_no_longer_offered_falls_back(tmp_path):
    """A relabelled option must not silently come to mean the other one."""
    path = tmp_path / "gui.json"
    path.write_text(json.dumps({"col_size": "whatever we called it in 0.9", "units": "furlongs"}),
                    encoding="utf-8")
    p = MainPresenter()
    p.load(path)
    assert p.values["col_size"] == COLUMN_SIZE_DEFAULT
    assert p.values["units"] == UNITS[0]


def test_a_home_that_cannot_be_written_does_not_stop_a_run(tmp_path):
    p = MainPresenter()
    p.save(tmp_path / "x.dxf" / "nested" / "gui.json")   # a file is not a folder
    assert p.problem() == "Pick a client drawing first."


def test_both_option_boxes_offer_their_choices_and_one_is_current():
    p = MainPresenter()
    boxes = p.option_boxes()
    assert [key for key, _, _, _ in boxes] == ["units", "col_size"]
    for key, label, choices, _hint in boxes:
        assert label and choices
        assert p.values[key] in choices, f"{key} starts on something it does not offer"
