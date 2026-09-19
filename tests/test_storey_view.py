"""The storey editor's behaviour, without opening a window.

The WPF window and the Tkinter fallback both drive this presenter, so what is asserted here is
what both of them do. The reversal between the model (lowest first, the way heights add up)
and the table (highest first, the way a section is drawn) is the thing most worth pinning down.
"""
from __future__ import annotations

import pytest

from c2b.storeys import StoreySchedule
from c2b.ui.storey_view import NO_PLAN, StoreyPresenter, format_mm, parse_mm


def stack(*heights, base=0.0, names=None, plans=True):
    s = StoreySchedule(base_elevation_mm=base)
    for i, h in enumerate(heights):
        s.add(name=(names[i] if names else f"L{i}"), height_mm=h,
              plan_floor_id=(f"F{i:02d}" if plans else None), source="cad")
    return s


def presenter(*heights, base=0.0, names=None, plans=True, floors=None):
    s = stack(*heights, base=base, names=names, plans=plans)
    known = floors if floors is not None else [(f"F{i:02d}", f"PLAN {i}") for i in range(len(heights))]
    return StoreyPresenter(schedule=s, plan_floors=known)


# ------------------------------------------------------- the table as it reads

def test_the_table_is_drawn_highest_storey_first():
    p = presenter(0, 3000, 3000, names=["GF", "1F", "2F"])
    assert [r.name for r in p.rows()] == ["2F", "1F", "GF"]
    assert [r.elevation_text for r in p.rows()] == ["6000", "3000", "0"]


def test_the_lowest_storey_shows_no_height_and_is_marked_as_the_base():
    rows = presenter(0, 3000).rows()
    assert rows[-1].is_base and rows[-1].height_text == ""
    assert rows[0].is_top and rows[0].height_text == "3000"


def test_a_row_keeps_its_own_storey_number_however_it_is_drawn():
    rows = presenter(0, 3000, 3000).rows()
    assert [r.number for r in rows] == [2, 1, 0]


def test_a_row_says_which_plan_it_is_built_from():
    p = presenter(0, 3000)
    assert p.rows()[-1].plan_label == "F00  PLAN 0"


def test_a_storey_with_nothing_drawn_says_so():
    p = presenter(0, plans=False)
    assert p.rows()[0].plan_label == NO_PLAN


def test_the_plan_choices_offer_nothing_drawn_first():
    p = presenter(0, 3000)
    choices = p.plan_choices()
    assert choices[0] == (NO_PLAN, None)
    assert ("F01  PLAN 1", "F01") in choices


def test_a_row_carries_the_worst_thing_said_about_it():
    p = presenter(0, 0, names=["GF", "1F"])          # 1F is level with GF
    marked = {r.name: r.severity for r in p.rows()}
    assert marked["1F"] == "ERROR"


def test_an_error_on_a_storey_outranks_a_warning_on_the_same_one():
    p = presenter(0, 0, names=["GF", "1F"], plans=False)
    assert {r.severity for r in p.rows() if r.name == "1F"} == {"ERROR"}


# -------------------------------------------------------------- editing text

def test_typing_a_height_moves_the_storeys_above():
    p = presenter(0, 3000, 3000)
    assert p.set_height(p.schedule.storeys[1].id, "4000") == ""
    assert p.schedule.elevations() == [0, 4000, 7000]


def test_typing_a_height_that_is_not_a_number_changes_nothing_and_says_so():
    p = presenter(0, 3000)
    problem = p.set_height(p.schedule.storeys[1].id, "three metres")
    assert "not a height" in problem
    assert p.schedule.elevations() == [0, 3000]


def test_a_height_typed_on_the_lowest_storey_is_ignored_without_complaint():
    p = presenter(0, 3000)
    assert p.set_height(p.schedule.storeys[0].id, "9999") == ""
    assert p.schedule.elevations() == [0, 3000]


def test_typing_an_elevation_leaves_the_storeys_above_where_they_are():
    p = presenter(0, 3000, 3000, names=["GF", "1F", "2F"])
    assert p.set_elevation(p.schedule.storeys[1].id, "3500") == ""
    assert p.schedule.elevations() == [0, 3500, 6500]


