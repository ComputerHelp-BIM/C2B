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
from c2b.revit.plan import RevitAction, RevitLevel, RevitPlan, _boundary, _revit_ready, _snap_to_axis, audit_heights

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


@pytest.mark.parametrize(("what", "outer", "holes"), [
    ("a clean panel", SQUARE, [INSIDE]),
    ("an outline that crosses itself", [[0, 0], [1000, 1000], [1000, 0], [0, 1000]], []),
    ("an opening outside the outline", SQUARE, [INSIDE, [[6000, 6000], [7000, 6000], [7000, 7000], [6000, 7000]]]),
    ("two openings that overlap", SQUARE, [[[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]],
                                           [[2000, 2000], [4000, 2000], [4000, 4000], [2000, 4000]]]),
    ("an opening that reaches the edge", SQUARE, [[[3000, 1000], [5000, 1000], [5000, 2000], [3000, 2000]]]),
    ("an opening that shares a whole edge", SQUARE, [[[2500, 2500], [5000, 2500], [5000, 0], [2500, 0]]]),
    ("an opening touching at one point", SQUARE, [[[1000, 1000], [3000, 1000], [5000, 3000], [1000, 3000]]]),
    ("openings nested inside each other", SQUARE, [[[1000, 1000], [4000, 1000], [4000, 4000], [1000, 4000]],
                                                   [[2000, 2000], [3000, 2000], [3000, 3000], [2000, 3000]]]),
    ("an opening that eats the panel", SQUARE, [SQUARE]),
    ("a sliver on one edge", [[0, 0], [5000, 0], [5000, 5000], [0.4, 5000], [0, 5000]], []),
])
def test_a_boundary_is_either_one_revit_will_take_or_none_at_all(what, outer, holes):
    """The whole point. Revit's refusal names six possible causes and no element a drafter can
    open, so a panel it would refuse has to be caught here or it is not caught at all."""
    rings, notes = _boundary(outer, holes)
    if rings is None:
        assert notes, f"{what} was skipped without saying why"
        return
    assert _revit_ready(rings) == "", f"{what} produced a boundary Revit will refuse"


def test_revit_is_stricter_than_shapely_about_an_opening_that_touches():
    """shapely calls a ring valid that meets its own outline at one point. Revit calls that an
    intersection, and this is the gap the second round of failures fell through."""
    from shapely.geometry import Polygon

    touching = [[1000, 1000], [3000, 1000], [5000, 3000], [1000, 3000]]
    assert Polygon(SQUARE, [touching]).is_valid, "shapely's opinion has changed; re-read this"
    assert _revit_ready([SQUARE, touching]) != ""


# ---------------------------------------------------------------------------
# "Line in Sketch is slightly off axis and may cause inaccuracies"
# ---------------------------------------------------------------------------

def test_an_edge_within_a_hair_of_square_is_squared_up():
    """1962 of them on one template. The drawing is traced round beam faces that are a
    fraction of a degree out of square, and Revit says so once per line."""
    ring, snapped = _snap_to_axis([[0, 0], [5000, 3], [5002, 5000], [1, 4998]], 5.0)
    assert snapped == 4
    for i in range(4):
        a, b = ring[i], ring[(i + 1) % 4]
        assert a[0] == b[0] or a[1] == b[1], "an edge came out neither horizontal nor vertical"


def test_an_edge_that_is_properly_on_a_slope_is_left_alone():
    """A ramp, a splayed corner, a site boundary. Squaring those is not tidying, it is wrong.

    The tolerance is a distance and not an angle for this reason: a tenth of a degree is 2 mm
    on a short edge and 20 mm on a long one, and 20 mm is a wall somebody measured.
    """
    splayed = [[0, 0], [5000, 900], [5000, 5000], [0, 5002]]
    ring, snapped = _snap_to_axis(splayed, 5.0)
    assert snapped == 1, "only the top edge, which was 2 mm out"
    assert ring[1] == [5000, 900], "the splayed edge was flattened"


def test_an_edge_already_square_is_not_counted_as_squared():
    """A count that says 1962 when nothing moved is a count nobody reads twice."""
    _ring, snapped = _snap_to_axis([[0, 0], [5000, 0], [5000, 5000], [0, 5000]], 5.0)
    assert snapped == 0


def test_squaring_can_be_turned_off_for_a_client_whose_geometry_is_theirs():
    from c2b.revit.mapping import RevitMapping

    assert RevitMapping().slab_axis_snap_mm > 0
    assert RevitMapping(slab_axis_snap_mm=0.0).slab_axis_snap_mm == 0.0


def test_squaring_is_reported_once_and_not_once_per_edge():
    source = (Path(__file__).resolve().parents[1] / "src" / "c2b" / "revit" / "plan.py"
              ).read_text(encoding="utf-8")
    assert "REVIT_EDGES_SQUARED" in source
    assert source.count("REVIT_EDGES_SQUARED") == 1


# ---------------------------------------------------------------------------
# 'Elements have duplicate "Mark" values'
# ---------------------------------------------------------------------------

def test_the_built_in_mark_is_never_written():
    """468 warnings on one template, every one of them about the marks working as intended: a
    column stack carries one mark on every level, and a typical floor repeats its slab marks on
    every storey built from it. The firm's own shared parameter has no such rule."""
    from c2b.revit.mapping import RevitMapping

    assert RevitMapping().mark_params == ["CH-ScheduleMark"]
    assert "Mark" not in RevitMapping().mark_params


def test_a_columns_offset_is_read_from_a_columns_own_parameter():
    """171 columns were reported as built at 0 mm when they were at -3000, because the check
    read the "Height Offset From Level" a point-hosted footing carries. A warning about a fault
    the model does not have costs more of an afternoon than no warning would."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "_COLUMN_OFFSET_BIPS" in source
    assert "FAMILY_BASE_LEVEL_OFFSET_PARAM" in source.split("_COLUMN_OFFSET_BIPS")[1][:200]
    check = source.split("def check_offsets_of")[1].split("\ndef ")[0]
    assert "_COLUMN_OFFSET_BIPS if action.get(\"kind\") in (\"column\", \"pile\")" in check


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
