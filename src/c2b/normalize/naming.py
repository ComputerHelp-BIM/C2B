"""Floor and level names in template form."""
from __future__ import annotations

import re

_STRIP = [r"^\s*layout\s+(plan\s+)?(at|-)\s*", r"^\s*structural\s+layout\s+at\s*", r"\(t\d+\)", r"\(tower\s*\d+\)\s*-?", r"^\s*-\s*", r"\bscale\b.*$"]


def normalise_floor_name(name: str) -> str:
    s = name.strip()
    low = s.lower()
    for pat in _STRIP:
        low = re.sub(pat, " ", low)
    low = re.sub(r"\s+", " ", low).strip(" -.")
    up = low.upper()
    up = re.sub(r"\bLEVEL\b\.?", "LVL.", up)
    up = re.sub(r"\bLVL\b(?!\.)", "LVL.", up)
    up = re.sub(r"\bFLR\b\.?", "FLOOR", up)
    up = re.sub(r"\s+", " ", up).strip()
    if "LVL." not in up and "SLAB" not in up:
        up += " LVL."
    return up


def title_from_level_name(level_name: str) -> str:
    """'GROUND FLOOR LVL.' -> 'GROUND FLOOR LEVEL' for plan titles."""
    return level_name.replace("LVL.", "LEVEL").strip()
