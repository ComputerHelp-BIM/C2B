"""Canonical C2B schema (v0.1.0).

This is the contract between all C2B utilities. Every downstream tool (template
DXF writer, Revit importer, cross-checker) reads this and nothing else.

Conventions:
- all lengths are millimetres, all angles degrees,
- coordinates are floor-local: the floor ``Origin`` point is (0, 0),
- ``source_handles`` always point back to the DXF entities an element came from,
- anything the extractor was unsure about is expressed as a ``Diagnostic``, never dropped silently.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from . import SCHEMA_VERSION, __version__

Severity = Literal["ERROR", "WARNING", "INFO"]
SizeSource = Literal["tag", "schedule", "layer", "block", "geometry", "default", "unknown"]


class Point2(BaseModel):
    x: float
    y: float


class Diagnostic(BaseModel):
    severity: Severity
    code: str
    message: str
    floor_id: str | None = None
    layer: str | None = None
    handle: str | None = None
    element_id: str | None = None
    location: Point2 | None = None


class DrawingInfo(BaseModel):
    file: str
    dxf_version: str
    insunits: int | None
    unit_name: str
    unit_scale_to_mm: float
    unit_source: str
    unit_confidence: str
    layouts: list[str] = Field(default_factory=list)
    extents_min: Point2 | None = None
    extents_max: Point2 | None = None
    entity_count: int = 0


class LayerMapEntry(BaseModel):
    layer: str
    geometry_role: str
    text_role: str
    modifiers: list[str] = Field(default_factory=list)
    confidence: str            # "high" | "medium" | "low" | "none"
    source: str                # "auto" | "profile"
    entity_counts: dict[str, int] = Field(default_factory=dict)
    layer_size: list[float] | None = None   # width/depth encoded in the layer name, e.g. B-200x400


class Floor(BaseModel):
    id: str
    index: int
    name: str
    name_source: str           # "title_block" | "text" | "layout" | "fallback"
    origin: Point2             # in drawing coordinates (after unit scaling)
    boundary: list[Point2] = Field(default_factory=list)   # drawing coordinates
    elevation_mm: float | None = None
    floor_to_floor_mm: float | None = None
    default_beam_depth_mm: float | None = None
    default_slab_thickness_mm: float | None = None
    notes: list[str] = Field(default_factory=list)      # client general notes found inside the frame, verbatim
    counts: dict[str, int] = Field(default_factory=dict)


class LevelHint(BaseModel):
    """A level read from a client section/elevation text, e.g. 'GROUND FLOOR LVL. +2.500'."""

    name: str
    elevation_mm: float
    text: str
    handle: str
    layer: str
    floor_id: str | None = None


class TagRef(BaseModel):
    handle: str
    text: str
    layer: str
    position: Point2


class Grid(BaseModel):
    id: str
    floor_id: str
    label: str | None
    axis: Literal["X", "Y", "other"]   # X = vertical line at constant x, Y = horizontal line at constant y
    start: Point2
    end: Point2
    angle_deg: float
    offset_mm: float                  # x for axis X, y for axis Y
    source_layer: str
    source_handles: list[str] = Field(default_factory=list)


class Column(BaseModel):
    id: str
    floor_id: str
    mark: str | None = None
    shape: Literal["rect", "circle", "polygon"]
    center: Point2
    width_mm: float | None = None
    depth_mm: float | None = None
    rotation_deg: float = 0.0
    diameter_mm: float | None = None
    outline: list[Point2] = Field(default_factory=list)
    area_mm2: float = 0.0
    drawn_width_mm: float | None = None
    drawn_depth_mm: float | None = None
    size_source: SizeSource = "unknown"
    wall_like: bool = False
    modifier: str | None = None          # start | stop | stub | hidden
    grid_ref: str | None = None
    tags: list[TagRef] = Field(default_factory=list)
    source_layer: str
    source_kind: str                     # polyline | hatch | circle | lines | block
    source_handles: list[str] = Field(default_factory=list)
    confidence: str = "high"


class Beam(BaseModel):
    id: str
    floor_id: str
    mark: str | None = None
    start: Point2
    end: Point2
    length_mm: float
    width_mm: float | None = None
    depth_mm: float | None = None
    depth_alt_mm: float | None = None
    drawn_width_mm: float
    angle_deg: float
    inverted: bool = False
    sunk_mm: float | None = None
    outline: list[Point2] = Field(default_factory=list)
    size_source: SizeSource = "unknown"
    depth_source: SizeSource = "unknown"
    tags: list[TagRef] = Field(default_factory=list)
    source_layer: str
    source_kind: str                     # paired_lines | polyline | block
    source_handles: list[str] = Field(default_factory=list)
    n_edge_parts: int = 2
    confidence: str = "high"


class Slab(BaseModel):
    id: str
    floor_id: str
    mark: str | None = None
    thickness_mm: float | None = None
    thickness_source: SizeSource = "unknown"
    position: Point2                     # tag position (or outline centroid)
    outline: list[Point2] = Field(default_factory=list)   # empty when only a tag exists
    sunk_mm: float | None = None
    modifier: str | None = None          # drop | fold | projection | sunk
    tags: list[TagRef] = Field(default_factory=list)
    source_layer: str
    source_kind: str                     # tag | polyline
    source_handles: list[str] = Field(default_factory=list)


class Footing(BaseModel):
    id: str
    floor_id: str
    mark: str | None = None
    shape: Literal["rect", "circle", "polygon"]
    center: Point2
    width_mm: float | None = None
    depth_mm: float | None = None
    rotation_deg: float = 0.0
    thickness_mm: float | None = None
    fold_mm: float | None = None
    outline: list[Point2] = Field(default_factory=list)
    area_mm2: float = 0.0
    drawn_width_mm: float | None = None
    drawn_depth_mm: float | None = None
    size_source: SizeSource = "unknown"
    modifier: str | None = None
    tags: list[TagRef] = Field(default_factory=list)
    source_layer: str
    source_handles: list[str] = Field(default_factory=list)
    confidence: str = "high"


class Opening(BaseModel):
    id: str
    floor_id: str
    label: str | None = None
    center: Point2
    outline: list[Point2] = Field(default_factory=list)
    area_mm2: float = 0.0
    source_layer: str
    source_handles: list[str] = Field(default_factory=list)


class SlabEdge(BaseModel):
    """A slab edge line drawn by the client (free edges of cantilevers, chajjas, balconies)."""

    floor_id: str
    start: Point2
    end: Point2
    source_layer: str
    source_handle: str


class LegendItem(BaseModel):
    """One line of the client's legend: a hatch pattern and what it means."""

    pattern: str
    meaning: str                 # sunk | beam_bottom | column_stop | cutout | fold | upstand | drop | projection | other
    value_mm: float | None = None
    text: str
    handle: str


