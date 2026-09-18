"""What the Revit import will create, as a workbook to check before opening Revit."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook

from ..revit.plan import RevitPlan
from .excel import _SEV_FILL, _sheet


def write_revit_workbook(plan: RevitPlan, path: str | Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    check = plan.template_check

    summary: list[list] = [
        ["Source", plan.source_file], ["Mapping", plan.mapping_name], ["Generator", plan.generator],
        ["Plan version", plan.plan_version], [],
        *[[k, v] for k, v in sorted(plan.counts.items())], [],
        ["Errors", sum(1 for d in plan.diagnostics if d.severity == "ERROR")],
        ["Warnings", sum(1 for d in plan.diagnostics if d.severity == "WARNING")],
    ]
    if check:
        summary += [[], ["Template", check.template_name], ["Template file", check.template_file],
                    *[[k.replace("_", " ").capitalize(), v] for k, v in check.summary().items()]]
    _sheet(wb, "Summary", ["Item", "Value"], summary)

    _sheet(wb, "Levels", ["Id", "Name", "Elevation (mm)", "In the template"],
           [[lv.id, lv.name, lv.elevation_mm, "no, will be created" if check and lv.name in check.new_levels else
             ("yes" if check else "?")] for lv in plan.levels])

    if check:
        # the template was read, so each type can say whether it already exists
        _sheet(wb, "Types to create", ["Status", "Category", "Family", "Type", "How many", "Duplicated from",
                                       "Dimensions", "Worth a look"],
               [["in template" if t.exists else ("create" if t.will_create else "FAMILY MISSING"),
                 t.category, t.family, t.type_name, t.count, "" if t.exists else (t.base_type or ""),
                 ", ".join(f"{k} {v:.0f}" for k, v in t.params.items()), t.note or ""]
                for t in plan.template_check.types])
        _sheet(wb, "Template check", ["Item", "Value", "What it means"], [
            ["Template", check.template_name, "read from the template description, not from Revit"],
            [],
            *[["Family missing", f, "load this family into the project, or nothing using it can be built"]
              for f in check.missing_families],
            *[["Mark goes to" if pc.survives else "Mark would vanish", pc.name, pc.advice] for pc in check.params],
            [],
            *[["Level to create", n, "not in the template"] for n in check.new_levels],
            [],
            *[["Grid name already used", n, "the template has a grid of this name; Revit will not hold two, "
               "so the template's is renamed out of the way"] for n in check.grid_clashes],
        ])
    else:
        families = Counter((a.kind, a.category, a.family or "(system family)", a.type_name or "") for a in plan.actions)
        _sheet(wb, "Types to create", ["Kind", "Category", "Family", "Type", "How many"],
               [[k, c, f, t, n] for (k, c, f, t), n in sorted(families.items(), key=lambda kv: (kv[0][0], -kv[1]))])

    _sheet(wb, "Actions", ["Id", "Kind", "Category", "Family", "Type", "Level", "Top level", "Top offset", "Mark", "Note"],
           [[a.id, a.kind, a.category, a.family, a.type_name, a.level_id, a.top_level_id, a.top_offset_mm, a.mark, a.comment]
            for a in plan.actions])
    ws = _sheet(wb, "Diagnostics", ["Severity", "Code", "Floor", "Element", "Message"],
                [[d.severity, d.code, d.floor_id, d.element_id, d.message] for d in plan.diagnostics])
    for row in ws.iter_rows(min_row=2):
        fill = _SEV_FILL.get(row[0].value)
        if fill:
            row[0].fill = fill
    wb.save(str(path))
    return Path(path)
