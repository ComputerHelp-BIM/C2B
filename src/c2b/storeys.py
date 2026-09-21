"""The storey schedule: what floors the building has, how tall they are and where they sit.

A plan tells us how many floor layouts were drawn and what is on each. It cannot tell us how
far apart they are -- that lives in a section, a level schedule or the engineer's head. This
module is where that answer is held, edited and kept.

**Heights drive; elevations follow.** Every storey carries ``height_mm``, the rise from the
storey *below* it, which is the convention every structural engineer already uses (ETABS story
data, a level schedule, a section). The lowest storey has nothing below it, so its height is
not used and the schedule's ``base_elevation_mm`` places it. Every elevation above is then
arithmetic, so a stack can never drift out of step with itself:

    elevation[0] = base_elevation_mm
    elevation[i] = elevation[i - 1] + height[i]

A drafter who prefers to type elevations still can -- :meth:`StoreySchedule.set_elevation`
turns one into the height that produces it and leaves the storeys above where they are.

**One CAD plan can serve several storeys.** That is a typical floor: the drawing has one
layout, the building has eight of them. A storey therefore carries a ``repeat`` count, and one
*row* of the schedule builds that many levels -- which is how a drawing says it in the first
place ("TYPICAL FLOOR PLAN (2ND TO 8TH FLOOR)") and how the firm's other tools show it.
:meth:`StoreySchedule.expanded` is where a row becomes the levels it stands for; everything
downstream -- ``levels.xlsx``, the Revit plan -- reads the expansion, never the rows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:            # pragma: no cover - typing only
    from .schema import Project

#: Version of the storey schedule sidecar. Bumped when a stored field changes meaning, so an
#: old ``.storeys.json`` is never read as though it said something it did not.
STOREY_SCHEMA_VERSION = "1.0.0"

#: What a storey is worth when nothing in the drawing says. A residential floor-to-floor.
DEFAULT_HEIGHT_MM = 3000.0

#: Two levels closer than this are the same level as far as Revit is concerned, and a column
#: between them has no height to be built with.
MIN_HEIGHT_MM = 1.0

StoreySource = Literal["cad", "hint", "levels", "added", "repeat"]


def s_repeat(storey) -> int:
    """A storey's repeat count, tolerating a sidecar written before the field existed."""
    return int(getattr(storey, "repeat", 1) or 1)


def _count_on(name: str, k: int, taken: set[str]) -> str:
    """The k-th name after ``name``, counting on the way a repeat always has."""
    out = name
    for _ in range(k):
        out = _next_name(out)
    while out.strip().upper() in taken:
        out = _next_name(out)
    return out


def _next_name(like: str) -> str:
    """The name one after this one: "3rd Floor" -> "4th Floor", "LEVEL 01" -> "LEVEL 02"."""
    match = re.search(r"^(.*?)(\d+)(\D*)$", like.strip())
    if not match:
        return f"{like.strip()} 2" if not like.strip().endswith(" 2") else f"{like.strip()[:-2]}3"
    head, number, tail = match.group(1), int(match.group(2)), match.group(3)
    width = len(match.group(2))
    ordinal = re.match(r"(st|nd|rd|th)\b", tail, re.I)
    if ordinal:
        suffix = _ordinal_suffix(number + 1)
        tail = (suffix.upper() if ordinal.group(1).isupper() else suffix) + tail[2:]
    return f"{head}{number + 1:0{width}d}{tail}"


def _ordinal_suffix(n: int) -> str:
    """``st``, ``nd``, ``rd`` or ``th`` for a whole number, English rules and the teens.

    A drawing names its floors "1st", "2nd", "3rd", "11th", so a storey repeated from one of
    them has to be named the same way -- "4rd Floor Level" is the sort of thing that ends up
    on a drawing issued to a client.
    """
    n = abs(int(n))
    if n % 100 in (11, 12, 13):
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")

#: Why each storey is in the schedule, in words a drafter can act on.
SOURCE_WORDS: dict[str, str] = {
    "cad": "a floor plan in the drawing",
    "hint": "a level text in the drawing",
    "levels": "the level workbook",
    "added": "added here",
    "repeat": "a repeat of the plan below",
}


