"""The storey schedule: the arithmetic, and every operation the window offers."""
from __future__ import annotations

import pytest

from c2b.storeys import (
    DEFAULT_HEIGHT_MM,
    STOREY_SCHEMA_VERSION,
    Storey,
    StoreySchedule,
    from_level_rows,
    from_project,
)


def stack(*heights: float, base: float = 0.0, names: list[str] | None = None) -> StoreySchedule:
    """A schedule of len(heights) storeys. heights[0] is the lowest and is never used."""
    s = StoreySchedule(base_elevation_mm=base)
    for i, h in enumerate(heights):
        s.add(name=(names[i] if names else f"L{i}"), height_mm=h, plan_floor_id=f"F{i:02d}", source="cad")
    return s


# --------------------------------------------------------------- elevations

def test_elevations_are_the_heights_added_up_from_the_base():
    s = stack(0, 3000, 3000, 3500, base=-2500)
    assert s.elevations() == [-2500, 500, 3500, 7000]


def test_the_lowest_storeys_height_is_not_used():
    s = stack(9999, 3000, base=100)
    assert s.elevations() == [100, 3100]


def test_an_empty_schedule_has_no_elevations_and_no_height():
    s = StoreySchedule()
    assert s.elevations() == []
    assert s.total_height_mm() == 0.0


def test_total_height_is_base_to_top():
    assert stack(0, 3000, 4000, base=-1000).total_height_mm() == 7000


def test_rows_blank_the_base_height_and_flag_the_ends():
    rows = stack(0, 3000, 3000).rows()
    assert [r["height_mm"] for r in rows] == [None, 3000, 3000]
    assert [r["is_base"] for r in rows] == [True, False, False]
    assert [r["is_top"] for r in rows] == [False, False, True]
    assert rows[0]["source_words"] == "a floor plan in the drawing"


# ---------------------------------------------------------------------- add

def test_adding_on_top_makes_the_building_taller():
    s = stack(0, 3000)
    s.add(name="ROOF", height_mm=2800)
    assert s.elevations() == [0, 3000, 5800]


def test_adding_in_the_middle_pushes_everything_above_up():
    s = stack(0, 3000, 3000, names=["GF", "1F", "2F"])
    s.add(index=2, name="MEZZ", height_mm=1500)
    assert [x.name for x in s.storeys] == ["GF", "1F", "MEZZ", "2F"]
    assert s.elevations() == [0, 3000, 4500, 7500]


def test_adding_at_the_bottom_keeps_the_datum_and_lifts_the_rest():
    """A foundation added under the ground floor takes the datum; the building rises off it."""
    s = stack(0, 3000, names=["GF", "1F"])
    s.add(index=0, name="FOUNDATION", height_mm=2500)
    assert [x.name for x in s.storeys] == ["FOUNDATION", "GF", "1F"]
    assert s.elevations() == [0, 2500, 5500]


def test_adding_to_an_empty_schedule_starts_the_stack():
    s = StoreySchedule(base_elevation_mm=-500)
    s.add(index=0, name="FOUNDATION", height_mm=2500)
    assert s.elevations() == [-500]


def test_add_takes_the_default_height_when_none_is_given():
    s = StoreySchedule(default_height_mm=3300)
    s.add(name="GF")
    s.add(name="1F")
    assert s.elevations() == [0, 3300]


def test_add_clamps_an_index_past_either_end():
    s = stack(0, 3000)
    s.add(index=99, name="ROOF", height_mm=1000)
    s.add(index=-5, name="PILE CAP", height_mm=800)
    assert [x.name for x in s.storeys] == ["PILE CAP", "L0", "L1", "ROOF"]


def test_added_storeys_get_ids_that_are_never_reused():
    s = stack(0, 3000)
    first = s.add(name="ROOF")
    s.remove(s.index_of(first.id))
    second = s.add(name="ROOF 2")
    assert second.id != first.id


# ------------------------------------------------------------------- remove

