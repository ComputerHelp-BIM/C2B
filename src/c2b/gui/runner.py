"""The pipeline as a background job that reports progress to the window.

Nothing here touches Tk, so it can be tested without a display.
"""
from __future__ import annotations

import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

Progress = Callable[[str, str], None]        # (level, message): level in info | step | good | warn | bad


#: What the drafter picks in the window -> the value the extractor takes. The label is what the
#: settings file stores, so this mapping is also what protects a saved choice from a relabelling:
#: an unknown label falls back to the default rather than silently meaning the other option.
COLUMN_SIZE_FROM = {"tag or schedule": "tag", "drawn outline": "outline"}
COLUMN_SIZE_DEFAULT = "tag or schedule"


def column_size_value(label: str | None) -> str:
    """The extractor's value for a picked label, defaulting to the client's stated size."""
    return COLUMN_SIZE_FROM.get(label or "", COLUMN_SIZE_FROM[COLUMN_SIZE_DEFAULT])


def column_size_label(saved: str | None) -> str | None:
    """A label remembered from a previous run, or None when it is not one we offer now."""
    return saved if saved in COLUMN_SIZE_FROM else None


@dataclass
class JobSettings:
    drawing: Path
    out_dir: Path | None = None
    seed: Path | None = None
    spec: Path | None = None
    profile: Path | None = None
    levels: Path | None = None
    units: str | None = None                 # None = read from the drawing
    column_size_from: str = "tag"            # "tag" (the client's stated size) or "outline" (measure the drawing)


@dataclass
class JobResult:
    ok: bool = False
    out_dir: Path | None = None
    template_dxf: Path | None = None
    review_xlsx: Path | None = None
    schedules_xlsx: Path | None = None
    verify_md: Path | None = None
    review_dxf: Path | None = None
    levels_xlsx: Path | None = None
    counts: dict[str, int] = field(default_factory=dict)
    issues: list[tuple[str, str, int, str]] = field(default_factory=list)   # severity, code, count, meaning
    error: str | None = None


def run_job(settings: JobSettings, progress: Progress) -> JobResult:
    """Run extract, normalise and verify, reporting each step. Never raises."""
    from ..diagnostics import CODES
    from ..dwg import ensure_dxf
    from ..export.excel import write_workbook
    from ..export.jsonout import write_json
    from ..export.levels import read_level_settings, read_levels, write_levels_template
    from ..export.normalized_excel import write_normalized_workbook
    from ..export.report import write_report
    from ..export.review_dxf import write_review_dxf
    from ..export.template_dxf import write_template_dxf
    from ..export.verify import write_verify_report, write_verify_workbook
    from ..normalize.pipeline import normalize
    from ..normalize.spec import TemplateSpec
    from ..pipeline import extract
    from ..profile import Profile
    from ..roundtrip.diff import CODES as RT_CODES
    from ..roundtrip.diff import compare
    from ..roundtrip.reader import read_template

    res = JobResult()
    try:
        drawing = Path(settings.drawing)
        stem = drawing.stem
        out = Path(settings.out_dir) if settings.out_dir else drawing.parent / "out" / stem
        out.mkdir(parents=True, exist_ok=True)
        res.out_dir = out

        dxf, converted = ensure_dxf(drawing, out)
        if converted:
            progress("info", f"Converted {drawing.name} to DXF")

        progress("step", f"1 of 3   Reading {dxf.name}")
        profile = Profile.load(settings.profile) if settings.profile else Profile()
        profile.size_sources.column = settings.column_size_from
        if settings.column_size_from == "outline":
            progress("info", "         column sizes measured from the drawn outline, not the tag")
        project = extract(dxf, profile, settings.units or None)
        p = project.project
        write_json(p, out / f"{stem}.c2b.json")
        res.review_xlsx = write_workbook(p, out / f"{stem}.review.xlsx")
        write_report(p, out / f"{stem}.report.md")
        res.review_dxf = write_review_dxf(p, out / f"{stem}.review.dxf")
        project.profile.save(out / f"{stem}.profile.yaml")
        s1 = p.summary
        progress("good", f"         {s1.floors} floors, {s1.columns} columns, {s1.beams} beams, {s1.slabs} slab tags, {s1.footings} footings")
        for f in p.floors:
            progress("info", f"           {f.id}  {f.name}")

        levels_path = Path(settings.levels) if settings.levels else out / f"{stem}.levels.xlsx"
        res.levels_xlsx = levels_path
        rows = ref = None
        if levels_path.exists():
            rows = read_levels(levels_path)
            ref = read_level_settings(levels_path).get("level_reference")
            filled = [r for r in rows if r.elevation is not None]
            progress("info" if filled else "warn",
                     f"         levels: {len(filled)} of {len(rows)} floors have an elevation in {levels_path.name}")
            rows = rows if filled else None
        else:
            write_levels_template(p, levels_path)
            progress("warn", f"         fill {levels_path.name} with floor elevations and run again for the elevation frame")

        progress("step", "2 of 3   Drawing it in the template")
        spec = TemplateSpec.load(settings.spec) if settings.spec else TemplateSpec()
        np_ = normalize(p, spec, rows, source_file=dxf.name, level_reference=ref)
        (out / f"{stem}.normalized.json").write_text(np_.model_dump_json(indent=2), encoding="utf-8")
        res.schedules_xlsx = write_normalized_workbook(np_, out / f"{stem}.schedules.xlsx")
        spec.save(out / f"{stem}.template-spec.yaml")
        res.template_dxf = write_template_dxf(np_, out / f"{stem}.template.dxf", spec, settings.seed)
        s2 = np_.summary
        progress("good", f"         {s2.columns} columns in {s2.stacks} stacks, {s2.beams} beam spans, {s2.panels} slab panels, {s2.levels} levels")

        progress("step", "3 of 3   Checking the drawing against the data")
        drawing_model = read_template(res.template_dxf, spec)
        (out / f"{stem}.reread.json").write_text(drawing_model.model_dump_json(indent=2), encoding="utf-8")
        write_normalized_workbook(drawing_model, out / f"{stem}.reread.xlsx")
        diff = compare(np_, drawing_model)
        write_verify_workbook(diff, np_, drawing_model, out / f"{stem}.verify.xlsx")
        res.verify_md = write_verify_report(diff, np_, drawing_model, out / f"{stem}.verify.md")
        progress("good" if diff.ok() else "warn",
                 f"         {'the drawing matches the data exactly' if diff.ok() else f'{diff.errors} errors, {diff.warnings} differences'}")

        res.counts = {"floors": s1.floors, "columns": s2.columns, "beam spans": s2.beams, "slab panels": s2.panels,
                      "footings": s2.footings, "grids": s2.grids, "cut-outs": s2.openings, "levels": s2.levels}
        seen = Counter((d.severity, d.code) for d in p.diagnostics if d.severity in ("ERROR", "WARNING"))
        seen.update(Counter((d.severity, d.code) for d in np_.diagnostics if d.severity in ("ERROR", "WARNING")))
        seen.update(Counter((d.severity, d.code) for d in diff.findings if d.severity in ("ERROR", "WARNING")))
        order = {"ERROR": 0, "WARNING": 1}
        res.issues = [(sev, code, n, CODES.get(code) or RT_CODES.get(code, ""))
                      for (sev, code), n in sorted(seen.items(), key=lambda kv: (order[kv[0][0]], -kv[1]))]
        res.ok = s1.errors == 0 and s2.errors == 0 and diff.errors == 0
        progress("good" if res.ok else "warn", "Finished." if res.ok else "Finished with things to check.")
    except Exception as ex:                      # a drafter must never see a stack trace in the window
        res.error = f"{type(ex).__name__}: {ex}"
        progress("bad", f"Stopped: {res.error}")
        progress("info", traceback.format_exc(limit=3))
    return res


