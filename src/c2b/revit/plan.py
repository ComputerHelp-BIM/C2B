"""Turn the normalised model into an ordered list of instructions for Revit.

Every decision (which level, which type, which offset, which loop is a hole) is made here,
where it can be tested. The Revit script only executes what this file produces, which keeps
the part that runs inside Revit small enough to review.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .. import __version__
from ..diagnostics import DiagnosticsCollector
from ..normalize.model import NormalizedProject
from ..schema import Diagnostic
from .mapping import REVIT_BUILTIN_PARAMS, RevitMapping
from .template import SharedParam, TemplateDigest

REVIT_PLAN_VERSION = "0.4.0"


class TypeNeed(BaseModel):
    """One family type the plan needs, and whether the template already has it."""

    category: str
    family: str
    type_name: str
    count: int = 0
    exists: bool = False
    will_create: bool = False          # created in Revit by duplicating base_type
    base_type: str | None = None
    params: dict[str, float] = Field(default_factory=dict)
    note: str | None = None            # why this type is worth a second look before it is created


class ParamCheck(BaseModel):
    """One parameter C2B writes to, and whether this template will keep the value."""

    name: str
    bound: bool = False            # the template binds it, so a write survives
    defined: bool = False          # the shared parameter file defines it
    builtin: bool = False          # Revit gives it to every instance
    advice: str = ""

    @property
    def survives(self) -> bool:
        return self.bound or self.builtin


class PickerLevel(BaseModel):
    """One level on the build picker: what the plan holds for it, and how much of it."""

    id: str
    name: str
    elevation_mm: float = 0.0
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class PickerKind(BaseModel):
    """One kind of member on the build picker, across every level."""

    kind: str
    label: str
    total: int = 0


class RevitPicker(BaseModel):
    """What the window inside Revit offers to build, counted here rather than in there.

    The pyRevit script cannot import C2B -- it runs in Revit's own engine against the plan
    file alone -- so anything it would otherwise have to work out for itself is worked out
    here, where it can be tested. It renders these rows and builds the actions whose level and
    kind are both ticked. That is the whole of the rule.
    """

    levels: list[PickerLevel] = Field(default_factory=list)
    kinds: list[PickerKind] = Field(default_factory=list)
    #: Actions belonging to no level -- the grids -- which a level tick cannot govern.
    off_level: int = 0
    total: int = 0


#: What each kind of action is called on the picker. A drafter ticks "Slabs", not "floor".
KIND_LABELS = {"grid": "Grids", "column": "Columns", "beam": "Beams", "floor": "Slabs",
               "wall": "Walls", "footing": "Footings", "pcc": "PCC under footings",
               "pile": "Piles", "shaft": "Shaft openings"}


def build_picker(plan: RevitPlan) -> RevitPicker:
    """Count the plan by level and by kind, in the order the window shows them.

    Levels read downwards, top storey first, the way a drafter reads a stack -- and the same
    way the storey editor lists them, because they are the same storeys.
    """
    by_level: dict[str, dict[str, int]] = {}
    by_kind: dict[str, int] = {}
    off_level = 0
    for a in plan.actions:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
        if a.level_id:
            by_level.setdefault(a.level_id, {})
            by_level[a.level_id][a.kind] = by_level[a.level_id].get(a.kind, 0) + 1
        else:
            off_level += 1
    picker = RevitPicker(off_level=off_level, total=len(plan.actions))
    for lv in sorted(plan.levels, key=lambda x: x.elevation_mm, reverse=True):
        counts = by_level.get(lv.id, {})
        picker.levels.append(PickerLevel(id=lv.id, name=lv.name, elevation_mm=lv.elevation_mm,
                                         counts=counts, total=sum(counts.values())))
    for kind, total in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        picker.kinds.append(PickerKind(kind=kind, label=KIND_LABELS.get(kind, kind.title() + "s"),
                                       total=total))
    return picker


class TemplateCheck(BaseModel):
    """What a plan asks of a Revit template, answered before Revit is opened."""

    template_name: str = ""
    template_file: str = ""
    types: list[TypeNeed] = Field(default_factory=list)
    missing_families: list[str] = Field(default_factory=list)
    params: list[ParamCheck] = Field(default_factory=list)
    new_levels: list[str] = Field(default_factory=list)
    grid_clashes: list[str] = Field(default_factory=list)   # grid labels the template already uses

    @property
    def bound_params(self) -> list[str]:
        return [p.name for p in self.params if p.survives]

    @property
    def unbound_params(self) -> list[str]:
        return [p.name for p in self.params if not p.survives]

    def marks_lost(self, mark_params: list[str]) -> bool:
        """Would every mark this run writes vanish into a parameter nothing carries?

        Revit's built-in ``Mark`` used to be the safety net: it is on every element whatever a
        template binds, so a mark was never wholly lost. C2B does not write it any more -- it
        is meant to be unique within a category and a structural mark is not -- and with the
        net gone, a template that does not bind ``CH-ScheduleMark`` loses every mark in the
        model, silently, in a way no count or level name shows.
        """
        wanted = {n for n in mark_params}
        return bool(wanted) and not any(p.survives for p in self.params if p.name in wanted)

    def summary(self) -> dict[str, int]:
        return {"types_needed": len(self.types),
                "types_present": sum(1 for t in self.types if t.exists),
                "types_to_create": sum(1 for t in self.types if t.will_create),
                "types_to_look_at": sum(1 for t in self.types if t.note),
                "missing_families": len(self.missing_families),
                "params_that_survive": len(self.bound_params),
                "params_that_vanish": len(self.unbound_params),
                "new_levels": len(self.new_levels),
                "grid_clashes": len(self.grid_clashes)}


class RevitLevel(BaseModel):
    id: str
    name: str
    elevation_mm: float


class RevitAction(BaseModel):
    """One thing to create in Revit."""

    id: str
    kind: str                       # column | beam | floor | footing | pcc | pile | wall | shaft | grid
    category: str                   # Revit category name, for the log
    family: str | None = None
    type_name: str | None = None
    base_type: str | None = None
    params: dict[str, float] = Field(default_factory=dict)      # type parameters to set when creating the type
    level_id: str | None = None
    top_level_id: str | None = None
    base_offset_mm: float = 0.0
    top_offset_mm: float = 0.0
    point: list[float] | None = None                            # [x, y] for point-hosted elements
    start: list[float] | None = None
    end: list[float] | None = None
    rotation_deg: float = 0.0
    loops: list[list[list[float]]] = Field(default_factory=list)  # [outer, hole, hole...] each a list of [x, y]
    height_mm: float | None = None
    thickness_mm: float | None = None      # system types (floor, wall, raft, PCC) are duplicated, then set to this
    # Where the member sits across its own section, stated rather than left to the family. A
    # family carries its own z justification and offset, and whatever it carries wins over
    # everything the plan says until the plan says otherwise.
    z_justification: str | None = None     # top | center | bottom | origin
    z_offset_mm: float = 0.0
    mark: str | None = None
    comment: str | None = None


class RevitPlan(BaseModel):
    plan_version: str = REVIT_PLAN_VERSION
    generator: str = f"c2b {__version__}"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    units: str = "mm"
    source_file: str
    mapping_name: str
    project_base_point: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    mark_params: list[str] = Field(default_factory=list)     # every name the mark is written to
    id_params: list[str] = Field(default_factory=list)       # every name the C2B element id is written to
    level_params: list[str] = Field(default_factory=list)    # every name the level's own name is written to
    comment_param: str | None = None
    grid_name_clash: str = "rename_existing"                 # what to do when the project already has that grid
    template_check: TemplateCheck | None = None              # what the Revit template does and does not carry
    picker: RevitPicker | None = None                        # what the window inside Revit offers to build
    levels: list[RevitLevel] = Field(default_factory=list)
    actions: list[RevitAction] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)

    def recount(self) -> None:
        self.counts = dict(Counter(a.kind for a in self.actions))
        self.counts["levels"] = len(self.levels)


def _round(value: float | None, step: float) -> float | None:
    return None if value is None else round(round(value / step) * step, 1)


def _fmt(pattern: str, **kw) -> str:
    class _Safe(dict):
        def __missing__(self, key):
            return "?"
    try:
        return pattern.format_map(_Safe(**{k: (v if v is not None else 0) for k, v in kw.items()}))
    except (ValueError, TypeError):
        return pattern


#: How far a vertex may sit off the line through its neighbours before it is a real corner.
#: Revit's own short-curve tolerance is about 0.8 mm, and a vertex inside that is not a corner
#: to it -- the loop is rejected outright with "the input curve loops cannot compose a valid
#: boundary". The client's outlines are full of them: a panel closed against beam faces that are
#: a fraction of a degree off square picks up a vertex a third of a millimetre out of line, and
#: 208 of Test17's 2330 panels were refused for it.
_COLLINEAR_TOL_MM = 1.0
_MIN_EDGE_MM = 1.0


def _ring_area(ring: list[list[float]]) -> float:
    """Twice the signed area of a closed ring, by the shoelace rule."""
    n = len(ring)
    return abs(sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1]
                   for i in range(n))) / 2.0


def _clean_ring(points: list[list[float]], tol: float = _COLLINEAR_TOL_MM) -> list[list[float]] | None:
    """Drop the vertices that are not corners, so Revit can close the loop.

    Two kinds go: a vertex within a hair of its neighbour, which makes an edge with no direction,
    and a vertex within the tolerance of the line through its neighbours, which makes a straight
    run reported as two edges. One removal can expose the next, so it removes one at a time until
    nothing more can go -- the rings are a few dozen points, so simple beats clever here.

    Returns None when what is left encloses no area, which is a ring that was never a panel.
    """
    ring = [list(p) for p in points]
    if len(ring) > 2 and math.dist(ring[0], ring[-1]) <= _MIN_EDGE_MM:
        ring.pop()

    dropped = True
    while dropped and len(ring) > 3:
        dropped = False
        n = len(ring)
        for i in range(n):
            before, here, after = ring[i - 1], ring[i], ring[(i + 1) % n]
            if math.dist(before, here) <= _MIN_EDGE_MM:
                del ring[i]
                dropped = True
                break
            base = math.dist(before, after)
            if base > 1e-9:
                twice_area = abs((here[0] - before[0]) * (after[1] - before[1])
                                 - (here[1] - before[1]) * (after[0] - before[0]))
                if twice_area / base <= tol:          # a straight run, not a corner
                    del ring[i]
                    dropped = True
                    break

    if len(ring) < 3 or _ring_area(ring) <= tol * tol:
        return None
    return ring


#: How far the end of a slab edge may sit off horizontal or vertical before it is left where
#: it was drawn. Revit warns "Line in Sketch is slightly off axis and may cause inaccuracies"
#: on anything inside about a tenth of a degree, and an outline traced round beam faces that
#: are a fraction of a degree out of square is full of them: 1962 of them on one import.
#:
#: A distance and not an angle, deliberately. A tenth of a degree is 2 mm on a short edge and
#: 20 mm on a long one, and 20 mm on a long one is a wall somebody measured. This squares up
#: what is obviously meant to be square and leaves alone what might not be.
AXIS_SNAP_MM = 5.0


def _snap_to_axis(ring: list[list[float]], tol: float) -> tuple[list[list[float]], int]:
    """Square up the edges that are within a hair of horizontal or vertical.

    Moving one edge moves the vertex its neighbour shares, which can bring the neighbour into
    range, so it goes round a few times. An edge that is already square has no component left
    to move and is not counted twice.
    """
    ring = [list(p) for p in ring]
    n, snapped = len(ring), 0
    for _ in range(3):
        moved = False
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            if dy and abs(dy) <= tol and abs(dx) > abs(dy):
                a[1] = b[1] = round((a[1] + b[1]) / 2.0, 3)
                moved, snapped = True, snapped + 1
            elif dx and abs(dx) <= tol and abs(dy) > abs(dx):
                a[0] = b[0] = round((a[0] + b[0]) / 2.0, 3)
                moved, snapped = True, snapped + 1
        if not moved:
            break
    return ring, snapped


def _loop(points, snap_mm: float = 0.0, tally: dict | None = None) -> list[list[float]] | None:
    """A ring in floor-local millimetres, which is what stacks floor to floor."""
    ring = _clean_ring([[round(p.x, 2), round(p.y, 2)] for p in points])
    if ring is None or snap_mm <= 0:
        return ring
    ring, snapped = _snap_to_axis(ring, snap_mm)
    if snapped and tally is not None:
        tally["snapped"] = tally.get("snapped", 0) + snapped
    # Squaring an edge can turn the corner at its end into a straight run.
    return _clean_ring(ring) if snapped else ring


def _revit_ready(rings: list[list[list[float]]]) -> str:
    """What Revit will refuse, said before it is asked, in words naming which of it.

    shapely calls a ring valid that touches its own outline at a single point; Revit calls
    that an intersection and refuses the boundary. So the rings are checked against what Revit
    actually requires rather than against what shapely tolerates -- and a panel that still
    cannot be built is named here, by C2B, rather than becoming one more line of the same
    six-cause sentence an hour later.
    """
    from shapely.geometry import LinearRing, Polygon

    for ring in rings:
        if len(ring) < 3:
            return "a ring with fewer than three corners"
        if not LinearRing(ring).is_simple:
            return "a ring that crosses itself"
        for j in range(len(ring)):
            if math.dist(ring[j], ring[(j + 1) % len(ring)]) < _MIN_EDGE_MM:
                return f"an edge shorter than the {_MIN_EDGE_MM:.0f} mm Revit can draw"
    outer = Polygon(rings[0])
    patches = [Polygon(h) for h in rings[1:]]
    for i, patch in enumerate(patches):
        if not outer.contains(patch) or patch.exterior.intersects(outer.exterior):
            return "an opening that touches or crosses the edge of the panel"
        if any(patch.intersects(other) for other in patches[i + 1:]):
            return "two openings that touch or overlap"
    return ""


def _boundary(outer: list[list[float]],
              holes: list[list[list[float]]]) -> tuple[list[list[list[float]]] | None, list[str]]:
    """Rings Revit will accept as one boundary, and what had to change to get there.

    :func:`_clean_ring` takes out the vertices that are not corners. Three things it cannot
    see, and Revit refuses all three with the same sentence about curve loops that "cannot
    compose a valid boundary":

    * an outline that crosses itself, which a panel closed the long way round a re-entrant
      corner does;
    * an opening that is not inside the outline it is supposed to be cut from;
    * two openings that overlap, which two tags read off one shaft will produce.

    109 of Test17's panels were refused for these -- the same dozen shapes, once per typical
    floor, so one bad outline costs eight slabs. Nothing in the message says which of the three
    it was, or which vertex, so it is not something a drafter can act on.

    shapely already knows this problem, so the rings are handed to it as a polygon and taken
    back as whatever it can make valid: an outline that crosses itself comes back as two
    pieces and the larger one is the panel, an opening that is not inside stops being one.
    What changed comes back with it, because a panel quietly built to a different shape is
    worse than one that was refused.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    def largest(geometry):
        parts = [g for g in (getattr(geometry, "geoms", None) or [geometry])
                 if g.geom_type == "Polygon" and not g.is_empty]
        parts.sort(key=lambda g: g.area, reverse=True)
        return parts[0] if parts and parts[0].area > _COLLINEAR_TOL_MM ** 2 else None

    def rings_of(body, notes):
        rings = [_clean_ring([list(c) for c in body.exterior.coords[:-1]])]
        if rings[0] is None:
            return None
        for interior in body.interiors:
            ring = _clean_ring([list(c) for c in interior.coords[:-1]])
            if ring is not None:
                rings.append(ring)
        cut = len(rings) - 1
        if cut != len(holes):
            drawn = f"{len(holes)} opening{'s' if len(holes) != 1 else ''}"
            was = "were" if len(holes) != 1 else "was"
            notes.append(f"{drawn} {was} drawn and {cut} cut: one that is not wholly inside the "
                         "outline, or two that overlap, cannot be cut on their own")
        return rings

    notes: list[str] = []
    try:
        if Polygon(outer, holes).is_valid and not _revit_ready([outer, *holes]):
            return [outer, *holes], notes
        crossed = not Polygon(outer).is_valid
        # Cut rather than declare. difference() answers all four at once: an opening outside
        # the outline takes nothing away, two that overlap come out as one, and one that
        # reaches the edge becomes a notch in the outline instead of an opening Revit refuses.
        shape = largest(make_valid(Polygon(outer)))
        if shape is None:
            return None, ["the outline encloses no area"]
        patches = [largest(make_valid(Polygon(h))) for h in holes]
        patches = [g for g in patches if g is not None]
        if patches:
            shape = largest(shape.difference(unary_union(patches)))
        if shape is None:
            return None, ["the openings take away the whole panel"]
    except Exception as ex:                      # a ring shapely cannot read at all
        return None, [f"the outline could not be read as a shape ({type(ex).__name__})"]

    if crossed:
        notes.append("the outline crossed itself; the largest piece of it was built")
    rings = rings_of(shape, notes)
    if rings is None:
        return None, [*notes, "nothing enclosing an area was left"]

    refused = _revit_ready(rings)
    if refused:
        # One thing difference() cannot resolve: an opening that meets the outline at exactly
        # one point stays an opening, and Revit counts that meeting as an intersection. Widen
        # the openings by the smallest edge it can draw and cut again, so the meeting becomes
        # a crossing and the opening becomes a notch.
        try:
            widened = [g.buffer(_MIN_EDGE_MM) for g in patches]
            wider = largest(largest(make_valid(Polygon(outer))).difference(unary_union(widened)))
            again = rings_of(wider, []) if wider is not None else None
        except Exception:
            again = None
        if again is None or _revit_ready(again):
            return None, [*notes, refused]
        notes.append(f"{refused}; it was widened by {_MIN_EDGE_MM:.0f} mm so the panel could be cut")
        rings = again
    return rings, notes