class Storey(BaseModel):
    """One storey of the building: a Revit level, and what is built on it."""

    id: str                                  # stable for the life of the schedule; never reused
    name: str                                # what the drafter calls it; the Revit level is named from this
    height_mm: float = DEFAULT_HEIGHT_MM     # rise from the storey below. Not used by the lowest storey.
    #: How many levels this one row builds. A typical floor drawn once and repeated eight
    #: times is one row with repeat 8, not eight rows -- which is what the drawing says and
    #: what the firm's other tools show.
    repeat: int = 1
    plan_floor_id: str | None = None         # the CAD floor plan built on this storey, if any
    source: StoreySource = "added"
    note: str = ""

    @property
    def source_words(self) -> str:
        return SOURCE_WORDS.get(self.source, self.source)


class StoreyProblem(BaseModel):
    severity: Literal["ERROR", "WARNING"]
    storey_id: str | None
    message: str


class StoreySchedule(BaseModel):
    """The storeys of one building, lowest first."""

    schema_version: str = STOREY_SCHEMA_VERSION
    source_file: str = ""
    #: Elevation of the lowest storey. Everything else is this plus the heights above it.
    base_elevation_mm: float = 0.0
    default_height_mm: float = DEFAULT_HEIGHT_MM
    storeys: list[Storey] = Field(default_factory=list)
    next_id: int = 1                         # ids are handed out from here and never reused

    # ------------------------------------------------------------------ read
    def __len__(self) -> int:
        return len(self.storeys)

    def elevations(self) -> list[float]:
        """Elevation of the first level each row builds, lowest first. Derived, never stored.

        A row with a repeat of 8 occupies eight storeys' worth of height, so the row above it
        starts that much higher -- this is the elevation of the row, not of the top of it.
        """
        out: list[float] = []
        z = self.base_elevation_mm
        for i, s in enumerate(self.storeys):
            if i:
                z += s.height_mm + self.storeys[i - 1].height_mm * (max(s_repeat(self.storeys[i - 1]), 1) - 1)
            out.append(z)
        return out

    def expanded(self) -> list[tuple[str, float, str | None, str]]:
        """Every level the schedule builds: ``(name, elevation, plan floor id, storey id)``.

        A row's repeat becomes that many levels here, named by counting on from the row's own
        name the way a repeat always has. This is what ``levels.xlsx`` and the Revit plan are
        built from -- the rows are what a person edits, and this is what the building is.
        """
        out: list[tuple[str, float, str | None, str]] = []
        z = self.base_elevation_mm
        # Every row's own name is spoken for before a single repeat is counted out. A repeat of
        # "1F" three times would otherwise generate "3F" while a row further up is already
        # called that, and Revit will not hold two levels of one name.
        taken: set[str] = {x.name.strip().upper() for x in self.storeys}
        for i, storey in enumerate(self.storeys):
            if i:
                z += storey.height_mm
            for k in range(max(s_repeat(storey), 1)):
                if k:
                    z += storey.height_mm
                name = storey.name if k == 0 else _count_on(storey.name, k, taken)
                taken.add(name.strip().upper())
                out.append((name, z, storey.plan_floor_id, storey.id))
        return out

    def level_count(self) -> int:
        """How many Revit levels the schedule builds, repeats included."""
        return sum(max(s_repeat(x), 1) for x in self.storeys)

    def rows(self) -> list[dict]:
        """The schedule as plain rows, for a table in a window or a workbook.

        ``height_mm`` is blank on the lowest storey: there is nothing below it to rise from,
        and showing a number there invites a drafter to change one that does nothing.
        """
        elevs = self.elevations()
        top = len(self.storeys) - 1
        return [{"n": i, "id": s.id, "name": s.name,
                 "height_mm": None if i == 0 else s.height_mm,
                 "elevation_mm": elevs[i],
                 "repeat": max(s_repeat(s), 1),
                 "plan_floor_id": s.plan_floor_id,
                 "source": s.source, "source_words": s.source_words,
                 "note": s.note, "is_base": i == 0, "is_top": i == top}
                for i, s in enumerate(self.storeys)]

    def index_of(self, storey_id: str) -> int:
        for i, s in enumerate(self.storeys):
            if s.id == storey_id:
                return i
        raise KeyError(f"no storey {storey_id!r} in this schedule")

    def total_height_mm(self) -> float:
        """Lowest level to highest, repeats included."""
        levels = self.expanded()
        return (levels[-1][1] - levels[0][1]) if levels else 0.0

    # ----------------------------------------------------------------- write
    def _mint_id(self) -> str:
        sid = f"S{self.next_id:02d}"
        self.next_id += 1
        return sid

    def add(self, index: int | None = None, name: str | None = None,
            height_mm: float | None = None, plan_floor_id: str | None = None,
            source: StoreySource = "added") -> Storey:
        """Insert a storey and make the building taller by its height.

        ``index`` is where it lands, 0 being the new lowest storey; the default is the top.
        Adding never squashes an existing storey: everything above the new one rises by its
        height, which is what "add a storey" means to anyone who has drawn one.
        """
        index = len(self.storeys) if index is None else max(0, min(int(index), len(self.storeys)))
        h = float(height_mm) if height_mm is not None else self.default_height_mm
        storey = Storey(id=self._mint_id(), name=name or self._free_name("LEVEL"),
                        height_mm=h, plan_floor_id=plan_floor_id, source=source)
        if index == 0 and self.storeys:
            # The new storey takes the datum and the old lowest one rises off it, so the whole
            # stack above moves up by h rather than the new storey landing on top of it.
            self.storeys[0].height_mm = h
        self.storeys.insert(index, storey)
        return storey

    def remove(self, index: int) -> Storey:
        """Delete a storey.

        Deleting one from inside the stack makes the building shorter: everything above comes
        down by its height. Deleting the *lowest* storey instead leaves every other storey
        exactly where it is -- a drafter removing a foundation level does not expect the ground
        floor to follow it down.
        """
        self._check_index(index)
        if index == 0 and len(self.storeys) > 1:
            self.base_elevation_mm += self.storeys[1].height_mm
        return self.storeys.pop(index)

    def move(self, index: int, delta: int) -> int:
        """Move a storey up (+1) or down (-1) in the stack, carrying its height with it.

        Returns the index it ended at, which is the one it started at when it could not move.
        """
        self._check_index(index)
        target = index + int(delta)
        if not 0 <= target < len(self.storeys):
            return index
        storey = self.storeys.pop(index)
        self.storeys.insert(target, storey)
        return target

    def repeat(self, index: int, times: int = 1) -> list[Storey]:
        """Stack ``times`` more storeys like this one on top of it -- the typical floor.

        Each copy keeps the original's height and its CAD plan, so one drawn layout builds
        every one of them. The names are taken from the original by counting on from whatever
        number it ends with.
        """
        self._check_index(index)
        times = max(0, int(times))
        original = self.storeys[index]
        made: list[Storey] = []
        for k in range(times):
            copy = Storey(id=self._mint_id(), name=self._free_name(original.name),
                          height_mm=original.height_mm, plan_floor_id=original.plan_floor_id,
                          source="repeat", note=f"repeat of {original.name}")
            self.storeys.insert(index + 1 + k, copy)
            made.append(copy)
        return made

    def rename(self, index: int, name: str) -> None:
        self._check_index(index)
        self.storeys[index].name = name.strip() or self.storeys[index].name

    def set_height(self, index: int, height_mm: float) -> None:
        """Set a storey's rise from the one below. Everything above it moves with it."""
        self._check_index(index)
        self.storeys[index].height_mm = float(height_mm)

    def set_elevation(self, index: int, elevation_mm: float) -> None:
        """Put a storey at an elevation, keeping the storeys above the same distance away.

        On the lowest storey this moves the whole building; anywhere else it is the height
        below that changes, which is the only one that can put a storey where it was asked for
        without disturbing what is under it.

        A storey rises from the **top** of the row below it, which is not the same thing as
        that row's elevation when the row repeats: a typical floor built five times occupies
        four more storey heights than its own elevation admits to.
        """
        self._check_index(index)
        if index == 0:
            self.base_elevation_mm = float(elevation_mm)
            return
        below = self.storeys[index - 1]
        top_of_below = (self.elevations()[index - 1]
                        + below.height_mm * (max(s_repeat(below), 1) - 1))
        self.storeys[index].height_mm = float(elevation_mm) - top_of_below

    def duplicate(self, index: int) -> Storey:
        """Copy a storey and put the copy directly above it.

        Everything above rises by the copy's height, which is what happens when a floor is
        built twice. The copy carries the original's height, plan, repeat and note -- the
        point of it is a storey that is the same as the one below -- and takes the next free
        name in the original's own style, because Revit will not hold two levels of one name.
        """
        self._check_index(index)
        original = self.storeys[index]
        copy = Storey(id=self._mint_id(), name=self._free_name(original.name),
                      height_mm=original.height_mm, repeat=max(s_repeat(original), 1),
                      plan_floor_id=original.plan_floor_id, source="added",
                      note=original.note)
        self.storeys.insert(index + 1, copy)
        return copy

    def set_repeat(self, index: int, times: int) -> None:
        """How many levels this row builds. One is an ordinary storey."""
        self._check_index(index)
        self.storeys[index].repeat = max(1, int(times))

    def set_plan(self, index: int, plan_floor_id: str | None) -> None:
        """Say which drawn floor plan is built on this storey."""
        self._check_index(index)
        self.storeys[index].plan_floor_id = plan_floor_id or None

    def sort_by_elevation(self) -> None:
        """Order the stack lowest first, which is the only order the heights describe.

        Elevations are already monotonic by construction, so this only matters after a
        :meth:`move` that put a storey somewhere its height makes no sense; it re-derives the
        heights from the elevations the stack had before the sort.
        """
        elevs = self.elevations()
        paired = sorted(zip(elevs, range(len(self.storeys)), self.storeys), key=lambda t: (t[0], t[1]))
        self.base_elevation_mm = paired[0][0] if paired else self.base_elevation_mm
        self.storeys = [s for _, _, s in paired]
        for i in range(1, len(self.storeys)):
            self.storeys[i].height_mm = paired[i][0] - paired[i - 1][0]

    def _check_index(self, index: int) -> None:
        if not 0 <= index < len(self.storeys):
            raise IndexError(f"storey {index} is not in a schedule of {len(self.storeys)}")

    def _free_name(self, like: str) -> str:
        """A name in the style of ``like`` that nothing else in the schedule is using.

        ``like`` itself when it is free -- the first storey a drafter adds is "LEVEL", not
        "LEVEL 2". A repeat always counts on, because the name it is given is the name of the
        storey being repeated and is therefore always taken.
        """
        taken = {s.name.strip().upper() for s in self.storeys}
        if like.strip() and like.strip().upper() not in taken:
            return like.strip()
        match = re.search(r"^(.*?)(\d+)(\D*)$", like.strip())
        if match:
            head, number, tail = match.group(1), int(match.group(2)), match.group(3)
            width = len(match.group(2))
            # An English ordinal suffix belongs to the number, not to the text after it, so
            # repeating "3rd Floor Level" gives "4th Floor Level" and not "4rd Floor Level".
            ordinal = re.match(r"(st|nd|rd|th)\b", tail, re.I)
            for n in range(number + 1, number + 500):
                ending = tail
                if ordinal:
                    suffix = _ordinal_suffix(n)
                    ending = (suffix.upper() if ordinal.group(1).isupper() else suffix) + tail[2:]
                candidate = f"{head}{n:0{width}d}{ending}"
                if candidate.upper() not in taken:
                    return candidate
        base = like.strip() or "LEVEL"
        for n in range(2, 500):
            candidate = f"{base} {n}"
            if candidate.upper() not in taken:
                return candidate
        return f"{base} {len(self.storeys) + 1}"          # pragma: no cover - 500 of one name

    # ------------------------------------------------------------- reporting
    def problems(self, plan_floor_ids: list[str] | None = None) -> list[StoreyProblem]:
        """Everything about this schedule that would go wrong later, said now.

        ``plan_floor_ids`` is the floors the drawing actually has; pass it and a plan nobody
        builds is reported here rather than discovered as missing elements in Revit.
        """
        out: list[StoreyProblem] = []
        if not self.storeys:
            out.append(StoreyProblem(severity="ERROR", storey_id=None,
                                     message="The building has no storeys, so there is nothing to build in Revit."))
            return out

        seen: dict[str, str] = {}
        for s in self.storeys:
            key = s.name.strip().upper()
            if not key:
                out.append(StoreyProblem(severity="ERROR", storey_id=s.id, message="A storey has no name."))
            elif key in seen:
                out.append(StoreyProblem(severity="ERROR", storey_id=s.id,
                                         message=f"Two storeys are called '{s.name}'. Revit will not hold two levels "
                                                 f"of one name, so one of them would be lost - rename it."))
            else:
                seen[key] = s.id

        for i, s in enumerate(self.storeys[1:], start=1):
            if s.height_mm < MIN_HEIGHT_MM:
                below = self.storeys[i - 1].name
                out.append(StoreyProblem(
                    severity="ERROR", storey_id=s.id,
                    message=f"'{s.name}' is {s.height_mm:.0f} mm above '{below}'. Two levels at the same height "
                            f"leave the columns between them nothing to be built with."))

        for s in self.storeys:
            if not s.plan_floor_id:
                out.append(StoreyProblem(severity="WARNING", storey_id=s.id,
                                         message=f"Nothing is drawn for '{s.name}', so it is created as a level "
                                                 f"with no columns, beams or slab on it."))

        if plan_floor_ids is not None:
            built = {s.plan_floor_id for s in self.storeys if s.plan_floor_id}
            for fid in plan_floor_ids:
                if fid not in built:
                    out.append(StoreyProblem(severity="WARNING", storey_id=None,
                                             message=f"Floor plan {fid} is drawn but no storey is built from it, "
                                                     f"so everything on it is left out of the model."))
        return out

    def ok(self, plan_floor_ids: list[str] | None = None) -> bool:
        return not any(p.severity == "ERROR" for p in self.problems(plan_floor_ids))

    # ----------------------------------------------------------- persistence
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> StoreySchedule:
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    def level_rows(self):
        """The schedule as the level rows the normaliser takes.

        The storey name is handed over as the *Revit* name so the drafter's wording survives
        the trip; the template spec still numbers it, which is the firm's convention.
        """
        from .normalize.pipeline import LevelRow

        levels = self.expanded()
        rows = []
        for i, (name, elevation, plan_floor_id, _sid) in enumerate(levels):
            nxt = (levels[i + 1][1] - elevation) if i + 1 < len(levels) else None
            rows.append(LevelRow(plan_floor_id, name, i, elevation, nxt, name))
        return rows