def run_verify(template_dxf: Path, spec_path: Path | None, progress: Progress) -> JobResult:
    """Re-check an edited template DXF against the data it was written from."""
    from ..export.normalized_excel import write_normalized_workbook
    from ..export.verify import write_verify_report, write_verify_workbook
    from ..normalize.model import NormalizedProject
    from ..normalize.spec import TemplateSpec
    from ..roundtrip.diff import CODES as RT_CODES
    from ..roundtrip.diff import compare
    from ..roundtrip.reader import read_template

    res = JobResult()
    try:
        template_dxf = Path(template_dxf)
        stem = template_dxf.name.replace(".template.dxf", "").replace(".dxf", "")
        out = template_dxf.parent
        res.out_dir = out
        spec_file = Path(spec_path) if spec_path else out / f"{stem}.template-spec.yaml"
        spec = TemplateSpec.load(spec_file) if spec_file.exists() else TemplateSpec()
        progress("step", f"Reading {template_dxf.name}")
        drawing = read_template(template_dxf, spec)
        (out / f"{stem}.reread.json").write_text(drawing.model_dump_json(indent=2), encoding="utf-8")
        write_normalized_workbook(drawing, out / f"{stem}.reread.xlsx")
        s = drawing.summary
        progress("good", f"         {s.columns} columns, {s.beams} beam spans, {s.panels} slab panels")
        model_path = out / f"{stem}.normalized.json"
        if not model_path.exists():
            progress("warn", "No matching data file, so only the drawing was read.")
            res.ok = True
            res.counts = {"columns": s.columns, "beam spans": s.beams, "slab panels": s.panels}
            return res
        model = NormalizedProject.model_validate_json(model_path.read_text(encoding="utf-8"))
        diff = compare(model, drawing)
        write_verify_workbook(diff, model, drawing, out / f"{stem}.verify.xlsx")
        res.verify_md = write_verify_report(diff, model, drawing, out / f"{stem}.verify.md")
        res.issues = [(sev, code, n, RT_CODES.get(code, "")) for (sev, code), n in
                      sorted(Counter((d.severity, d.code) for d in diff.findings).items(), key=lambda kv: -kv[1])]
        res.counts = {"columns": s.columns, "beam spans": s.beams, "slab panels": s.panels,
                      "changes": len(diff.findings)}
        res.ok = diff.ok()
        progress("good" if res.ok else "warn", "No changes since the drawing was generated." if res.ok else f"{len(diff.findings)} changes listed.")
    except Exception as ex:
        res.error = f"{type(ex).__name__}: {ex}"
        progress("bad", f"Stopped: {res.error}")
    return res
