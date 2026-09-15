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
    _sheet(wb, "Summary", ["Item", "Value"], [
        ["Source", plan.source_file], ["Mapping", plan.mapping_name], ["Generator", plan.generator],
        ["Plan version", plan.plan_version], [],
        *[[k, v] for k, v in sorted(plan.counts.items())], [],
        ["Errors", sum(1 for d in plan.diagnostics if d.severity == "ERROR")],
        ["Warnings", sum(1 for d in plan.diagnostics if d.severity == "WARNING")],
    ])
    _sheet(wb, "Levels", ["Id", "Name", "Elevation (mm)"], [[l.id, l.name, l.elevation_mm] for l in plan.levels])
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