def _sole_ring(ring, what: str, diag, **where) -> list[list[float]] | None:
    """One ring, made valid. A footing or a cut-out has no openings but can still cross itself."""
    if ring is None:
        return None
    loops, repairs = _boundary(ring, [])
    for repair in repairs:
        diag.warning("REVIT_OUTLINE_REPAIRED", f"{what}: {repair}.", **where)
    return loops[0] if loops else None


def audit_heights(plan: RevitPlan, diag: DiagnosticsCollector, minimum_mm: float) -> int:
    """Every member that spans two levels, measured the way Revit will measure it.

    One column Revit computes as having no height is an ERROR and not a warning, so it refuses
    the whole transaction: every type, every beam, every floor, the lot. 171 of them did that
    to a Test17 run, and the report afterwards could only say that nothing the run made was
    there. Whatever put them there, the plan is not handed over holding one.

    Returns how many it had to correct, so the caller can say so.
    """
    elevation = {lv.id: lv.elevation_mm for lv in plan.levels}
    name = {lv.id: lv.name for lv in plan.levels}
    fixed = 0
    for a in plan.actions:
        if a.kind not in ("column", "pile", "wall") or a.top_level_id is None:
            continue
        base, top = elevation.get(a.level_id), elevation.get(a.top_level_id)
        if base is None or top is None:
            continue
        height = (top + a.top_offset_mm) - (base + a.base_offset_mm)
        if height > 1.0:
            continue
        a.base_offset_mm = (top + a.top_offset_mm) - base - abs(minimum_mm)
        fixed += 1
        diag.error("REVIT_NO_HEIGHT",
                   f"{a.kind.title()} {a.mark or a.id} came out {height:.0f} mm tall between "
                   f"{name.get(a.level_id, a.level_id)} and {name.get(a.top_level_id, a.top_level_id)}. "
                   f"Revit refuses that outright and one of them stops the whole import, so it is "
                   f"built {abs(minimum_mm):.0f} mm tall instead. Check the floor heights.",
                   floor_id=getattr(a, "floor_id", None), element_id=a.id)
    return fixed