def test_removing_from_the_middle_brings_the_building_down():
    s = stack(0, 3000, 3000, 3000, names=["GF", "1F", "2F", "3F"])
    s.remove(2)
    assert [x.name for x in s.storeys] == ["GF", "1F", "3F"]
    assert s.elevations() == [0, 3000, 6000]


def test_removing_the_lowest_storey_leaves_every_other_where_it_was():
    """Deleting a foundation must not drag the ground floor down to where it was."""
    s = stack(0, 2500, 3000, names=["FOUNDATION", "GF", "1F"])
    assert s.elevations() == [0, 2500, 5500]
    s.remove(0)
    assert [x.name for x in s.storeys] == ["GF", "1F"]
    assert s.elevations() == [2500, 5500]


def test_removing_the_only_storey_empties_the_schedule():
    s = stack(0)
    s.remove(0)
    assert s.storeys == []


def test_removing_an_index_that_is_not_there_is_refused():
    with pytest.raises(IndexError):
        stack(0, 3000).remove(7)


# --------------------------------------------------------------------- move

def test_moving_a_storey_up_carries_its_height_with_it():
    s = stack(0, 3000, 4000, names=["GF", "1F", "2F"])
    assert s.move(1, +1) == 2
    assert [x.name for x in s.storeys] == ["GF", "2F", "1F"]
    assert s.elevations() == [0, 4000, 7000]


def test_moving_a_storey_down_swaps_it_with_the_one_below():
    s = stack(0, 3000, 4000, names=["GF", "1F", "2F"])
    assert s.move(2, -1) == 1
    assert [x.name for x in s.storeys] == ["GF", "2F", "1F"]


def test_moving_past_the_end_does_nothing_rather_than_failing():
    s = stack(0, 3000)
    assert s.move(1, +1) == 1
    assert s.move(0, -1) == 0
    assert [x.name for x in s.storeys] == ["L0", "L1"]


# ------------------------------------------------------------------- repeat

def test_repeat_stacks_typical_floors_on_one_drawn_plan():
    s = stack(0, 3000, names=["GF", "1F"])
    made = s.repeat(1, times=7)
    assert len(s.storeys) == 9
    assert len(made) == 7
    assert [x.plan_floor_id for x in s.storeys] == ["F00"] + ["F01"] * 8
    assert s.elevations() == [0, 3000, 6000, 9000, 12000, 15000, 18000, 21000, 24000]


def test_repeat_counts_on_from_the_number_in_the_name():
    s = stack(0, 3000, names=["GF", "1F"])
    s.repeat(1, times=3)
    assert [x.name for x in s.storeys] == ["GF", "1F", "2F", "3F", "4F"]


def test_repeat_keeps_the_padding_of_a_zero_padded_name():
    s = stack(0, names=["LEVEL 01"])
    s.repeat(0, times=2)
    assert [x.name for x in s.storeys] == ["LEVEL 01", "LEVEL 02", "LEVEL 03"]


def test_repeat_skips_a_name_already_in_use():
    s = stack(0, 3000, 3000, names=["GF", "1F", "3F"])
    s.repeat(1, times=1)
    assert [x.name for x in s.storeys] == ["GF", "1F", "2F", "3F"]


def test_repeat_of_a_name_with_no_number_counts_beside_it():
    s = stack(0, names=["ROOF"])
    s.repeat(0, times=2)
    assert [x.name for x in s.storeys] == ["ROOF", "ROOF 2", "ROOF 3"]


def test_repeat_zero_times_changes_nothing():
    s = stack(0, 3000)
    assert s.repeat(1, times=0) == []
    assert len(s.storeys) == 2


def test_a_repeat_says_what_it_is_a_repeat_of():
    s = stack(0, 3000, names=["GF", "1F"])
    copy = s.repeat(1, times=1)[0]
    assert copy.source == "repeat"
    assert "1F" in copy.note


# ------------------------------------------------------- heights, elevations

def test_setting_a_height_moves_everything_above_it():
    s = stack(0, 3000, 3000, 3000)
    s.set_height(1, 4000)
    assert s.elevations() == [0, 4000, 7000, 10000]


