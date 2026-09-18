"""Check what Revit actually built against what the plan asked for.

Utilities 3 and 4 close a loop: the template DXF is written, read back, and every difference is
listed. Utility 5 had no such loop -- the plan went into Revit and nothing came back out.

It can have one, because the firm's *Extract Template* tool describes any model, not only a
template. Run it on the project after the import and it reports how many elements each
category holds, which types exist and what dimensions each of them carries. That is enough to
answer the three questions worth asking after an import:

* did everything get built, or did some of it fail quietly?
* does every type the plan needed now exist?
* is each created type the size the plan asked for -- a duplicated ``175 THK. RCC SLAB`` that
  came out 150 thick looks completely normal in the project browser

Nothing here talks to Revit. It compares two files, so it runs anywhere.
"""
from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from .plan import RevitPlan
from .template import TemplateDigest

# The plan's own ``category`` is the Revit category an action lands in, so it is used directly.
# These are the ones worth counting; anything else is reported but not judged.
_COUNTED = ("Structural Columns", "Structural Framing", "Floors", "Structural Foundations",
            "Walls", "Grids", "Shaft Openings")

_TOLERANCE_MM = 0.6      # the extractor writes three decimals; anything larger is a real difference


class BuiltRow(BaseModel):
    """One thing the plan asked for, and what the model turned out to hold."""

    kind: str                  # category | level | grid | type
    what: str
    planned: str = ""
    found: str = ""
    ok: bool = True
    note: str = ""


class ImportCheck(BaseModel):
    model_name: str = ""
    model_file: str = ""
    plan_source: str = ""
    rows: list[BuiltRow] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {"checked": len(self.rows),
                "as planned": sum(1 for r in self.rows if r.ok),
                "not as planned": sum(1 for r in self.rows if not r.ok)}

    def problems(self) -> list[BuiltRow]:
        return [r for r in self.rows if not r.ok]