class Region(BaseModel):
    """A hatched area whose meaning comes from the legend (e.g. slab sunk by 75)."""

    id: str
    floor_id: str
    meaning: str
    value_mm: float | None = None
    pattern: str
    outline: list[Point2]
    area_mm2: float
    source_layer: str
    source_handles: list[str] = Field(default_factory=list)


class Joint(BaseModel):
    """Expansion / construction joint line carried through as drawn."""

    id: str
    floor_id: str
    start: Point2
    end: Point2
    source_layer: str
    source_handle: str


class Stair(BaseModel):
    """Stair geometry carried through as drawn (outline polygons and raw lines)."""

    id: str
    floor_id: str
    label: str | None = None
    center: Point2
    outline: list[Point2] = Field(default_factory=list)
    lines: list[list[Point2]] = Field(default_factory=list)
    area_mm2: float = 0.0
    source_layer: str
    source_handles: list[str] = Field(default_factory=list)


class Wall(BaseModel):
    id: str
    floor_id: str
    mark: str | None = None
    center: Point2
    outline: list[Point2] = Field(default_factory=list)
    length_mm: float | None = None
    thickness_mm: float | None = None
    rotation_deg: float = 0.0
    area_mm2: float = 0.0
    structural: bool = True
    tags: list[TagRef] = Field(default_factory=list)
    source_layer: str
    source_handles: list[str] = Field(default_factory=list)


class ScheduleRow(BaseModel):
    mark: str
    values: dict[str, float | str | None] = Field(default_factory=dict)


class Schedule(BaseModel):
    id: str
    title: str | None
    category: str | None            # column | beam | slab | footing | wall
    columns: list[str]
    rows: list[ScheduleRow]
    source_layer: str
    floor_id: str | None = None


class UnassignedTag(BaseModel):
    handle: str
    layer: str
    text: str
    role: str
    floor_id: str | None
    position: Point2
    parsed: dict


class Summary(BaseModel):
    floors: int = 0
    grids: int = 0
    columns: int = 0
    beams: int = 0
    slabs: int = 0
    footings: int = 0
    openings: int = 0
    walls: int = 0
    stairs: int = 0
    schedules: int = 0
    tags_unassigned: int = 0
    errors: int = 0
    warnings: int = 0
    infos: int = 0


class Project(BaseModel):
    schema_version: str = SCHEMA_VERSION
    generator: str = f"c2b {__version__}"
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    units: Literal["mm"] = "mm"
    drawing: DrawingInfo
    profile_name: str | None = None
    layer_map: list[LayerMapEntry] = Field(default_factory=list)
    floors: list[Floor] = Field(default_factory=list)
    grids: list[Grid] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)
    beams: list[Beam] = Field(default_factory=list)
    slabs: list[Slab] = Field(default_factory=list)
    footings: list[Footing] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)
    stairs: list[Stair] = Field(default_factory=list)
    slab_edges: list[SlabEdge] = Field(default_factory=list)
    legend: list[LegendItem] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    joints: list[Joint] = Field(default_factory=list)
    level_hints: list[LevelHint] = Field(default_factory=list)
    schedules: list[Schedule] = Field(default_factory=list)
    tags_unassigned: list[UnassignedTag] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)

    def recompute_summary(self) -> None:
        self.summary = Summary(
            floors=len(self.floors), grids=len(self.grids), columns=len(self.columns), beams=len(self.beams),
            slabs=len(self.slabs), footings=len(self.footings), openings=len(self.openings), walls=len(self.walls),
            stairs=len(self.stairs), schedules=len(self.schedules), tags_unassigned=len(self.tags_unassigned),
            errors=sum(1 for d in self.diagnostics if d.severity == "ERROR"),
            warnings=sum(1 for d in self.diagnostics if d.severity == "WARNING"),
            infos=sum(1 for d in self.diagnostics if d.severity == "INFO"),
        )
        for f in self.floors:
            f.counts = {
                "grids": sum(1 for g in self.grids if g.floor_id == f.id),
                "columns": sum(1 for c in self.columns if c.floor_id == f.id),
                "beams": sum(1 for b in self.beams if b.floor_id == f.id),
                "slabs": sum(1 for s in self.slabs if s.floor_id == f.id),
                "footings": sum(1 for x in self.footings if x.floor_id == f.id),
                "openings": sum(1 for o in self.openings if o.floor_id == f.id),
                "walls": sum(1 for w in self.walls if w.floor_id == f.id),
            }
