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
    # What to build a beam or a slab the drawing never sized. Empty means do not build it.
    default_beam_depth_mm: float | None = None
    default_slab_thickness_mm: float | None = None


#: Where the firm's Revit template description lives. Looked for beside the output, then in a
#: "templates" folder next to the drawing, then in the one shipped with C2B. Nobody should have
#: to type a path to a file that only ever sits in one place.
REVIT_TEMPLATE_NAMES = ("R25_TEMPLATE.template.md", "*.template.md")
SHARED_PARAM_NAMES = ("CH-shared-parameters.txt", "*shared*parameter*.txt")
#: The firm's own template DXF, which every drawing is redrawn into. It lives in the repository
#: now, so the window has one less thing to ask for.
SEED_TEMPLATE_NAMES = ("CH-TEMPLATE.dxf", "CH-TEMPLATE*.dxf", "*TEMPLATE*.dxf")


def _find_beside(out: Path, drawing: Path, patterns) -> Path | None:
    """The first file matching any pattern, in the places it is worth looking."""
    roots = [out, drawing.parent, drawing.parent / "templates",
             Path.cwd() / "templates", Path(__file__).resolve().parents[3] / "templates"]
    for root in roots:
        for pattern in patterns:
            try:
                hits = sorted(root.glob(pattern)) if root.is_dir() else []
            except OSError:
                continue
            if hits:
                return hits[0]
    return None


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
    storeys_json: Path | None = None
    #: The floor plans the drawing has, as (floor_id, name), for the storey editor's
    #: "Built from" column. Without it the editor can only offer ids.
    plan_floors: list[tuple[str, str]] = field(default_factory=list)
    revit_json: Path | None = None
    revit_xlsx: Path | None = None
    next_step: str = ""                      # the one thing to do next, in plain words
    #: What the run cost, already worded -- see :mod:`c2b.ui.timing`. Empty when nothing timed it.
    timing: dict = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    issues: list[tuple[str, str, int, str]] = field(default_factory=list)   # severity, code, count, meaning
    error: str | None = None