def build_plan(np_: NormalizedProject, mapping: RevitMapping, diag: DiagnosticsCollector | None = None) -> RevitPlan:
    """Model + mapping -> an ordered build plan.

    Coordinates stay **floor-local**, which is what makes the building stack. Each plan in the
    client drawing sits somewhere else in model space, and the ``Origin`` point the firm draws
    inside every boundary is the datum that says which point of each plan is the same point of
    the building. Elements are already stored relative to it, so a column at (1000, 2000) on one
    floor is directly above the column at (1000, 2000) on the next. Adding the origin back would
    put every floor where its plan happens to sit on the sheet, which is a staircase of floors
    across the site rather than a building.
    """
    diag = diag or DiagnosticsCollector()
    plan = RevitPlan(source_file=np_.source_file, mapping_name=mapping.name,
                     mark_params=list(mapping.mark_params), id_params=list(mapping.id_params),
                     level_params=list(mapping.level_params), comment_param=mapping.comment_param,
                     grid_name_clash=mapping.grid_name_clash)
    step = mapping.round_sizes_to_mm

    # ---- levels ------------------------------------------------------------
    levels = sorted(np_.levels, key=lambda l: l.elevation_mm)
    if not levels:
        diag.error("REVIT_NO_LEVELS", "The model has no levels; fill the level workbook and normalise again. "
                                      "Without levels nothing can be placed in Revit.")
        plan.diagnostics = diag.items
        plan.recount()
        return plan
    for l in levels:
        plan.levels.append(RevitLevel(id=l.id, name=f"{mapping.level_prefix}{l.name}", elevation_mm=l.elevation_mm))

    # a plan floor can serve several levels (a typical floor); build on each of them
    floor_levels: dict[str, list[str]] = {}
    for l in levels:
        if l.plan_floor_id:
            floor_levels.setdefault(l.plan_floor_id, []).append(l.id)
    for f in np_.floors:
        if f.id not in floor_levels:
            diag.warning("REVIT_FLOOR_NO_LEVEL", f"Floor {f.id} '{f.name}' has no level in the workbook; its elements are skipped", floor_id=f.id)
    level_above = {l.id: (levels[i + 1].id if i + 1 < len(levels) else None) for i, l in enumerate(levels)}
    # Everything belonging to a floor is built BELOW that floor's level: the beams and the slab
    # hang under it, and the columns hold it up from the level beneath. So a column's top is its
    # own floor's level and its base is the one under that.
    level_under = {l.id: (levels[i - 1].id if i > 0 else None) for i, l in enumerate(levels)}
    # Floors the drawing gives something to stand on. A column on the lowest level of a founded
    # plan is the same member the floor above already builds, drawn again at its base.
    founded_floors = {f.floor_id for f in np_.footings}
    elevation = {lv.id: lv.elevation_mm for lv in levels}

    def levels_for(floor_id: str) -> list[str]:
        return floor_levels.get(floor_id, [])

    squared: dict[str, int] = {}

    def ring(points):
        """Every outline goes through one place, so one setting squares all of them."""
        return _loop(points, mapping.slab_axis_snap_mm, squared)

    def plan_level_name(level_id: str | None) -> str:
        return next((lv.name for lv in levels if lv.id == level_id), str(level_id))

    # ---- grids (once, from the lowest floor that has them) -----------------
    if mapping.build.get("grids") and mapping.create_grids:
        seen: set[str] = set()
        for g in np_.grids:
            key = f"{g.axis}:{g.label}"
            if not g.label or key in seen:
                continue
            seen.add(key)
            plan.actions.append(RevitAction(id=g.id, kind="grid", category="Grids", mark=f"{mapping.grid_prefix}{g.label}",
                                            start=[g.start.x, g.start.y], end=[g.end.x, g.end.y]))

    # ---- columns -----------------------------------------------------------
    if mapping.build.get("columns"):
        for c in np_.columns:
            as_wall = (mapping.wall_like_as == "wall" and c.wall_like and c.shape == "rect"
                       and min(c.width_mm or 0, c.depth_mm or 0) >= mapping.wall_like_min_thickness_mm)
            for lid in levels_for(c.floor_id):
                # the member holds up its own floor, so that level is its TOP
                top, base = lid, level_under.get(lid)
                base_offset = 0.0
                if base is None:
                    if c.floor_id in founded_floors and not mapping.column_below_lowest_when_founded:
                        diag.info("REVIT_COLUMN_ON_FOOTING",
                                  f"Column {c.mark} sits on a footing on the lowest plan, and the floor above "
                                  "already builds it down to here; a second one below the foundation would "
                                  "stand on nothing", floor_id=c.floor_id, element_id=c.id)
                        continue
                    # nothing is drawn to hold it, so it hangs below its own level by a stated
                    # depth rather than not being built at all
                    base, base_offset = lid, -abs(mapping.column_min_height_mm)

                # Two levels at the same height, or a workbook where one is above the next, make
                # a column of no height at all. Revit refuses it outright -- "Change Offset Value
                # so that Column height is not 0.0" is an error that cannot be ignored, and one
                # of them stops the whole import -- so the member is given the stated minimum
                # and the workbook is reported rather than the run being lost.
                height = (elevation.get(top, 0.0)) - (elevation.get(base, 0.0) + base_offset)
                if height <= 1.0:
                    diag.warning("REVIT_LEVELS_NOT_APART",
                                 f"Column {c.mark} spans {plan_level_name(base)} to {plan_level_name(top)}, "
                                 f"which are {height:.0f} mm apart; built {mapping.column_min_height_mm:.0f} mm "
                                 "tall instead. Check the floor heights.", floor_id=c.floor_id, element_id=c.id)
                    base_offset = elevation.get(top, 0.0) - elevation.get(base, 0.0) - abs(mapping.column_min_height_mm)
                if as_wall:
                    # a leg modelled as a wall: it runs along its own longer side, and the
                    # shorter side is the wall thickness
                    long_mm, thk = max(c.width_mm, c.depth_mm), _round(min(c.width_mm, c.depth_mm), step)
                    ang = c.rotation_deg + (0.0 if c.width_mm >= c.depth_mm else 90.0)
                    half = long_mm / 2.0
                    ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                    plan.actions.append(RevitAction(
                        id=f"{c.id}@{lid}", kind="wall", category="Walls", family=mapping.wall.family,
                        type_name=_fmt(mapping.wall.type_name, thk=thk), base_type=mapping.wall.base_type,
                        level_id=base, top_level_id=top, base_offset_mm=base_offset,
                        start=[c.center.x - ux * half, c.center.y - uy * half],
                        end=[c.center.x + ux * half, c.center.y + uy * half],
                        thickness_mm=thk, mark=c.mark, comment=f"wall-like leg, stack {c.stack_id}"))
                    continue
                if c.shape == "circle" and c.diameter_mm:
                    rule = mapping.column_round
                    dia = _round(c.diameter_mm, step)
                    type_name = _fmt(rule.type_name, dia=dia)
                    params = {rule.diameter_param: dia} if rule.diameter_param else {}
                else:
                    rule = mapping.column
                    w, d = _round(c.width_mm, step), _round(c.depth_mm, step)
                    if not w or not d:
                        diag.warning("REVIT_NO_SIZE", f"Column {c.mark} ({c.id}) has no size; it is skipped", floor_id=c.floor_id, element_id=c.id)
                        continue
                    type_name = _fmt(rule.type_name, w=w, d=d)
                    params = {k: v for k, v in ((rule.width_param, w), (rule.depth_param, d)) if k}
                plan.actions.append(RevitAction(
                    id=f"{c.id}@{lid}", kind="column", category="Structural Columns", family=rule.family, type_name=type_name,
                    base_type=rule.fallback_type, params=params, level_id=base, top_level_id=top,
                    base_offset_mm=base_offset,
                    point=[c.center.x, c.center.y], rotation_deg=c.rotation_deg, mark=c.mark,
                    comment=f"stack {c.stack_id}" + (" (stops here)" if c.stops_here else "")))

    # ---- beams -------------------------------------------------------------
    if mapping.build.get("beams"):
        for b in np_.beams:
            w, d = _round(b.width_mm, step), _round(b.depth_mm, step)
            assumed = False
            if w and not d and mapping.default_beam_depth_mm:
                d, assumed = _round(mapping.default_beam_depth_mm, step), True
                diag.info("REVIT_DEPTH_ASSUMED", f"Beam {b.mark} ({b.id}) has no depth in the drawing; "
                          f"built at the {d:.0f} mm default", floor_id=b.floor_id, element_id=b.id)
            if not w or not d:
                diag.warning("REVIT_NO_SIZE", f"Beam {b.mark} ({b.id}) has no depth and no default is set, "
                             "so it is not built", floor_id=b.floor_id, element_id=b.id)
                continue
            # a beam the drawing gives two depths is a different family: stepped, or tapered
            # when the second depth is at a free end
            d2 = _round(b.depth_tip_mm or b.depth_alt_mm, step)
            if d2 and d2 != d:
                rule = mapping.beam_rule_for(b.inverted, tapered=b.depth_tip_mm is not None)
                type_name = _fmt(rule.type_name, w=w, d=d, d2=d2)
                params = {k: v for k, v in ((rule.width_param, w), (rule.depth_param, d), (rule.depth_alt_param, d2)) if k}
            else:
                rule = mapping.beam
                type_name = _fmt(rule.type_name, w=w, d=d)
                params = {k: v for k, v in ((rule.width_param, w), (rule.depth_param, d)) if k}
            note = "inverted" if b.inverted else ("cantilever" if b.cantilever else None)
            if assumed:
                note = f"{note}, depth assumed" if note else "depth assumed"
            if b.depth_rule:
                note = f"{note}, depth from {b.depth_rule}" if note else f"depth from {b.depth_rule}"
            for lid in levels_for(b.floor_id):
                plan.actions.append(RevitAction(
                    id=f"{b.id}@{lid}", kind="beam", category="Structural Framing", family=rule.family,
                    type_name=type_name, base_type=rule.fallback_type, params=params,
                    level_id=lid, start=[b.start.x, b.start.y], end=[b.end.x, b.end.y],
                    top_offset_mm=b.top_offset_mm, mark=b.mark, comment=note,
                    z_justification=mapping.beam_z_justification,
                    z_offset_mm=b.top_offset_mm if mapping.beam_top_at_level else 0.0))

    # ---- floors (slab, cantilever, ramp) -----------------------------------
    if mapping.build.get("floors"):
        for p in np_.panels:
            if p.kind not in ("slab", "cantilever", "ramp"):
                continue
            thk = _round(p.thickness_mm, step)
            thk_assumed = False
            if not thk and mapping.default_slab_thickness_mm:
                thk, thk_assumed = _round(mapping.default_slab_thickness_mm, step), True
                diag.info("REVIT_DEPTH_ASSUMED", f"Slab panel {p.mark} ({p.id}) has no thickness in the drawing; "
                          f"built at the {thk:.0f} mm default", floor_id=p.floor_id, element_id=p.id)
            if not thk:
                diag.warning("REVIT_NO_SIZE", f"Slab panel {p.mark} ({p.id}) has no thickness and no default is "
                             "set, so it is not built", floor_id=p.floor_id, element_id=p.id)
                continue
            rule = mapping.ramp_floor if p.kind == "ramp" else mapping.floor
            outer = ring(p.outline)
            if outer is None:
                diag.warning("REVIT_NO_OUTLINE", f"Slab panel {p.mark} ({p.id}) has no usable outline once "
                             "the near-collinear vertices are removed; it is skipped",
                             floor_id=p.floor_id, element_id=p.id)
                continue
            holes = [h for h in (ring(h) for h in p.holes) if h is not None]
            loops, repairs = _boundary(outer, holes)
            if loops is None:
                diag.warning("REVIT_BAD_OUTLINE", f"Slab panel {p.mark} ({p.id}) has an outline Revit "
                             f"will not close: {'; '.join(repairs)}. It is skipped.",
                             floor_id=p.floor_id, element_id=p.id)
                continue
            for repair in repairs:
                diag.warning("REVIT_OUTLINE_REPAIRED", f"Slab panel {p.mark} ({p.id}): {repair}. "
                             "It is built, but not quite as it was drawn.",
                             floor_id=p.floor_id, element_id=p.id)
            for lid in levels_for(p.floor_id):
                plan.actions.append(RevitAction(
                    id=f"{p.id}@{lid}", kind="floor", category="Floors", type_name=_fmt(rule.type_name, thk=thk),
                    base_type=rule.base_type, params={}, level_id=lid, top_offset_mm=p.top_offset_mm,
                    loops=loops, height_mm=thk, thickness_mm=thk, mark=p.mark,
                    comment=f"{p.kind}" + (f", sunk {p.sunk_mm:.0f}" if p.sunk_mm else "")
                            + (f", {p.slope_ratio} {p.direction or ''}" if p.slope_ratio else "")
                            + (", thickness assumed" if thk_assumed else "")))

    # ---- foundations, PCC, piles -------------------------------------------
    if mapping.build.get("foundations"):
        for x in np_.footings:
            lid = next(iter(levels_for(x.floor_id)), None)
            if lid is None:
                continue
            thk = _round(x.thickness_mm, step)
            if x.kind in ("fold", "sunk"):
                continue          # drawn on the plan; the engineer models the step in Revit
            if x.kind in ("raft", "pilecap", "pit"):
                rule = mapping.raft
                outline = _sole_ring(ring(x.outline), f"{x.kind} {x.mark}", diag,
                                     floor_id=x.floor_id, element_id=x.id)
                if outline is None:
                    diag.warning("REVIT_NO_OUTLINE", f"{x.kind} {x.mark} has no usable outline; it is skipped",
                                 floor_id=x.floor_id, element_id=x.id)
                    continue
                if not thk:
                    diag.warning("REVIT_NO_SIZE", f"{x.kind} {x.mark} has no thickness; it is skipped", floor_id=x.floor_id, element_id=x.id)
                    continue
                plan.actions.append(RevitAction(
                    id=x.id, kind="footing", category="Structural Foundations", type_name=_fmt(rule.type_name, thk=thk),
                    base_type=rule.base_type, level_id=lid, loops=[outline], height_mm=thk,
                    thickness_mm=thk, base_offset_mm=-(x.pit_depth_mm or 0.0), mark=x.mark, comment=x.kind))
            else:
                rule = mapping.footing
                w, d = _round(x.width_mm, step), _round(x.depth_mm, step)
                if not (w and d and thk):
                    diag.warning("REVIT_NO_SIZE", f"Footing {x.mark} has no size or thickness; it is skipped", floor_id=x.floor_id, element_id=x.id)
                    continue
                plan.actions.append(RevitAction(
                    id=x.id, kind="footing", category="Structural Foundations", family=rule.family,
                    type_name=_fmt(rule.type_name, w=w, d=d, thk=thk), base_type=rule.fallback_type,
                    params={k: v for k, v in ((rule.width_param, w), (rule.depth_param, d), (rule.thickness_param, thk)) if k},
                    level_id=lid, point=[x.center.x, x.center.y], rotation_deg=x.rotation_deg, mark=x.mark, comment=x.kind))
            pcc_outline = ring(x.pcc_outline) if x.pcc_outline else None
            if mapping.build.get("pcc") and pcc_outline and x.pcc_thickness_mm:
                pthk = _round(x.pcc_thickness_mm, step)
                plan.actions.append(RevitAction(
                    id=f"{x.id}-PCC", kind="pcc", category="Structural Foundations", type_name=_fmt(mapping.pcc.type_name, thk=pthk),
                    base_type=mapping.pcc.base_type, level_id=lid, loops=[pcc_outline], height_mm=pthk,
                    thickness_mm=pthk, base_offset_mm=-((thk or 0.0) + (x.pit_depth_mm or 0.0)), mark="PCC", comment=f"under {x.mark}"))
    if mapping.build.get("piles"):
        rule = mapping.pile
        for pl in np_.piles:
            lid = next(iter(levels_for(pl.floor_id)), None)
            if lid is None or not pl.diameter_mm:
                continue
            dia = _round(pl.diameter_mm, step)
            plan.actions.append(RevitAction(
                id=pl.id, kind="pile", category="Structural Columns", family=rule.family, type_name=_fmt(rule.type_name, dia=dia),
                params={rule.diameter_param: dia} if rule.diameter_param else {}, level_id=lid,
                point=[pl.center.x, pl.center.y], mark="PILE", comment=f"cap {pl.pilecap_id or '-'}"))

    # ---- walls -------------------------------------------------------------
    if mapping.build.get("walls"):
        rule = mapping.wall
        for w in np_.walls:
            if mapping.structural_only and not w.structural:
                continue
            thk = _round(w.thickness_mm, step)
            if not thk or not w.length_mm:
                continue
            half = w.length_mm / 2.0
            ux, uy = math.cos(math.radians(w.rotation_deg)), math.sin(math.radians(w.rotation_deg))
            start = [w.center.x - ux * half, w.center.y - uy * half]
            end = [w.center.x + ux * half, w.center.y + uy * half]
            for lid in levels_for(w.floor_id):
                top = level_above.get(lid)
                plan.actions.append(RevitAction(
                    id=f"{w.id}@{lid}", kind="wall", category="Walls", type_name=_fmt(rule.type_name, thk=thk),
                    base_type=rule.base_type, level_id=lid, top_level_id=top, top_offset_mm=w.top_offset_mm,
                    start=start, end=end, thickness_mm=thk, mark=w.mark, comment="RCC wall"))

    # ---- shafts (lift, stair, duct cut-outs that run through) ---------------
    if mapping.build.get("shafts"):
        for o in np_.openings:
            label = (o.label or "").upper()
            if not any(word in label for word in mapping.shaft_from):
                continue
            lid = next(iter(levels_for(o.floor_id)), None)
            if lid is None:
                continue
            top = level_above.get(lid)
            outline = _sole_ring(ring(o.outline), f"cut-out {o.label}", diag, floor_id=o.floor_id)
            if outline is None:
                continue
            plan.actions.append(RevitAction(
                id=o.id, kind="shaft", category="Shaft Openings", level_id=lid, top_level_id=top,
                loops=[outline], mark=o.label, comment="cut-out through the floor"))

    # Last, over the finished plan: every per-element guard above works on the elevations it
    # was given, and this measures what actually came out of them. A plan is not handed over
    # holding a member Revit will refuse.
    audit_heights(plan, diag, mapping.column_min_height_mm)

    plan.picker = build_picker(plan)

    if squared.get("snapped"):
        diag.info("REVIT_EDGES_SQUARED",
                  f"{squared['snapped']} outline edges sat within {mapping.slab_axis_snap_mm:.0f} mm "
                  "of horizontal or vertical and were squared up. Revit warns that every one of "
                  "them is slightly off axis otherwise, which is thousands of warnings about a "
                  "drawing traced round beam faces a fraction of a degree out of square. Set "
                  "slab_axis_snap_mm to 0 in the mapping to keep the client's geometry exactly "
                  "as drawn.")

    plan.diagnostics = diag.items
    plan.recount()
    return plan


