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


@dataclass
class StoreyPresenter:
    """The storey editor's state and every command it offers."""

    schedule: StoreySchedule
    plan_floors: list[tuple[str, str]] = field(default_factory=list)   # (floor_id, name)
    selected_id: str | None = None

    # ------------------------------------------------------------------ read
    def __post_init__(self) -> None:
        if self.selected_id is None and self.schedule.storeys:
            self.selected_id = self.schedule.storeys[-1].id

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
                          severity=worst.get(r["id"], ""))
               for r in self.schedule.rows()]
        out.reverse()
        return out

    def worst_by_storey(self) -> dict[str, str]:
        """The most serious thing said about each storey, for marking its row."""
        worst: dict[str, str] = {}
        for p in self.schedule.problems(self.plan_floor_ids()):
            if p.storey_id and worst.get(p.storey_id) != "ERROR":
                worst[p.storey_id] = p.severity
        return worst

    def plan_floor_ids(self) -> list[str]:
        return [fid for fid, _ in self.plan_floors]

    def problem_lines(self) -> list[tuple[str, str]]:
        """Everything wrong with the stack, worst first, as (severity, message)."""
        problems = self.schedule.problems(self.plan_floor_ids())
        order = {"ERROR": 0, "WARNING": 1}
        problems.sort(key=lambda p: order.get(p.severity, 2))
        return [(p.severity, p.message) for p in problems]

    def status(self) -> tuple[str, str, str]:
        """(severity, badge word, status line) for the footer.

        The count and the outcome sit together, and the badge never carries the meaning on its
        own -- the line beside it says the same thing in words.
        """
        problems = self.schedule.problems(self.plan_floor_ids())
        errors = sum(1 for p in problems if p.severity == "ERROR")
        warnings = len(problems) - errors
        n = len(self.schedule)
        stack = f"{n} {'storey' if n == 1 else 'storeys'}, {format_mm(self.schedule.total_height_mm())} mm overall"
        if errors:
            return "ERROR", "ERROR", f"{stack}. {errors} to fix before this can be built."
        if warnings:
            return "WARNING", "WARNING", f"{stack}. {warnings} worth a look."
        return "SUCCESS", "READY", f"{stack}. Nothing to flag."

    def can_save(self) -> bool:
        """A stack with an error is not saved: it would fail in Revit instead, an hour later."""
        return self.schedule.ok(self.plan_floor_ids())

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

    def set_default_height(self, text: str) -> str:
        value = parse_mm(text)
        if value is None or value < MIN_HEIGHT_MM:
            return f"'{text.strip()}' is not a storey height in millimetres."
        self.schedule.default_height_mm = value
        return ""

    # -------------------------------------------------------------- commands
    def select(self, storey_id: str | None) -> None:
        self.selected_id = storey_id

    def add(self) -> str:
        """A storey above the selected one, or on top when nothing is selected."""
        index = (self.at(self.selected_id) + 1) if self.selected_id else len(self.schedule)
        storey = self.schedule.add(index=index)
        self.selected_id = storey.id
        return ""

    def add_below(self) -> str:
        """A storey under the selected one -- how a foundation gets under a ground floor."""
        index = self.at(self.selected_id) if self.selected_id else 0
        storey = self.schedule.add(index=index)
        self.selected_id = storey.id
        return ""

    def remove(self) -> str:
        if not self.selected_id:
            return "Pick a storey to remove."
        index = self.at(self.selected_id)
        self.schedule.remove(index)
        self.selected_id = (self.schedule.storeys[min(index, len(self.schedule) - 1)].id
                            if self.schedule.storeys else None)
        return ""

    def move(self, delta: int) -> str:
        """Move the selected storey up (+1) or down (-1) the stack."""
        if not self.selected_id:
            return "Pick a storey to move."
        self.schedule.move(self.at(self.selected_id), delta)
        return ""

    def repeat(self, times_text: str = "1") -> str:
        """Stack more storeys like the selected one -- the typical floor, drawn once."""
        if not self.selected_id:
            return "Pick the storey to repeat."
        times = parse_mm(times_text)
        if times is None or times < 1:
            return f"'{times_text.strip()}' is not a number of storeys."
        made = self.schedule.repeat(self.at(self.selected_id), times=int(times))
        if made:
            self.selected_id = made[-1].id
        return ""


# ---------------------------------------------------------------------------
# Numbers, as a drafter types them
# ---------------------------------------------------------------------------

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
