"""Beam runs -> spans between supports."""
from __future__ import annotations

from shapely.geometry import Polygon

from ..schema import Beam, Project
from .geometry import Axis, Run, Support, complement, crossing_cuts, poly_from_points, span_rectangle, support_cuts
from .spec import TemplateSpec


def runs_for_floor(project: Project, fid: str) -> list[Run]:
    runs = []
    for b in project.beams:
        if b.floor_id != fid or b.length_mm <= 0:
            continue
        outline = poly_from_points(b.outline)
        if outline is None:
            continue
        runs.append(Run(b.id, Axis((b.start.x, b.start.y), (b.end.x, b.end.y)), b.width_mm or b.drawn_width_mm, b.depth_mm, outline, b))
    return runs


def split_runs(runs: list[Run], supports: list[Support], spec: TemplateSpec, diag, fid: str) -> list[dict]:
    """Return span records: {run, t1, t2, outline, support_start, support_end}."""
    rules = spec.split
    out: list[dict] = []
    for run in runs:
        t_min, t_max = 0.0, run.axis.length
        cuts = []
        if rules.at_columns or rules.at_walls:
            cuts, t_min, t_max = support_cuts(run, supports, rules.support_cover_ratio, rules.irregular_support_to_centre, rules.irregular_angle_tol_deg)
        cuts += crossing_cuts(run, runs, end_tol=max(run.width, 50.0), trim_at_faces=rules.trim_at_beam_faces, split_crossing_by=rules.split_crossing_by)
        free = complement([(c.t1, c.t2) for c in cuts], t_max, t_min)
        for i, (t1, t2) in enumerate(free):
            if t2 - t1 < rules.min_span_mm:
                diag.info("SPAN_DROPPED", f"Span of {t2 - t1:.0f} mm on beam {run.id} dropped", floor_id=fid, element_id=run.id, location=run.axis.point_at(t1))
                continue
            start_sup = _support_at(cuts, t1, before=True) or _touching_support(run, t1, supports, runs, run.width)
            end_sup = _support_at(cuts, t2, before=False) or _touching_support(run, t2, supports, runs, run.width)
            out.append({"run": run, "t1": t1, "t2": t2, "outline": span_rectangle(run, t1, t2), "support_start": start_sup, "support_end": end_sup})
    return out


def _touching_support(run: Run, t: float, supports, runs, width: float) -> str | None:
    """A span that ends where a column or another beam begins (touching, not overlapping)."""
    from shapely.geometry import Point
    p = Point(run.axis.point_at(t))
    tol = max(60.0, 0.25 * width)
    best, best_d = None, None
    for sup in supports:
        d = sup.poly.distance(p)
        if d <= tol and (best_d is None or d < best_d):
            best, best_d = sup.id, d
    if best is None:
        for other in runs:
            if other.id == run.id:
                continue
            d = other.outline.distance(p)
            if d <= tol and (best_d is None or d < best_d):
                best, best_d = other.id, d
    return best


def _support_at(cuts, t: float, before: bool) -> str | None:
    best = None
    for c in cuts:
        if before and abs(c.t2 - t) < 1e-6:
            best = c.by
        if not before and abs(c.t1 - t) < 1e-6:
            best = c.by
    return best
