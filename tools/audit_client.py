"""Audit an extraction against the client drawing it came from.

Answers the only question that matters early on: of what the client drew and tagged, how
much did C2B actually pick up, and what did it invent? Everything is per floor, because a
single bad floor is invisible in a total.

Usage: python tools/audit_client.py <client.dxf> <out/<stem>/<stem>.c2b.json> [<...>.normalized.json]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import Point, Polygon


def poly_of(points):
    pts = [(p["x"], p["y"]) for p in points] if points and isinstance(points[0], dict) else list(points)
    if len(pts) < 3:
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return None if poly.is_empty else (max(poly.geoms, key=lambda g: g.area) if poly.geom_type == "MultiPolygon" else poly)


def main(client_path: str, extract_path: str, normalized_path: str | None = None) -> None:
    project = json.loads(Path(extract_path).read_text())
    normalized = json.loads(Path(normalized_path).read_text()) if normalized_path else None
    roles = {l["layer"]: (l["geometry_role"], l["text_role"]) for l in project["layer_map"]}
    floors = {f["id"]: f for f in project["floors"]}
    frames = {f["id"]: poly_of([(p["x"], p["y"]) for p in f["boundary"]]) for f in project["floors"] if f["boundary"]}

    # read the client exactly as the extractor does: blocks exploded, units scaled, aligned text anchored
    from c2b.dxfio import iter_prims, load_document, modelspace_extent, read_meta
    from c2b.units import resolve_units

    doc = load_document(client_path)
    meta = read_meta(doc, client_path)
    scale = resolve_units(meta.insunits, modelspace_extent(doc)).scale_to_mm
    prims, _log = iter_prims(doc, scale)
    msp = doc.modelspace()

    def floor_of(x: float, y: float) -> str | None:
        for fid, frame in frames.items():
            if frame is not None and frame.contains(Point(x, y)):
                return fid
        return None

    # ---- what the client tagged, per floor and per role ----------------------
    client_tags: dict[tuple[str, str], int] = Counter()
    tag_points: dict[tuple[str, str], list] = defaultdict(list)
    for prim in prims:
        if prim.kind != "text" or not (prim.text or "").strip():
            continue
        role = roles.get(prim.layer, ("UNKNOWN", "NOTE"))[1]
        if not role.endswith("_TAG"):
            continue
        x, y = prim.rep_point()
        fid = floor_of(x, y)
        if fid is None:
            continue
        client_tags[(fid, role)] += 1
        tag_points[(fid, role)].append((x - floors[fid]["origin"]["x"], y - floors[fid]["origin"]["y"], prim.text.strip()))

    # ---- what the client drew: grid lines and column-ish outlines ------------
    client_grid_labels: dict[str, set] = defaultdict(set)
    for e in msp.query("LINE LWPOLYLINE"):
        if roles.get(e.dxf.layer, ("",))[0] != "GRID":
            continue
        if e.dxftype() == "LINE":
            (x0, y0), (x1, y1) = (e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)
        else:
            pts = list(e.get_points("xy"))
            if len(pts) < 2:
                continue
            (x0, y0), (x1, y1) = pts[0], pts[-1]
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        fid = floor_of(x, y)
        if fid:
            # one entry per distinct grid line position, so segments of one line count once
            client_grid_labels[fid].add(round(x, 1) if abs(x0 - x1) < 1 else (round(y, 1) if abs(y0 - y1) < 1 else None))
            client_grid_labels[fid].discard(None)

    print(f"client : {Path(client_path).name}")
    print(f"extract: {Path(extract_path).name}\n")
    header = f"{'floor':5s} {'name':34s} {'grids':>12s} {'columns':>18s} {'beams':>18s} {'slabs':>18s}"
    print(header)
    print("-" * len(header))
    out_by_floor = defaultdict(lambda: defaultdict(list))
    for key in ("grids", "columns", "beams", "slabs"):
        for el in project[key]:
            out_by_floor[el["floor_id"]][key].append(el)
    n_by_floor = defaultdict(lambda: defaultdict(list))
    if normalized:
        for key in ("grids", "columns", "beams", "panels"):
            for el in normalized[key]:
                n_by_floor[el["floor_id"]][key].append(el)

    totals = Counter()
    for fid, floor in floors.items():
        cols = out_by_floor[fid]["columns"]
        beams = out_by_floor[fid]["beams"]
        slabs = out_by_floor[fid]["slabs"]
        grids = out_by_floor[fid]["grids"]
        c_tags = client_tags[(fid, "COLUMN_TAG")]
        b_tags = client_tags[(fid, "BEAM_TAG")]
        s_tags = client_tags[(fid, "SLAB_TAG")]
        c_marked = sum(1 for c in cols if c["mark"])
        b_marked = sum(1 for b in beams if b["mark"])
        s_thk = sum(1 for s in slabs if s["thickness_mm"])
        panels = n_by_floor[fid]["panels"] if normalized else []
        p_thk = sum(1 for p in panels if p.get("thickness_mm") and p.get("kind") in ("slab", "cantilever", "ramp"))
        p_all = sum(1 for p in panels if p.get("kind") in ("slab", "cantilever", "ramp"))
        print(f"{fid:5s} {floor['name'][:34]:34s} "
              f"{len(grids):5d}/{len(client_grid_labels[fid]):<6d} "
              f"{len(cols):5d} {c_marked:4d}/{c_tags:<6d} "
              f"{len(beams):5d} {b_marked:4d}/{b_tags:<6d} "
              f"{p_all if normalized else len(slabs):5d} {p_thk if normalized else s_thk:4d}/{s_tags:<6d}")
        totals["grids_out"] += len(grids)
        totals["grids_client"] += len(client_grid_labels[fid])
        totals["cols_out"] += len(cols)
        totals["cols_marked"] += c_marked
        totals["cols_tags"] += c_tags
        totals["beams_out"] += len(beams)
        totals["beams_marked"] += b_marked
        totals["beams_tags"] += b_tags
        totals["panels"] += p_all
        totals["panels_thk"] += p_thk
        totals["slab_tags"] += s_tags
    print("-" * len(header))
    print(f"{'ALL':5s} {'':34s} {totals['grids_out']:5d}/{totals['grids_client']:<6d} "
          f"{totals['cols_out']:5d} {totals['cols_marked']:4d}/{totals['cols_tags']:<6d} "
          f"{totals['beams_out']:5d} {totals['beams_marked']:4d}/{totals['beams_tags']:<6d} "
          f"{totals['panels']:5d} {totals['panels_thk']:4d}/{totals['slab_tags']:<6d}")
    print("\nkey: drawn/client for grids; extracted marked/client-tags for columns and beams; panels with-thickness/client-tags for slabs")

    print("\nunassigned client tags by role and floor:")
    for (fid, role), n in sorted(Counter((t["floor_id"], t["role"]) for t in project["tags_unassigned"]).items()):
        print(f"  {fid} {role:12s} {n}")

    print("\ncolumns without a size source from a tag or schedule:")
    print("  ", Counter(c["size_source"] for c in project["columns"]).most_common())
    print("beam depth sources:")
    print("  ", Counter(b["depth_source"] for b in project["beams"]).most_common())
    if normalized:
        print("panel thickness sources:")
        print("  ", Counter(p.get("thickness_source") for p in normalized["panels"] if p.get("kind") in ("slab", "cantilever", "ramp")).most_common())
        print("panel kinds:", Counter(p.get("kind") for p in normalized["panels"]).most_common())


if __name__ == "__main__":
    main(*sys.argv[1:4])
