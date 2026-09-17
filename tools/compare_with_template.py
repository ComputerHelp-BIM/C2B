"""Compare a generated template DXF with the firm's reference template DXF, frame by frame.

Usage: python tools/compare_with_template.py <generated.dxf> <reference.dxf> [--frame-match-tol 2000]

Frames are matched by their Boundary rectangles (nearest left-bottom corner). For each
matched frame the script reports entity counts per layer and, for columns, beams and
slabs, how many reference outlines have a generated outline with IoU >= 0.6.
"""
from __future__ import annotations

import sys
from collections import Counter

import ezdxf
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree


def polys(msp, layer):
    out = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
        pts = list(e.get_points("xy"))
        if e.closed and len(pts) >= 3:
            p = Polygon(pts)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                out.append(p)
    for e in msp.query(f'CIRCLE[layer=="{layer}"]'):
        out.append(Point(e.dxf.center.x, e.dxf.center.y).buffer(e.dxf.radius))
    return out


def frames(msp, layer="0-Boundary"):
    return [Polygon(list(e.get_points("xy"))) for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]') if e.closed]


def match_rate(ref, gen, min_iou=0.6):
    if not ref:
        return 0, 0, []
    tree = STRtree(gen) if gen else None
    hits = 0
    missed = []
    for r in ref:
        best = 0.0
        if tree is not None:
            for i in tree.query(r, predicate="intersects"):
                g = gen[int(i)]
                inter = r.intersection(g).area
                if inter > 0:
                    best = max(best, inter / (r.area + g.area - inter))
        if best >= min_iou:
            hits += 1
        else:
            missed.append((round(r.centroid.x), round(r.centroid.y), round(r.bounds[2] - r.bounds[0]), round(r.bounds[3] - r.bounds[1]), round(best, 2)))
    return hits, len(ref), missed


def main(gen_path, ref_path, tol=3000.0):
    gen = ezdxf.readfile(gen_path).modelspace()
    ref = ezdxf.readfile(ref_path).modelspace()
    gframes, rframes = frames(gen), frames(ref)
    print(f"frames: generated {len(gframes)}, reference {len(rframes)}")
    for rf in sorted(rframes, key=lambda f: f.bounds[0]):
        gf = min(gframes, key=lambda g: abs(g.bounds[0] - rf.bounds[0]) + abs(g.bounds[1] - rf.bounds[1]), default=None)
        if gf is None or abs(gf.bounds[0] - rf.bounds[0]) > tol:
            print(f"\n== reference frame at x={rf.bounds[0]:.0f}: no generated frame nearby")
            continue
        print(f"\n== frame x={rf.bounds[0]:.0f}..{rf.bounds[2]:.0f} (generated x={gf.bounds[0]:.0f}..{gf.bounds[2]:.0f}, y={gf.bounds[1]:.0f}..{gf.bounds[3]:.0f} vs ref y={rf.bounds[1]:.0f}..{rf.bounds[3]:.0f})")
        rc = Counter((e.dxf.layer, e.dxftype()) for e in ref if rf.contains(_rep(e)))
        gc = Counter((e.dxf.layer, e.dxftype()) for e in gen if gf.contains(_rep(e)))
        layers = sorted(set(k[0] for k in rc) | set(k[0] for k in gc))
        print(f"   {'layer':28s} {'reference':>28s} {'generated':>28s}")
        for lay in layers:
            r = {k[1]: v for k, v in rc.items() if k[0] == lay}
            g = {k[1]: v for k, v in gc.items() if k[0] == lay}
            print(f"   {lay:28s} {r!s:>28s} {g!s:>28s}")
        for lay in ("CH-S-COLUMN", "CH-S-BEAM", "CH-S-SLAB", "CH-S-FND", "CH-S-RAFT"):
            rp = [p for p in polys(ref, lay) if rf.contains(p.centroid)]
            gp = [p for p in polys(gen, lay) if gf.contains(p.centroid)]
            if not rp and not gp:
                continue
            hits, n, missed = match_rate(rp, gp)
            extra = len(gp) - hits
            print(f"   {lay}: {hits}/{n} reference outlines matched (IoU>=0.6); generated has {len(gp)} ({extra} unmatched)")
            for m in missed[:8]:
                print(f"      missed ref @({m[0]},{m[1]}) size {m[2]}x{m[3]} best IoU {m[4]}")


def _rep(e):
    t = e.dxftype()
    try:
        if t in ("LWPOLYLINE",):
            pts = list(e.get_points("xy"))
            return Point(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        if t in ("MTEXT", "TEXT"):
            return Point(e.dxf.insert.x, e.dxf.insert.y)
        if t == "LINE":
            return Point((e.dxf.start.x + e.dxf.end.x) / 2, (e.dxf.start.y + e.dxf.end.y) / 2)
        if t == "CIRCLE":
            return Point(e.dxf.center.x, e.dxf.center.y)
        if t == "POINT":
            return Point(e.dxf.location.x, e.dxf.location.y)
        if t == "HATCH":
            from ezdxf import path as ezpath
            pts = [(v.x, v.y) for p in ezpath.from_hatch(e) for v in p.flattening(10)]
            return Point(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        if t == "DIMENSION":
            return Point(e.dxf.defpoint.x, e.dxf.defpoint.y)
    except Exception:
        pass
    return Point(1e12, 1e12)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 3000.0)