def run_job(settings: JobSettings, progress: Progress, stopwatch=None) -> JobResult:
    """Run extract, normalise and verify, reporting each step. Never raises.

    ``stopwatch`` is a :class:`c2b.ui.timing.Stopwatch` the caller already started -- it holds
    the time a person spent in the storey window, which is theirs and not the tool's, so the
    run adds its own phases to it rather than starting a fresh one.
    """
    from ..diagnostics import CODES
    from ..dwg import ensure_dxf
    from ..export.excel import write_workbook
    from ..export.jsonout import write_json
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
    from ..ui.timing import Stopwatch

    watch = stopwatch or Stopwatch()
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

        watch.start("reading the drawing")
        progress("step", f"1 of 4   Reading {dxf.name}")
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

        res.plan_floors = [(f.id, f.name) for f in p.floors]
        rows, ref, res.levels_xlsx, res.storeys_json = _levels_from_storeys(p, settings, out, stem, progress)

        watch.start("drawing the template")
        progress("step", "2 of 4   Drawing it in the template")
        seed = Path(settings.seed) if settings.seed else _find_beside(out, drawing, SEED_TEMPLATE_NAMES)
        if settings.seed is None and seed is not None:
            progress("info", f"         drawn into {seed.name}, found without being asked for")
        spec = TemplateSpec.load(settings.spec) if settings.spec else TemplateSpec()
        np_ = normalize(p, spec, rows, source_file=dxf.name, level_reference=ref)
        (out / f"{stem}.normalized.json").write_text(np_.model_dump_json(indent=2), encoding="utf-8")
        res.schedules_xlsx = write_normalized_workbook(np_, out / f"{stem}.schedules.xlsx")
        spec.save(out / f"{stem}.template-spec.yaml")
        res.template_dxf = write_template_dxf(np_, out / f"{stem}.template.dxf", spec, seed)
        s2 = np_.summary
        progress("good", f"         {s2.columns} columns in {s2.stacks} stacks, {s2.beams} beam spans, {s2.panels} slab panels, {s2.levels} levels")

        watch.start("checking it")
        progress("step", "3 of 4   Checking the drawing against the data")
        drawing_model = read_template(res.template_dxf, spec)
        (out / f"{stem}.reread.json").write_text(drawing_model.model_dump_json(indent=2), encoding="utf-8")
        write_normalized_workbook(drawing_model, out / f"{stem}.reread.xlsx")
        diff = compare(np_, drawing_model)
        write_verify_workbook(diff, np_, drawing_model, out / f"{stem}.verify.xlsx")
        res.verify_md = write_verify_report(diff, np_, drawing_model, out / f"{stem}.verify.md")
        progress("good" if diff.ok() else "warn",
                 f"         {'the drawing matches the data exactly' if diff.ok() else f'{diff.errors} errors, {diff.warnings} differences'}")

        # ---- 4: the Revit build plan ------------------------------------
        watch.start("preparing Revit")
        progress("step", "4 of 4   Preparing the Revit model")
        if not np_.levels:
            progress("warn", "         no floor elevations yet, so there is nothing to place in Revit")
            res.next_step = ("Fill in the floor elevations below and press Run again. "
                             "Until then the Revit model cannot be built.")
        else:
            res.revit_json, res.revit_xlsx = _write_revit_plan(
                np_, out, stem, dxf, progress,
                {"beam": settings.default_beam_depth_mm, "slab": settings.default_slab_thickness_mm})
            res.next_step = ("Open Revit on your structural template, press C2B and pick "
                             f"{res.revit_json.name}." if res.revit_json else
                             "The Revit plan could not be written; see the messages above.")

        res.counts = {"floors": s1.floors, "columns": s2.columns, "beam spans": s2.beams, "slab panels": s2.panels,
                      "footings": s2.footings, "grids": s2.grids, "cut-outs": s2.openings, "levels": s2.levels}
        seen = Counter((d.severity, d.code) for d in p.diagnostics if d.severity in ("ERROR", "WARNING"))
        seen.update(Counter((d.severity, d.code) for d in np_.diagnostics if d.severity in ("ERROR", "WARNING")))
        seen.update(Counter((d.severity, d.code) for d in diff.findings if d.severity in ("ERROR", "WARNING")))
        order = {"ERROR": 0, "WARNING": 1}
        res.issues = [(sev, code, n, CODES.get(code) or RT_CODES.get(code, ""))
                      for (sev, code), n in sorted(seen.items(), key=lambda kv: (order[kv[0][0]], -kv[1]))]
        res.ok = s1.errors == 0 and s2.errors == 0 and diff.errors == 0
        watch.stop()
        res.timing = watch.report(headline="Drawing prepared",
                                  caption="preparing the drawing and the Revit plan")
        progress("good" if res.ok else "warn", "Finished." if res.ok else "Finished with things to check.")
        progress("info", f"         {res.timing['elapsed']} of work   -   {res.timing['breakdown']}")
    except Exception as ex:                      # a drafter must never see a stack trace in the window
        watch.stop()
        res.timing = watch.report(headline="Stopped", caption="before it stopped")
        res.error = f"{type(ex).__name__}: {ex}"
        progress("bad", f"Stopped: {res.error}")
        progress("info", traceback.format_exc(limit=3))
    return res


def storey_sidecar(out: Path, stem: str) -> Path:
    """Where a drawing's storey schedule is kept. One file, beside its other output."""
    return out / f"{stem}.storeys.json"


def load_storeys(project, out: Path, stem: str, levels: Path | None = None):
    """The storey schedule for this drawing, from the best source available.

    In order: the sidecar the storey window wrote, then a level workbook somebody filled in
    before the window existed, then the drawing itself. The sidecar wins because the storey
    window owns the levels now -- ``levels.xlsx`` is written from it on every run, so reading
    the workbook back in preference would undo the last edit made in the window.

    A workbook named explicitly (``--levels``) is a deliberate instruction and does win: that
    is how a scripted run drives its own levels.
    """
    from ..export.levels import read_levels
    from ..storeys import StoreySchedule, from_level_rows, from_project

    if levels is not None and Path(levels).exists():
        return from_level_rows(read_levels(levels), source_file=stem), "the workbook you chose"
    sidecar = storey_sidecar(out, stem)
    if sidecar.exists():
        try:
            return StoreySchedule.load(sidecar), "your storeys"
        except Exception:
            pass                       # a damaged sidecar is re-seeded rather than fatal
    workbook = out / f"{stem}.levels.xlsx"
    if workbook.exists():
        schedule = from_level_rows(read_levels(workbook), source_file=stem)
        if len(schedule):
            return schedule, f"{workbook.name}, from before the storey window"
    return from_project(project), "the drawing"


