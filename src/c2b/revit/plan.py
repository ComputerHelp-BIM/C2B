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

REVIT_PLAN_VERSION = "0.3.0"


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
    comment_param: str | None = None
    grid_name_clash: str = "rename_existing"                 # what to do when the project already has that grid
    template_check: TemplateCheck | None = None              # what the Revit template does and does not carry
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


def _loop(points) -> list[list[float]]:
    """A ring in floor-local millimetres, which is what stacks floor to floor."""
    return [[round(p.x, 2), round(p.y, 2)] for p in points]


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
                     comment_param=mapping.comment_param, grid_name_clash=mapping.grid_name_clash)
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

    def levels_for(floor_id: str) -> list[str]:
        return floor_levels.get(floor_id, [])

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
                top = level_above.get(lid)
                if top is None:
                    diag.info("REVIT_COLUMN_NO_TOP", f"Column {c.mark} on the highest level has no level above; it is skipped", element_id=c.id)
                    continue
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
                        level_id=lid, top_level_id=top,
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
                    base_type=rule.fallback_type, params=params, level_id=lid, top_level_id=top,
                    point=[c.center.x, c.center.y], rotation_deg=c.rotation_deg, mark=c.mark,
                    comment=f"stack {c.stack_id}" + (" (stops here)" if c.stops_here else "")))

    # ---- beams -------------------------------------------------------------
    if mapping.build.get("beams"):
        for b in np_.beams:
            w, d = _round(b.width_mm, step), _round(b.depth_mm, step)
            if not w or not d:
                diag.warning("REVIT_NO_SIZE", f"Beam {b.mark} ({b.id}) has no depth; it is skipped", floor_id=b.floor_id, element_id=b.id)
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
            if not thk:
                diag.warning("REVIT_NO_SIZE", f"Slab panel {p.mark} ({p.id}) has no thickness; it is skipped", floor_id=p.floor_id, element_id=p.id)
                continue
            rule = mapping.ramp_floor if p.kind == "ramp" else mapping.floor
            loops = [_loop(p.outline)] + [_loop(h) for h in p.holes]
            for lid in levels_for(p.floor_id):
                plan.actions.append(RevitAction(
                    id=f"{p.id}@{lid}", kind="floor", category="Floors", type_name=_fmt(rule.type_name, thk=thk),
                    base_type=rule.base_type, params={}, level_id=lid, top_offset_mm=p.top_offset_mm,
                    loops=loops, height_mm=thk, thickness_mm=thk, mark=p.mark,
                    comment=f"{p.kind}" + (f", sunk {p.sunk_mm:.0f}" if p.sunk_mm else "") + (f", {p.slope_ratio} {p.direction or ''}" if p.slope_ratio else "")))

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
                if not thk:
                    diag.warning("REVIT_NO_SIZE", f"{x.kind} {x.mark} has no thickness; it is skipped", floor_id=x.floor_id, element_id=x.id)
                    continue
                plan.actions.append(RevitAction(
                    id=x.id, kind="footing", category="Structural Foundations", type_name=_fmt(rule.type_name, thk=thk),
                    base_type=rule.base_type, level_id=lid, loops=[_loop(x.outline)], height_mm=thk,
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
            if mapping.build.get("pcc") and x.pcc_outline and x.pcc_thickness_mm:
                pthk = _round(x.pcc_thickness_mm, step)
                plan.actions.append(RevitAction(
                    id=f"{x.id}-PCC", kind="pcc", category="Structural Foundations", type_name=_fmt(mapping.pcc.type_name, thk=pthk),
                    base_type=mapping.pcc.base_type, level_id=lid, loops=[_loop(x.pcc_outline)], height_mm=pthk,
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
            plan.actions.append(RevitAction(
                id=o.id, kind="shaft", category="Shaft Openings", level_id=lid, top_level_id=top,
                loops=[_loop(o.outline)], mark=o.label, comment="cut-out through the floor"))

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
    for name in list(plan.mark_params) + list(plan.id_params) + ([plan.comment_param] if plan.comment_param else []):
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