# ---------------------------------------------------------------------------
# Seeding a schedule from what we already know
# ---------------------------------------------------------------------------

def from_project(project: Project, default_height_mm: float = DEFAULT_HEIGHT_MM) -> StoreySchedule:
    """A first schedule from the drawing: one storey per floor plan, lowest first.

    A drafter should open the storey window on a stack that is already nearly right rather than
    on an empty table. Elevations come from the floor if the drawing carried one, then from a
    level text matched to the floor's name, and only then from a default height -- and every
    storey says which of the three it was, so what still needs checking is visible.
    """
    from .export.levels import match_level_hint

    floors = sorted(project.floors, key=lambda f: f.index)
    #: (elevation or None, where it came from) per floor, in the drawing's own order.
    known: list[tuple[float | None, str]] = []
    for f in floors:
        if f.elevation_mm is not None:
            known.append((float(f.elevation_mm), "cad"))
            continue
        hit = match_level_hint(f.name, project.level_hints) if project.level_hints else None
        known.append((float(hit[0]), "hint") if hit else (None, ""))

    # Order by elevation where we have one; floors we know nothing about keep the drawing's own
    # order, which for a sheet laid out left to right is usually the order they are stacked in.
    order = sorted(range(len(floors)),
                   key=lambda i: (known[i][0] is None, known[i][0] if known[i][0] is not None else 0.0, i))

    schedule = StoreySchedule(source_file=project.drawing.file, default_height_mm=default_height_mm)
    placed = [known[i][0] for i in order if known[i][0] is not None]
    schedule.base_elevation_mm = placed[0] if placed else 0.0

    previous: float | None = None
    for floor, (elevation, from_where) in ((floors[i], known[i]) for i in order):
        if elevation is None:
            elevation = (previous + default_height_mm) if previous is not None else schedule.base_elevation_mm
            note = "height assumed - please check"
        elif from_where == "hint":
            note = "from a level text in the drawing - please confirm"
        else:
            note = ""
        schedule.storeys.append(Storey(
            id=schedule._mint_id(), name=floor.name.strip() or floor.id,
            height_mm=default_height_mm if previous is None else max(elevation - previous, 0.0),
            plan_floor_id=floor.id, source="hint" if from_where == "hint" else "cad", note=note))
        previous = elevation
    return schedule


def from_level_rows(rows, source_file: str = "", default_height_mm: float = DEFAULT_HEIGHT_MM) -> StoreySchedule:
    """A schedule from a level workbook that was filled in before the storey window existed.

    Nobody's earlier work is thrown away by this feature arriving: an existing ``levels.xlsx``
    still opens as a stack of storeys, and from then on the window owns it.
    """
    usable = [r for r in rows if getattr(r, "elevation", None) is not None]
    usable.sort(key=lambda r: (float(r.elevation), r.order if r.order is not None else 0))
    schedule = StoreySchedule(source_file=source_file, default_height_mm=default_height_mm)
    if not usable:
        return schedule
    schedule.base_elevation_mm = float(usable[0].elevation)
    previous: float | None = None
    for r in usable:
        elev = float(r.elevation)
        name = (r.revit_name or r.name or r.floor_id or "LEVEL").strip()
        schedule.storeys.append(Storey(
            id=schedule._mint_id(), name=name,
            height_mm=default_height_mm if previous is None else elev - previous,
            plan_floor_id=r.floor_id, source="levels"))
        previous = elev
    return schedule
