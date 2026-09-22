"""The build window inside Revit: what it offers, and what a tick means.

The pyRevit script cannot import C2B -- it runs in Revit's own engine against the plan file
alone -- so everything it would otherwise work out for itself is worked out here, where it can
be tested, and handed over in the plan. It renders the rows and builds the actions whose level
and kind are both ticked. That is the whole of the rule.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from c2b.export.revit_picker import picker_path, write_picker_window
from c2b.revit.plan import KIND_LABELS, RevitAction, RevitLevel, RevitPlan, build_picker

SCRIPT = (Path(__file__).resolve().parents[1] / "revit" / "C2B.extension" / "C2B.tab"
          / "Model.panel" / "Import C2B.pushbutton" / "script.py")


@pytest.fixture
def plan() -> RevitPlan:
    p = RevitPlan(source_file="Test17.dxf", mapping_name="CH")
    p.levels = [RevitLevel(id="LV00", name="LV00", elevation_mm=0.0),
                RevitLevel(id="LV01", name="LV01", elevation_mm=3000.0),
                RevitLevel(id="LV02", name="LV02", elevation_mm=6000.0)]
    p.actions = (
        [RevitAction(id=f"c{i}", kind="column", category="Structural Columns", level_id="LV00")
         for i in range(5)]
        + [RevitAction(id=f"b{i}", kind="beam", category="Structural Framing", level_id="LV01")
           for i in range(9)]
        + [RevitAction(id=f"s{i}", kind="floor", category="Floors", level_id="LV01")
           for i in range(4)]
        + [RevitAction(id="g1", kind="grid", category="Grids")])
    return p


# ---------------------------------------------------------------------------
# What the window offers
# ---------------------------------------------------------------------------

def test_a_storey_carries_the_count_of_what_is_on_it(plan):
    picker = build_picker(plan)
    rows = {lv.name: lv for lv in picker.levels}
    assert rows["LV00"].total == 5 and rows["LV00"].counts == {"column": 5}
    assert rows["LV01"].total == 13 and rows["LV01"].counts == {"beam": 9, "floor": 4}
    assert rows["LV02"].total == 0, "a storey with nothing on it is still offered, at zero"


def test_the_storeys_read_downwards_like_a_stack(plan):
    """The same way the storey editor lists them, because they are the same storeys."""
    assert [lv.name for lv in build_picker(plan).levels] == ["LV02", "LV01", "LV00"]


def test_a_grid_belongs_to_no_storey(plan):
    """Nothing about a grid is per-floor, so no storey tick can leave one out."""
    picker = build_picker(plan)
    assert picker.off_level == 1
    assert sum(lv.counts.get("grid", 0) for lv in picker.levels) == 0
    assert any(k.kind == "grid" and k.total == 1 for k in picker.kinds)


def test_the_kinds_are_named_the_way_a_drafter_says_them(plan):
    labels = {k.kind: k.label for k in build_picker(plan).kinds}
    assert labels["floor"] == "Slabs", "nobody ticks 'floor'"
    assert labels["column"] == "Columns" and labels["beam"] == "Beams"
    assert set(KIND_LABELS) >= {"grid", "column", "beam", "floor", "wall", "footing"}


def test_the_biggest_kind_is_offered_first(plan):
    assert build_picker(plan).kinds[0].kind == "beam"


def test_every_action_is_counted_once_somewhere(plan):
    picker = build_picker(plan)
    assert picker.total == len(plan.actions)
    assert sum(k.total for k in picker.kinds) == picker.total
    assert sum(lv.total for lv in picker.levels) + picker.off_level == picker.total


def test_a_run_puts_the_picker_in_the_plan():
    """The script reads it from there; there is no C2B on that side to ask."""
    source = (Path(__file__).resolve().parents[1] / "src" / "c2b" / "revit" / "plan.py"
              ).read_text(encoding="utf-8")
    assert "plan.picker = build_picker(plan)" in source
    assert "picker: RevitPicker | None" in source


# ---------------------------------------------------------------------------
# The window itself, written out for the other side of the fence
# ---------------------------------------------------------------------------

def test_the_window_is_written_beside_the_plan_and_stands_on_its_own(tmp_path):
    """Themed here, because a second copy of the palette in the extension is how two surfaces
    drift apart."""
    json_path = tmp_path / "Test17.revit.json"
    json_path.write_text("{}", encoding="utf-8")
    written = write_picker_window(json_path)
    assert written == picker_path(json_path) == tmp_path / "Test17.revit.xaml"
    ET.parse(written), "the markup the Revit script loads does not parse"
    markup = written.read_text(encoding="utf-8")
    assert "BrushVividRed" in markup, "the theme was not spliced in, so it is not branded"
    for name in ("LevelsHost", "KindsHost", "SelectionText", "BtnBuild", "BtnCancel"):
        assert f'x:Name="{name}"' in markup


def test_both_ways_of_running_write_the_window():
    for module in ("cli.py", "gui/runner.py"):
        source = (Path(__file__).resolve().parents[1] / "src" / "c2b" / module
                  ).read_text(encoding="utf-8")
        assert "write_picker_window(" in source, f"{module} writes a plan with no window"


def test_the_window_asks_for_nothing_but_ticks():
    """Every decision was already made in C2B. Nothing here is a question worth asking again."""
    markup = (Path(__file__).resolve().parents[1] / "src" / "c2b" / "ui" / "build_picker.xaml"
              ).read_text(encoding="utf-8")
    body = markup.split("-->", 1)[1].split("<Window", 1)[1].split(">", 1)[1]
    assert "<TextBox" not in body and "<ComboBox" not in body
    assert "<DataGrid" not in body, "a picker is not a table"


# ---------------------------------------------------------------------------
# What a tick means, on the side that acts on it
# ---------------------------------------------------------------------------

def test_only_what_is_ticked_on_both_sides_is_built():
    source = SCRIPT.read_text(encoding="utf-8")
    rule = source.split("plan[\"actions\"] = [a for a in everything")[1].split("]")[0]
    assert 'a.get("kind") in wanted_kinds' in rule
    assert 'a.get("level_id") in wanted_levels' in rule
    assert 'not a.get("level_id")' in rule, "a grid has no storey and must not need one"


def test_the_levels_are_still_all_created_and_it_says_why():
    """A member on a storey you did tick is measured from the level under it."""
    source = SCRIPT.read_text(encoding="utf-8")
    said = source.split("left_out = len(everything)")[1].split("\n\n")[0]
    assert "Every level is still created" in said
    assert "measured from the level under it" in said


def test_the_window_falls_back_to_a_plain_list_rather_than_stopping():
    """C2B is not always what wrote the plan file sitting next to it."""
    body = SCRIPT.read_text(encoding="utf-8").split("def choose_what_to_build")[1].split("\ndef ")[0]
    assert "os.path.isfile(xaml_path)" in body
    assert "forms.SelectFromList" in body
    assert "except Exception" in body


def test_a_plan_from_before_the_picker_builds_everything():
    """An older plan file has no picker in it, and must not therefore build nothing."""
    body = SCRIPT.read_text(encoding="utf-8").split("def choose_what_to_build")[1].split("\ndef ")[0]
    guard = body.split('if not picker.get("kinds"):')[1].split("return")[1].split("\n\n")[0]
    assert "plan.get" in guard


def test_a_kind_with_nothing_in_it_cannot_be_ticked():
    body = SCRIPT.read_text(encoding="utf-8").split("def _row")[1].split("\n    def ")[0]
    assert "box.IsEnabled = count > 0" in body
    assert "box.IsChecked = count > 0" in body