def test_an_impossible_elevation_is_kept_and_reported_not_corrected():
    """The window shows what was typed; the problem panel says why it cannot be built."""
    p = presenter(0, 3000, 3000, names=["GF", "1F", "2F"])
    assert p.set_elevation(p.schedule.storeys[1].id, "-500") == ""
    assert p.schedule.elevations()[1] == -500
    assert any(s == "ERROR" for s, _ in p.problem_lines())


def test_renaming_a_storey_takes():
    p = presenter(0)
    p.set_name(p.schedule.storeys[0].id, "FOUNDATION")
    assert p.rows()[0].name == "FOUNDATION"


def test_choosing_a_plan_for_a_storey_takes():
    p = presenter(0, 3000, plans=False)
    p.set_plan(p.schedule.storeys[0].id, "F00")
    assert p.schedule.storeys[0].plan_floor_id == "F00"


def test_the_default_height_is_remembered_for_the_next_storey_added():
    p = presenter(0)
    assert p.set_default_height("3,300") == ""
    p.add_above()
    assert p.schedule.elevations() == [0, 3300]


def test_a_default_height_that_is_not_a_height_is_refused():
    p = presenter(0)
    assert "not a storey height" in p.set_default_height("tall")
    assert "not a storey height" in p.set_default_height("0")


# ----------------------------------------------------------------- commands
# Every command names the storey it acts on, so a test reads the way the window does: this
# button, on this row.

def test_add_above_puts_the_new_storey_over_the_one_named():
    p = presenter(0, 3000, names=["GF", "1F"])
    p.add_above(p.schedule.storeys[0].id)                 # above GF
    assert [s.name for s in p.schedule.storeys] == ["GF", "LEVEL", "1F"]
    assert p.schedule.elevations() == [0, 3000, 6000]


def test_add_below_puts_a_foundation_under_the_ground_floor():
    p = presenter(0, 3000, names=["GF", "1F"])
    p.add_below(p.schedule.storeys[0].id)
    p.set_name(p.schedule.storeys[0].id, "FOUNDATION")
    assert [s.name for s in p.schedule.storeys] == ["FOUNDATION", "GF", "1F"]
    assert p.schedule.elevations() == [0, 3000, 6000]


def test_add_with_no_storey_named_goes_on_top():
    p = presenter(0, 3000)
    p.add_above()
    assert len(p.schedule) == 3
    assert p.schedule.elevations()[-1] == 6000


def test_add_below_with_no_storey_named_goes_under_everything():
    p = presenter(0, 3000, names=["GF", "1F"])
    p.add_below()
    assert p.schedule.storeys[0].name == "LEVEL"


def test_remove_takes_the_storey_it_was_asked_for():
    p = presenter(0, 3000, 3000, names=["GF", "1F", "2F"])
    assert p.remove(p.schedule.storeys[1].id) == ""
    assert [s.name for s in p.schedule.storeys] == ["GF", "2F"]


def test_move_up_walks_that_storey_up_the_stack():
    p = presenter(0, 3000, 4000, names=["GF", "1F", "2F"])
    p.move(p.schedule.storeys[1].id, +1)
    assert [s.name for s in p.schedule.storeys] == ["GF", "2F", "1F"]


def test_repeat_stacks_typical_floors_on_the_row_it_was_pressed_on():
    p = presenter(0, 3000, names=["GF", "1F"])
    assert p.repeat(p.schedule.storeys[1].id, "7") == ""
    assert len(p.schedule) == 9
    assert all(s.plan_floor_id == "F01" for s in p.schedule.storeys[1:])
    assert p.schedule.elevations()[-1] == 24000


def test_repeat_refuses_a_count_that_is_not_a_count():
    p = presenter(0, 3000)
    sid = p.schedule.storeys[1].id
    assert "not a number of storeys" in p.repeat(sid, "lots")
    assert "not a number of storeys" in p.repeat(sid, "0")
    assert len(p.schedule) == 2


def test_a_command_names_a_storey_that_is_not_there_and_is_refused_loudly():
    """A row button carrying a stale id is a bug, not something to paper over."""
    p = presenter(0, 3000)
    with pytest.raises(KeyError):
        p.remove("S99")


# ------------------------------------------------------------------- status