def _levels_from_storeys(project, settings: JobSettings, out: Path, stem: str, progress: Progress):
    """Load the storeys, write the level workbook from them, and hand the rows on.

    Returns ``(level rows, level reference, workbook path, sidecar path)``.
    """
    from ..export.levels import read_level_settings, write_levels_from_storeys

    levels = Path(settings.levels) if settings.levels else None
    schedule, where = load_storeys(project, out, stem, levels)
    sidecar = storey_sidecar(out, stem)
    schedule.save(sidecar)

    workbook = levels if levels is not None else out / f"{stem}.levels.xlsx"
    reference = read_level_settings(workbook).get("level_reference") if workbook.exists() else None
    if levels is None:
        write_levels_from_storeys(schedule, workbook, project, level_reference=reference or "SSL")

    problems = schedule.problems([f.id for f in project.floors])
    errors = [x for x in problems if x.severity == "ERROR"]
    if not len(schedule):
        progress("warn", "         no storeys yet - press 'Storeys' to set the building up")
    else:
        elevations = schedule.elevations()
        progress("good" if not errors else "warn",
                 f"         {len(schedule)} storeys from {where}, {elevations[0]:.0f} to {elevations[-1]:.0f} mm")
    for x in errors[:5]:
        progress("bad", f"         {x.message}")
    for x in [y for y in problems if y.severity == "WARNING"][:5]:
        progress("warn", f"         {x.message}")
    return (schedule.level_rows() if len(schedule) and not errors else None,
            reference, workbook, sidecar)


def _write_revit_plan(np_, out: Path, stem: str, drawing: Path, progress: Progress, defaults: dict):
    """The Revit build plan, checked against the firm's template, as part of the ordinary run.

    Nobody should have to open a terminal to reach the last step of the pipeline, and nobody
    should have to know where the template description lives: it is found, not asked for.
    """
    from ..export.revit_excel import write_revit_workbook
    from ..export.revit_picker import write_picker_window
    from ..revit.mapping import RevitMapping
    from ..revit.plan import build_plan, check_against_template
    from ..revit.template import parse_shared_parameters, parse_template_md

    mapping_path = out / f"{stem}.revit-mapping.yaml"
    mapping = RevitMapping.load(mapping_path) if mapping_path.exists() else RevitMapping()
    if defaults.get("beam") is not None:
        mapping.default_beam_depth_mm = defaults["beam"]
    if defaults.get("slab") is not None:
        mapping.default_slab_thickness_mm = defaults["slab"]
    mapping.save(mapping_path)
    plan = build_plan(np_, mapping)

    template = _find_beside(out, drawing, REVIT_TEMPLATE_NAMES)
    if template is not None:
        shared_path = _find_beside(out, drawing, SHARED_PARAM_NAMES)
        shared = parse_shared_parameters(shared_path) if shared_path else None
        plan.template_check = check_against_template(plan, mapping, parse_template_md(template), shared)
    else:
        progress("warn", "         no Revit template description found, so the plan could not be checked "
                         "against it; put it in a 'templates' folder beside the drawing")

    json_path = out / f"{stem}.revit.json"
    json_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    # The window the Revit script shows, themed here because there is no C2B over there.
    write_picker_window(json_path)
    xlsx_path = write_revit_workbook(plan, out / f"{stem}.revit.xlsx")

    built = ", ".join(f"{n} {kind}s" for kind, n in sorted(plan.counts.items()) if kind != "levels" and n)
    progress("good", f"         {built or 'nothing to build'}")
    assumed = sum(1 for d in plan.diagnostics if d.code == "REVIT_DEPTH_ASSUMED")
    unsized = sum(1 for d in plan.diagnostics if d.code == "REVIT_NO_SIZE")
    if assumed:
        progress("info", f"         {assumed} members the drawing never sized were built at the default")
    if unsized:
        progress("warn", f"         {unsized} members have no size and no default, so they are not built - "
                         "set a default beam depth and slab thickness to include them")
    check = plan.template_check
    if check is not None:
        c = check.summary()
        progress("info", f"         against {check.template_name}: {c['types_present']} of {c['types_needed']} "
                         f"types already there, {c['types_to_create']} will be created")
        for fam in check.missing_families:
            progress("bad", f"         {fam} is not in your Revit template - load it, or nothing using it can be built")
        for pc in [x for x in check.params if not x.survives]:
            progress("warn", f"         {pc.name}: {pc.advice}")
        if check.marks_lost(plan.mark_params):
            progress("bad", f"         your Revit template binds none of {', '.join(plan.mark_params)}, so "
                            "every mark would be dropped. Revit's built-in Mark is not written any more, "
                            "so there is nothing to fall back on - bind it as a project parameter first")
        if check.grid_clashes:
            progress("warn", f"         your Revit template already has grids {', '.join(check.grid_clashes[:10])} - "
                             "the template's will be renamed out of the way so the client's can be created")
        for t in [x for x in check.types if x.note]:
            progress("warn", f"         {t.type_name} x{t.count}: {t.note}")
    return json_path, xlsx_path


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
