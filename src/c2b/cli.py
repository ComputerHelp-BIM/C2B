"""Command line interface: ``c2b inspect | profile suggest | extract | render``."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import SCHEMA_VERSION, __version__

app = typer.Typer(help="C2B: CAD to BIM. Step 1 extracts structural elements from client DXF drawings.", no_args_is_help=True)
profile_app = typer.Typer(help="Layer-role profiles.")
app.add_typer(profile_app, name="profile")


@app.command()
def version() -> None:
    """Print tool and schema versions."""
    typer.echo(f"c2b {__version__} (schema {SCHEMA_VERSION})")


@app.command()
def gui(drawing: Optional[Path] = typer.Argument(None, exists=True, help="Optional drawing to preload")) -> None:
    """Open the C2B window: pick a drawing, press Run, read the issues."""
    from .gui import run_gui

    raise typer.Exit(run_gui(drawing))


@app.command()
def demo(out: Path = typer.Option(Path("demo"), "--out", "-o", help="Folder for the demo drawing")) -> None:
    """Write a small demo client drawing so the whole pipeline can be tried without client data."""
    from .demo import build_demo_drawing

    out.mkdir(parents=True, exist_ok=True)
    path = build_demo_drawing(out / "demo.dxf")
    typer.echo(f"Demo client drawing: {path}")
    typer.echo(f"Try it with:  c2b run {path}")


@app.command()
def doctor(selftest: bool = typer.Option(True, "--selftest/--no-selftest", help="Run the whole pipeline on the demo drawing")) -> None:
    """Check the installation: Python, dependencies, DWG converter, and a full pipeline self-test."""
    import platform
    import tempfile

    from . import SCHEMA_VERSION
    from .dwg import converter_status

    ok = True
    typer.echo(f"c2b            {__version__} (extraction schema {SCHEMA_VERSION})")
    typer.echo(f"python         {platform.python_version()} on {platform.system()} {platform.release()}")
    for mod in ("ezdxf", "shapely", "pydantic", "openpyxl", "typer", "yaml"):
        try:
            m = __import__(mod)
            typer.echo(f"{mod:14s} {getattr(m, '__version__', 'ok')}")
        except ImportError:
            typer.secho(f"{mod:14s} MISSING - run: pip install -e .", fg=typer.colors.RED)
            ok = False
    # Which window C2B would open, and why. This is the first thing to look at when the
    # branded window is not the one that appeared.
    from .ui import wpf as _wpf

    if _wpf.available():
        typer.secho(f"{'window':14s} branded (WPF) on {_wpf.runtime()}", fg=typer.colors.GREEN)
        # WPF builds a control only on a single-threaded apartment. STA here means the window
        # opens on this thread; anything else means it gets one of its own, which also works.
        state = _wpf.apartment()
        typer.echo(f"{'window thread':14s} {state}" + ("" if state == "STA" else
                                                       " - the window will open on a thread of its own"))
    else:
        typer.secho(f"{'window':14s} plain (Tkinter)", fg=typer.colors.YELLOW)
        for line in _wpf.why_not_in_full().splitlines():
            typer.secho(f"{'':14s} {line}", fg=typer.colors.YELLOW)
        found = _wpf.desktop_runtimes()
        typer.secho(f"{'.NET desktop':14s} " + (", ".join(".".join(str(p) for p in v) for v in found)
                                                if found else "none - WPF needs the .NET Desktop Runtime"),
                    fg=typer.colors.YELLOW if not found else None)

    try:
        import matplotlib
        typer.echo(f"{'matplotlib':14s} {matplotlib.__version__} (optional, for c2b render)")
    except ImportError:
        typer.echo(f"{'matplotlib':14s} not installed (optional, only needed for c2b render)")
    conv = converter_status()
    if conv["oda_file_converter"]:
        typer.echo(f"{'DWG':14s} ODA File Converter at {conv['oda_file_converter']}")
    elif conv["accoreconsole"]:
        typer.echo(f"{'DWG':14s} AutoCAD accoreconsole at {conv['accoreconsole']}")
    else:
        typer.echo(f"{'DWG':14s} no converter found - save DXF from AutoCAD, or install ODA File Converter")

    if selftest:
        typer.echo("\nSelf-test: demo drawing -> extract -> normalize -> verify")
        from .demo import build_demo_drawing
        from .export.template_dxf import write_template_dxf
        from .normalize.pipeline import normalize as run_normalize
        from .normalize.spec import TemplateSpec
        from .pipeline import extract as run_extract
        from .roundtrip.diff import compare
        from .roundtrip.reader import read_template

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dxf = build_demo_drawing(tmp / "demo.dxf")
            result = run_extract(dxf)
            spec = TemplateSpec()
            np_ = run_normalize(result.project, spec, None, source_file=dxf.name)
            tpl = write_template_dxf(np_, tmp / "demo.template.dxf", spec)
            res = compare(np_, read_template(tpl, spec))
            for label, value, good in (
                ("extract", f"{result.project.summary.columns} columns, {result.project.summary.beams} beams", result.project.summary.errors == 0),
                ("normalize", f"{np_.summary.columns} columns, {np_.summary.beams} spans, {np_.summary.panels} panels", np_.summary.errors == 0),
                ("template dxf", f"{tpl.stat().st_size // 1024} KB", tpl.exists()),
                ("round trip", "identical" if res.ok() else f"{res.errors} errors, {res.warnings} warnings", res.ok()),
            ):
                typer.secho(f"  {label:14s} {value}", fg=typer.colors.GREEN if good else typer.colors.RED)
                ok = ok and good
    typer.secho("\nREADY" if ok else "\nPROBLEMS FOUND", fg=typer.colors.GREEN if ok else typer.colors.RED)
    raise typer.Exit(0 if ok else 1)


@app.command()
def run(
    drawing: Path = typer.Argument(..., exists=True, readable=True, help="Client DXF (or DWG when a converter is installed)"),
    out: Path = typer.Option(None, "--out", "-o", help="Output folder (default: <drawing folder>/out/<stem>)"),
    seed: Optional[Path] = typer.Option(None, "--seed", exists=True, help="Seed template DXF (your CH template)"),
    spec: Optional[Path] = typer.Option(None, "--spec", "-s", exists=True, help="Template spec YAML"),
    profile: Optional[Path] = typer.Option(None, "--profile", "-p", exists=True, help="Layer profile YAML for this client"),
    levels: Optional[Path] = typer.Option(None, "--levels", "-l", exists=True, help="Filled level schedule (default: the one in the output folder)"),
    units: Optional[str] = typer.Option(None, "--units", "-u", help="Override drawing units: mm, cm, m, in, ft"),
) -> None:
    """The whole pipeline in one command: extract, normalise to the template, and verify the round trip."""
    from .dwg import ensure_dxf
    from .export.excel import write_workbook
    from .export.jsonout import write_json
    from .export.levels import read_level_settings, write_levels_from_storeys
    from .export.normalized_excel import write_normalized_workbook
    from .export.report import write_report
    from .export.review_dxf import write_review_dxf
    from .export.template_dxf import write_template_dxf
    from .export.verify import write_verify_report, write_verify_workbook
    from .normalize.pipeline import normalize as run_normalize
    from .normalize.spec import TemplateSpec
    from .pipeline import extract as run_extract
    from .profile import Profile
    from .roundtrip.diff import compare
    from .roundtrip.reader import read_template

    stem = drawing.stem
    out = out or drawing.parent / "out" / stem
    out.mkdir(parents=True, exist_ok=True)
    try:
        dxf, converted = ensure_dxf(drawing, out)
    except RuntimeError as ex:
        typer.secho(str(ex), fg=typer.colors.RED)
        raise typer.Exit(2) from None
    if converted:
        typer.echo(f"Converted {drawing.name} to {dxf.name}")

    typer.secho(f"\n1/3  Extracting {dxf.name}", bold=True)
    result = run_extract(dxf, Profile.load(profile) if profile else None, units)
    project = result.project
    write_json(project, out / f"{stem}.c2b.json")
    write_workbook(project, out / f"{stem}.review.xlsx")
    write_report(project, out / f"{stem}.report.md")
    write_review_dxf(project, out / f"{stem}.review.dxf")
    result.profile.save(out / f"{stem}.profile.yaml")
    s1 = project.summary
    typer.echo(f"     floors {s1.floors} | columns {s1.columns} | beams {s1.beams} | slabs {s1.slabs} | footings {s1.footings} | {s1.errors} errors, {s1.warnings} warnings")

    # The storeys are the building's levels, and the storey window owns them; the workbook is
    # written from them. A run with no storeys yet seeds them from the drawing, so the first run
    # already has an elevation for every floor rather than an empty form to go and fill in.
    from .gui.runner import load_storeys, storey_sidecar

    schedule, where = load_storeys(project, out, stem, levels)
    schedule.save(storey_sidecar(out, stem))
    levels_path = levels or (out / f"{stem}.levels.xlsx")
    level_ref = read_level_settings(levels_path).get("level_reference") if levels_path.exists() else None
    if levels is None:
        write_levels_from_storeys(schedule, levels_path, project, level_reference=level_ref or "SSL")
    problems = schedule.problems([f.id for f in project.floors])
    errors = [x for x in problems if x.severity == "ERROR"]
    typer.echo(f"     storeys: {len(schedule)} from {where}"
               + (f", {len(errors)} to fix" if errors else ""))
    for x in errors[:5]:
        typer.secho(f"     {x.message}", fg=typer.colors.RED)
    level_rows = schedule.level_rows() if len(schedule) and not errors else None

    typer.secho("2/3  Normalising to the template", bold=True)
    tspec = TemplateSpec.load(spec) if spec else TemplateSpec()
    np_ = run_normalize(project, tspec, level_rows, source_file=dxf.name, level_reference=level_ref)
    (out / f"{stem}.normalized.json").write_text(np_.model_dump_json(indent=2), encoding="utf-8")
    write_normalized_workbook(np_, out / f"{stem}.schedules.xlsx")
    tspec.save(out / f"{stem}.template-spec.yaml")
    template = write_template_dxf(np_, out / f"{stem}.template.dxf", tspec, seed)
    s2 = np_.summary
    typer.echo(f"     stacks {s2.stacks} | columns {s2.columns} | spans {s2.beams} | panels {s2.panels} | footings {s2.footings} | levels {s2.levels} | {s2.errors} errors, {s2.warnings} warnings")

    typer.secho("3/3  Verifying the round trip", bold=True)
    drawing_model = read_template(template, tspec)
    (out / f"{stem}.reread.json").write_text(drawing_model.model_dump_json(indent=2), encoding="utf-8")
    write_normalized_workbook(drawing_model, out / f"{stem}.reread.xlsx")
    res = compare(np_, drawing_model)
    write_verify_workbook(res, np_, drawing_model, out / f"{stem}.verify.xlsx")
    write_verify_report(res, np_, drawing_model, out / f"{stem}.verify.md")
    color = typer.colors.GREEN if res.ok() else (typer.colors.RED if res.errors else typer.colors.YELLOW)
    typer.secho(f"     {'identical' if res.ok() else 'differences'}: {res.errors} errors, {res.warnings} warnings", fg=color)

    typer.secho("\nDone. Open these next:", bold=True)
    typer.echo(f"  {out / f'{stem}.template.dxf'}       the drawing in your template")
    typer.echo(f"  {out / f'{stem}.review.xlsx'}        what was read from the client drawing, with diagnostics")
    typer.echo(f"  {out / f'{stem}.schedules.xlsx'}     column / beam / slab / footing schedules")
    typer.echo(f"  {out / f'{stem}.verify.md'}          round-trip check")
    typer.echo(f"  {out / f'{stem}.review.dxf'}         overlay on the client drawing to see what was recognised")


@app.command()
def inspect(dxf: Path = typer.Argument(..., exists=True, readable=True, help="DXF file"),
            units: Optional[str] = typer.Option(None, "--units", "-u", help="Override drawing units: mm, cm, m, in, ft")) -> None:
    """Summarise a DXF: units, layers, entity counts, floors found."""
    from .dxfio import iter_prims, layer_stats, load_document, modelspace_extent, read_meta
    from .units import resolve_units

    doc = load_document(dxf)
    meta = read_meta(doc, dxf)
    res = resolve_units(meta.insunits, modelspace_extent(doc), units)
    typer.echo(f"File: {meta.file}  DXF {meta.dxf_version}  entities: {meta.entity_count}  layouts: {', '.join(meta.layouts)}")
    typer.echo(f"Units: {res.name} (x{res.scale_to_mm} to mm, {res.source}, {res.confidence})")
    prims, _ = iter_prims(doc, res.scale_to_mm)
    from .profile import suggest_rule
    typer.echo(f"\n{'Layer':40s} {'Role':14s} {'Conf':7s} entities")
    for layer, counts in sorted(layer_stats(prims).items()):
        rule = suggest_rule(layer, counts)
        typer.echo(f"{layer[:40]:40s} {rule.geometry:14s} {rule.confidence:7s} {dict(sorted(counts.items(), key=lambda kv: -kv[1]))}")


@profile_app.command("suggest")
def profile_suggest(dxf: Path = typer.Argument(..., exists=True), out: Path = typer.Option(None, "--out", "-o", help="YAML path (default <dxf>.profile.yaml)"),
                    units: Optional[str] = typer.Option(None, "--units", "-u")) -> None:
    """Write an editable layer profile suggested from the drawing."""
    from .pipeline import suggest_profile_for_file

    profile = suggest_profile_for_file(dxf, units)
    out = out or dxf.with_suffix(".profile.yaml")
    profile.save(out)
    low = [l for l, r in profile.layers.items() if r.confidence in ("low", "none") and r.geometry != "IGNORE"]
    typer.echo(f"Profile written to {out} ({len(profile.layers)} layers; {len(low)} need review: {', '.join(low[:10])}{' ...' if len(low) > 10 else ''})")


@app.command()
def extract(
    dxf: Path = typer.Argument(..., exists=True, readable=True, help="Client DXF file"),
    out: Path = typer.Option(None, "--out", "-o", help="Output folder (default: <dxf folder>/out/<stem>)"),
    profile: Optional[Path] = typer.Option(None, "--profile", "-p", exists=True, help="Layer profile YAML"),
    levels: Optional[Path] = typer.Option(None, "--levels", "-l", exists=True, help="Filled level schedule (xlsx)"),
    units: Optional[str] = typer.Option(None, "--units", "-u", help="Override drawing units: mm, cm, m, in, ft"),
    review_dxf: bool = typer.Option(True, "--review-dxf/--no-review-dxf", help="Write the review overlay DXF"),
) -> None:
    """Extract structural elements to JSON + Excel + diagnostics (+ review DXF)."""
    from .export.excel import write_workbook
    from .export.jsonout import write_json
    from .export.levels import apply_levels, write_levels_template
    from .export.report import write_report
    from .export.review_dxf import write_review_dxf
    from .pipeline import extract as run_extract
    from .profile import Profile

    user_profile = Profile.load(profile) if profile else None
    out = out or dxf.parent / "out" / dxf.stem
    out.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Extracting {dxf.name} ...")
    result = run_extract(dxf, user_profile, units)
    project = result.project
    if levels:
        problems = apply_levels(project, levels)
        for p in problems:
            typer.secho(f"  levels: {p}", fg=typer.colors.YELLOW)
        project.recompute_summary()

    stem = dxf.stem
    write_json(project, out / f"{stem}.c2b.json")
    write_workbook(project, out / f"{stem}.review.xlsx")
    write_report(project, out / f"{stem}.report.md")
    write_levels_template(project, out / f"{stem}.levels.xlsx")   # extract alone: no storeys yet
    result.profile.name = result.profile.name if result.profile.name != "auto" else stem
    result.profile.save(out / f"{stem}.profile.yaml")
    if review_dxf:
        write_review_dxf(project, out / f"{stem}.review.dxf")

    s = project.summary
    typer.echo(f"Floors {s.floors} | grids {s.grids} | columns {s.columns} | beams {s.beams} | slabs {s.slabs} | footings {s.footings} | openings {s.openings} | walls {s.walls} | schedules {s.schedules}")
    color = typer.colors.RED if s.errors else typer.colors.YELLOW if s.warnings else typer.colors.GREEN
    typer.secho(f"Diagnostics: {s.errors} errors, {s.warnings} warnings, {s.infos} infos", fg=color)
    for f in project.floors:
        c = f.counts
        typer.echo(f"  {f.id} {f.name[:40]:40s} cols {c.get('columns', 0):4d} beams {c.get('beams', 0):4d} slabs {c.get('slabs', 0):4d} ftg {c.get('footings', 0):4d} grids {c.get('grids', 0):3d}")
    typer.echo(f"Outputs in {out}")


@app.command()
def normalize(
    json_file: Path = typer.Argument(..., exists=True, help="<stem>.c2b.json produced by extract"),
    out: Path = typer.Option(None, "--out", "-o", help="Output folder (default: next to the JSON)"),
    spec: Optional[Path] = typer.Option(None, "--spec", "-s", exists=True, help="Template spec YAML (default: built-in CH template spec)"),
    seed: Optional[Path] = typer.Option(None, "--seed", exists=True, help="Seed template DXF whose layers/styles/legend are reused"),
    levels: Optional[Path] = typer.Option(None, "--levels", "-l", exists=True, help="Level schedule xlsx (elevations)"),
) -> None:
    """Utility 3: normalise to the template (stacks, spans, panels, marks) and write the template DXF."""
    from .export.jsonout import read_json
    from .export.levels import read_level_settings, read_levels
    from .export.normalized_excel import write_normalized_workbook
    from .export.template_dxf import write_template_dxf
    from .normalize.pipeline import normalize as run_normalize
    from .normalize.spec import TemplateSpec

    project = read_json(json_file)
    tspec = TemplateSpec.load(spec) if spec else TemplateSpec()
    level_rows = read_levels(levels) if levels else None
    level_ref = read_level_settings(levels).get("level_reference") if levels else None
    out = out or json_file.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = json_file.name.replace(".c2b.json", "")
    typer.echo(f"Normalising {json_file.name} ...")
    np_ = run_normalize(project, tspec, level_rows, source_file=project.drawing.file, level_reference=level_ref)
    from .diagnostics import DiagnosticsCollector
    diag = DiagnosticsCollector()
    dxf_path = write_template_dxf(np_, out / f"{stem}.template.dxf", tspec, seed, diag)
    np_.diagnostics.extend(diag.items)
    np_.recompute_summary()
    (out / f"{stem}.normalized.json").write_text(np_.model_dump_json(indent=2), encoding="utf-8")
    write_normalized_workbook(np_, out / f"{stem}.schedules.xlsx")
    tspec.save(out / f"{stem}.template-spec.yaml")
    s = np_.summary
    typer.echo(f"Floors {s.floors} | levels {s.levels} | stacks {s.stacks} | columns {s.columns} | beam spans {s.beams} | panels {s.panels} | footings {s.footings} | grids {s.grids} | openings {s.openings}")
    color = typer.colors.RED if s.errors else typer.colors.YELLOW if s.warnings else typer.colors.GREEN
    typer.secho(f"Diagnostics: {s.errors} errors, {s.warnings} warnings, {s.infos} infos", fg=color)
    for f in np_.floors:
        c = f.counts
        typer.echo(f"  {f.id} {f.name[:36]:36s} cols {c.get('columns', 0):4d} spans {c.get('beams', 0):4d} panels {c.get('panels', 0):4d} ftg {c.get('footings', 0):3d} grids {c.get('grids', 0):3d}")
    typer.echo(f"Template DXF: {dxf_path}")


@app.command()
def verify(
    template: Path = typer.Argument(..., exists=True, readable=True, help="<stem>.template.dxf written by normalize"),
    against: Optional[Path] = typer.Option(None, "--against", "-a", exists=True, help="<stem>.normalized.json to compare with (default: next to the DXF)"),
    spec: Optional[Path] = typer.Option(None, "--spec", "-s", exists=True, help="Template spec YAML (default: <stem>.template-spec.yaml next to the DXF, else built-in)"),
    out: Path = typer.Option(None, "--out", "-o", help="Output folder (default: next to the DXF)"),
) -> None:
    """Utility 4: read the template DXF back to JSON + Excel and verify it against the normalised model."""
    from .diagnostics import DiagnosticsCollector
    from .export.normalized_excel import write_normalized_workbook
    from .export.verify import write_verify_report, write_verify_workbook
    from .normalize.model import NormalizedProject
    from .normalize.spec import TemplateSpec
    from .roundtrip.diff import compare
    from .roundtrip.reader import read_template

    stem = template.name.replace(".template.dxf", "").replace(".dxf", "")
    out = out or template.parent
    out.mkdir(parents=True, exist_ok=True)
    spec_path = spec or (template.parent / f"{stem}.template-spec.yaml")
    tspec = TemplateSpec.load(spec_path) if spec_path.exists() else TemplateSpec()
    typer.echo(f"Reading {template.name} with spec '{tspec.name}' ...")
    diag = DiagnosticsCollector()
    drawing = read_template(template, tspec, diag)
    (out / f"{stem}.reread.json").write_text(drawing.model_dump_json(indent=2), encoding="utf-8")
    write_normalized_workbook(drawing, out / f"{stem}.reread.xlsx")
    s = drawing.summary
    typer.echo(f"Floors {s.floors} | levels {s.levels} | columns {s.columns} | beam spans {s.beams} | panels {s.panels} | footings {s.footings} | grids {s.grids} | openings {s.openings}")

    model_path = against or (template.parent / f"{stem}.normalized.json")
    if not model_path.exists():
        typer.secho(f"No normalised model at {model_path}; wrote the re-read JSON and workbook only.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)
    model = NormalizedProject.model_validate_json(model_path.read_text(encoding="utf-8"))
    res = compare(model, drawing)
    write_verify_workbook(res, model, drawing, out / f"{stem}.verify.xlsx")
    write_verify_report(res, model, drawing, out / f"{stem}.verify.md")
    color = typer.colors.GREEN if res.ok() else (typer.colors.RED if res.errors else typer.colors.YELLOW)
    typer.secho(f"{'PASS' if res.ok() else 'DIFFERENCES FOUND'}: {res.errors} errors, {res.warnings} warnings, {res.infos} infos", fg=color)
    from collections import Counter as _C
    for code, n in _C(d.code for d in res.findings).most_common(8):
        typer.echo(f"  {code:20s} {n}")
    typer.echo(f"Outputs in {out}")
    raise typer.Exit(0 if res.ok() else 1)


@app.command("revit-plan")
def revit_plan(
    normalized: Path = typer.Argument(..., exists=True, help="<stem>.normalized.json from normalize (or .reread.json after drafter edits)"),
    mapping: Optional[Path] = typer.Option(None, "--mapping", "-m", help="Revit family mapping YAML (default: next to the file, else built-in)"),
    out: Path = typer.Option(None, "--out", "-o", help="Output folder (default: next to the JSON)"),
    template: Optional[Path] = typer.Option(None, "--template", "-t", exists=True,
                                            help="Revit template description (.md from Extract Template): checks the plan against it"),
    shared_params: Optional[Path] = typer.Option(None, "--shared-params", exists=True,
                                                 help="Revit shared parameter file, so an unbound name can be told from a name that does not exist"),
    write_mapping: bool = typer.Option(False, "--write-mapping", help="Write a starting mapping file and stop"),
) -> None:
    """Utility 5, step 1: turn the model into a Revit build plan and a workbook of what will be created."""
    from .export.revit_excel import write_revit_workbook
    from .export.revit_picker import write_picker_window
    from .normalize.model import NormalizedProject
    from .revit.mapping import RevitMapping
    from .revit.plan import build_plan, check_against_template
    from .revit.template import parse_shared_parameters, parse_template_md

    stem = normalized.name.replace(".normalized.json", "").replace(".reread.json", "").replace(".json", "")
    out = out or normalized.parent
    out.mkdir(parents=True, exist_ok=True)
    mapping_path = mapping or (out / f"{stem}.revit-mapping.yaml")
    if write_mapping:
        RevitMapping().save(mapping_path)
        typer.echo(f"Mapping written to {mapping_path}. Edit the family and type names to match your Revit template.")
        raise typer.Exit(0)
    rm = RevitMapping.load(mapping_path) if mapping_path.exists() else RevitMapping()
    if not mapping_path.exists():
        rm.save(mapping_path)
        typer.secho(f"No mapping found, so a starting one was written to {mapping_path.name}. Check the family names in it.", fg=typer.colors.YELLOW)
    model = NormalizedProject.model_validate_json(normalized.read_text(encoding="utf-8"))
    plan = build_plan(model, rm)
    if template is not None:
        digest = parse_template_md(template)
        shared = parse_shared_parameters(shared_params) if shared_params else None
        plan.template_check = check_against_template(plan, rm, digest, shared)
    (out / f"{stem}.revit.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    # The window the Revit script shows, themed here because there is no C2B over there.
    write_picker_window(out / f"{stem}.revit.json")
    write_revit_workbook(plan, out / f"{stem}.revit.xlsx")
    errors = [d for d in plan.diagnostics if d.severity == "ERROR"]
    for kind, n in sorted(plan.counts.items()):
        typer.echo(f"  {kind:12s} {n}")
    if plan.template_check is not None:
        c = plan.template_check
        s = c.summary()
        typer.echo(f"\n  against {c.template_name}: {s['types_present']} of {s['types_needed']} types already there, "
                   f"{s['types_to_create']} to create, {s['new_levels']} levels to create")
        for fam in c.missing_families:
            typer.secho(f"  family not in the template: {fam} - load it, or nothing using it can be built", fg=typer.colors.RED)
        for pc in [x for x in c.params if not x.survives]:
            typer.secho(f"  {pc.name}: {pc.advice}", fg=typer.colors.YELLOW)
        if c.marks_lost(plan.mark_params):
            typer.secho(f"  NO MARKS: this template binds none of {', '.join(plan.mark_params)}, so every "
                        "mark C2B writes is dropped. Revit's built-in Mark is not written any more -- it "
                        "must be unique within a category and a structural mark is not -- so there is "
                        "nothing to fall back on. Bind it as a project parameter before importing.",
                        fg=typer.colors.RED)
        if c.grid_clashes:
            typer.secho(f"  the template already has grids {', '.join(c.grid_clashes[:10])}; "
                        "its own will be renamed so the client's can be created", fg=typer.colors.YELLOW)
        for t in [x for x in c.types if x.note]:
            typer.secho(f"  worth a look: {t.type_name} x{t.count} - {t.note}", fg=typer.colors.YELLOW)
    if errors:
        for d in errors[:5]:
            typer.secho(f"  {d.code}: {d.message}", fg=typer.colors.RED)
    typer.secho(f"Build plan: {out / f'{stem}.revit.json'}", fg=typer.colors.RED if errors else typer.colors.GREEN)
    typer.echo(f"Check {out / f'{stem}.revit.xlsx'} (Types to create) before running it in Revit.")
    raise typer.Exit(1 if errors else 0)


@app.command("revit-verify")
def revit_verify(
    plan_json: Path = typer.Argument(..., exists=True, help="<stem>.revit.json, the build plan that was run"),
    built: Path = typer.Argument(..., exists=True, help="Extract Template .md of the Revit project AFTER the import"),
    out: Path = typer.Option(None, "--out", "-o", help="Output folder (default: next to the plan)"),
) -> None:
    """Utility 5, step 2: check what Revit built against what the plan asked for.

    Run the firm's Extract Template tool on the project after importing, and pass its markdown
    here. Nothing talks to Revit: this compares two files.
    """
    from .revit.plan import RevitPlan
    from .revit.template import parse_template_md
    from .revit.verify import verify_after_import, write_import_report

    plan = RevitPlan.model_validate_json(plan_json.read_text(encoding="utf-8"))
    check = verify_after_import(plan, parse_template_md(built))
    out = out or plan_json.parent
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{plan_json.name.replace('.revit.json', '')}.revit-check.md"
    write_import_report(check, report)

    s = check.summary()
    for key, value in s.items():
        typer.echo(f"  {key:16s} {value}")
    for row in check.problems()[:20]:
        typer.secho(f"  {row.what}: planned {row.planned}, model has {row.found}", fg=typer.colors.RED)
        if row.note:
            typer.echo(f"      {row.note}")
    typer.secho(f"Import check: {report}", fg=typer.colors.RED if check.problems() else typer.colors.GREEN)
    raise typer.Exit(1 if check.problems() else 0)


@app.command()
def render(json_file: Path = typer.Argument(..., exists=True, help="<stem>.c2b.json produced by extract"),
           out: Path = typer.Option(None, "--out", "-o", help="PNG path"), floor: Optional[str] = typer.Option(None, "--floor", help="Floor id, e.g. L01"),
           dpi: int = typer.Option(150, "--dpi")) -> None:
    """Render extracted elements of one floor to PNG (requires matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as ex:  # pragma: no cover
        raise typer.BadParameter("matplotlib is not installed (pip install c2b[render])") from ex
    from .export.jsonout import read_json

    project = read_json(json_file)
    fids = [floor] if floor else [f.id for f in project.floors]
    for fid in fids:
        fig, ax = plt.subplots(figsize=(16, 12))
        for g in project.grids:
            if g.floor_id == fid:
                ax.plot([g.start.x, g.end.x], [g.start.y, g.end.y], color="0.75", lw=0.5, ls="--")
                if g.label:
                    ax.text(g.start.x, g.start.y, g.label, fontsize=6, color="0.4")
        for b in project.beams:
            if b.floor_id == fid:
                xs = [p.x for p in b.outline] + [b.outline[0].x]
                ys = [p.y for p in b.outline] + [b.outline[0].y]
                ax.fill(xs, ys, color="tab:green", alpha=0.35, lw=0)
                ax.plot([b.start.x, b.end.x], [b.start.y, b.end.y], color="tab:green", lw=0.6)
        for c in project.columns:
            if c.floor_id == fid:
                xs = [p.x for p in c.outline] + [c.outline[0].x]
                ys = [p.y for p in c.outline] + [c.outline[0].y]
                ax.fill(xs, ys, color="tab:orange" if c.wall_like else "tab:red", alpha=0.8, lw=0)
                if c.mark or c.width_mm:
                    ax.text(c.center.x, c.center.y, f"{c.mark or ''} {c.width_mm or c.diameter_mm or ''}", fontsize=4, ha="center")
        for f in project.footings:
            if f.floor_id == fid:
                xs = [p.x for p in f.outline] + [f.outline[0].x]
                ys = [p.y for p in f.outline] + [f.outline[0].y]
                ax.plot(xs, ys, color="tab:brown", lw=0.8)
        for o in project.openings:
            if o.floor_id == fid:
                xs = [p.x for p in o.outline] + [o.outline[0].x]
                ys = [p.y for p in o.outline] + [o.outline[0].y]
                ax.fill(xs, ys, color="tab:purple", alpha=0.3, lw=0)
        for s in project.slabs:
            if s.floor_id == fid:
                ax.text(s.position.x, s.position.y, f"{s.thickness_mm or '?'}", fontsize=4, color="tab:blue", ha="center")
        for d in project.diagnostics:
            if d.floor_id == fid and d.location and d.severity != "INFO":
                ax.plot(d.location.x, d.location.y, marker="x", color="red" if d.severity == "ERROR" else "orange", ms=4, mew=0.8)
        name = next((f.name for f in project.floors if f.id == fid), fid)
        ax.set_aspect("equal")
        ax.set_title(f"{project.drawing.file}  {fid} {name}")
        ax.autoscale()
        target = out if (out and len(fids) == 1) else (out or json_file.parent) / f"{json_file.stem.replace('.c2b', '')}.{fid}.png"
        fig.savefig(target, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        typer.echo(f"Rendered {target}")


if __name__ == "__main__":  # pragma: no cover
    app()
