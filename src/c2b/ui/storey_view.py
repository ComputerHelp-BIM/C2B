"""What the storey editor does, with nothing in it that knows about a toolkit.

The window is WPF and the fallback is Tkinter, and both of them do the same thing: show the
stack, take an edit, run a command, say what is wrong. That "same thing" lives here, so it is
tested on any machine rather than only on the one that can open a window -- and so the two
views cannot drift into behaving differently.

Two decisions are the presenter's and not the model's:

* **The stack is shown highest first**, the way a section is drawn and the way an engineer
  reads a level schedule. The model is ordered lowest first, because that is the direction the
  heights add up in. Everything crossing between them goes through :meth:`StoreyPresenter.at`,
  and every command names a **storey id** rather than a row number, so the reversal cannot
  become an off-by-one.
* **A typed value is kept even when it is wrong.** A number that will not parse leaves the
  field alone and says so; a number that parses but makes an impossible stack is applied and
  reported. The window never silently corrects what somebody typed.

Every command names the storey it acts on. An earlier version kept a "selected" storey and a
toolbar that acted on it, which reads well in a specification and badly in a window: what is
selected is invisible until you look for the focus ring, so "Repeat" is a button whose effect
you have to work out. A row that carries its own buttons has no such question in it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..storeys import MIN_HEIGHT_MM, StoreySchedule

#: A trailing unit, so a grouped number can be checked without it.
_UNIT = re.compile(r"(?:mm|MM|Mm|m|M)$")
#: A number whose commas are all thousands separators.
_GROUPED = re.compile(r"[+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?")

#: What a plan floor is called in the "Built from" column when a storey has none.
NO_PLAN = "(nothing drawn)"

#: A storey's provenance in one word, for a narrow column. The whole sentence goes in the
#: tooltip: seven rows each reading "a floor plan in the drawing; height assumed - please
#: check" is a wall of identical text that hides the one row that says something different.
SHORT_SOURCE: dict[str, str] = {
    "cad": "drawn", "hint": "level text", "levels": "workbook",
    "added": "added", "repeat": "repeat",
}


@dataclass
class DisplayRow:
    """One line of the table, as the window should show it."""

    storey_id: str
    number: int                 # the storey's own number, lowest = 0, shown as drawn
    name: str
    height_text: str            # blank on the lowest storey: nothing below it to rise from
    elevation_text: str
    plan_label: str
    source_words: str
    note: str
    is_base: bool
    is_top: bool
    severity: str = ""          # "ERROR" | "WARNING" | "" -- what to mark this row with
    flag: str = ""              # the one word the narrow column shows
    tooltip: str = ""           # the whole of it, for hovering over that word
    repeat: int = 1             # how many levels this one row builds
    build: bool = True          # ticked = built; unticked leaves the storey out


@dataclass
class StoreyPresenter:
    """The storey editor's state and every command it offers."""

    schedule: StoreySchedule
    plan_floors: list[tuple[str, str]] = field(default_factory=list)   # (floor_id, name)
    #: Storeys the drafter unticked. They stay in the table -- a storey you removed by mistake
    #: should be one tick away from coming back, not a row you have to build again -- and they
    #: are left out of everything downstream.
    dropped: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ read
    def at(self, storey_id: str) -> int:
        """The model index of a storey. The one place a row and an index meet."""
        return self.schedule.index_of(storey_id)

    def plan_label(self, floor_id: str | None) -> str:
        if not floor_id:
            return NO_PLAN
        name = dict(self.plan_floors).get(floor_id)
        return f"{floor_id}  {name}" if name else floor_id

    def plan_choices(self) -> list[tuple[str, str | None]]:
        """Every option for the "Built from" column, the empty one first."""
        return [(NO_PLAN, None)] + [(self.plan_label(fid), fid) for fid, _ in self.plan_floors]

    def rows(self) -> list[DisplayRow]:
        """The table, highest storey first."""
        worst = self.worst_by_storey()
        out = [DisplayRow(storey_id=r["id"], number=r["n"], name=r["name"],
                          height_text="" if r["is_base"] else format_mm(r["height_mm"]),
                          elevation_text=format_mm(r["elevation_mm"]),
                          plan_label=self.plan_label(r["plan_floor_id"]),
                          source_words=r["source_words"], note=r["note"],
                          is_base=r["is_base"], is_top=r["is_top"],
                          severity=worst.get(r["id"], ""),
                          flag=short_flag(r["source"], r["note"], worst.get(r["id"], "")),
                          tooltip="; ".join(x for x in (r["source_words"], r["note"]) if x),
                          repeat=r["repeat"], build=r["id"] not in self.dropped)
               for r in self.schedule.rows()]
        out.reverse()
        return out

    def worst_by_storey(self) -> dict[str, str]:
        """The most serious thing said about each storey, for marking its row."""
        worst: dict[str, str] = {}
        for p in self.built_schedule().problems(self.plan_floor_ids()):
            if p.storey_id and worst.get(p.storey_id) != "ERROR":
                worst[p.storey_id] = p.severity
        return worst

    def plan_floor_ids(self) -> list[str]:
        return [fid for fid, _ in self.plan_floors]

    def problem_lines(self) -> list[tuple[str, str]]:
        """Everything wrong with the stack, worst first, as (severity, message)."""
        problems = self.built_schedule().problems(self.plan_floor_ids())
        order = {"ERROR": 0, "WARNING": 1}
        problems.sort(key=lambda p: order.get(p.severity, 2))
        return [(p.severity, p.message) for p in problems]

    def status(self) -> tuple[str, str, str]:
        """(severity, badge word, status line) for the footer.

        The count and the outcome sit together, and the badge never carries the meaning on its
        own -- the line beside it says the same thing in words.
        """
        kept = self.built_schedule()
        problems = kept.problems(self.plan_floor_ids())
        errors = sum(1 for p in problems if p.severity == "ERROR")
        warnings = len(problems) - errors
        n = kept.level_count()
        stack = f"{n} {'level' if n == 1 else 'levels'}, {format_mm(kept.total_height_mm())} mm overall"
        if self.dropped:
            stack += f", {len(self.dropped)} left out"
        if errors:
            return "ERROR", "ERROR", f"{stack}. {errors} to fix before this can be built."
        if warnings:
            return "WARNING", "WARNING", f"{stack}. {warnings} worth a look."
        return "SUCCESS", "READY", f"{stack}. Nothing to flag."

    def can_save(self) -> bool:
        """A stack with an error is not saved: it would fail in Revit instead, an hour later."""
        return self.built_schedule().ok(self.plan_floor_ids())

    # ----------------------------------------------------------------- edits
    def set_name(self, storey_id: str, text: str) -> str:
        self.schedule.rename(self.at(storey_id), text)
        return ""

    def set_height(self, storey_id: str, text: str) -> str:
        index = self.at(storey_id)
        if index == 0:
            return ""                       # the lowest storey rises from nothing
        value = parse_mm(text)
        if value is None:
            return f"'{text.strip()}' is not a height in millimetres."
        self.schedule.set_height(index, value)
        return ""

    def set_elevation(self, storey_id: str, text: str) -> str:
        value = parse_mm(text)
        if value is None:
            return f"'{text.strip()}' is not an elevation in millimetres."
        self.schedule.set_elevation(self.at(storey_id), value)
        return ""

    def set_plan(self, storey_id: str, floor_id: str | None) -> str:
        self.schedule.set_plan(self.at(storey_id), floor_id)
        return ""

    def set_plan_label(self, storey_id: str, label: str) -> str:
        """Set the plan from the label a dropdown shows, which is what a bound combo gives."""
        return self.set_plan(storey_id, dict(self.plan_choices()).get(label))

    def set_repeat(self, storey_id: str, text) -> str:
        """How many levels this one row builds. A typical floor drawn once, built eight times."""
        times = parse_mm(text if isinstance(text, str) else str(text))
        if times is None or times < 1:
            return f"'{str(text).strip()}' is not a number of storeys."
        self.schedule.set_repeat(self.at(storey_id), int(times))
        return ""

    def set_build(self, storey_id: str, build: bool) -> str:
        """Tick or untick a storey. An unticked one stays in the table and out of the model."""
        self.at(storey_id)                       # a storey that is not there is a bug, not a no-op
        if build:
            self.dropped.discard(storey_id)
        else:
            self.dropped.add(storey_id)
        return ""

    def built_schedule(self) -> StoreySchedule:
        """The schedule with the unticked storeys left out -- what is actually saved."""
        kept = self.schedule.model_copy(deep=True)
        kept.storeys = [x for x in kept.storeys if x.id not in self.dropped]
        return kept

    def set_default_height(self, text: str) -> str:
        value = parse_mm(text)
        if value is None or value < MIN_HEIGHT_MM:
            return f"'{text.strip()}' is not a storey height in millimetres."
        self.schedule.default_height_mm = value
        return ""

    # -------------------------------------------------------------- commands
    def add_above(self, storey_id: str | None = None) -> str:
        """A storey above the one named, or on top of the stack when none is."""
        index = (self.at(storey_id) + 1) if storey_id else len(self.schedule)
        self.schedule.add(index=index)
        return ""

    def add_below(self, storey_id: str | None = None) -> str:
        """A storey under the one named -- how a foundation gets under a ground floor."""
        index = self.at(storey_id) if storey_id else 0
        self.schedule.add(index=index)
        return ""

    def remove(self, storey_id: str) -> str:
        self.schedule.remove(self.at(storey_id))
        return ""

    def move(self, storey_id: str, delta: int) -> str:
        """Move a storey up (+1) or down (-1) the stack."""
        self.schedule.move(self.at(storey_id), delta)
        return ""

    def repeat(self, storey_id: str, times_text: str = "1") -> str:
        """Stack more storeys like this one -- the typical floor, drawn once."""
        times = parse_mm(times_text)
        if times is None or times < 1:
            return f"'{times_text.strip()}' is not a number of storeys."
        self.schedule.repeat(self.at(storey_id), times=int(times))
        return ""

