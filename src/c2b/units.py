"""Drawing unit resolution.

Everything inside C2B is millimetres. This module works out the factor that
converts drawing units to millimetres, using (in order of trust):

1. an explicit override from the operator,
2. the DXF ``$INSUNITS`` header,
3. a heuristic based on the size of the drawing, which is always reported as
   low confidence so a human checks it.
"""
from __future__ import annotations

from dataclasses import dataclass

# DXF $INSUNITS code -> millimetres per drawing unit.
INSUNITS_TO_MM: dict[int, float] = {
    1: 25.4,        # inches
    2: 304.8,       # feet
    4: 1.0,         # millimetres
    5: 10.0,        # centimetres
    6: 1000.0,      # metres
    10: 914.4,      # yards
    13: 0.001,      # microns
    14: 100.0,      # decimetres
    15: 10_000.0,   # decametres
    16: 100_000.0,  # hectometres
}

INSUNITS_NAMES: dict[int, str] = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "millimetres",
    5: "centimetres",
    6: "metres",
    7: "kilometres",
    10: "yards",
    13: "microns",
    14: "decimetres",
    15: "decametres",
    16: "hectometres",
}

# Names accepted on the command line / in profiles.
UNIT_ALIASES: dict[str, tuple[float, str]] = {
    "mm": (1.0, "millimetres"),
    "millimetre": (1.0, "millimetres"),
    "millimeter": (1.0, "millimetres"),
    "cm": (10.0, "centimetres"),
    "m": (1000.0, "metres"),
    "metre": (1000.0, "metres"),
    "meter": (1000.0, "metres"),
    "in": (25.4, "inches"),
    "inch": (25.4, "inches"),
    "ft": (304.8, "feet"),
    "foot": (304.8, "feet"),
    "feet": (304.8, "feet"),
}


@dataclass(frozen=True)
class UnitResolution:
    """Result of working out the drawing units."""

    scale_to_mm: float
    name: str
    source: str        # "override" | "insunits" | "heuristic"
    confidence: str    # "high" | "medium" | "low"
    note: str = ""


def parse_unit_name(name: str) -> UnitResolution:
    """Turn a user supplied unit name (``mm``, ``m``, ``ft`` ...) into a resolution."""
    key = name.strip().lower().rstrip("s") if name.strip().lower() not in UNIT_ALIASES else name.strip().lower()
    if key not in UNIT_ALIASES:
        raise ValueError(f"Unknown unit name {name!r}; expected one of {sorted(UNIT_ALIASES)}")
    scale, canonical = UNIT_ALIASES[key]
    return UnitResolution(scale, canonical, "override", "high", "unit supplied by operator")


def guess_units_from_extent(max_dim: float, imperial_text_hits: int = 0, metric_text_hits: int = 0) -> UnitResolution:
    """Guess drawing units from the largest drawing extent.

    The thresholds assume a building plan (or several side by side). Feet and
    metres overlap badly in this range, so text hints (``'`` and ``"`` marks
    versus ``mm``/``THK`` strings) are used to break the tie. The result is
    always low confidence so the operator is asked to confirm.
    """
    if max_dim <= 0:
        return UnitResolution(1.0, "millimetres", "heuristic", "low", "empty drawing extents; assumed millimetres")
    if max_dim > 20_000:
        return UnitResolution(1.0, "millimetres", "heuristic", "low",
                              f"extent {max_dim:.0f} units is typical of millimetres")
    if max_dim > 2_000:
        return UnitResolution(25.4, "inches", "heuristic", "low",
                              f"extent {max_dim:.0f} units is typical of inches")
    if imperial_text_hits > metric_text_hits:
        return UnitResolution(304.8, "feet", "heuristic", "low",
                              f"extent {max_dim:.0f} units with imperial text hints suggests feet")
    return UnitResolution(1000.0, "metres", "heuristic", "low",
                          f"extent {max_dim:.0f} units suggests metres")


def resolve_units(
    insunits: int | None,
    max_extent_dim: float,
    override: str | None = None,
    imperial_text_hits: int = 0,
    metric_text_hits: int = 0,
) -> UnitResolution:
    """Decide the drawing-unit to millimetre factor."""
    if override:
        return parse_unit_name(override)
    if insunits in INSUNITS_TO_MM:
        return UnitResolution(
            INSUNITS_TO_MM[insunits],
            INSUNITS_NAMES.get(insunits, str(insunits)),
            "insunits",
            "high",
            f"$INSUNITS={insunits} ({INSUNITS_NAMES.get(insunits, '?')})",
        )
    guess = guess_units_from_extent(max_extent_dim, imperial_text_hits, metric_text_hits)
    return UnitResolution(guess.scale_to_mm, guess.name, guess.source, guess.confidence,
                          f"$INSUNITS={insunits!r} is not usable; {guess.note}")
