"""How C2B elements become Revit families, types and parameters.

The firm's Revit template decides the family names, so they live in a YAML file rather than
in code. ``c2b revit-plan --write-mapping`` writes a starting point that a Revit user edits
once per template.

The defaults below are read off **R25_TEMPLATE** (`templates/R25_TEMPLATE.template.md`):
every family name, type-name pattern and dimension parameter here exists in that template.
``c2b revit-plan --template <md>`` checks a plan against it and reports anything missing
before Revit is opened.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# Revit gives every instance these; they are never project parameters, so a digest will not
# list them and a "not bound" report must not claim they are missing.
REVIT_BUILTIN_PARAMS = {"Mark", "Comments", "Type Mark", "Type Comments", "Description"}


class TypeRule(BaseModel):
    """One Revit family and how its types are named and sized."""

    family: str                                   # family name in the project, e.g. "CH-Concrete-Rectangular-Column"
    type_name: str = "CH-{w:.0f} X {d:.0f}"       # type name built from the size; created by duplication when missing
    width_param: str | None = "b"                 # type parameter that holds the width
    depth_param: str | None = "h"                 # type parameter that holds the depth
    depth_alt_param: str | None = None            # second depth, for a stepped or tapered member
    diameter_param: str | None = None
    thickness_param: str | None = None
    create_missing_types: bool = True             # duplicate the nearest type and set the parameters
    fallback_type: str | None = None              # the type duplicated to make a missing one


class SystemTypeRule(BaseModel):
    """A system family (floor, wall, foundation slab): types are picked by name, never created by parameter."""

    family: str = ""                              # for the template check; Revit finds system types by name alone
    type_name: str = "{thk:.0f}mm"
    create_missing_types: bool = True
    base_type: str | None = None                  # the type duplicated to make a missing one
    fallback_type: str | None = None


class RevitMapping(BaseModel):
    name: str = "CH structural template (R25)"
    revit_version: str = "2025"
    units: Literal["mm"] = "mm"
    level_prefix: str = ""                        # prepended to the level names from the workbook
    create_levels: bool = True
    create_grids: bool = True
    grid_prefix: str = ""

    # -- where the mark and the C2B id are written --------------------------
    # Every name that exists on the element is written, and the run reports which ones took.
    # R25_TEMPLATE binds the firm's own CH- names; "Mark" is Revit's built-in and is always
    # there, so a mark is never lost even on a template that binds nothing.
    mark_params: list[str] = Field(default_factory=lambda: ["CH-ScheduleMark", "Mark"])
    id_params: list[str] = Field(default_factory=lambda: ["CH-ID"])
    # The level an element was built on, written where the firm's schedules read it from.
    level_params: list[str] = Field(default_factory=lambda: ["CH-LEVEL"])
    comment_param: str | None = "Comments"

    # -- structural columns --------------------------------------------------
    column: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Rectangular-Column", type_name="CH-{w:.0f} X {d:.0f}",
        width_param="b", depth_param="h", fallback_type="CH-300 X 600"))
    column_round: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Round-Column", type_name="CH-{dia:.0f}",
        width_param=None, depth_param=None, diameter_param="b", fallback_type="CH-300"))

    # -- structural framing --------------------------------------------------
    beam: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Rectangular-Beam", type_name="CH-{w:.0f} X {d:.0f}",
        width_param="b", depth_param="h", fallback_type="CH-300 X 600"))
    # A beam the drawing gives two depths (B5-200X900/600). A normal beam hangs below the slab,
    # so its top is flush and the step is underneath -> "Bottom"; an inverted beam steps up -> "Top".
    beam_step: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Step-Beam-Bottom", type_name="CH-{w:.0f} X {d:.0f}/{d2:.0f}",
        width_param="W", depth_param="H", depth_alt_param="H1", fallback_type="CH-200 X 450/700"))
    beam_step_inverted: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Step-Beam-Top", type_name="CH-{w:.0f} X {d:.0f}/{d2:.0f}",
        width_param="W", depth_param="H", depth_alt_param="H1", fallback_type="CH-200 X 550/600"))
    beam_taper: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Tapered-Beam-Bottom", type_name="CH-{w:.0f} X {d:.0f}/{d2:.0f}",
        width_param="W", depth_param="H", depth_alt_param="H1", fallback_type="CH-300 X 750/1000"))
    beam_taper_inverted: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Tapered-Beam-Top", type_name="CH-{w:.0f} X {d:.0f}/{d2:.0f}",
        width_param="W", depth_param="H", depth_alt_param="H1", fallback_type="CH-300 X 750/1000"))
    two_depth_beam: Literal["step", "taper"] = "step"     # what a mark like 200X900/600 means on this client's drawings

    # -- foundations ---------------------------------------------------------
    footing: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Rectangular-Footing", type_name="CH-{w:.0f} X {d:.0f} X {thk:.0f}",
        width_param="Width", depth_param="Length", thickness_param="Foundation Thickness",
        fallback_type="CH-1200 X 1800 X 600"))
    pile: TypeRule = Field(default_factory=lambda: TypeRule(
        family="CH-Concrete-Round-Column", type_name="CH-{dia:.0f}",
        width_param=None, depth_param=None, diameter_param="b", fallback_type="CH-300"))

    # -- system families -----------------------------------------------------
    floor: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(
        family="Floor", type_name="{thk:.0f} THK. RCC SLAB", base_type="150 THK. RCC SLAB"))
    ramp_floor: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(
        family="Floor", type_name="{thk:.0f} THK. RCC RAMP", base_type="150 THK. RCC SLAB"))
    raft: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(
        family="Foundation Slab", type_name="CH-FOOTING-{thk:.0f}", base_type="CH-FOOTING-600"))
    pcc: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(
        family="Foundation Slab", type_name="CH-PCC-{thk:.0f}", base_type="CH-SLAB-150"))
    wall: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(
        family="Basic Wall", type_name="CH-SHEAR-WALL-{thk:.0f}", base_type="CH-SHEAR-WALL-300"))

    # -- what to build -------------------------------------------------------
    build: dict[str, bool] = Field(default_factory=lambda: {
        "levels": True, "grids": True, "columns": True, "beams": True, "floors": True,
        "foundations": True, "pcc": True, "piles": True, "walls": True, "shafts": True, "stairs": False,
    })
    # A leg of a shaped wall is a column in the drawing and in the schedule, and C2B split it as
    # one, so it is a Structural Column by default -- one Revit element per tagged leg. Switch to
    # "wall" when the client wants shear walls modelled as walls; "wall_like_min_thickness_mm"
    # then keeps the thin ones as columns.
    wall_like_as: Literal["column", "wall"] = "column"
    wall_like_min_thickness_mm: float = 0.0
    structural_only: bool = True                  # skip non-structural walls
    shaft_from: list[str] = Field(default_factory=lambda: ["LIFT", "SHAFT", "STAIR"])   # cut-out labels that become shafts
    column_top_attachment: Literal["level", "beam_soffit"] = "level"
    # A column holds up its own floor, so that floor's level is its top and the level beneath is
    # its base. On the lowest level there is nothing beneath, so it hangs this far below its own
    # level instead of not being built.
    column_min_height_mm: float = 3000.0
    # ...but only where nothing is drawn to hold it. A foundation plan draws the columns again
    # at their base, and the column between foundation and ground is already built from the
    # ground floor's own outline, so hanging another one below the foundation makes a column
    # standing on nothing and counts the same member twice.
    column_below_lowest_when_founded: bool = False

    # A beam or a slab the drawing never sizes. C2B leaves it empty through the model and the
    # template DXF, where "300X?" is a drafter's cue, but a Revit model cannot hold a beam with
    # no depth and dropping it loses the member altogether. A default set here builds it and
    # says so on the element.
    default_beam_depth_mm: float | None = None
    default_slab_thickness_mm: float | None = None
    # A beam's height in Revit is decided by its family's own z justification and offset unless
    # something states them. CH-Concrete-Rectangular-Beam carries Top / -1500, so every beam sat
    # 1500 below its level on every floor whatever the plan said. C2B states them instead: the
    # top face flush with the level (top of structural slab), moved by the element's own offset,
    # which is what carries an inverted beam up and a sunk one down.
    beam_z_justification: Literal["top", "center", "bottom", "origin"] = "top"
    beam_top_at_level: bool = True                # beam top flush with the level, offset by the element's top offset
    # The firm's template ships sample grids (1, 2, 3, A-E). A client grid of the same name
    # cannot be created beside one: Revit refuses, and the grid is simply lost.
    grid_name_clash: Literal["rename_existing", "reuse", "skip"] = "rename_existing"
    round_sizes_to_mm: float = 5.0                # sizes are rounded to this before naming a type

    @classmethod
    def load(cls, path: str | Path) -> RevitMapping:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def save(self, path: str | Path) -> None:
        header = ("# C2B -> Revit mapping. Edit the family and type names to match your Revit template,\n"
                  "# then keep this file with the project. 'c2b revit-plan --mapping <this file>' uses it.\n"
                  "# Check it against the template first: 'c2b revit-plan <json> --template <template>.md'\n")
        Path(path).write_text(header + yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")

    # -- rules by name, for the template check -------------------------------
    def loadable_rules(self) -> dict[str, TypeRule]:
        return {n: getattr(self, n) for n in
                ("column", "column_round", "beam", "beam_step", "beam_step_inverted",
                 "beam_taper", "beam_taper_inverted", "footing", "pile")}

    def system_rules(self) -> dict[str, SystemTypeRule]:
        return {n: getattr(self, n) for n in ("floor", "ramp_floor", "raft", "pcc", "wall")}

    def beam_rule_for(self, inverted: bool, tapered: bool) -> TypeRule:
        """Which framing family a two-depth beam belongs to."""
        if tapered or self.two_depth_beam == "taper":
            return self.beam_taper_inverted if inverted else self.beam_taper
        return self.beam_step_inverted if inverted else self.beam_step
