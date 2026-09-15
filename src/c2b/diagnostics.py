"""Diagnostics collector.

Every extractor reports what it could not understand through this object. The
result is the "drawing checker" output: the same run that extracts the data
also produces the error list, so the two can never disagree.
"""
from __future__ import annotations

from .schema import Diagnostic, Point2

# Codes are stable identifiers; downstream tooling and people filter on them.
CODES: dict[str, str] = {
    "UNITS_GUESSED": "Drawing units were guessed from extents; confirm with --units",
    "COORDS_LARGE": "Coordinates are very large (georeferenced?); floor origins compensate",
    "Z_NONZERO": "Entities have non-zero Z; flattened to the XY plane",
    "DUPLICATE_ENTITY": "Exact duplicate entities on the same layer; only one kept",
    "LAYER_UNMAPPED": "Layer with geometry that no role matched; review the profile",
    "LAYER_LOW_CONFIDENCE": "Layer role guessed with low confidence",
    "LAYER_HIDDEN": "Layer looks like hidden-line content and was skipped",
    "NO_BOUNDARY": "No floor boundaries found; the whole drawing is one floor",
    "FLOOR_NO_ORIGIN": "Floor boundary without an Origin point; boundary corner used",
    "FLOOR_NO_LABEL": "Floor name could not be read from the drawing",
    "BOUNDARY_NOT_CLOSED": "Boundary polyline is not closed",
    "POLYLINE_NOT_CLOSED": "Outline polyline is not closed; closed automatically within tolerance",
    "POLYLINE_OPEN_REJECTED": "Outline polyline is open beyond tolerance; ignored",
    "COLUMN_NO_SIZE": "Column has no size from tag, schedule, block or layer; drawn size used",
    "COLUMN_SIZE_MISMATCH": "Column tag size differs from drawn size",
    "COLUMN_ODD_SIZE": "Column size is outside the expected range",
    "COLUMN_WALL_LIKE": "Column geometry looks like a shear wall",
    "COLUMN_MULTI_SIZE": "Column has conflicting size tags",
    "BEAM_NO_DEPTH": "Beam depth unknown (no tag, schedule, layer size or note default)",
    "BEAM_NO_WIDTH_TAG": "Beam width taken from drawn edges only",
    "BEAM_WIDTH_MISMATCH": "Beam tag width differs from drawn width",
    "BEAM_MULTI_SIZE": "Beam has conflicting size tags along its length",
    "BEAM_UNPAIRED_LINES": "Lines on a beam layer could not be paired into beams",
    "BEAM_DEFAULT_DEPTH": "Beam depth taken from a general note",
    "SLAB_NO_THICKNESS": "Slab tag has no thickness and no schedule match",
    "SLAB_NONE_ON_FLOOR": "No slab thickness information found on this floor",
    "SLAB_DEFAULT_THICKNESS": "Slab thickness default read from a general note",
    "FOOTING_NO_SIZE": "Footing has no thickness or schedule size",
    "TAG_UNPARSED": "Tag text could not be parsed",
    "TAG_UNASSIGNED": "Tag could not be matched to any element",
    "TAG_CATEGORY_MISMATCH": "Tag prefix suggests a different element category than its layer",
    "SCHEDULE_MARK_MISSING": "Mark used on plan does not exist in any schedule",
    "SCHEDULE_PLAN_MISMATCH": "Plan tag size differs from schedule size for the same mark",
    "SCHEDULE_PARSE": "Schedule table could not be parsed completely",
    "GRID_NO_LABEL": "Grid line without a label",
    "GRID_DUPLICATE_LABEL": "Two non-collinear grid lines share the same label",
    "NO_GRIDS": "No grid lines found on this floor",
    "ELEMENT_OUTSIDE_FLOORS": "Structural entities lie outside every floor boundary",
    "BLOCK_EXPLODED": "Block reference exploded to read its content",
    "DEFAULT_APPLIED": "A default value from a note was applied",
    # --- normaliser (utility 3) ---
    "LEVELS_MISSING": "No level elevations supplied; elevation frame not drawn",
    "LEVEL_ROW_UNMATCHED": "Level schedule row does not match a plan floor",
    "STACK_JUMP": "Column matched to the stack below with an offset",
    "STACK_ORPHAN": "Column starts above a floor without a column under it",
    "STACK_SIZE_CHANGE": "Column size changes between floors",
    "SPAN_DROPPED": "Beam span shorter than the minimum was dropped",
    "SPAN_FREE_END": "Beam span ends without a support (cantilever or missing column)",
    "BEAM_OVERLAP": "Two beams overlap along their length",
    "PANEL_NO_TAG": "Slab panel without a thickness tag inside it",
    "PANEL_MULTI_TAG": "Slab panel contains tags with different thicknesses",
    "PANEL_LARGE": "Slab panel larger than expected; a beam may be missing",
    "PANEL_TAG_OUTSIDE": "Slab tag lies in no panel",
    "PANEL_NO_LATTICE": "Floor has beams but no closed panels could be formed",
    "FOOTING_NO_COLUMN": "Footing has no column stack over it",
    "COLUMN_NO_FOOTING": "Column stack on the foundation floor has no footing",
    "MARK_FIT": "Mark does not fit inside the element; placed outside",
    "SEED_MISSING": "Seed template DXF not found; layers created from the spec instead",
    "NAME_NORMALISED": "Floor name normalised for the template",
    "PANEL_OFFSET_UNKNOWN": "Panel level offset could not be computed (beam depth or thickness missing)",
    "BEAM_ALT_DEPTH": "Beam tag carries a second depth without a free end",
    "PIT_DEPTH_UNKNOWN": "Lift pit without a depth text or level",
    "STAIR_ESTIMATED": "Stair risers and landing level estimated from the plan; verify against a section",
    "FOLD_THICKNESS_UNKNOWN": "Fold has no vertical slab thickness on its tag",
    "PILE_NO_DIAMETER": "Pile drawn without a diameter",
    # --- round trip (utility 4) ---
    "RT_FLOOR_NO_ORIGIN": "Plan frame in the template DXF has no Origin point",
    "RT_LEVELS_RELATIVE": "Level lines carry no elevation data; elevations measured from the lowest line",
    "RT_NO_ID": "Entity on a C2B layer without a C2B id (added or copied by hand)",
    "RT_ORPHAN_MARK": "Mark text in the drawing belongs to no element",
}


class DiagnosticsCollector:
    def __init__(self) -> None:
        self.items: list[Diagnostic] = []

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        *,
        floor_id: str | None = None,
        layer: str | None = None,
        handle: str | None = None,
        element_id: str | None = None,
        location: tuple[float, float] | None = None,
    ) -> Diagnostic:
        if code not in CODES:
            raise KeyError(f"Unknown diagnostic code {code!r}; add it to diagnostics.CODES")
        d = Diagnostic(
            severity=severity, code=code, message=message, floor_id=floor_id, layer=layer, handle=handle,
            element_id=element_id, location=Point2(x=location[0], y=location[1]) if location else None,
        )
        self.items.append(d)
        return d

    def error(self, code: str, message: str, **ctx) -> Diagnostic:
        return self.add("ERROR", code, message, **ctx)

    def warning(self, code: str, message: str, **ctx) -> Diagnostic:
        return self.add("WARNING", code, message, **ctx)

    def info(self, code: str, message: str, **ctx) -> Diagnostic:
        return self.add("INFO", code, message, **ctx)

    def counts(self) -> dict[str, int]:
        out = {"ERROR": 0, "WARNING": 0, "INFO": 0}
        for d in self.items:
            out[d.severity] += 1
        return out
