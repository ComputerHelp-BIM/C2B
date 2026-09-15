"""Tag text parsing.

Client drawings label members in dozens of ways. This module turns a raw text
string such as ``C_300 X 900``, ``B6 (200X900/600)``, ``F3_750MM THK`` or
``1'-6" x 2'-0"`` into a :class:`ParsedTag` with normalised millimetre values.

The parser is deliberately rule based: every rule is a regular expression that
can be read, tested and extended when a new client convention shows up. Text
that no rule understands is kept verbatim and flagged ``unparsed`` so it lands
in the diagnostics instead of silently disappearing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Length parsing (metric and imperial)
# ---------------------------------------------------------------------------

_FRACTION = r"(?:\d+\s*/\s*\d+)"
_NUM = r"\d+(?:\.\d+)?"

# feet-inches: 1'-6", 1' 6", 1'6, 12'-0 1/2", 3ft 4in
_FT_IN = rf"{_NUM}\s*(?:'|’|ft|feet)\s*-?\s*(?:{_NUM}(?:\s+{_FRACTION})?\s*(?:\"|”|''|in|inch)?)?"
# inches only: 12", 6 1/2", 18in
_IN = rf"{_NUM}(?:\s+{_FRACTION})?\s*(?:\"|”|''|in\b|inch)"
# metric: 300, 300mm, 0.3m, 30cm
_METRIC = rf"{_NUM}\s*(?:mm|cm|m)?(?!\d)"

LENGTH = rf"(?:{_FT_IN}|{_IN}|{_METRIC})"

_RE_FT_IN = re.compile(
    rf"^\s*(?P<ft>{_NUM})\s*(?:'|’|ft|feet)\s*-?\s*(?:(?P<in>{_NUM})?(?:\s+(?P<fn>\d+)\s*/\s*(?P<fd>\d+))?\s*(?:\"|”|''|in|inch)?)?\s*$",
    re.I,
)
_RE_IN = re.compile(rf"^\s*(?P<in>{_NUM})(?:\s+(?P<fn>\d+)\s*/\s*(?P<fd>\d+))?\s*(?:\"|”|''|in|inch)\s*$", re.I)
_RE_METRIC = re.compile(rf"^\s*(?P<val>{_NUM})\s*(?P<unit>mm|cm|m)?\s*$", re.I)


def parse_length_mm(text: str) -> float | None:
    """Parse a single length token to millimetres. Returns ``None`` if not a length."""
    if text is None:
        return None
    s = text.strip()
    m = _RE_FT_IN.match(s)
    if m:
        ft = float(m.group("ft"))
        inches = float(m.group("in")) if m.group("in") else 0.0
        if m.group("fn") and m.group("fd") and float(m.group("fd")) != 0:
            inches += float(m.group("fn")) / float(m.group("fd"))
        return round(ft * 304.8 + inches * 25.4, 3)
    m = _RE_IN.match(s)
    if m:
        inches = float(m.group("in"))
        if m.group("fn") and m.group("fd") and float(m.group("fd")) != 0:
            inches += float(m.group("fn")) / float(m.group("fd"))
        return round(inches * 25.4, 3)
    m = _RE_METRIC.match(s)
    if m:
        val = float(m.group("val"))
        unit = (m.group("unit") or "mm").lower()
        return round(val * {"mm": 1.0, "cm": 10.0, "m": 1000.0}[unit], 3)
    return None


# ---------------------------------------------------------------------------
# Tag patterns
# ---------------------------------------------------------------------------

# 300 X 600, 200x750/675, 1'-6" x 2'-0", 300*600
RE_SIZE = re.compile(
    rf"(?P<w>{LENGTH})\s*[xX×*]\s*(?P<d>{LENGTH})(?:\s*/\s*(?P<d2>{LENGTH}))?",
)
# 600D, 600 DIA, Ø600, %%C600, DIA 600
RE_DIA = re.compile(rf"(?:(?P<a>{_NUM})\s*(?:MM)?\s*(?:D|DIA\.?|Ø)(?![A-Z])|(?:Ø|DIA\.?)\s*(?P<b>{_NUM}))", re.I)
# 150 THK., 1200MM THK, 150THK
RE_THK = re.compile(rf"(?P<t>{_NUM})\s*(?:MM)?\s*(?:THK|THICK|TH)\b\.?", re.I)
RE_FOLD = re.compile(rf"(?P<f>{_NUM})\s*(?:MM)?\s*FOLD", re.I)
RE_SUNK = re.compile(rf"(?:SUNK\s*(?:BY)?\s*(?P<a>{_NUM})\s*(?:MM)?|(?P<b>{_NUM})\s*(?:MM)?\s*SUNK)", re.I)
RE_INVERTED = re.compile(r"\b(INV\.?|INVERTED|UPSTAND|UPTURN)\b", re.I)
# "ALL BEAMS ARE 750MM IN DEPTH U.N.O.", "* ALL SLABS 150THK. R.C.C. SLAB UNLESS ..."
RE_NOTE_DEFAULT = re.compile(
    rf"ALL\s+(?P<what>BEAMS?|SLABS?|SALBS?|COLUMNS?)\s+(?:ARE\s+)?(?P<v>{_NUM})\s*(?:MM)?\s*(?:THK\.?|THICK|IN\s+DEPTH|DEEP|DEPTH)?",
    re.I,
)

# Tokens that look like marks but are vocabulary.
_STOPWORDS = {
    "THK", "MM", "CM", "M", "FOLD", "SUNK", "INV", "SLAB", "BEAM", "BEAMS", "COL", "COLUMN", "DN", "UP", "LIFT",
    "SHAFT", "CUTOUT", "TYP", "UNO", "ALL", "ARE", "IN", "DEPTH", "DIA", "X", "AT", "LVL", "LEVEL", "FLOOR",
    "PLAN", "NOTE", "NOTES", "RCC", "R", "C", "BY", "THUS", "MARKED", "FOR", "REFER", "ARCH", "DRG", "SCALE",
    "TOP", "BOT", "BOTTOM", "FFL", "SSL", "PLINTH", "WALL", "END", "START", "STOP", "DROP", "TO", "OF",
    "WITH", "AND", "THE", "NO", "SIZE", "SIZES", "MARK", "SCHEDULE", "SEC", "SECTION", "DETAIL", "ST", "STAIR",
}

# category hints from the leading letters of a mark
_PREFIX_CATEGORY: dict[str, str] = {
    "C": "column", "SC": "column", "PC": "column", "CL": "column",
    "B": "beam", "MB": "beam", "LB": "beam", "SB": "beam", "BK": "beam", "PB": "beam", "TB": "beam",
    "CB": "beam", "GB": "beam", "FB": "beam", "RB": "beam", "BKT": "beam",
    "F": "footing", "RF": "footing", "CF": "footing", "IF": "footing", "PF": "footing", "FT": "footing",
    "SW": "wall", "W": "wall", "RW": "wall",
    "S": "slab",
}

_RE_MARK_TOKEN = re.compile(r"^(?:[A-Z]{1,4}\d{1,4}[A-Za-z]{0,2}|[A-Z]{1,2}\d{1,2}[A-Z]{1,3}\d{1,4}[a-z]?|[A-Z]{2,4})$")
_RE_PREFIX = re.compile(r"^[A-Z]+")
_RE_MTEXT_BREAK = re.compile(r"\\P|\\n", re.I)
_RE_CAD_CODES = re.compile(r"%%[UuOoKk]")


@dataclass
class ParsedTag:
    """Normalised content of one tag string. All lengths are millimetres."""

    raw: str
    text: str
    mark: str | None = None
    marks: list[str] = field(default_factory=list)
    category_hint: str | None = None
    width_mm: float | None = None
    depth_mm: float | None = None
    depth_alt_mm: float | None = None
    diameter_mm: float | None = None
    thickness_mm: float | None = None
    fold_mm: float | None = None
    sunk_mm: float | None = None
    inverted: bool = False
    note_default: tuple[str, float] | None = None   # ("beam" | "slab" | "column", value)
    unparsed: bool = False

    @property
    def has_size(self) -> bool:
        return self.width_mm is not None or self.diameter_mm is not None or self.thickness_mm is not None

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["note_default"] = list(self.note_default) if self.note_default else None
        return d


def clean_text(raw: str) -> str:
    """Strip CAD formatting codes and normalise whitespace and quotes."""
    s = _RE_MTEXT_BREAK.sub("\n", raw or "")
    s = _RE_CAD_CODES.sub("", s)
    s = s.replace("%%C", "Ø").replace("%%c", "Ø").replace("%%D", "°").replace("%%P", "±")
    s = s.replace("’", "'").replace("”", '"').replace("″", '"').replace("′", "'")
    s = re.sub(r"[ \t]+", " ", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    return s.strip()


def _prefix_category(mark: str) -> str | None:
    m = _RE_PREFIX.match(mark)
    if not m:
        return None
    prefix = m.group(0)
    # longest known prefix first (SW before S, BK before B)
    for length in range(len(prefix), 0, -1):
        cat = _PREFIX_CATEGORY.get(prefix[:length])
        if cat:
            return cat
    return None


def parse_tag(raw: str) -> ParsedTag:
    """Parse one tag string.

    The size-like patterns are matched first and removed from the text, then the
    remainder is scanned for mark tokens. This ordering is what stops
    ``C_300 X 900`` from producing a mark called ``C_300``.
    """
    text = clean_text(raw)
    tag = ParsedTag(raw=raw, text=text)
    if not text:
        tag.unparsed = True
        return tag

    remainder = text
    upper = text.upper()

    m = RE_NOTE_DEFAULT.search(upper)
    if m:
        what = m.group("what").upper()
        what = "slab" if what.startswith("S") else "beam" if what.startswith("B") else "column"
        val = parse_length_mm(m.group("v"))
        if val:
            tag.note_default = (what, val)

    m = RE_SIZE.search(remainder)
    if m:
        w, d = parse_length_mm(m.group("w")), parse_length_mm(m.group("d"))
        if w and d and w >= 25 and d >= 25:
            tag.width_mm, tag.depth_mm = w, d
            if m.group("d2"):
                tag.depth_alt_mm = parse_length_mm(m.group("d2"))
            remainder = remainder[: m.start()] + " " + remainder[m.end():]

    if tag.width_mm is None:
        m = RE_DIA.search(remainder)
        if m:
            val = parse_length_mm(m.group("a") or m.group("b"))
            if val and val >= 100:
                tag.diameter_mm = val
                remainder = remainder[: m.start()] + " " + remainder[m.end():]

    m = RE_THK.search(remainder)
    if m:
        tag.thickness_mm = parse_length_mm(m.group("t"))
        remainder = remainder[: m.start()] + " " + remainder[m.end():]

    m = RE_FOLD.search(remainder)
    if m:
        tag.fold_mm = parse_length_mm(m.group("f"))
        remainder = remainder[: m.start()] + " " + remainder[m.end():]

    m = RE_SUNK.search(remainder)
    if m:
        tag.sunk_mm = parse_length_mm(m.group("a") or m.group("b"))
        remainder = remainder[: m.start()] + " " + remainder[m.end():]

    if RE_INVERTED.search(remainder):
        tag.inverted = True
        remainder = RE_INVERTED.sub(" ", remainder)

    # Marks: tokens of the remainder that look like member marks.
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", remainder) if t]
    marks: list[str] = []
    single_prefix: str | None = None
    for tok in tokens:
        if tok.upper() in _STOPWORDS and not (len(tok) > 1 and tok[-1].isdigit()):
            # a bare category letter such as "C" in "C_300 X 900" is a hint, not a mark
            if len(tok) == 1 and tok.isalpha() and single_prefix is None:
                single_prefix = tok.upper()
            continue
        if len(tok) == 1 and tok.isalpha():
            single_prefix = tok.upper()
            continue
        if tok.isalpha():
            # a bare word is a mark only when it stands alone ("MB") or is a known member prefix ("BKT")
            if not (len(tokens) == 1 or tok.upper() in _PREFIX_CATEGORY):
                continue
        if _RE_MARK_TOKEN.match(tok) and not tok.isdigit():
            marks.append(tok)
    tag.marks = marks
    if marks:
        tag.mark = marks[0]
        tag.category_hint = _prefix_category(marks[0].upper())
    elif single_prefix:
        tag.category_hint = _PREFIX_CATEGORY.get(single_prefix)
    if tag.category_hint is None and tag.thickness_mm is not None and "SLAB" in upper:
        tag.category_hint = "slab"

    tag.unparsed = not (tag.has_size or tag.mark or tag.note_default or tag.fold_mm or tag.sunk_mm or tag.inverted)
    return tag


def parse_size_from_name(name: str) -> tuple[float, float] | None:
    """Parse ``B-200x400`` / ``500X750`` style layer or block names into (width, depth) mm."""
    m = RE_SIZE.search(name or "")
    if not m:
        return None
    w, d = parse_length_mm(m.group("w")), parse_length_mm(m.group("d"))
    if w and d and w >= 50 and d >= 50:
        return (w, d)
    return None


# ---------------------------------------------------------------------------
# Level hints and general notes
# ---------------------------------------------------------------------------

_RE_LEVEL = re.compile(
    r"(?P<name>[A-Za-z0-9 .\-/&()']*?)\b(?P<kw>LVL|LEVEL|FFL|SFL|SSL|TOS|TOF|TOC|PLINTH|GL|NGL|EGL)\b\.?\s*[:=]?\s*"
    r"(?P<sign>[+\-−]?)\s*(?P<val>\d{1,3}(?:[.,]\d{1,3})?|\d{3,6})\s*(?P<unit>mm|m|MM|M)?(?![\d])",
    re.I,
)
_RE_NOTE_START = re.compile(r"^\s*(?:\d{1,2}\s*[).:-]|\*|NOTES?\b|ALL\b|REFER\b|FOR\b|UNLESS\b|U\.N\.O)", re.I)


def parse_level_hint(text: str) -> tuple[str, float] | None:
    """Return (name, elevation_mm) when the text carries a level value, else None."""
    s = clean_text(text).replace("\n", " ")
    m = _RE_LEVEL.search(s)
    if not m:
        return None
    raw = m.group("val").replace(",", ".")
    unit = (m.group("unit") or "").lower()
    val = float(raw)
    if unit == "m" or (not unit and "." in raw):
        mm = val * 1000.0
    elif unit == "mm" or abs(val) >= 100:
        mm = val
    else:
        mm = val * 1000.0
    if m.group("sign") in ("-", "−"):
        mm = -mm
    name = (m.group("name") or "").strip(" -:.")
    kw = m.group("kw").upper()
    if kw in ("LVL", "LEVEL") and name:
        name = f"{name} LVL."
    elif not name:
        name = kw
    else:
        name = f"{name} {kw}"
    return name.upper(), round(mm, 1)


def looks_like_note(text: str, min_len: int = 12) -> bool:
    s = clean_text(text)
    return len(s) >= min_len and bool(_RE_NOTE_START.match(s))


def strip_note_number(text: str) -> str:
    """Remove a leading 'NOTE -', 'NOTES:', '1)', '2.' or '*' so notes can be renumbered."""
    s = re.sub(r"^\s*NOTES?\s*[:\-]?\s*", "", clean_text(text), flags=re.I)
    return re.sub(r"^\s*(?:\d{1,2}\s*[).:-]\s*|\*\s*)", "", s).strip()
