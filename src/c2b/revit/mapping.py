"""How C2B elements become Revit families, types and parameters.

The firm's Revit template decides the family names, so they live in a YAML file rather than
in code. ``c2b revit-plan --write-mapping`` writes a starting point that a Revit user edits
once per template.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class TypeRule(BaseModel):
    """One Revit family and how its types are named and sized."""

    family: str                                   # family name in the project, e.g. "M_Concrete-Rectangular-Column"
    type_name: str = "{w:.0f} x {d:.0f}mm"        # type name built from the size; created by duplication when missing
    width_param: str | None = "b"                 # type parameter that holds the width
    depth_param: str | None = "h"                 # type parameter that holds the depth
    diameter_param: str | None = None
    thickness_param: str | None = None
    create_missing_types: bool = True             # duplicate the nearest type and set the parameters
    fallback_type: str | None = None              # used when a type cannot be created


class SystemTypeRule(BaseModel):
    """A system family (floor, wall, foundation slab): types are picked by name, never created by parameter."""

    type_name: str = "{thk:.0f}mm"
    create_missing_types: bool = True
    base_type: str | None = None                  # the type duplicated to make a missing one
    fallback_type: str | None = None


class RevitMapping(BaseModel):
    name: str = "CH structural template"
    revit_version: str = "2025"
    units: Literal["mm"] = "mm"
    level_prefix: str = ""                        # prepended to the level names from the workbook
    create_levels: bool = True
    create_grids: bool = True
    grid_prefix: str = ""

    column: TypeRule = Field(default_factory=lambda: TypeRule(family="M_Concrete-Rectangular-Column"))
    column_round: TypeRule = Field(default_factory=lambda: TypeRule(
        family="M_Concrete-Round-Column", type_name="{dia:.0f}mm", width_param=None, depth_param=None, diameter_param="b"))
    beam: TypeRule = Field(default_factory=lambda: TypeRule(family="M_Concrete-Rectangular Beam"))
    footing: TypeRule = Field(default_factory=lambda: TypeRule(
        family="M_Footing-Rectangular", type_name="{w:.0f} x {d:.0f} x {thk:.0f}mm", width_param="Width", depth_param="Length", thickness_param="Thickness"))
    pile: TypeRule = Field(default_factory=lambda: TypeRule(
        family="M_Concrete-Round-Column", type_name="{dia:.0f}mm", width_param=None, depth_param=None, diameter_param="b"))

    floor: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(type_name="RCC {thk:.0f}mm", base_type="Generic 150mm"))
    ramp_floor: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(type_name="RCC RAMP {thk:.0f}mm", base_type="Generic 150mm"))
    raft: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(type_name="RAFT {thk:.0f}mm", base_type="Generic 300mm"))
    pcc: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(type_name="PCC {thk:.0f}mm", base_type="Generic 100mm"))
    wall: SystemTypeRule = Field(default_factory=lambda: SystemTypeRule(type_name="RCC {thk:.0f}mm", base_type="Generic - 200mm"))

    # what to build
    build: dict[str, bool] = Field(default_factory=lambda: {
        "levels": True, "grids": True, "columns": True, "beams": True, "floors": True,
        "foundations": True, "pcc": True, "piles": True, "walls": True, "shafts": True, "stairs": False,
    })
    structural_only: bool = True                  # skip non-structural walls
    shaft_from: list[str] = Field(default_factory=lambda: ["LIFT", "SHAFT", "STAIR"])   # cut-out labels that become shafts
    column_top_attachment: Literal["level", "beam_soffit"] = "level"
    beam_top_at_level: bool = True                # beam top flush with the level, offset by the element's top offset
    round_sizes_to_mm: float = 5.0                # sizes are rounded to this before naming a type

    @classmethod
    def load(cls, path: str | Path) -> RevitMapping:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def save(self, path: str | Path) -> None:
        header = ("# C2B -> Revit mapping. Edit the family and type names to match your Revit template,\n"
                  "# then keep this file with the project. 'c2b revit-plan --mapping <this file>' uses it.\n")
        Path(path).write_text(header + yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