# A size beyond which a type is worth a human's glance before Revit creates it. These are not
# limits -- the plan still carries the element -- they are the sizes at which the firm's own
# classification rules produce something a modeller would not expect to see in that family.
_ODD_ABOVE_MM = {"Structural Columns": 3000.0, "Structural Framing": 2500.0}
_ODD_FOOTING_AREA_M2 = 40.0


def _odd_note(category: str, params: dict[str, float], family: str) -> str | None:
    """Say why a type looks wrong for its family, or nothing."""
    sizes = sorted((v for v in params.values() if v), reverse=True)
    if not sizes:
        return None
    if category == "Structural Foundations" and len(sizes) >= 2 and sizes[0] * sizes[1] / 1e6 >= _ODD_FOOTING_AREA_M2:
        return (f"{sizes[0] / 1000:.1f} x {sizes[1] / 1000:.1f} m is a raft, not an isolated footing; "
                "the client did not mark it RF/RAFT/MAT, so C2B kept it a footing")
    limit = _ODD_ABOVE_MM.get(category)
    if limit and sizes[0] > limit:
        if category == "Structural Columns":
            return (f"{sizes[0]:.0f} mm long: this is a wall leg modelled as a column "
                    "(set wall_like_as: wall in the mapping to model it as a wall instead)")
        return f"{sizes[0]:.0f} mm is deeper than a beam usually is; check the tag it came from"
    return None


