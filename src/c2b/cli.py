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
    write_levels_template(project, out / f"{stem}.levels.xlsx")
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
