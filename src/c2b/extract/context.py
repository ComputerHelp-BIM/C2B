"""Shared per-floor context handed to every extractor."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..diagnostics import DiagnosticsCollector
from ..dxfio import Prim
from ..floors import FloorFrame
from shapely.geometry import Point

from ..profile import LayerRule, SizeSources, Tolerances
from ..tags import parse_size_from_name, strip_mtext_codes
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
    size_sources: SizeSources = field(default_factory=SizeSources)
    legend_zones: list = field(default_factory=list)   # strips the client's legend occupies; not structure
    size_tag_role: str | None = "BEAM_TAG"            # role a dimension's size override is read as
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
                continue
            if p.kind == "dimension" and self.size_tag_role:
                # A drafter who overrides a dimension's text with a size is stating that member's
                # section: "{\H0.666667x;200x400}" on the dimension across a beam is how this
                # client gives a stepped beam its two depths. An override with no size in it is
                # an ordinary annotation and is left alone.
                txt = strip_mtext_codes(p.text or "")
                if txt and parse_size_from_name(txt):
                    # how far a tag may sit from its member is measured in text heights, and a
                    # dimension often states none, so fall back rather than give it no reach
                    height = p.text_height or self.tol.dimension_tag_height_mm
                    self.by_text_role.setdefault(self.size_tag_role, []).append(
                        replace(p, kind="text", text=txt, text_height=height))
                    continue
            self.by_geom_role.setdefault(geom_role, []).append(p)

    @property
    def floor_id(self) -> str:
        return self.frame.id

    def in_legend(self, p: Prim) -> bool:
        """Does this primitive sit in the band the client's legend occupies?

        Area is compared for a shape and the representative point for anything thinner: a swatch
        whose representative point lands on the zone's own edge would otherwise slip through, and
        the swatches are exactly the shapes that must not.
        """
        if not self.legend_zones:
            return False
        g = p.geom
        for z in self.legend_zones:
            if not z.intersects(g):
                continue
            if g.geom_type in ("Polygon", "MultiPolygon") and g.area > 0:
                if g.intersection(z).area >= 0.5 * g.area:
                    return True
            elif z.contains(Point(p.rep_point())):
                return True
        return False

    def geoms(self, role: str, *kinds: str) -> list[Prim]:
        items = self.by_geom_role.get(role, [])
        if kinds:
            items = [p for p in items if p.kind in kinds]
        return [p for p in items
                if "hidden" not in self.rules.get(p.layer, LayerRule()).modifiers and not self.in_legend(p)]

    def texts(self, role: str) -> list[Prim]:
        return [p for p in self.by_text_role.get(role, [])
                if p.text and p.text.strip() and not self.in_legend(p)]

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