def check_against_template(plan: RevitPlan, mapping: RevitMapping, digest: TemplateDigest,
                           shared: dict[str, SharedParam] | None = None) -> TemplateCheck:
    """Answer, before Revit is opened, what this plan asks of the template and what is missing.

    A family that is not in the template cannot have a type duplicated inside it, so every
    element needing it is unbuildable until someone loads the family -- that is worth knowing
    now rather than halfway through a run. A mark written to a parameter the template does not
    bind is worse: Revit accepts the write, drops the value, and the model looks finished.
    """
    check = TemplateCheck(template_name=digest.name, template_file=digest.source_file)

    # -- the types the plan needs, counted --------------------------------
    base_for: dict[str, str | None] = {}
    for rule in list(mapping.loadable_rules().values()) + list(mapping.system_rules().values()):
        base = getattr(rule, "fallback_type", None) or getattr(rule, "base_type", None)
        if rule.family:
            base_for.setdefault(rule.family, base)

    needs: dict[tuple[str, str], TypeNeed] = {}
    for a in plan.actions:
        if a.kind in ("grid", "shaft") or not a.type_name:
            continue
        family = a.family or _system_family(a, mapping)
        if not family:
            continue
        key = (family, a.type_name)
        need = needs.get(key)
        if need is None:
            fam = digest.family(family)
            exists = bool(fam and a.type_name in fam.type_names())
            need = needs[key] = TypeNeed(
                category=a.category, family=family, type_name=a.type_name, exists=exists,
                will_create=not exists and fam is not None,
                base_type=a.base_type or base_for.get(family), params=a.params,
                note=_odd_note(a.category, a.params, family))
            if fam is None and family not in check.missing_families:
                check.missing_families.append(family)
        need.count += 1
    check.types = sorted(needs.values(), key=lambda t: (t.category, t.family, t.type_name))

    # -- where the marks go ------------------------------------------------
    # with no actions there is no category to check against, so ask whether the template binds
    # the name at all rather than declaring every name unbound
    categories = ({a.category for a in plan.actions} - {"Grids", "Shaft Openings"}) or {None}
    for name in (list(plan.mark_params) + list(plan.id_params) + list(plan.level_params)
                 + ([plan.comment_param] if plan.comment_param else [])):
        pc = ParamCheck(name=name, builtin=name in REVIT_BUILTIN_PARAMS,
                        bound=any(digest.binds(name, c) for c in categories),
                        defined=bool(shared and name in shared))
        if pc.builtin:
            pc.advice = "a Revit built-in: always there"
        elif pc.bound:
            pc.advice = "bound in the template; the value survives"
        elif pc.defined:
            pc.advice = ("defined in the shared parameter file but not bound in the template -- "
                         "add it as a project parameter, or C2B's write is dropped")
        else:
            pc.advice = ("neither defined in the shared parameter file nor bound in the template -- "
                         "it is a name nothing carries, so remove it from the mapping")
        check.params.append(pc)

    # -- levels ------------------------------------------------------------
    have = digest.level_names()
    check.new_levels = [lv.name for lv in plan.levels if lv.name not in have]

    # -- grids the template already uses -------------------------------------
    # Revit will not hold two grids of one name. The template's are samples and the client's are
    # real, so a clash is not a detail: it is that many of the client's grids never arriving.
    template_grids = set(digest.grid_names)
    check.grid_clashes = sorted({a.mark for a in plan.actions
                                 if a.kind == "grid" and a.mark and a.mark in template_grids})
    return check


def _system_family(action: RevitAction, mapping: RevitMapping) -> str | None:
    """A system-family action carries no family name; its kind says which rule made it."""
    rule = {"floor": mapping.floor, "wall": mapping.wall, "pcc": mapping.pcc}.get(action.kind)
    if action.kind == "footing" and not action.family:
        rule = mapping.raft
    return rule.family if rule else None