def test_setting_an_elevation_leaves_the_storeys_above_the_same_distance_away():
    s = stack(0, 3000, 3000, 3000, names=["GF", "1F", "2F", "3F"])
    s.set_elevation(2, 7000)
    assert s.elevations() == [0, 3000, 7000, 10000]
    assert s.storeys[2].height_mm == 4000


def test_setting_the_lowest_elevation_moves_the_whole_building():
    s = stack(0, 3000, 3000)
    s.set_elevation(0, -2500)
    assert s.elevations() == [-2500, 500, 3500]


def test_setting_an_elevation_below_the_storey_under_it_is_kept_and_reported():
    """The window must not silently correct a typo; it shows what was typed and flags it."""
    s = stack(0, 3000, 3000, names=["GF", "1F", "2F"])
    s.set_elevation(1, -1000)
    assert s.elevations()[1] == -1000
    assert any(p.severity == "ERROR" and "1F" in p.message for p in s.problems())


def test_rename_ignores_an_empty_name():
    s = stack(0)
    s.rename(0, "   ")
    assert s.storeys[0].name == "L0"


def test_set_plan_clears_with_an_empty_string():
    s = stack(0)
    s.set_plan(0, "")
    assert s.storeys[0].plan_floor_id is None


# ------------------------------------------------------------ sorting, index

def test_sort_by_elevation_reorders_and_re_derives_the_heights():
    s = stack(0, 3000, 4000, names=["GF", "1F", "2F"])       # 0, 3000, 7000
    s.move(0, +1)                                             # 1F(3000) GF(0)... heights travel
    s.sort_by_elevation()
    assert s.elevations() == sorted(s.elevations())
    assert all(x.height_mm >= 0 for x in s.storeys[1:])


def test_index_of_finds_a_storey_and_refuses_an_unknown_one():
    s = stack(0, 3000)
    assert s.index_of(s.storeys[1].id) == 1
    with pytest.raises(KeyError):
        s.index_of("nope")


# ----------------------------------------------------------------- problems

def test_two_storeys_of_one_name_are_an_error():
    s = stack(0, 3000, names=["GF", "GF"])
    problems = s.problems()
    assert [p.severity for p in problems].count("ERROR") == 1
    assert "Revit will not hold two levels" in problems[0].message


def test_a_name_that_differs_only_in_case_is_still_a_clash():
    s = stack(0, 3000, names=["Ground", "GROUND"])
    assert any(p.severity == "ERROR" for p in s.problems())


def test_two_storeys_at_the_same_height_are_an_error():
    s = stack(0, 0, names=["GF", "1F"])
    assert any(p.severity == "ERROR" and "nothing to be built with" in p.message for p in s.problems())


def test_a_storey_with_no_plan_is_a_warning_not_an_error():
    s = stack(0, 3000)
    s.set_plan(1, None)
    problems = s.problems()
    assert any(p.severity == "WARNING" and "created as a level" in p.message for p in problems)
    assert s.ok()


def test_a_drawn_plan_no_storey_builds_is_reported():
    s = stack(0, 3000)                                        # builds F00 and F01
    problems = s.problems(plan_floor_ids=["F00", "F01", "F02"])
    assert any("F02" in p.message and "left out of the model" in p.message for p in problems)


def test_an_empty_schedule_is_an_error_on_its_own():
    problems = StoreySchedule().problems()
    assert len(problems) == 1 and problems[0].severity == "ERROR"
    assert not StoreySchedule().ok()


def test_a_storey_with_a_blank_name_is_an_error():
    s = stack(0)
    s.storeys[0].name = "  "
    assert any(p.severity == "ERROR" and "no name" in p.message for p in s.problems())


# -------------------------------------------------------------- persistence

def test_a_schedule_survives_a_round_trip_through_disk(tmp_path):
    s = stack(0, 3000, 3500, base=-2500, names=["FOUNDATION", "GF", "1F"])
    s.repeat(2, times=2)
    path = s.save(tmp_path / "x.storeys.json")
    back = StoreySchedule.load(path)
    assert back.elevations() == s.elevations()
    assert [x.name for x in back.storeys] == [x.name for x in s.storeys]
    assert back.next_id == s.next_id
    assert back.schema_version == STOREY_SCHEMA_VERSION


