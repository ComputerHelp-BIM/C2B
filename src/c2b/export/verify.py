"""Verification outputs: a workbook and a markdown report for the round trip."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook

from ..normalize.model import NormalizedProject
from ..roundtrip.diff import CODES, DiffResult
from .excel import _SEV_FILL, _sheet


def write_verify_workbook(res: DiffResult, model: NormalizedProject, drawing: NormalizedProject, path: str | Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Summary", ["Item", "Value"], [
        ["Model", model.source_file], ["Drawing", drawing.source_file], ["Model schema", model.schema_version],
        ["Verdict", "PASS" if res.ok() else "DIFFERENCES FOUND"], [],
        ["Errors", res.errors], ["Warnings", res.warnings], ["Infos", res.infos], [],
        *[[f"{code}", n] for (code, n) in Counter(d.code for d in res.findings).most_common()],
    ])
    _sheet(wb, "Counts", ["Floor", "Category", "Model", "Drawing", "Difference"],
           [[c["floor"], c["category"], c["model"], c["drawing"], c["drawing"] - c["model"]] for c in res.counts])
    ws = _sheet(wb, "Findings", ["Severity", "Code", "Meaning", "Floor", "Element", "X", "Y", "Message"],
                [[d.severity, d.code, CODES.get(d.code, ""), d.floor_id, d.element_id,
                  d.location.x if d.location else None, d.location.y if d.location else None, d.message]
                 for d in sorted(res.findings, key=lambda d: ({"ERROR": 0, "WARNING": 1, "INFO": 2}[d.severity], d.code, d.floor_id or ""))])
    for row in ws.iter_rows(min_row=2):
        fill = _SEV_FILL.get(row[0].value)
        if fill:
            row[0].fill = fill
    _sheet(wb, "Drawing diagnostics", ["Severity", "Code", "Floor", "Element", "Message"],
           [[d.severity, d.code, d.floor_id, d.element_id, d.message] for d in drawing.diagnostics])
    wb.save(str(path))
    return Path(path)


def write_verify_report(res: DiffResult, model: NormalizedProject, drawing: NormalizedProject, path: str | Path) -> Path:
    lines = [
        f"# C2B round-trip verification: {drawing.source_file}",
        "",
        f"Model: `{model.source_file}` (schema {model.schema_version})  ",
        f"Drawing: `{drawing.source_file}`",
        "",
        f"**{'PASS' if res.ok() else 'DIFFERENCES FOUND'}** — {res.errors} errors, {res.warnings} warnings, {res.infos} infos.",
        "",
        "## Counts per floor",
        "",
        "| Floor | Category | Model | Drawing | Diff |",
        "|---|---|---|---|---|",
    ]
    for c in res.counts:
        if c["model"] or c["drawing"]:
            lines.append(f"| {c['floor']} | {c['category']} | {c['model']} | {c['drawing']} | {c['drawing'] - c['model']:+d} |")
    lines += ["", "## Findings by code", "", "| Severity | Code | Count | Meaning |", "|---|---|---|---|"]
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    for (sev, code), n in sorted(Counter((d.severity, d.code) for d in res.findings).items(), key=lambda kv: (order[kv[0][0]], -kv[1])):
        lines.append(f"| {sev} | {code} | {n} | {CODES.get(code, '')} |")
    lines += ["", "## Findings (first 300)", ""]
    for d in sorted(res.findings, key=lambda d: (order[d.severity], d.code))[:300]:
        loc = f" @({d.location.x:.0f},{d.location.y:.0f})" if d.location else ""
        lines.append(f"- **{d.severity}** `{d.code}` [{d.floor_id or '-'}]{loc}: {d.message}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)