def test_a_clean_stack_reads_ready_and_counts_itself():
    severity, badge, line = presenter(0, 3000, 3000).status()
    assert (severity, badge) == ("SUCCESS", "READY")
    assert "3 storeys" in line and "6000 mm overall" in line


def test_one_storey_is_not_called_storeys():
    assert "1 storey," in presenter(0).status()[2]


def test_an_error_is_counted_and_named_as_something_to_fix():
    severity, badge, line = presenter(0, 0, names=["GF", "GF"]).status()
    assert (severity, badge) == ("ERROR", "ERROR")
    assert "to fix before this can be built" in line


def test_a_warning_alone_does_not_read_as_an_error():
    severity, _, line = presenter(0, 3000, plans=False).status()
    assert severity == "WARNING" and "worth a look" in line


def test_a_stack_with_an_error_is_not_saved():
    assert not presenter(0, 0, names=["GF", "GF"]).can_save()
    assert presenter(0, 3000).can_save()


def test_a_warning_does_not_stop_a_save():
    assert presenter(0, 3000, plans=False).can_save()


def test_problems_are_listed_worst_first():
    p = presenter(0, 0, names=["GF", "GF"], plans=False)
    assert next(s for s, _ in p.problem_lines()) == "ERROR"


def test_a_drawn_plan_no_storey_builds_reaches_the_problem_list():
    p = presenter(0, 3000, floors=[("F00", "GROUND"), ("F01", "FIRST"), ("F09", "ROOF")])
    assert any("F09" in m for _, m in p.problem_lines())


# ------------------------------------------------------- numbers as typed

@pytest.mark.parametrize("text, expected", [
    ("3000", 3000.0), ("3,300", 3300.0), (" 2500 ", 2500.0), ("-2500", -2500.0),
    ("+3000", 3000.0), ("3000mm", 3000.0), ("3000 MM", 3000.0), ("3.5m", 3500.0),
    ("-2.5M", -2500.0), ("0", 0.0), ("3000.5", 3000.5),
])
def test_a_length_is_read_the_way_it_is_written_on_a_drawing(text, expected):
    assert parse_mm(text) == expected


@pytest.mark.parametrize("text", ["", "   ", None, "three", "3,,0", "mm", "1e", "--5"])
def test_something_that_is_not_a_length_is_refused_rather_than_guessed(text):
    assert parse_mm(text) is None


def test_a_bare_small_decimal_is_taken_at_its_word_not_guessed_as_metres():
    """Guessing is how a storey silently ends up 3 mm tall. It reads 3, and it is flagged."""
    assert parse_mm("3") == 3.0


@pytest.mark.parametrize("value, expected", [
    (3000.0, "3000"), (0.0, "0"), (-2500.0, "-2500"), (3000.04, "3000"),
    (3000.5, "3000.5"), (None, ""),
])
def test_a_length_is_shown_in_whole_millimetres_unless_it_is_not_one(value, expected):
    assert format_mm(value) == expected


# ------------------------------------------------- the note column, shortened

def test_a_row_carries_one_word_for_the_narrow_column_and_the_whole_of_it_in_a_tooltip():
    """Seven rows all reading the same sentence hide the one row that says something else."""
    p = presenter(0, 3000)
    p.schedule.storeys[1].note = "height assumed - please check"
    row = next(r for r in p.rows() if r.number == 1)
    assert row.flag == "assumed"
    assert "a floor plan in the drawing" in row.tooltip and "please check" in row.tooltip


def test_a_problem_outranks_where_the_storey_came_from():
    p = presenter(0, 0, names=["GF", "1F"])
    assert next(r for r in p.rows() if r.name == "1F").flag == "fix this"


def test_a_warning_reads_as_something_to_check():
    p = presenter(0, 3000, plans=False)
    assert {r.flag for r in p.rows()} == {"check"}


def test_an_ordinary_storey_says_only_where_it_came_from():
    assert {r.flag for r in presenter(0, 3000).rows()} == {"drawn"}


def test_a_repeated_storey_says_so_in_one_word():
    p = presenter(0, 3000, names=["GF", "1F"])
    p.repeat(p.schedule.storeys[1].id, "1")
    assert "repeat" in {r.flag for r in p.rows()}
