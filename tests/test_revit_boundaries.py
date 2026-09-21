"""The two things a Test17 import failed on, in Revit, an hour after C2B said it was finished.

Both were reported by Revit in words that name every possible cause and none of the actual
ones, on elements identified only by an internal id. Neither is something a drafter can act
on, and one of them is not even a warning: a column Revit measures as having no height is an
ERROR, so a single one of them refuses the whole transaction and the run is rolled back --
every type, every beam, every floor. 171 of them did that.

So both are C2B's to catch, before the file is handed over.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from c2b.diagnostics import DiagnosticsCollector
from c2b.revit.plan import RevitAction, RevitLevel, RevitPlan, _boundary, audit_heights

SCRIPT = (Path(__file__).resolve().parents[1] / "revit" / "C2B.extension" / "C2B.tab"
          / "Model.panel" / "Import C2B.pushbutton" / "script.py")

SQUARE = [[0, 0], [5000, 0], [5000, 5000], [0, 5000]]
INSIDE = [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]


# ---------------------------------------------------------------------------
# "The input curve loops cannot compose a valid boundary"
# ---------------------------------------------------------------------------

def test_a_boundary_that_is_already_valid_is_handed_over_untouched():
    """The common case must not be rewritten by a repair that had nothing to repair."""
    loops, repairs = _boundary(SQUARE, [INSIDE])
    assert loops == [SQUARE, INSIDE]
    assert repairs == []


def test_an_outline_that_crosses_itself_is_cut_down_to_its_largest_piece():
    """A panel closed the long way round a re-entrant corner. Revit refuses the whole loop."""
    bowtie = [[0, 0], [1000, 1000], [1000, 0], [0, 1000]]
    loops, repairs = _boundary(bowtie, [])
    assert loops and len(loops) == 1
    assert any("crossed itself" in r for r in repairs)


def test_an_opening_outside_the_outline_is_not_cut_and_is_reported():
    outside = [[6000, 6000], [7000, 6000], [7000, 7000], [6000, 7000]]
    loops, repairs = _boundary(SQUARE, [INSIDE, outside])
    assert loops and len(loops) == 2, "the opening that was outside was cut anyway"
    assert any("2 openings were drawn and 1 cut" in r for r in repairs)


def test_two_openings_that_overlap_become_one():
    """Two tags read off one shaft. Revit will not cut loops that intersect each other."""
    a = [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]]
    b = [[2000, 2000], [4000, 2000], [4000, 4000], [2000, 4000]]
    loops, repairs = _boundary(SQUARE, [a, b])
    assert loops and len(loops) == 2
    assert repairs, "a panel built to a different shape than drawn says nothing"


def test_an_outline_that_encloses_nothing_is_refused_rather_than_built():
    loops, repairs = _boundary([[0, 0], [1000, 0], [0, 0], [1000, 0]], [])
    assert loops is None
    assert repairs


def test_the_message_never_says_the_outline_crossed_itself_when_it_did_not():
    """It is the difference between looking at the panel and looking at the opening in it."""
    outside = [[6000, 6000], [7000, 6000], [7000, 7000], [6000, 7000]]
    _loops, repairs = _boundary(SQUARE, [outside])
    assert not any("crossed itself" in r for r in repairs)


def test_a_repaired_panel_is_reported_rather_than_quietly_built():
    source = (Path(__file__).resolve().parents[1] / "src" / "c2b" / "revit" / "plan.py"
              ).read_text(encoding="utf-8")
    assert "REVIT_OUTLINE_REPAIRED" in source
    assert "REVIT_BAD_OUTLINE" in source, "a panel that cannot be repaired is skipped in silence"


# ---------------------------------------------------------------------------
# "Change Offset Value so that Column height is not 0.0"
# ---------------------------------------------------------------------------

def plan_with(*actions: RevitAction) -> RevitPlan:
    plan = RevitPlan(source_file="test17.dxf", mapping_name="CH")
    plan.levels = [RevitLevel(id="LV00", name="LV00", elevation_mm=0.0),
                   RevitLevel(id="LV01", name="LV01", elevation_mm=3000.0)]
    plan.actions = list(actions)
    return plan


def column(**kw) -> RevitAction:
    args = {"id": "C1", "kind": "column", "category": "Structural Columns",
            "level_id": "LV00", "top_level_id": "LV00", "mark": "T1SW135c"}
    args.update(kw)
    return RevitAction(**args)


def test_a_column_of_no_height_is_never_handed_over():
    """One of them is an error, and an error refuses the whole transaction."""
    diag = DiagnosticsCollector()
    plan = plan_with(column(base_offset_mm=0.0))
    assert audit_heights(plan, diag, 3000.0) == 1
    assert plan.actions[0].base_offset_mm == -3000.0
    assert [d.code for d in diag.items] == ["REVIT_NO_HEIGHT"]
    assert diag.items[0].severity == "ERROR"


def test_the_column_it_names_is_the_one_a_drafter_can_find():
    diag = DiagnosticsCollector()
    audit_heights(plan_with(column(base_offset_mm=0.0)), diag, 3000.0)
    said = diag.items[0].message
    assert "T1SW135c" in said and "LV00" in said
    assert "Check the floor heights" in said


def test_a_column_that_stands_up_is_left_exactly_as_it_was():
    diag = DiagnosticsCollector()
    plan = plan_with(column(top_level_id="LV01"))
    assert audit_heights(plan, diag, 3000.0) == 0
    assert plan.actions[0].base_offset_mm == 0.0
    assert diag.items == []


def test_the_lowest_plans_columns_hang_below_their_own_level_and_that_is_fine():
    """Base and top are the same level; what makes them a column is the base offset."""
    diag = DiagnosticsCollector()
    plan = plan_with(column(base_offset_mm=-3000.0))
    assert audit_heights(plan, diag, 3000.0) == 0
    assert diag.items == []


@pytest.mark.parametrize("kind", ["column", "pile", "wall"])
def test_everything_that_spans_two_levels_is_measured(kind):
    diag = DiagnosticsCollector()
    assert audit_heights(plan_with(column(kind=kind, base_offset_mm=0.0)), diag, 3000.0) == 1


def test_a_beam_is_not_measured_because_its_curve_says_how_long_it_is():
    diag = DiagnosticsCollector()
    assert audit_heights(plan_with(column(kind="beam", base_offset_mm=0.0)), diag, 3000.0) == 0


# ---------------------------------------------------------------------------
# And the same thing again on the Revit side, because the plan is not the model
# ---------------------------------------------------------------------------

def test_the_base_offset_is_stated_before_the_top_level():
    """Asking Revit to put the top level on the base level while the offsets still read zero
    is asking for a column of no height, and what it does with that is its business."""
    source = SCRIPT.read_text(encoding="utf-8")
    branch = source.split('elif kind in ("column", "pile"):')[1].split('elif kind ==')[0]
    assert branch.index("FAMILY_BASE_LEVEL_OFFSET_PARAM") < branch.index("FAMILY_TOP_LEVEL_PARAM")
    assert "ensure_standing(inst, action)" in branch
    assert ".Set(" not in branch, "a raw Set hides a parameter that would not take the value"


def test_the_script_measures_what_revit_made_rather_than_what_was_asked_for():
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("def column_height_mm")[1].split("\ndef ")[0]
    assert "FAMILY_BASE_LEVEL_PARAM" in body and "FAMILY_TOP_LEVEL_PARAM" in body
    standing = source.split("def ensure_standing")[1].split("\ndef ")[0]
    assert "column_height_mm(inst)" in standing
    assert "note(" in standing, "a column silently moved is a column nobody goes and checks"


def test_the_revit_script_is_valid_python():
    ast.parse(SCRIPT.read_text(encoding="utf-8"))
