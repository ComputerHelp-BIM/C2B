"""Turn the normalised model into an ordered list of instructions for Revit.

Every decision (which level, which type, which offset, which loop is a hole) is made here,
where it can be tested. The Revit script only executes what this file produces, which keeps
the part that runs inside Revit small enough to review.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .. import __version__
from ..diagnostics import DiagnosticsCollector
from ..normalize.model import NormalizedProject
from ..schema import Diagnostic
from .mapping import RevitMapping

REVIT_PLAN_VERSION = "0.1.0"


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
    mark: str | None = None
    comment: str | None = None


class RevitPlan(BaseModel):
    plan_version: str = REVIT_PLAN_VERSION
    generator: str = f"c2b {__version__}"
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    units: str = "mm"
    source_file: str
    mapping_name: str
    project_base_point: list[float] = Field(default_factory=lambda: [0.0, 0.0])
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


def _loop(points, ox: float, oy: float) -> list[list[float]]:
    return [[round(p.x + ox, 2), round(p.y + oy, 2)] for p in points]


def build_plan(np_: NormalizedProject, mapping: RevitMapping, diag: DiagnosticsCollector | None = None) -> RevitPlan:
    """Model + mapping -> an ordered build plan. Coordinates become project coordinates (floor origin applied)."""
    diag = diag or DiagnosticsCollector()
    plan = RevitPlan(source_file=np_.source_file, mapping_name=mapping.name)
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
    level_index = {l.id: i for i, l in enumerate(levels)}
    level_above = {l.id: (levels[i + 1].id if i + 1 < len(levels) else None) for i, l in enumerate(levels)}
    origin = {f.id: (f.origin.x, f.origin.y) for f in np_.floors}

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
            ox, oy = origin.get(g.floor_id, (0.0, 0.0))
            plan.actions.append(RevitAction(id=g.id, kind="grid", category="Grids", mark=f"{mapping.grid_prefix}{g.label}",
                                            start=[g.start.x + ox, g.start.y + oy], end=[g.end.x + ox, g.end.y + oy]))

    # ---- columns -----------------------------------------------------------
    if mapping.build.get("columns"):
        for c in np_.columns:
            ox, oy = origin.get(c.floor_id, (0.0, 0.0))
            for lid in levels_for(c.floor_id):
                top = level_above.get(lid)
                if top is None:
                    diag.info("REVIT_COLUMN_NO_TOP", f"Column {c.mark} on the highest level has no level above; it is skipped", element_id=c.id)
                    continue
                if c.shape == "circle" and c.diameter_mm:
                    rule = mapping.column_round
                    dia = _round(c.diameter_mm, step)
                    type_name = _fmt(rule.type_name, dia=dia)
                    params = {rule.diameter_param: dia} if rule.diameter_param else {}
                else:
                    rule = mapping.column
                    w, d = _round(c.width_mm or c.drawn_width_mm if hasattr(c, "drawn_width_mm") else c.width_mm, step), _round(c.depth_mm, step)
                    if not w or not d:
                        diag.warning("REVIT_NO_SIZE", f"Column {c.mark} ({c.id}) has no size; it is skipped", floor_id=c.floor_id, element_id=c.id)
                        continue
                    type_name = _fmt(rule.type_name, w=w, d=d)
                    params = {k: v for k, v in ((rule.width_param, w), (rule.depth_param, d)) if k}
                plan.actions.append(RevitAction(
                    id=f"{c.id}@{lid}", kind="column", category="Structural Columns", family=rule.family, type_name=type_name,
                    base_type=rule.fallback_type, params=params, level_id=lid, top_level_id=top,
                    point=[c.center.x + ox, c.center.y + oy], rotation_deg=c.rotation_deg, mark=c.mark,
                    comment=f"stack {c.stack_id}" + (" (stops here)" if c.stops_here else "")))

    # ---- beams -------------------------------------------------------------
    if mapping.build.get("beams"):
        rule = mapping.beam
        for b in np_.beams:
            ox, oy = origin.get(b.floor_id, (0.0, 0.0))
            w, d = _round(b.width_mm, step), _round(b.depth_mm, step)
            if not w or not d:
                diag.warning("REVIT_NO_SIZE", f"Beam {b.mark} ({b.id}) has no depth; it is skipped", floor_id=b.floor_id, element_id=b.id)
                continue
            for lid in levels_for(b.floor_id):
                plan.actions.append(RevitAction(
                    id=f"{b.id}@{lid}", kind="beam", category="Structural Framing", family=rule.family,
                    type_name=_fmt(rule.type_name, w=w, d=d), base_type=rule.fallback_type,
                    params={k: v for k, v in ((rule.width_param, w), (rule.depth_param, d)) if k},
                    level_id=lid, start=[b.start.x + ox, b.start.y + oy], end=[b.end.x + ox, b.end.y + oy],
                    top_offset_mm=b.top_offset_mm, mark=b.mark,
                    comment="inverted" if b.inverted else ("cantilever" if b.cantilever else None)))

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
            ox, oy = origin.get(p.floor_id, (0.0, 0.0))
            loops = [_loop(p.outline, ox, oy)] + [_loop(h, ox, oy) for h in p.holes]
            for lid in levels_for(p.floor_id):
                plan.actions.append(RevitAction(
                    id=f"{p.id}@{lid}", kind="floor", category="Floors", type_name=_fmt(rule.type_name, thk=thk),
                    base_type=rule.base_type, params={}, level_id=lid, top_offset_mm=p.top_offset_mm,
                    loops=loops, height_mm=thk, mark=p.mark,
                    comment=f"{p.kind}" + (f", sunk {p.sunk_mm:.0f}" if p.sunk_mm else "") + (f", {p.slope_ratio} {p.direction or ''}" if p.slope_ratio else "")))

    # ---- foundations, PCC, piles -------------------------------------------
    if mapping.build.get("foundations"):
        for x in np_.footings:
            lid = next(iter(levels_for(x.floor_id)), None)
            if lid is None:
                continue
            ox, oy = origin.get(x.floor_id, (0.0, 0.0))
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
                    base_type=rule.base_type, level_id=lid, loops=[_loop(x.outline, ox, oy)], height_mm=thk,
                    base_offset_mm=-(x.pit_depth_mm or 0.0), mark=x.mark, comment=x.kind))
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
                    level_id=lid, point=[x.center.x + ox, x.center.y + oy], rotation_deg=x.rotation_deg, mark=x.mark, comment=x.kind))
            if mapping.build.get("pcc") and x.pcc_outline and x.pcc_thickness_mm:
                pthk = _round(x.pcc_thickness_mm, step)
                plan.actions.append(RevitAction(
                    id=f"{x.id}-PCC", kind="pcc", category="Structural Foundations", type_name=_fmt(mapping.pcc.type_name, thk=pthk),
                    base_type=mapping.pcc.base_type, level_id=lid, loops=[_loop(x.pcc_outline, ox, oy)], height_mm=pthk,
                    base_offset_mm=-((thk or 0.0) + (x.pit_depth_mm or 0.0)), mark="PCC", comment=f"under {x.mark}"))
    if mapping.build.get("piles"):
        rule = mapping.pile
        for pl in np_.piles:
            lid = next(iter(levels_for(pl.floor_id)), None)
            if lid is None or not pl.diameter_mm:
                continue
            ox, oy = origin.get(pl.floor_id, (0.0, 0.0))
            dia = _round(pl.diameter_mm, step)
            plan.actions.append(RevitAction(
                id=pl.id, kind="pile", category="Structural Columns", family=rule.family, type_name=_fmt(rule.type_name, dia=dia),
                params={rule.diameter_param: dia} if rule.diameter_param else {}, level_id=lid,
                point=[pl.center.x + ox, pl.center.y + oy], mark="PILE", comment=f"cap {pl.pilecap_id or '-'}"))

    # ---- walls -------------------------------------------------------------
    if mapping.build.get("walls"):
        rule = mapping.wall
        for w in np_.walls:
            if mapping.structural_only and not w.structural:
                continue
            thk = _round(w.thickness_mm, step)
            if not thk or not w.length_mm:
                continue
            ox, oy = origin.get(w.floor_id, (0.0, 0.0))
            half = w.length_mm / 2.0
            ux, uy = math.cos(math.radians(w.rotation_deg)), math.sin(math.radians(w.rotation_deg))
            start = [w.center.x + ox - ux * half, w.center.y + oy - uy * half]
            end = [w.center.x + ox + ux * half, w.center.y + oy + uy * half]
            for lid in levels_for(w.floor_id):
                top = level_above.get(lid)
                plan.actions.append(RevitAction(
                    id=f"{w.id}@{lid}", kind="wall", category="Walls", type_name=_fmt(rule.type_name, thk=thk),
                    base_type=rule.base_type, level_id=lid, top_level_id=top, top_offset_mm=w.top_offset_mm,
                    start=start, end=end, mark=w.mark, comment="RCC wall"))

    # ---- shafts (lift, stair, duct cut-outs that run through) ---------------
    if mapping.build.get("shafts"):
        for o in np_.openings:
            label = (o.label or "").upper()
            if not any(word in label for word in mapping.shaft_from):
                continue
            lid = next(iter(levels_for(o.floor_id)), None)
            if lid is None:
                continue
            ox, oy = origin.get(o.floor_id, (0.0, 0.0))
            top = level_above.get(lid)
            plan.actions.append(RevitAction(
                id=o.id, kind="shaft", category="Shaft Openings", level_id=lid, top_level_id=top,
                loops=[_loop(o.outline, ox, oy)], mark=o.label, comment="cut-out through the floor"))

    plan.diagnostics = diag.items
    plan.recount()
    return plan
