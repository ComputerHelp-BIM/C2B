"""Shared per-floor context handed to every extractor."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..diagnostics import DiagnosticsCollector
from ..dxfio import Prim
from ..floors import FloorFrame
from ..profile import LayerRule, Tolerances
from ..schedules import ScheduleIndex
from ..schema import Point2, TagRef


class IdGen:
    def __init__(self, floor_id: str):
        self.floor_id = floor_id
        self.counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{self.floor_id}-{prefix}{n:03d}"


@dataclass
class FloorContext:
    frame: FloorFrame
    roles: dict[str, tuple[str, str]]          # layer -> (geometry_role, text_role)
    rules: dict[str, LayerRule]
    tol: Tolerances
    diag: DiagnosticsCollector
    schedules: ScheduleIndex
    by_geom_role: dict[str, list[Prim]] = field(default_factory=dict)
    by_text_role: dict[str, list[Prim]] = field(default_factory=dict)
    assigned_tag_handles: set[str] = field(default_factory=set)
    ids: IdGen = None  # type: ignore[assignment]
    grids_x: list[tuple[str, float]] = field(default_factory=list)
    grids_y: list[tuple[str, float]] = field(default_factory=list)
    missing_marks: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ids is None:
            self.ids = IdGen(self.frame.id)
        for p in self.frame.prims:
            geom_role, text_role = self.roles.get(p.layer, ("UNKNOWN", "NOTE"))
            if p.kind == "text":
                self.by_text_role.setdefault(text_role, []).append(p)
            else:
                self.by_geom_role.setdefault(geom_role, []).append(p)

    @property
    def floor_id(self) -> str:
        return self.frame.id

    def geoms(self, role: str, *kinds: str) -> list[Prim]:
        items = self.by_geom_role.get(role, [])
        if kinds:
            items = [p for p in items if p.kind in kinds]
        return [p for p in items if "hidden" not in self.rules.get(p.layer, LayerRule()).modifiers]

    def texts(self, role: str) -> list[Prim]:
        return [p for p in self.by_text_role.get(role, []) if p.text and p.text.strip()]

    def modifier_for(self, layer: str) -> str | None:
        mods = [m for m in self.rules.get(layer, LayerRule()).modifiers if m not in ("tag_layer", "hatch")]
        return mods[0] if mods else None

    def note_missing_mark(self, category: str, mark: str, element_id: str) -> None:
        """Record a plan mark that no schedule knows; reported once per floor and mark."""
        self.missing_marks.setdefault((category, mark), []).append(element_id)

    def flush_missing_marks(self) -> None:
        for (category, mark), ids in sorted(self.missing_marks.items()):
            self.diag.warning("SCHEDULE_MARK_MISSING", f"{category.capitalize()} mark '{mark}' is used by {len(ids)} element(s) on this floor but is not in any schedule (e.g. {', '.join(ids[:4])})", floor_id=self.floor_id)
        self.missing_marks.clear()

    def layer_size(self, layer: str) -> tuple[float, float] | None:
        from ..tags import parse_size_from_name
        return parse_size_from_name(layer)


def tag_ref(prim: Prim) -> TagRef:
    c = prim.rep_point()
    return TagRef(handle=prim.handle, text=prim.text or "", layer=prim.layer, position=Point2(x=c[0], y=c[1]))


def pt(p: tuple[float, float]) -> Point2:
    return Point2(x=round(p[0], 3), y=round(p[1], 3))


def outline_points(poly) -> list[Point2]:
    coords = list(poly.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [pt(c) for c in coords]
