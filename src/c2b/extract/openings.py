"""Openings (cut-outs, shafts) and walls."""
from __future__ import annotations

from shapely.geometry import Point

from ..geometry import classify_polygon
from ..schema import Opening, Wall
from .associate import make_tag_cands
from .context import FloorContext, outline_points, pt, tag_ref
from .outlines import collect_outlines


def _cross_openings(ctx: FloorContext, existing: list) -> list:
    """Openings drawn as an X cross: two diagonal lines crossing each other give the opening's bounding box."""
    import math
    from shapely.geometry import LineString, Polygon
    from .outlines import Outline
    diag = []
    for p in ctx.geoms("OPENING", "line"):
        (x1, y1), (x2, y2) = list(p.geom.coords)[0][:2], list(p.geom.coords)[-1][:2]
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0
        if 10.0 < ang < 80.0 or 100.0 < ang < 170.0:
            diag.append((p, LineString([(x1, y1), (x2, y2)])))
    used: set[int] = set()
    found = []
    for i, (pa, la) in enumerate(diag):
        if i in used:
            continue
        for j in range(i + 1, len(diag)):
            if j in used:
                continue
            pb, lb = diag[j]
            if not la.crosses(lb):
                continue
            xs = [c[0] for c in la.coords] + [c[0] for c in lb.coords]
            ys = [c[1] for c in la.coords] + [c[1] for c in lb.coords]
            minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
            tol = max(25.0, 0.02 * max(maxx - minx, maxy - miny))
            corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
            ends = [tuple(la.coords[0][:2]), tuple(la.coords[-1][:2]), tuple(lb.coords[0][:2]), tuple(lb.coords[-1][:2])]
            # a real X: the four line ends are the four corners of one box
            if not all(any(math.dist(e, c) <= tol for c in corners) for e in ends) or not all(any(math.dist(e, c) <= tol for e in ends) for c in corners):
                continue
            box = Polygon(corners)
            if box.area < ctx.tol.opening_min_area_mm2:
                continue
            if any(box.intersection(o.poly).area > 0.5 * box.area for o in existing):
                continue
            found.append(Outline(box, "cross", pa.layer, [pa.handle, pb.handle]))
            used.update((i, j))
            break
    return found


def extract_openings(ctx: FloorContext) -> list[Opening]:
    tol = ctx.tol
    outlines = collect_outlines(ctx, "OPENING", 100.0, tol.opening_min_area_mm2, 1e10, 1e6)
    outlines += _cross_openings(ctx, outlines)
    labels = [t for t in ctx.texts("OPENING_TAG")] + [t for t in ctx.texts("NOTE") if t.text and len(t.text) <= 20]
    out: list[Opening] = []
    for o in outlines:
        c = o.poly.centroid
        label = None
        for t in labels:
            if o.poly.contains(Point(t.rep_point())):
                label = (label + " " if label else "") + t.text.strip()
                ctx.assigned_tag_handles.add(t.handle)
        out.append(Opening(id=ctx.ids.next("O"), floor_id=ctx.floor_id, label=label, center=pt((c.x, c.y)), outline=outline_points(o.poly),
                           area_mm2=round(o.poly.area, 1), source_layer=o.layer, source_handles=o.handles + o.merged_handles))
    return out


def extract_walls(ctx: FloorContext) -> list[Wall]:
    outlines = collect_outlines(ctx, "WALL", 75.0, 5e4, 1e10, 1e6)
    tags = make_tag_cands(ctx.texts("WALL_TAG"), group_factor=0.0)
    out: list[Wall] = []
    for o in outlines:
        s = classify_polygon(o.poly)
        my = [t for t in tags if o.poly.buffer(max(600.0, 2 * t.height)).contains(Point(t.center))]
        for t in my:
            ctx.assigned_tag_handles.add(t.prim.handle)
        mark = next((t.parsed.mark for t in my if t.parsed.mark), None)
        rule_mods = ctx.rules.get(o.layer).modifiers if o.layer in ctx.rules else []
        out.append(Wall(id=ctx.ids.next("W"), floor_id=ctx.floor_id, mark=mark, center=pt(s.center), outline=outline_points(o.poly),
                        length_mm=round(max(s.width, s.depth), 1), thickness_mm=round(min(s.width, s.depth), 1) if s.shape == "rect" else None,
                        rotation_deg=round(s.rotation_deg, 3), area_mm2=round(o.poly.area, 1), structural="non_structural" not in rule_mods,
                        tags=[tag_ref(t.prim) for t in my], source_layer=o.layer, source_handles=o.handles + o.merged_handles))
    return out


def extract_stairs(ctx: FloorContext) -> list:
    """Stair geometry is carried through as drawn: closed outlines plus the raw lines (treads, arrows)."""
    from ..schema import Point2, Stair
    from .context import outline_points
    outlines = collect_outlines(ctx, "STAIR", 100.0, 1e5, 1e10, 1e6, drop_containers=False)
    out = []
    for o in outlines:
        c = o.poly.centroid
        labels = [t.text.strip() for t in ctx.texts("STAIR_TAG") if o.poly.buffer(1000).contains(Point(t.rep_point()))]
        out.append(Stair(id=ctx.ids.next("ST"), floor_id=ctx.floor_id, label=labels[0] if labels else None, center=Point2(x=c.x, y=c.y),
                         outline=outline_points(o.poly), area_mm2=round(o.poly.area, 1), source_layer=o.layer, source_handles=o.handles + o.merged_handles))
    lines = []
    for p in ctx.geoms("STAIR", "line", "polyline"):
        coords = list(p.geom.coords)
        for a, b in zip(coords[:-1], coords[1:]):
            lines.append([Point2(x=a[0], y=a[1]), Point2(x=b[0], y=b[1])])
    if lines:
        c = (sum(l[0].x for l in lines) / len(lines), sum(l[0].y for l in lines) / len(lines))
        out.append(Stair(id=ctx.ids.next("ST"), floor_id=ctx.floor_id, label=None, center=Point2(x=c[0], y=c[1]), outline=[], lines=lines,
                         area_mm2=0.0, source_layer=next(iter({p.layer for p in ctx.geoms("STAIR", "line", "polyline")})), source_handles=[p.handle for p in ctx.geoms("STAIR", "line", "polyline")]))
    return out
