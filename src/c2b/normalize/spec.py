"""Template specification.

Every convention observed in the firm's template drawing is a field here, so a
change of convention is a YAML edit, not a code change. Defaults reproduce
``CH-TEMPLATE-REMARKED.dxf``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LayerDef(BaseModel):
    name: str
    color: int = 7
    lineweight: int = 18          # 1/100 mm; -3 = default
    linetype: str = "Continuous"


class TextSpec(BaseModel):
    style: str = "JetBrains Mono"
    font: str = "JetBrainsMono-VariableFont_wght.ttf"
    fallback_font: str = "arial.ttf"
    mark_height: float = 125.0
    note_height: float = 250.0
    title_height: float = 500.0
    width_factor: float = 0.6         # approximate glyph width / height, used for fit checks


class MarkFormats(BaseModel):
    """Python format strings. Available fields: n, w, d, dia, thk, fold, sunk, client_mark."""
    column: str = "C{n}-{w:.0f}X{d:.0f}"
    column_circle: str = "C{n}-{dia:.0f}DIA"
    beam: str = "B{n}-{w:.0f}X{d:.0f}"
    beam_no_depth: str = "B{n}-{w:.0f}X?"
    slab: str = "S{n}-{thk:.0f}THK"
    slab_no_thickness: str = "S{n}-?THK"
    slab_cantilever: str = "CS{n}-{thk:.0f}THK"
    footing: str = "F{n}-{thk:.0f}THK"
    footing_no_thickness: str = "F{n}-?THK"
    footing_fold_line: str = "{fold:.0f} FOLD"
    footing_sunk_line: str = "{sunk:.0f} SUNK"
    raft: str = "RF{n}-{thk:.0f}THK"
    stair: str = "ST{n}-{thk:.0f}THK"
    level: str = "{n:02d} {name}"
    plan_title: str = "LAYOUT PLAN - {name}"
    elevation_title: str = "ELEVATION - LEVEL"


class Placement(BaseModel):
    column_mark: Literal["above", "centre", "auto"] = "centre"     # answer 1C: always inside
    column_mark_gap_mm: float = 120.0       # gap between column top edge and mark centre line (for "above")
    column_mark_rotate: Literal["none", "long-side"] = "long-side"  # answer 7: text runs along the longer side
    beam_mark: Literal["centre"] = "centre"
    beam_mark_rotate: bool = True           # answer 7B: text runs along the beam
    slab_mark: Literal["centroid", "representative"] = "representative"
    grid_bubble_radius_mm: float = 300.0
    grid_extension_mm: float = 1500.0       # how far grid lines run past the outermost member
    grid_bubble_end: Literal["start", "both"] = "start"


class Numbering(BaseModel):
    # row-major: A1, A2, ... then B1, B2 ... (rows bottom-up, left to right); column-major: down grid 1, then grid 2 ...
    columns: Literal["row-major", "column-major", "rows-top-down", "grid"] = "row-major"     # answer 2B
    keep_client_marks: bool = True          # answer 2C / 20C: a client column mark wins, numbering fills the gaps
    keep_client_beam_marks: bool = True     # answer 8: client beam marks win, numbering fills the gaps
    beams_per_floor: bool = True
    slabs_per_floor: bool = True
    footings_per_floor: bool = True


class SplitRules(BaseModel):
    irregular_support_to_centre: bool = True   # answer 5: beams end at the centre of round / rotated / odd-shaped columns
    irregular_angle_tol_deg: float = 3.0
    at_columns: bool = True
    at_walls: bool = True
    trim_at_beam_faces: bool = True         # a beam ending on another beam stops at its face
    split_crossing_by: Literal["depth", "none"] = "depth"   # at an X crossing the shallower beam is split
    min_span_mm: float = 150.0
    support_cover_ratio: float = 0.5        # a column must cover this share of the beam width to split it


class PanelRules(BaseModel):
    arc_fit_tol_mm: float = 2.5             # vertices this close to a circular column are replaced by a true arc (bulge)
    span_extend_mm: float = 150.0           # spans are lengthened this much at each end for the lattice only, so beam corners reach into round/odd supports
    min_area_m2: float = 0.25
    max_area_m2: float = 250.0
    subtract_openings: bool = True
    keep_arcs: bool = True                  # answer 10B: true arcs (bulges) at circular columns


class HatchMap(BaseModel):
    """Legend: which hatch pattern says what."""
    column_stop: str = "ANSI31"
    slab_sunk_75: str = "ANGLE"
    slab_sunk_150: str = "HEX"
    slab_at_beam_bottom: str = "ANSI33"
    raft_fold_sunk: str = "ANSI37"
    scale: float = 20.0
    hatch_all_columns: bool = False          # template hatched every column; legend says the hatch means "stops here"


class FrameLayout(BaseModel):
    keep_client_frames: bool = True          # reuse the client's Boundary rectangles and Origin points
    margin_mm: float = 4000.0                # used when frames must be built from the structure extents
    bottom_band_mm: float = 5000.0           # extra band under the plan for title, notes and legend
    title_above_band_mm: float = 770.0       # title centre line above the original frame bottom
    notes_offset_x_mm: float = -5300.0       # from frame centre
    notes_first_line_below_mm: float = 30.0  # below the original frame bottom
    notes_line_spacing_mm: float = 600.0
    legend_from_right_mm: float = 5660.0
    legend_top_above_mm: float = 735.0       # legend first box top above the original frame bottom
    legend_row_mm: float = 500.0
    elevation_frame_gap_mm: float = 6800.0   # gap between the elevation frame and the first plan frame
    level_line_inset_left_mm: float = 8050.0
    level_line_length_mm: float = 33940.0
    level_dim_offset_mm: float = 800.0       # dimension line right of the level line start
    level_base_above_bottom_mm: float = 12250.0   # y of the lowest level above the frame bottom


class TemplateSpec(BaseModel):
    name: str = "CH"
    description: str | None = "Defaults reproduce CH-TEMPLATE-REMARKED.dxf"
    seed_dxf: str | None = None              # template DXF whose tables (layers, styles, dimstyle, legend) are reused
    dimstyle: str = "Diagonal_-_2_5mm_JetBrains_Mono"
    grid_linetype: str = "Grid Line"
    grid_ltscale: float = 50.0
    xdata_appid: str = "C2B"
    layers: dict[str, LayerDef] = Field(default_factory=lambda: {
        "boundary": LayerDef(name="0-Boundary", color=40, lineweight=30),
        "origin": LayerDef(name="0-Origin", color=40, lineweight=30),
        "grid": LayerDef(name="CH-GRID", color=8, lineweight=9, linetype="Grid Line"),
        "grid_mark": LayerDef(name="CH-GRID-MARK", color=8, lineweight=9),
        "column": LayerDef(name="CH-S-COLUMN", color=12, lineweight=18),
        "column_hatch": LayerDef(name="CH-S-COLUMN-HATCH", color=252, lineweight=18),
        "column_mark": LayerDef(name="CH-S-COLUMN-MARK", color=171, lineweight=9),
        "beam": LayerDef(name="CH-S-BEAM", color=3, lineweight=18),
        "beam_cl": LayerDef(name="CH-S-BEAM-CL", color=3, lineweight=9, linetype="Dash"),
        "beam_mark": LayerDef(name="CH-S-BEAM-MARK", color=2, lineweight=9),
        "slab": LayerDef(name="CH-S-SLAB", color=192, lineweight=18),
        "slab_mark": LayerDef(name="CH-S-SLAB-MARK", color=11, lineweight=9),
        "slab_sunk": LayerDef(name="CH-S-SLAB-SUNK", color=8, lineweight=18),
        "slab_fold": LayerDef(name="CH-S-SLAB-FOLD", color=9, lineweight=18),
        "footing": LayerDef(name="CH-S-FND", color=3, lineweight=18),
        "footing_mark": LayerDef(name="CH-S-FND-MARK", color=3, lineweight=18),
        "footing_fold": LayerDef(name="CH-S-FND-FOLD", color=9, lineweight=18),
        "footing_sunk": LayerDef(name="CH-S-FND-SUNK", color=9, lineweight=18),
        "raft": LayerDef(name="CH-S-RAFT", color=2, lineweight=18),
        "raft_mark": LayerDef(name="CH-S-RAFT-MARK", color=2, lineweight=18),
        "raft_fold": LayerDef(name="CH-S-RAFT-FOLD", color=9, lineweight=18),
        "raft_sunk": LayerDef(name="CH-S-RAFT-SUNK", color=9, lineweight=18),
        "cutout": LayerDef(name="CH-CUTOUT", color=12, lineweight=18),
        "stairs": LayerDef(name="CH-STAIRS", color=31, lineweight=18),
        "stairs_mark": LayerDef(name="CH-STAIRS-MARK", color=31, lineweight=18),
        "level": LayerDef(name="CH-LEVEL", color=8, lineweight=9),
        "level_mark": LayerDef(name="CH-LEVEL-MARK", color=254, lineweight=9),
        "dim": LayerDef(name="CH-DIM", color=211, lineweight=9),
        "hatch": LayerDef(name="CH-HATCH", color=252, lineweight=-3),
        "legend": LayerDef(name="CH-LEGEND", color=40, lineweight=9),
        "text": LayerDef(name="CH-TEXT", color=7, lineweight=9),
        "wall": LayerDef(name="CH-S-WALL", color=30, lineweight=18),
        "wall_mark": LayerDef(name="CH-S-WALL-MARK", color=30, lineweight=9),
    })
    text: TextSpec = Field(default_factory=TextSpec)
    marks: MarkFormats = Field(default_factory=MarkFormats)
    placement: Placement = Field(default_factory=Placement)
    numbering: Numbering = Field(default_factory=Numbering)
    split: SplitRules = Field(default_factory=SplitRules)
    panels: PanelRules = Field(default_factory=PanelRules)
    hatch: HatchMap = Field(default_factory=HatchMap)
    frame: FrameLayout = Field(default_factory=FrameLayout)
    stack_match_tol_mm: float = 300.0        # centre distance for matching a column to the stack below
    stack_match_min_iou: float = 0.2
    raft_by_client: bool = True              # answer 14C: a raft is one the client calls RF / RAFT / MAT (layer, tag or mark)
    raft_min_area_m2: float = 0.0            # optional size rule (0 = off)
    raft_min_columns: int = 0                # optional stack-count rule (0 = off)
    beam_centreline: bool = True             # answer 6B: centreline on CH-S-BEAM-CL in addition to the outline
    client_notes: bool = True                # answer 18C: client general notes verbatim under each plan
    opening_panel_cover: float = 0.6         # a lattice hole covered this much by openings is a cut-out, not a slab
    stair_panel_cover: float = 0.5           # ... or by stair geometry, a stair
    notes: list[str] = Field(default_factory=list)   # extra note lines written under every plan
    write_generator_note: bool = True
    legend_from_seed: bool = True

    def layer(self, key: str) -> str:
        return self.layers[key].name

    @classmethod
    def load(cls, path: str | Path) -> "TemplateSpec":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def save(self, path: str | Path) -> None:
        header = "# C2B template spec. Every drawing convention of the template DXF lives here.\n"
        Path(path).write_text(header + yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