def test_saving_creates_the_folder_it_is_asked_for(tmp_path):
    stack(0).save(tmp_path / "deep" / "down" / "x.json")
    assert (tmp_path / "deep" / "down" / "x.json").exists()


# --------------------------------------------------------------- level rows

def test_level_rows_carry_the_elevation_the_plan_and_the_name():
    s = stack(0, 3000, 3000, base=-2500, names=["FOUNDATION", "GF", "1F"])
    rows = s.level_rows()
    assert [r.elevation for r in rows] == [-2500, 500, 3500]
    assert [r.floor_id for r in rows] == ["F00", "F01", "F02"]
    assert [r.revit_name for r in rows] == ["FOUNDATION", "GF", "1F"]
    assert [r.order for r in rows] == [0, 1, 2]


def test_level_rows_carry_the_floor_to_floor_up_to_the_next_storey():
    rows = stack(0, 3000, 4000).level_rows()
    assert [r.f2f for r in rows] == [3000, 4000, None]


def test_typical_floors_all_point_at_the_one_drawn_plan():
    s = stack(0, 3000, names=["GF", "1F"])
    s.repeat(1, times=3)
    rows = s.level_rows()
    assert [r.floor_id for r in rows] == ["F00", "F01", "F01", "F01", "F01"]
    assert [r.elevation for r in rows] == [0, 3000, 6000, 9000, 12000]


# ------------------------------------------------------------------ seeding

class _Floor:
    def __init__(self, fid, index, name, elevation=None):
        self.id, self.index, self.name, self.elevation_mm = fid, index, name, elevation


class _Hint:
    def __init__(self, name, elevation, text=""):
        self.name, self.elevation_mm, self.text = name, elevation, text or name


class _Project:
    def __init__(self, floors, hints=()):
        self.floors, self.level_hints = floors, list(hints)
        self.drawing = type("D", (), {"file": "job.dxf"})()


def test_seeding_from_a_drawing_that_carries_elevations_uses_them():
    p = _Project([_Floor("L01", 1, "GROUND FLOOR", 0.0), _Floor("L02", 2, "FIRST FLOOR", 3300.0)])
    s = from_project(p)
    assert s.elevations() == [0, 3300]
    assert [x.source for x in s.storeys] == ["cad", "cad"]
    assert s.storeys[1].height_mm == 3300


def test_seeding_orders_the_stack_by_elevation_not_by_the_sheet_layout():
    p = _Project([_Floor("L01", 1, "ROOF", 9000.0), _Floor("L02", 2, "GROUND", 0.0),
                  _Floor("L03", 3, "FIRST", 3000.0)])
    s = from_project(p)
    assert [x.name for x in s.storeys] == ["GROUND", "FIRST", "ROOF"]
    assert s.elevations() == [0, 3000, 9000]


def test_seeding_falls_back_to_a_level_text_when_the_floor_has_no_elevation():
    p = _Project([_Floor("L01", 1, "GROUND FLOOR"), _Floor("L02", 2, "FIRST FLOOR")],
                 hints=[_Hint("FIRST FLOOR", 3600.0, "FIRST FLOOR LVL. +3.600")])
    s = from_project(p)
    by_name = {x.name: x for x in s.storeys}
    assert by_name["FIRST FLOOR"].source == "hint"
    assert "please confirm" in by_name["FIRST FLOOR"].note


def test_seeding_a_drawing_that_says_nothing_still_gives_a_usable_stack():
    p = _Project([_Floor("L01", 1, "GROUND FLOOR"), _Floor("L02", 2, "FIRST FLOOR"),
                  _Floor("L03", 3, "ROOF")])
    s = from_project(p)
    assert s.elevations() == [0, DEFAULT_HEIGHT_MM, 2 * DEFAULT_HEIGHT_MM]
    assert all("assumed" in x.note for x in s.storeys)
    assert s.ok()                        # a stack you can run with, and correct on the way out


