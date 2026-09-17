"""Normalised model (schema 0.2.0): what the template DXF and the Revit importer consume.

Coordinates are floor-local millimetres as in the extraction schema. Every
element carries the ids of the extraction elements it came from, so the chain
client DXF -> extraction -> normalised -> template DXF is fully traceable.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .. import __version__
from ..schema import Diagnostic, Point2, TagRef

NORMALIZED_SCHEMA_VERSION = "0.10.0"


class NFloor(BaseModel):
    id: str
    index: int
    name: str                      # normalised display name, e.g. "GROUND FLOOR LVL."
    title: str                     # plan title, e.g. "LAYOUT PLAN - GROUND FLOOR LEVEL"
    source_name: str
    origin: Point2                 # drawing coordinates
    frame: list[Point2]            # boundary rectangle in drawing coordinates (with bottom band)
    plan_bottom_y: float           # original frame bottom (drawing coords), reference for title/notes
    elevation_mm: float | None = None
    levels: list[str] = Field(default_factory=list)   # level ids drawn from this plan (typical floors)
    default_beam_depth_mm: float | None = None
    default_slab_thickness_mm: float | None = None
    notes: list[str] = Field(default_factory=list)       # client notes, verbatim, written under the plan
    counts: dict[str, int] = Field(default_factory=dict)


class NLevel(BaseModel):
    id: str
    index: int
    name: str                      # e.g. "01 GROUND FLOOR LVL."
    elevation_mm: float
    floor_to_floor_mm: float | None = None
    plan_floor_id: str | None = None
    revit_level_name: str | None = None


class NStack(BaseModel):
    id: str
    number: int
    mark_base: str                 # "C12", or "ST3" for a stub column
    kind: Literal["column", "stub"] = "column"
    grid_ref: str | None = None
    centre: Point2                 # centre on the lowest floor
    floors: list[str] = Field(default_factory=list)          # floor ids where the column exists, bottom to top
    column_ids: dict[str, str] = Field(default_factory=dict)  # floor id -> normalised column id
    client_marks: list[str] = Field(default_factory=list)


class NColumn(BaseModel):
    id: str
    floor_id: str
    stack_id: str
    mark: str                      # "C12-300X900"
    mark_lines: list[str] = Field(default_factory=list)   # as drawn; a shear wall mark is split over two
    shape: Literal["rect", "circle", "polygon"]
    center: Point2
    width_mm: float | None = None
    depth_mm: float | None = None
    rotation_deg: float = 0.0
    diameter_mm: float | None = None
    outline: list[Point2]
    stops_here: bool = False       # not present on the floor above
    starts_here: bool = False      # not present on the floor below
    wall_like: bool = False
    size_source: str = "unknown"
    mark_position: Point2
    mark_rotation_deg: float = 0.0
    mark_height_mm: float | None = None    # shrunk to fit this member; None means the spec height
    client_mark: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    source_handles: list[str] = Field(default_factory=list)


class NBeam(BaseModel):
    id: str
    floor_id: str
    run_id: str                    # extraction beam id this span came from
    span_index: int
    mark: str                      # "B13-300X750"
    start: Point2
    end: Point2
    length_mm: float
    width_mm: float
    depth_mm: float | None = None
    depth_alt_mm: float | None = None
    depth_tip_mm: float | None = None      # tapered cantilever: depth at the free end
    cantilever: bool = False               # one end free
    angle_deg: float
    outline: list[Point2]
    inverted: bool = False
    top_offset_mm: float = 0.0             # beam top relative to the level (SSL); inverted beams sit above
    support_start: str | None = None   # stack id, beam id or None (free end)
    support_end: str | None = None
    size_source: str = "unknown"
    depth_source: str = "unknown"
    depth_rule: str | None = None          # the schedule stated a rule: slab_thickness | layout
    mark_position: Point2
    mark_rotation_deg: float = 0.0
    client_mark: str | None = None
    source_handles: list[str] = Field(default_factory=list)


class NPanel(BaseModel):
    id: str
    floor_id: str
    kind: Literal["slab", "cantilever", "ramp", "opening", "stair"] = "slab"   # cantilever = chajja / balcony with a free edge
    mark: str                      # "S16-200THK" / "CS3-100THK"
    thickness_mm: float | None = None
    thickness_source: str = "unknown"
    outline: list[Point2]
    bulges: list[float] = Field(default_factory=list)    # per outline vertex: DXF bulge of the segment to the next vertex (0 = straight)
    holes: list[list[Point2]] = Field(default_factory=list)   # interior cut-outs (inner loops of the Revit sketch)
    area_m2: float
    centroid: Point2
    mark_position: Point2
    sunk_mm: float | None = None
    sunk_source: str | None = None         # tag | legend
    #: when the sunk area is only a pocket in this panel rather than the whole of it, the rings
    #: of those pockets. Empty means the whole panel is sunk.
    sunk_outlines: list[list[Point2]] = Field(default_factory=list)
    top_offset_mm: float = 0.0             # slab top relative to the level (SSL); negative = below
    top_offset_rule: str | None = None     # beam_bottom | cantilever_bottom_align | sunk
    support_depth_mm: float | None = None  # deepest adjacent beam
    cantilever: bool = False
    slope_ratio: str | None = None         # ramps: "1:8"
    direction: str | None = None           # ramps: UP | DN (looking along the arrow)
    arrow: list[Point2] = Field(default_factory=list)      # ramps: arrow line as drawn
    fold_ids: list[str] = Field(default_factory=list)
    opening_ids: list[str] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)       # extraction slab ids used
    bounded_by: list[str] = Field(default_factory=list)    # beam / column ids around the panel


class NFold(BaseModel):
    """A folded (lowered) part of a slab: hatched region on CH-S-SLAB-FOLD, lower side inside (answer 3C).

    Revit: the panel splits into the outer part at the panel level and this region lowered by
    ``fold_mm``, joined by a vertical slab of ``vertical_thickness_mm`` along the outline (answer 6A).
    """

    id: str
    floor_id: str
    panel_id: str | None = None
    outline: list[Point2]
    fold_mm: float | None = None
    vertical_thickness_mm: float | None = None
    mark: str = ""
    mark_position: Point2
    source_ids: list[str] = Field(default_factory=list)


class NPile(BaseModel):
    """A pile under a pile cap; modelled in Revit as a round column."""

    id: str
    floor_id: str
    center: Point2
    diameter_mm: float | None = None
    pilecap_id: str | None = None
    source_id: str | None = None


class NFooting(BaseModel):
    id: str
    floor_id: str
    kind: Literal["footing", "combined", "raft", "pilecap", "pit", "fold", "sunk"]
    mark: str
    mark_lines: list[str] = Field(default_factory=list)
    shape: Literal["rect", "circle", "polygon"]
    center: Point2
    width_mm: float | None = None
    depth_mm: float | None = None
    rotation_deg: float = 0.0
    thickness_mm: float | None = None
    fold_mm: float | None = None
    sunk_mm: float | None = None
    outline: list[Point2]
    stack_ids: list[str] = Field(default_factory=list)
    pit_depth_mm: float | None = None           # lift pits: depth below the floor level
    pcc_thickness_mm: float | None = None       # PCC (lean concrete) below the footing
    pcc_projection_mm: float | None = None
    pcc_outline: list[Point2] = Field(default_factory=list)
    pile_ids: list[str] = Field(default_factory=list)
    client_mark: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class NGrid(BaseModel):
    id: str
    floor_id: str
    label: str
    axis: Literal["X", "Y", "other"]
    offset_mm: float
    start: Point2
    end: Point2
    bubble_centres: list[Point2] = Field(default_factory=list)
    source_id: str | None = None


class NOpening(BaseModel):
    id: str
    floor_id: str
    label: str | None = None
    outline: list[Point2]
    center: Point2
    panel_id: str | None = None
    source_id: str | None = None


class NWall(BaseModel):
    id: str
    floor_id: str
    mark: str | None = None
    outline: list[Point2]
    center: Point2
    thickness_mm: float | None = None
    length_mm: float | None = None
    structural: bool = True                 # only RCC walls are drawn and modelled (answer 6B)
    top_offset_mm: float = 0.0              # wall top below the level above by the depth of the beam on it (answer 6A)
    beam_above_id: str | None = None
    source_id: str | None = None


class NJoint(BaseModel):
    id: str
    floor_id: str
    start: Point2
    end: Point2
    source_id: str | None = None


class NStair(BaseModel):
    id: str
    floor_id: str
    mark: str | None = None
    waist_mm: float | None = None
    direction: str | None = None            # UP | DN from the client texts
    tread_count: int | None = None          # tread lines counted inside the outline (answer 5A)
    riser_count_est: int | None = None      # treads + 1
    landing_level_est_mm: float | None = None   # half the floor-to-floor height (answer 5B), flagged
    estimated: bool = False
    outline: list[Point2] = Field(default_factory=list)
    lines: list[list[Point2]] = Field(default_factory=list)
    center: Point2
    source_id: str | None = None


class MarkMap(BaseModel):
    element_id: str
    floor_id: str
    kind: str
    mark: str
    client_mark: str | None = None
    client_tags: list[TagRef] = Field(default_factory=list)


class NSummary(BaseModel):
    floors: int = 0
    levels: int = 0
    stacks: int = 0
    columns: int = 0
    beams: int = 0
    panels: int = 0
    footings: int = 0
    grids: int = 0
    openings: int = 0
    walls: int = 0
    stairs: int = 0
    errors: int = 0
    warnings: int = 0
    infos: int = 0


class NormalizedProject(BaseModel):
    schema_version: str = NORMALIZED_SCHEMA_VERSION
    generator: str = f"c2b {__version__}"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    units: Literal["mm"] = "mm"
    source_file: str
    source_schema_version: str
    spec_name: str
    floors: list[NFloor] = Field(default_factory=list)
    levels: list[NLevel] = Field(default_factory=list)
    stacks: list[NStack] = Field(default_factory=list)
    columns: list[NColumn] = Field(default_factory=list)
    beams: list[NBeam] = Field(default_factory=list)
    panels: list[NPanel] = Field(default_factory=list)
    footings: list[NFooting] = Field(default_factory=list)
    grids: list[NGrid] = Field(default_factory=list)
    openings: list[NOpening] = Field(default_factory=list)
    walls: list[NWall] = Field(default_factory=list)
    stairs: list[NStair] = Field(default_factory=list)
    joints: list[NJoint] = Field(default_factory=list)
    folds: list[NFold] = Field(default_factory=list)
    piles: list[NPile] = Field(default_factory=list)
    level_reference: str = "SSL"
    mark_map: list[MarkMap] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    summary: NSummary = Field(default_factory=NSummary)

    def recompute_summary(self) -> None:
        self.summary = NSummary(
            floors=len(self.floors), levels=len(self.levels), stacks=len(self.stacks), columns=len(self.columns), beams=len(self.beams),
            panels=len(self.panels), footings=len(self.footings), grids=len(self.grids), openings=len(self.openings), walls=len(self.walls), stairs=len(self.stairs),
            errors=sum(1 for d in self.diagnostics if d.severity == "ERROR"),
            warnings=sum(1 for d in self.diagnostics if d.severity == "WARNING"),
            infos=sum(1 for d in self.diagnostics if d.severity == "INFO"),
        )
        for f in self.floors:
            f.counts = {
                "columns": sum(1 for c in self.columns if c.floor_id == f.id),
                "beams": sum(1 for b in self.beams if b.floor_id == f.id),
                "panels": sum(1 for p in self.panels if p.floor_id == f.id and p.kind == "slab"),
                "footings": sum(1 for x in self.footings if x.floor_id == f.id),
                "grids": sum(1 for g in self.grids if g.floor_id == f.id),
                "openings": sum(1 for o in self.openings if o.floor_id == f.id),
                "walls": sum(1 for w in self.walls if w.floor_id == f.id),
            }
