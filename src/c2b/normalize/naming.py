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


#: A mark that ends in a stated size, e.g. ``T1SW136c-200X2500`` -> ``T1SW136c`` + ``200X2500``.
_RE_MARK_SIZE = re.compile(r"^(?P<base>.*?)[-\s]*(?P<size>\d+(?:\.\d+)?\s*[xX]\s*\d+(?:\.\d+)?)\s*$")


def split_mark_size(mark: str) -> tuple[str, str]:
    """Split a mark into its base and the size it states, or ``(mark, "")`` if it states none.

    The size is returned verbatim: a mark broken onto two lines must still read back as the same
    mark, so neither the numbers nor their order may be rewritten on the way.
    """
    m = _RE_MARK_SIZE.match(mark or "")
    return (m.group("base"), m.group("size")) if m else (mark or "", "")
