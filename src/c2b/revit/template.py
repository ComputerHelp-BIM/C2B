"""Read a Revit template description into something the planner can check against.

A ``.rte`` / ``.rvt`` is a compound binary, so a template cannot be read outside Revit. What
can be read is the markdown the firm's *Extract Template* tool writes from it: every family,
every type, every type's driving dimensions, the levels, the grids and the parameters the
model binds.

That file is a contract. Parsed here, ``c2b revit-plan`` can answer -- before anyone opens
Revit -- which types the plan needs and the template already carries, which ones will have to
be created by duplication, and whether the parameter a mark is written to exists at all. A
mark written to a parameter the template does not bind disappears silently, which is the one
failure that cannot be seen by looking at the model afterwards.

The parser is deliberately forgiving: an unrecognised line is skipped, never fatal. A
template description is written by a tool that will change, and a new heading in it must not
stop a project from being planned.
"""
from __future__ import annotations

import contextlib
import re
from pathlib import Path

from pydantic import BaseModel, Field

# "  - `CH-300 X 600` — b 300.000, h 600.000"   (the dash is U+2014, written by the extractor)
_TYPE_RE = re.compile(r"^\s*-\s+`(?P<name>[^`]+)`(?:\s*[—-]\s*(?P<params>.+))?\s*$")
# "- **CH-Concrete-Rectangular-Column** _(loadable)_"
_FAMILY_RE = re.compile(r"^-\s+\*\*(?P<name>.+?)\*\*\s+_\((?P<kind>loadable|system)\)_\s*$")
# "<details><summary><strong>CH-Concrete-Rectangular-Beam</strong> — 28 parameters, 16 writable</summary>"
_DETAILS_RE = re.compile(r"<summary><strong>(?P<name>.+?)</strong>")
_PARAM_PAIR_RE = re.compile(r"^(?P<name>.+?)\s+(?P<value>-?\d+(?:\.\d+)?)$")


class TemplateType(BaseModel):
    """One type inside a family, with whatever dimensions the extractor could read off it."""

    name: str
    params: dict[str, float] = Field(default_factory=dict)


class TemplateFamily(BaseModel):
    name: str
    category: str
    system: bool = False                      # a system family: types are made by duplication, never loaded
    types: list[TemplateType] = Field(default_factory=list)
    param_names: set[str] = Field(default_factory=set)        # from the Family parameters section
    writable: set[str] = Field(default_factory=set)

    def type_names(self) -> set[str]:
        return {t.name for t in self.types}


class BoundParam(BaseModel):
    """A parameter the *project* binds, which is what decides whether a written value survives."""

    name: str
    kind: str                                 # shared | project
    per: str = "instance"
    categories: set[str] = Field(default_factory=set)


class TemplateLevel(BaseModel):
    name: str
    elevation_mm: float


class TemplateDigest(BaseModel):
    """Everything the planner needs to know about a Revit template, read from its description."""

    name: str = ""
    source_file: str = ""
    survey_offset_mm: float | None = None
    levels: list[TemplateLevel] = Field(default_factory=list)
    grid_names: list[str] = Field(default_factory=list)
    families: list[TemplateFamily] = Field(default_factory=list)
    bound_params: list[BoundParam] = Field(default_factory=list)
    # from the Categories table: how many types a category carries and how many elements were
    # built with them. A template has types and no instances; a finished model has both, which
    # is what makes a re-export of an imported project worth comparing against the plan.
    instances: dict[str, int] = Field(default_factory=dict)

    # -- lookups the planner uses -------------------------------------------
    def family(self, name: str) -> TemplateFamily | None:
        """Families are matched exactly: Revit does, and a near miss here is a silent wrong answer."""
        for f in self.families:
            if f.name == name:
                return f
        return None

    def has_type(self, family: str, type_name: str) -> bool:
        f = self.family(family)
        return bool(f and type_name in f.type_names())

    def family_names(self, category: str) -> list[str]:
        return [f.name for f in self.families if f.category == category]

    def binds(self, param: str, category: str | None = None) -> bool:
        """Is this parameter bound in the project, and does it reach that category?"""
        return any(p.name == param and (category is None or not p.categories or category in p.categories)
                   for p in self.bound_params)

    def level_names(self) -> set[str]:
        return {lv.name for lv in self.levels}

    def counts(self) -> dict[str, int]:
        return {"families": len(self.families), "types": sum(len(f.types) for f in self.families),
                "levels": len(self.levels), "grids": len(self.grid_names), "bound_params": len(self.bound_params),
                "instances": sum(self.instances.values())}

    def type_params(self, family: str, type_name: str) -> dict[str, float] | None:
        """The dimensions a type actually carries, or None when there is no such type."""
        f = self.family(family)
        if f is None:
            return None
        for t in f.types:
            if t.name == type_name:
                return t.params
        return None


def _parse_params(text: str | None) -> dict[str, float]:
    """"b 300.000, h 600.000" -> {"b": 300.0, "h": 600.0}. A name may contain spaces."""
    out: dict[str, float] = {}
    for piece in (text or "").split(","):
        m = _PARAM_PAIR_RE.match(piece.strip())
        if m:
            out[m.group("name").strip()] = float(m.group("value"))
    return out


