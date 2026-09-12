"""Column stacks: the same column across floors, numbered once."""
from __future__ import annotations

import math

from shapely.geometry import Point, Polygon

from ..geometry import iou
from ..schema import Column, Project
from .model import NStack


def _order_key(mode: str, c: Column):
    if mode == "y-then-x":
        return (-round(c.center.y / 100.0), round(c.center.x / 100.0))
    if mode == "grid" and c.grid_ref:
        gx, gy = c.grid_ref.split("/", 1)
        return (_grid_sort(gx), _grid_sort(gy))
    return (round(c.center.x / 100.0), round(c.center.y / 100.0))


def _grid_sort(label: str):
    return (0, int(label)) if label.isdigit() else (1, label)


def build_stacks(project: Project, floors_in_order: list[str], mode: str, tol_mm: float, min_iou: float, diag) -> tuple[list[NStack], dict[str, str]]:
    """Group columns into stacks bottom-up. Returns stacks and a map extraction column id -> stack id."""
    cols_by_floor: dict[str, list[Column]] = {fid: [] for fid in floors_in_order}
    for c in project.columns:
        if c.floor_id in cols_by_floor:
            cols_by_floor[c.floor_id].append(c)

    stacks: list[dict] = []          # {"cols": {floor: Column}, "poly": Polygon, "centre": (x, y)}
    col_to_stack: dict[str, int] = {}
    prev_floor: str | None = None
    for fid in floors_in_order:
        prev_stacks = [s for s in stacks if prev_floor in s["cols"]] if prev_floor else []
        used: set[int] = set()
        for c in sorted(cols_by_floor[fid], key=lambda c: (c.center.x, c.center.y)):
            poly = Polygon([(p.x, p.y) for p in c.outline]) if len(c.outline) >= 3 else Point(c.center.x, c.center.y).buffer(150)
            if not poly.is_valid:
                poly = poly.buffer(0)
            best, best_score = None, 0.0
            for i, s in enumerate(stacks):
                if i in used or prev_floor not in s["cols"]:
                    continue
                d = math.dist((c.center.x, c.center.y), s["centre"])
                if d > tol_mm and not poly.intersects(s["poly"]):
                    continue
                score = iou(poly, s["poly"]) + (1.0 - min(d, tol_mm) / tol_mm) * 0.5
                if score > best_score:
                    best, best_score = i, score
            if best is not None and (best_score >= min_iou or math.dist((c.center.x, c.center.y), stacks[best]["centre"]) <= tol_mm):
                s = stacks[best]
                s["cols"][fid] = c
                s["poly"], s["centre"] = poly, (c.center.x, c.center.y)
                used.add(best)
                col_to_stack[c.id] = best
                d = math.dist((c.center.x, c.center.y), s["centre0"]) if "centre0" in s else 0.0
                if d > tol_mm / 2:
                    diag.info("STACK_JUMP", f"Column {c.id} sits {d:.0f} mm off the stack centre below", floor_id=fid, element_id=c.id, location=(c.center.x, c.center.y))
            else:
                if prev_floor is not None and cols_by_floor.get(prev_floor):
                    diag.info("STACK_ORPHAN", f"Column {c.id} has no column under it on {prev_floor}", floor_id=fid, element_id=c.id, location=(c.center.x, c.center.y))
                stacks.append({"cols": {fid: c}, "poly": poly, "centre": (c.center.x, c.center.y), "centre0": (c.center.x, c.center.y)})
                col_to_stack[c.id] = len(stacks) - 1
        prev_floor = fid

    # number stacks by the position of their lowest column
    order = sorted(range(len(stacks)), key=lambda i: _order_key(mode, stacks[i]["cols"][next(iter(stacks[i]["cols"]))]))
    result: list[NStack] = []
    remap: dict[int, str] = {}
    for n, i in enumerate(order, start=1):
        s = stacks[i]
        first = s["cols"][next(iter(s["cols"]))]
        sid = f"STK{n:03d}"
        remap[i] = sid
        present = [f for f in floors_in_order if f in s["cols"]]
        result.append(NStack(id=sid, number=n, mark_base=f"C{n}", grid_ref=first.grid_ref, centre=first.center, floors=present,
                             client_marks=sorted({c.mark for c in s["cols"].values() if c.mark})))
        sizes = {(c.width_mm, c.depth_mm, c.diameter_mm) for c in s["cols"].values()}
        if len(sizes) > 1:
            diag.info("STACK_SIZE_CHANGE", f"Stack {sid} (C{n}) changes size between floors: {sorted(str(x) for x in sizes)}", element_id=sid, location=(first.center.x, first.center.y))
    return result, {cid: remap[i] for cid, i in col_to_stack.items()}
