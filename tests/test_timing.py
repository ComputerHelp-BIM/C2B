"""How long a run took, and where the time went."""
from __future__ import annotations

import pytest

from c2b.ui.timing import Stopwatch, human


@pytest.mark.parametrize("seconds, said", [
    (0, "0.0s"), (0.04, "0.0s"), (8.25, "8.2s"), (12.0, "12.0s"), (59.9, "59.9s"),
    (60, "1m 00s"), (95, "1m 35s"), (3599, "59m 59s"), (3600, "1h 00m"), (7830, "2h 10m"),
])
def test_a_duration_is_said_the_way_a_person_says_it(seconds, said):
    assert human(seconds) == said


def test_a_negative_duration_is_not_a_thing():
    assert human(-5) == "0.0s"


def stopwatch(*phases):
    w = Stopwatch()
    for name, seconds, waiting in phases:
        w.mark(name, seconds, waiting)
    return w


def test_the_build_figure_is_the_tools_own_time():
    """The one number the tool can fairly be judged on."""
    w = stopwatch(("reading", 4.0, False), ("the storey window", 40.0, True), ("Revit plan", 6.0, False))
    assert w.build_seconds() == 10.0
    assert w.waiting_seconds() == 40.0


def test_a_person_reading_a_dialog_is_not_counted_against_the_tool():
    w = stopwatch(("reading", 10.0, False), ("the storey window", 300.0, True))
    assert w.report()["elapsed"] == "10.0s"
    assert w.report()["waiting"] == "5m 00s"


def test_from_the_click_is_never_less_than_the_parts_add_up_to():
    w = stopwatch(("reading", 30.0, False), ("a window", 90.0, True))
    assert w.total_seconds() >= 120.0


def test_a_stretch_nobody_named_is_still_time_that_passed():
    """The total is a wall clock, not a sum: an unnamed phase must not vanish from it."""
    w = Stopwatch()
    w.started -= 50.0
    w.mark("reading", 1.0)
    assert w.total_seconds() >= 50.0


def test_a_phase_is_timed_by_starting_and_stopping_it():
    w = Stopwatch()
    w.start("reading")
    w.stop()
    assert len(w.phases) == 1 and w.phases[0].name == "reading"
    assert w.phases[0].seconds >= 0


def test_starting_a_phase_closes_the_one_that_was_running():
    w = Stopwatch()
    w.start("one")
    w.start("two")
    w.stop()
    assert [p.name for p in w.phases] == ["one", "two"]


def test_stopping_twice_does_not_record_twice():
    w = Stopwatch()
    w.start("one")
    w.stop()
    w.stop()
    assert len(w.phases) == 1


def test_a_waiting_phase_stays_out_of_the_build_figure_when_it_is_timed_live():
    w = Stopwatch()
    w.start("a window", waiting=True)
    w.stop()
    assert w.build_seconds() == 0.0


# ------------------------------------------------------------- the breakdown

def test_the_breakdown_names_the_phases_slowest_first():
    w = stopwatch(("reading", 4.0, False), ("normalising", 10.0, False), ("Revit plan", 6.0, False))
    assert w.breakdown().startswith("normalising 10.0s")
    assert w.breakdown().index("Revit plan") < w.breakdown().index("reading")


def test_a_phase_that_is_noise_is_left_out_of_the_breakdown():
    """A line about where the time went should not be longer than the figure above it."""
    w = stopwatch(("reading", 100.0, False), ("a rounding error", 0.2, False))
    assert "rounding error" not in w.breakdown()
    assert "reading" in w.breakdown()


def test_the_breakdown_never_names_the_time_a_person_spent():
    w = stopwatch(("reading", 4.0, False), ("the storey window", 400.0, True))
    assert "storey window" not in w.breakdown()


def test_the_breakdown_is_capped_so_it_stays_one_line():
    w = stopwatch(*[(f"step {n}", 10.0, False) for n in range(20)])
    assert w.breakdown().count("step") == 6


def test_an_empty_run_reports_zeroes_rather_than_failing():
    report = Stopwatch().report()
    assert report["elapsed"] == "0.0s" and report["breakdown"] == "" and report["slowest"] == ""


def test_the_report_carries_every_line_the_window_shows():
    w = stopwatch(("normalising", 10.0, False), ("a window", 20.0, True))
    report = w.report(headline="Model built", caption="building the model")
    assert report["headline"] == "Model built"
    assert report["caption"] == "building the model"
    assert set(report) == {"headline", "caption", "elapsed", "waiting", "total",
                           "breakdown", "slowest"}
    assert report["slowest"] == "normalising"