# ---------------------------------------------------------------------------
# Numbers, as a drafter types them
# ---------------------------------------------------------------------------

def short_flag(source: str, note: str, severity: str = "") -> str:
    """One word for the narrow column: what most needs looking at about this storey.

    A problem outranks provenance -- a row that Revit will refuse should not be labelled
    "drawn" -- and an assumed height outranks the plan it came from, because the plan is the
    ordinary case and the assumption is the thing to check.
    """
    if severity == "ERROR":
        return "fix this"
    if "assumed" in note.lower():
        return "assumed"
    if severity == "WARNING":
        return "check"
    return SHORT_SOURCE.get(source, source)


def parse_mm(text: str | None) -> float | None:
    """A typed length in millimetres, or ``None`` when it is not one.

    A drafter types what is on the drawing, and what is on the drawing is ``3,300`` or
    ``+3.300 m`` or ``-2500``. All of those are a number; ``3m`` is metres and says so, and a
    bare decimal under 100 is almost certainly metres too -- but guessing that is how a storey
    silently ends up 3 mm tall, so it is refused rather than interpreted.
    """
    if text is None:
        return None
    cleaned = str(text).strip().replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned:
        # A comma is a thousands separator or it is a typo. Stripping every comma would read
        # "3,,0" as 30 -- a 30 mm storey, from a slip of a finger, with nothing said about it.
        body = _UNIT.sub("", cleaned)
        if not _GROUPED.fullmatch(body):
            return None
        cleaned = cleaned.replace(",", "")
    metres = False
    for suffix in ("mm", "MM", "Mm"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    else:
        for suffix in ("m", "M"):
            if cleaned.endswith(suffix):
                cleaned, metres = cleaned[: -len(suffix)], True
                break
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value * 1000.0 if metres else value


def format_mm(value: float | None) -> str:
    """A length as a drafter reads it: whole millimetres, and no trailing noise."""
    if value is None:
        return ""
    return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"