def _parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    """Read a markdown table starting at ``start``; returns its data rows and the line after it."""
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if not all(set(c) <= set("-: ") for c in cells):          # skip the |---|---| separator
            rows.append(cells)
        i += 1
    return rows[1:] if rows else [], i                             # drop the header row


def _clean(cell: str) -> str:
    return cell.strip().strip("`").strip()


def parse_template_md(path: str | Path) -> TemplateDigest:
    """Parse a template description written by *Extract Template* into a digest."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    digest = TemplateDigest(source_file=str(path))

    section = ""            # the current "## " heading
    sub = ""                # the current "### " heading
    family: TemplateFamily | None = None
    details: str | None = None      # the family whose parameter table we are inside

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("# ") and not digest.name:
            digest.name = line[2:].strip()
        elif line.startswith("## "):
            section, sub, family, details = line[3:].strip(), "", None, None
        elif line.startswith("### "):
            sub, family, details = line[4:].strip(), None, None

        # -- the header block ------------------------------------------------
        if line.startswith("- **File**"):
            m = re.search(r"`([^`]+)`", line)
            if m:
                digest.source_file = m.group(1)
        elif line.startswith("- **Survey offset**"):
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*mm", line)
            if m:
                digest.survey_offset_mm = float(m.group(1))

        # -- datum -----------------------------------------------------------
        elif section == "Datum" and line.lstrip().startswith("|") and sub in ("Levels", "Grids"):
            rows, i = _parse_table(lines, i)
            for r in rows:
                if sub == "Levels" and len(r) >= 2:
                    with contextlib.suppress(ValueError):
                        digest.levels.append(TemplateLevel(name=_clean(r[0]), elevation_mm=float(r[1])))
                elif sub == "Grids" and r:
                    digest.grid_names.append(_clean(r[0]))
            continue

        # -- what the model is made of ---------------------------------------
        elif section == "Categories" and line.lstrip().startswith("|"):
            rows, i = _parse_table(lines, i)
            for r in rows:
                if len(r) >= 3:
                    with contextlib.suppress(ValueError):
                        digest.instances[_clean(r[0])] = int(r[2])
            continue

        # -- families and types ----------------------------------------------
        elif section == "Families and types":
            fm = _FAMILY_RE.match(line)
            if fm:
                family = TemplateFamily(name=fm.group("name"), category=sub, system=fm.group("kind") == "system")
                digest.families.append(family)
            elif family is not None:
                tm = _TYPE_RE.match(line)
                if tm:
                    family.types.append(TemplateType(name=tm.group("name"), params=_parse_params(tm.group("params"))))

        # -- project-bound parameters ----------------------------------------
        elif section == "Parameters" and sub in ("Shared", "Project") and line.lstrip().startswith("|"):
            rows, i = _parse_table(lines, i)
            for r in rows:
                if len(r) >= 4:
                    digest.bound_params.append(BoundParam(
                        name=_clean(r[0]), kind=sub.lower(), per=_clean(r[2]) or "instance",
                        categories={c.strip() for c in r[3].split(",") if c.strip()}))
            continue

        # -- family parameters (the <details> blocks) -------------------------
        elif section == "Parameters" and sub == "Family":
            dm = _DETAILS_RE.search(line)
            if dm:
                details = dm.group("name")
            elif details and line.lstrip().startswith("|"):
                rows, i = _parse_table(lines, i)
                fam = digest.family(details)
                if fam is not None:
                    for r in rows:
                        if len(r) >= 4:
                            fam.param_names.add(_clean(r[0]))
                            if _clean(r[3]).lower() == "yes":
                                fam.writable.add(_clean(r[0]))
                continue

        i += 1

    return digest

# ---------------------------------------------------------------- shared parameter file
class SharedParam(BaseModel):
    """One definition from a Revit shared parameter file."""

    guid: str
    name: str
    data_type: str                            # TEXT | LENGTH | ANGLE | VOLUME | YESNO ...
    group: str = ""


def parse_shared_parameters(path: str | Path) -> dict[str, SharedParam]:
    """Read a Revit shared parameter file (``*.txt``, tab separated, usually UTF-16).

    Defining a parameter here is not the same as binding it: a definition says the name and
    GUID exist, while binding is what makes a category carry it. C2B reads the file so that
    "this name is not bound" can be told apart from "this name does not exist anywhere",
    which are two different mistakes with two different fixes.
    """
    raw = Path(path).read_bytes()
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            if "PARAM" in text:
                break
        except (UnicodeDecodeError, LookupError):
            continue
    else:                                                     # pragma: no cover - unreadable file
        return {}

    groups: dict[str, str] = {}
    out: dict[str, SharedParam] = {}
    for line in text.splitlines():
        cells = line.split("\t")
        if len(cells) >= 3 and cells[0] == "GROUP":
            groups[cells[1]] = cells[2]
        elif len(cells) >= 6 and cells[0] == "PARAM":
            out[cells[2]] = SharedParam(guid=cells[1], name=cells[2], data_type=cells[3],
                                        group=groups.get(cells[5], cells[5]))
    return out