def test_seeding_honours_a_house_storey_height():
    p = _Project([_Floor("L01", 1, "GF"), _Floor("L02", 2, "1F")])
    assert from_project(p, default_height_mm=3300).elevations() == [0, 3300]


def test_seeding_an_empty_drawing_gives_an_empty_schedule():
    s = from_project(_Project([]))
    assert len(s) == 0 and not s.ok()


def test_seeding_keeps_the_drawings_own_order_for_floors_it_knows_nothing_about():
    p = _Project([_Floor("L01", 1, "GF", 0.0), _Floor("L02", 2, "MYSTERY"), _Floor("L03", 3, "ROOF", 6000.0)])
    s = from_project(p)
    assert [x.name for x in s.storeys] == ["GF", "ROOF", "MYSTERY"]


# ------------------------------------------- an existing workbook still opens

class _Row:
    def __init__(self, floor_id, name, order, elevation, f2f=None, revit_name=None):
        self.floor_id, self.name, self.order = floor_id, name, order
        self.elevation, self.f2f, self.revit_name = elevation, f2f, revit_name


def test_a_filled_level_workbook_opens_as_a_stack_of_storeys():
    rows = [_Row("L02", "FIRST FLOOR", 2, 3300.0), _Row("L01", "GROUND FLOOR", 1, 0.0)]
    s = from_level_rows(rows, source_file="job.dxf")
    assert [x.name for x in s.storeys] == ["GROUND FLOOR", "FIRST FLOOR"]
    assert s.elevations() == [0, 3300]
    assert all(x.source == "levels" for x in s.storeys)


def test_rows_with_no_elevation_are_left_out_of_the_seeded_stack():
    rows = [_Row("L01", "GF", 1, 0.0), _Row("L02", "1F", 2, None)]
    assert len(from_level_rows(rows)) == 1


def test_an_unfilled_workbook_gives_an_empty_schedule():
    assert len(from_level_rows([_Row("L01", "GF", 1, None)])) == 0


def test_a_workbook_revit_name_wins_over_the_floor_name():
    rows = [_Row("L01", "GROUND FLOOR PLAN", 1, 0.0, revit_name="00 GF")]
    assert from_level_rows(rows).storeys[0].name == "00 GF"


# ------------------------------------------------------------------ the type

def test_a_storey_says_where_it_came_from_in_words():
    assert Storey(id="S01", name="GF", source="repeat").source_words == "a repeat of the plan below"


# ------------------------------------------------------- names a drawing uses

@pytest.mark.parametrize("n, suffix", [
    (1, "st"), (2, "nd"), (3, "rd"), (4, "th"), (10, "th"),
    (11, "th"), (12, "th"), (13, "th"),          # the teens are the exception
    (21, "st"), (22, "nd"), (23, "rd"), (101, "st"), (111, "th"),
])
def test_an_ordinal_takes_the_suffix_english_gives_it(n, suffix):
    from c2b.storeys import _ordinal_suffix
    assert _ordinal_suffix(n) == suffix


def test_repeating_an_ordinal_floor_name_keeps_it_grammatical():
    """A real drawing names its floors "1st", "2nd", "3rd" - and "4rd Floor" reaches a client."""
    s = stack(0, names=["3rd Floor Level"])
    s.repeat(0, times=10)
    assert [x.name for x in s.storeys][:4] == [
        "3rd Floor Level", "4th Floor Level", "5th Floor Level", "6th Floor Level"]
    assert "11th Floor Level" in {x.name for x in s.storeys}


def test_a_name_in_capitals_is_repeated_in_capitals():
    s = stack(0, names=["1ST FLOOR"])
    s.repeat(0, times=2)
    assert [x.name for x in s.storeys] == ["1ST FLOOR", "2ND FLOOR", "3RD FLOOR"]


def test_a_number_that_is_not_an_ordinal_keeps_whatever_follows_it():
    s = stack(0, names=["LEVEL 01 (PODIUM)"])
    s.repeat(0, times=1)
    assert s.storeys[1].name == "LEVEL 02 (PODIUM)"