def _expected_type_params(plan: RevitPlan) -> dict[tuple[str, str], dict[str, float]]:
    """The dimensions each type was supposed to end up with, by (family, type name)."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    for a in plan.actions:
        if not a.type_name:
            continue
        family = a.family or _system_family_of(a)
        if not family:
            continue
        want = dict(a.params)
        if not want and a.thickness_mm:
            # a system type carries no family parameters; its size is the core layer's width,
            # which the extractor reports as "Default Thickness"
            want = {"Default Thickness": a.thickness_mm}
        out.setdefault((family, a.type_name), want)
    return out


def _system_family_of(action) -> str:
    """System-family actions carry no family name in the plan; their kind says which it is."""
    return {"floor": "Floor", "wall": "Basic Wall", "pcc": "Foundation Slab",
            "footing": "Foundation Slab"}.get(action.kind, "")


def verify_after_import(plan: RevitPlan, built: TemplateDigest) -> ImportCheck:
    """Compare a build plan with a description of the model that was built from it."""
    check = ImportCheck(model_name=built.name, model_file=built.source_file, plan_source=plan.source_file)

    # -- did everything get built? ------------------------------------------
    planned = Counter(a.category for a in plan.actions)
    planned["Levels"] = len(plan.levels)
    for category in (*_COUNTED, "Levels"):
        want = planned.get(category, 0)
        if not want:
            continue
        got = built.instances.get(category)
        if got is None:
            check.rows.append(BuiltRow(kind="category", what=category, planned=str(want), found="not reported",
                                       ok=False, note="the model description has no count for this category"))
            continue
        row = BuiltRow(kind="category", what=category, planned=str(want), found=str(got), ok=got >= want)
        if got < want:
            row.note = (f"{want - got} missing -- look at the import log for the ones that failed, "
                        "and at whether a family or level was absent")
        elif got > want:
            row.note = f"{got - want} more than planned, so the project already held some before the import"
        check.rows.append(row)

    # -- are the levels there, at the right height? -------------------------
    by_name = {lv.name: lv.elevation_mm for lv in built.levels}
    for lv in plan.levels:
        if lv.name not in by_name:
            check.rows.append(BuiltRow(kind="level", what=lv.name, planned=f"{lv.elevation_mm:.0f} mm",
                                       found="not in the model", ok=False,
                                       note="nothing hosted on this level was built either"))
        elif abs(by_name[lv.name] - lv.elevation_mm) > _TOLERANCE_MM:
            check.rows.append(BuiltRow(kind="level", what=lv.name, planned=f"{lv.elevation_mm:.0f} mm",
                                       found=f"{by_name[lv.name]:.0f} mm", ok=False,
                                       note="the level already existed at a different height and was kept"))
        else:
            check.rows.append(BuiltRow(kind="level", what=lv.name, planned=f"{lv.elevation_mm:.0f} mm",
                                       found=f"{by_name[lv.name]:.0f} mm"))

    # -- are the grids there? -----------------------------------------------
    grid_marks = [a.mark for a in plan.actions if a.kind == "grid" and a.mark]
    missing_grids = [m for m in grid_marks if m not in set(built.grid_names)]
    if grid_marks:
        check.rows.append(BuiltRow(
            kind="grid", what="grid labels", planned=str(len(grid_marks)),
            found=str(len(grid_marks) - len(missing_grids)), ok=not missing_grids,
            note="" if not missing_grids else f"missing: {', '.join(missing_grids[:12])}"))

    # -- does every type exist, at the size it was asked for? ---------------
    for (family, type_name), want in sorted(_expected_type_params(plan).items()):
        got = built.type_params(family, type_name)
        if got is None:
            fam = built.family(family)
            check.rows.append(BuiltRow(
                kind="type", what=f"{family} / {type_name}", planned="exists", found="missing", ok=False,
                note=("the family itself is not in the model" if fam is None else
                      "the type was never created, so everything needing it failed")))
            continue
        wrong = [(k, v, got.get(k)) for k, v in want.items()
                 if got.get(k) is None or abs(got[k] - v) > _TOLERANCE_MM]
        if wrong:
            k, v, actual = wrong[0]
            check.rows.append(BuiltRow(
                kind="type", what=f"{family} / {type_name}", planned=f"{k} {v:.0f}",
                found=f"{k} {actual:.0f}" if actual is not None else f"{k} not reported", ok=False,
                note=("the type was duplicated from another one and kept its size -- "
                      "every element of this type is the wrong size")))
        else:
            check.rows.append(BuiltRow(kind="type", what=f"{family} / {type_name}", planned="as asked",
                                       found=", ".join(f"{k} {v:.0f}" for k, v in sorted(got.items())) or "created"))
    return check


def write_import_report(check: ImportCheck, path) -> str:
    """A markdown report of the comparison, next to the plan."""
    from pathlib import Path

    s = check.summary()
    lines = [f"# Revit import check — {check.model_name or 'the model'}", "",
             f"Plan from `{check.plan_source}` against `{check.model_file}`.", "",
             f"**{s['as planned']} of {s['checked']} checks as planned"
             + (f", {s['not as planned']} not.**" if s["not as planned"] else ".**"), ""]
    problems = check.problems()
    if problems:
        lines += ["## What is not as planned", "",
                  "| What | Planned | In the model | Why it matters |", "| --- | --- | --- | --- |"]
        lines += [f"| {r.what} | {r.planned} | {r.found} | {r.note} |" for r in problems]
        lines.append("")
    lines += ["## Everything checked", "", "| | What | Planned | In the model |", "| --- | --- | --- | --- |"]
    lines += [f"| {'ok' if r.ok else '**no**'} | {r.what} | {r.planned} | {r.found} |" for r in check.rows]
    text = "\n".join(lines) + "\n"
    Path(path).write_text(text, encoding="utf-8")
    return text
