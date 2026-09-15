"""Read a template DXF back into a :class:`NormalizedProject`.

Geometry and mark text come from the drawing itself, so a drafter's edits are picked up.
The ``C2B`` XDATA supplies identity and the few values a drawing cannot carry.
"""
from __future__ import annotations

import math
from pathlib import Path

import ezdxf
from shapely.geometry import LineString, Point, Polygon

from ..diagnostics import DiagnosticsCollector
from ..geometry import classify_polygon
from ..normalize.geometry import poly_from_points, ring_points
from ..normalize.model import (NBeam, NColumn, NFloor, NFold, NFooting, NGrid, NJoint, NLevel, NOpening, NPanel, NPile,
                               NStair, NWall, NormalizedProject)
from ..normalize.spec import TemplateSpec
from ..schema import Point2
from .marks import TemplateMark, parse_template_mark

_FOOTING_PREFIX = {"F": "footing", "CF": "combined", "RF": "raft", "PC": "pilecap", "LP": "pit"}


def _pt(x: float, y: float) -> Point2:
    return Point2(x=round(x, 2), y=round(y, 2))


def _text_height(e) -> float:
    """Character height of a TEXT or MTEXT entity."""
    for attr in ("char_height", "height"):
        if e.dxf.hasattr(attr):
            try:
                return float(e.dxf.get(attr))
            except Exception:
                pass
    return 0.0


class TemplateReader:
    def __init__(self, spec: TemplateSpec, diag: DiagnosticsCollector | None = None):
        self.spec = spec
        self.diag = diag or DiagnosticsCollector()
        self.by_name = {ld.name.upper(): key for key, ld in spec.layers.items()}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _new_id(floor_id: str, prefix: str, e) -> str:
        """Id for an entity the drawing has but the model does not: never collides with a model id."""
        return f"{floor_id}-{prefix}NEW-{e.dxf.handle}"

    def _xdata(self, e) -> dict[str, str]:
        try:
            if not e.has_xdata(self.spec.xdata_appid):
                return {}
            out = {}
            for code, value in e.get_xdata(self.spec.xdata_appid):
                if code == 1000 and "=" in str(value):
                    k, v = str(value).split("=", 1)
                    out[k] = v
            return out
        except Exception:
            return {}

    def _layer_key(self, e) -> str | None:
        return self.by_name.get(e.dxf.layer.upper())

    def _polys(self, msp, key: str):
        name = self.spec.layer(key)
        out = []
        for e in msp.query(f'LWPOLYLINE[layer=="{name}"]'):
            pts = list(e.get_points("xy"))
            if len(pts) < 3:
                continue
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.area <= 0:
                continue
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda g: g.area)
            bulges = [p[4] for p in e.get_points()]
            out.append((e, poly, bulges))
        return out

    def _circles(self, msp, key: str):
        name = self.spec.layer(key)
        return [(e, Point(e.dxf.center.x, e.dxf.center.y).buffer(e.dxf.radius, quad_segs=32)) for e in msp.query(f'CIRCLE[layer=="{name}"]')]

    def _texts(self, msp, key: str):
        name = self.spec.layer(key)
        out = []
        for e in msp.query(f'MTEXT[layer=="{name}"]'):
            out.append((e, e.plain_text(), (e.dxf.insert.x, e.dxf.insert.y), float(e.dxf.get("rotation", 0.0))))
        for e in msp.query(f'TEXT[layer=="{name}"]'):
            out.append((e, e.dxf.text or "", (e.dxf.insert.x, e.dxf.insert.y), float(e.dxf.get("rotation", 0.0))))
        return out

    def _lines(self, msp, key: str):
        name = self.spec.layer(key)
        out = [(e, (e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)) for e in msp.query(f'LINE[layer=="{name}"]')]
        for e in msp.query(f'LWPOLYLINE[layer=="{name}"]'):
            pts = list(e.get_points("xy"))
            for a, b in zip(pts[:-1], pts[1:]):
                out.append((e, (a[0], a[1]), (b[0], b[1])))
        return out

    # --------------------------------------------------------------------- read
    def read(self, path: str | Path, source_file: str = "") -> NormalizedProject:
        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()
        spec = self.spec
        np_ = NormalizedProject(source_file=source_file or Path(path).name, source_schema_version="reread", spec_name=spec.name)

        frames = [(e, Polygon(list(e.get_points("xy")))) for e in msp.query(f'LWPOLYLINE[layer=="{spec.layer("boundary")}"]') if len(list(e.get_points())) >= 3]
        origins = [(e, (e.dxf.location.x, e.dxf.location.y)) for e in msp.query(f'POINT[layer=="{spec.layer("origin")}"]')]
        titles = self._texts(msp, "text")
        level_lines = self._lines(msp, "level")

        plans: list[tuple[Polygon, tuple[float, float], NFloor]] = []
        elevation_frame: Polygon | None = None
        index = 0
        for e, frame in sorted(frames, key=lambda fr: fr[1].bounds[0]):
            has_levels = any(frame.contains(Point(a)) for _, a, _ in level_lines)
            xd_frame = self._xdata(e)
            origin = None
            if xd_frame.get("origin"):
                try:
                    ox, oy = (float(v) for v in xd_frame["origin"].split(","))
                    origin = (ox, oy)
                except ValueError:
                    origin = None
            if origin is None:
                origin = next((o for _, o in origins if frame.contains(Point(o))), None)
            if has_levels and origin is None and not xd_frame.get("floor"):
                elevation_frame = frame
                continue
            index += 1
            if origin is None:
                origin = (frame.bounds[0], frame.bounds[1])
                self.diag.warning("RT_FLOOR_NO_ORIGIN", f"Frame at x={frame.bounds[0]:.0f} has no Origin point; its lower-left corner was used")
            title_texts = [(t, txt, pos) for t, txt, pos, _r in titles if frame.contains(Point(pos)) and self._xdata(t).get("kind", "title") == "title"
                           and _text_height(t) >= spec.text.title_height * 0.9]
            title = title_texts[0][1].strip() if title_texts else f"Floor {index}"
            name = xd_frame.get("name") or (title.split("-", 1)[1].strip().replace("LEVEL", "LVL.") if "-" in title else title)
            fid = xd_frame.get("floor") or f"L{index:02d}"
            plan_bottom = frame.bounds[1] + spec.frame.bottom_band_mm
            notes = [txt.strip() for t, txt, pos, _r in titles if frame.contains(Point(pos)) and self._xdata(t).get("kind") == "note"]
            floor = NFloor(id=fid, index=index, name=name, title=title, source_name=name, origin=_pt(*origin),
                           frame=[_pt(x, y) for x, y in list(frame.exterior.coords)[:-1]], plan_bottom_y=plan_bottom,
                           notes=[__import__("re").sub(r"^\s*\d+\)\s*", "", n) for n in notes])
            plans.append((frame, origin, floor))
            np_.floors.append(floor)

        def owner(pt: tuple[float, float]):
            for frame, origin, floor in plans:
                if frame.contains(Point(pt)):
                    return floor, origin
            return None, None

        def local(origin, x: float, y: float) -> Point2:
            return _pt(x - origin[0], y - origin[1])

        def ring_local(poly: Polygon, origin) -> list[Point2]:
            return [local(origin, x, y) for x, y in ring_points(poly)]

        def nearest_mark(marks, poly: Polygon, centre):
            inside = [m for m in marks if poly.contains(Point(m[2]))]
            if inside:
                return min(inside, key=lambda m: math.dist(m[2], centre))
            near = [m for m in marks if poly.distance(Point(m[2])) <= max(1500.0, 2 * math.sqrt(poly.area))]
            return min(near, key=lambda m: poly.distance(Point(m[2]))) if near else None

        # ---- columns ---------------------------------------------------------
        col_marks = self._texts(msp, "column_mark")
        used_marks: set[int] = set()
        for e, poly, _bulges in self._polys(msp, "column") + [(c[0], c[1], []) for c in self._circles(msp, "column")]:
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            if floor is None:
                continue
            xd = self._xdata(e)
            shape = classify_polygon(poly)
            is_circle = e.dxftype() == "CIRCLE" or shape.shape == "circle"
            mk = nearest_mark(col_marks, poly, centre)
            tm: TemplateMark = parse_template_mark(mk[1]) if mk else TemplateMark(text="")
            if mk:
                used_marks.add(id(mk[0]))
            n = len([c for c in np_.columns if c.floor_id == floor.id]) + 1
            np_.columns.append(NColumn(
                id=xd.get("id") or self._new_id(floor.id, "C", e), floor_id=floor.id, stack_id=xd.get("stack", tm.base or ""), mark=tm.text,
                shape="circle" if is_circle else shape.shape, center=local(origin, *centre),
                width_mm=tm.width_mm or (None if is_circle else round(shape.width, 1)),
                depth_mm=tm.depth_mm or (None if is_circle else round(shape.depth, 1)),
                rotation_deg=0.0 if is_circle else round(shape.rotation_deg, 3),
                diameter_mm=tm.diameter_mm or (round(e.dxf.radius * 2, 1) if e.dxftype() == "CIRCLE" else None),
                outline=ring_local(poly, origin), mark_position=local(origin, *mk[2]) if mk else local(origin, *centre),
                mark_rotation_deg=round(mk[3], 3) if mk else 0.0, client_mark=xd.get("client"), source_ids=[xd.get("src")] if xd.get("src") else []))

        # ---- beams -----------------------------------------------------------
        beam_marks = self._texts(msp, "beam_mark")
        for e, poly, _bulges in self._polys(msp, "beam"):
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            if floor is None:
                continue
            xd = self._xdata(e)
            shape = classify_polygon(poly)
            long_side, short_side = max(shape.width, shape.depth), min(shape.width, shape.depth)
            mk0 = nearest_mark(beam_marks, poly, (poly.centroid.x, poly.centroid.y))
            stated = parse_template_mark(mk0[1]).width_mm if mk0 else None
            # a bracket is wider than it is long: the mark's width says which side is which
            stub = bool(stated and abs(long_side - stated) <= 26 and abs(short_side - stated) > 26) or self._xdata(e).get("stub") == "1"
            if stub:
                long_side, short_side = short_side, long_side
            along_width = (shape.width >= shape.depth) != stub
            ang = (shape.rotation_deg if along_width else shape.rotation_deg + 90.0) % 180.0
            ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            half = long_side / 2
            p1 = (centre[0] - ux * half, centre[1] - uy * half)
            p2 = (centre[0] + ux * half, centre[1] + uy * half)
            mk = mk0
            tm = parse_template_mark(mk[1]) if mk else TemplateMark(text="")
            if mk:
                used_marks.add(id(mk[0]))
            n = len([b for b in np_.beams if b.floor_id == floor.id]) + 1
            np_.beams.append(NBeam(
                id=xd.get("id") or self._new_id(floor.id, "B", e), floor_id=floor.id, run_id=xd.get("run", ""), span_index=n, mark=tm.text,
                start=local(origin, *p1), end=local(origin, *p2), length_mm=round(long_side, 1),
                width_mm=round(short_side, 1), depth_mm=tm.depth_mm, depth_tip_mm=tm.depth_tip_mm, inverted=tm.inverted,
                angle_deg=round(ang, 3), outline=ring_local(poly, origin),
                mark_position=local(origin, *mk[2]) if mk else local(origin, *centre), mark_rotation_deg=round(mk[3], 3) if mk else 0.0,
                client_mark=xd.get("client")))

        # ---- panels (slab, cantilever, ramp) ---------------------------------
        for key, mark_key in (("slab", "slab_mark"), ("ramp", "ramp_mark")):
            marks = self._texts(msp, mark_key)
            for e, poly, bulges in self._polys(msp, key):
                centre = (poly.centroid.x, poly.centroid.y)
                floor, origin = owner(centre)
                if floor is None:
                    continue
                xd = self._xdata(e)
                mk = nearest_mark(marks, poly, centre)
                tm = parse_template_mark(mk[1]) if mk else TemplateMark(text="")
                if mk:
                    used_marks.add(id(mk[0]))
                kind = xd.get("kind") or ("ramp" if key == "ramp" else ("cantilever" if (tm.base or "").upper().startswith("CS") else "slab"))
                n = len([p for p in np_.panels if p.floor_id == floor.id]) + 1
                np_.panels.append(NPanel(
                    id=xd.get("id") or self._new_id(floor.id, "S", e), floor_id=floor.id, kind=kind, mark=tm.text, thickness_mm=tm.thickness_mm,
                    thickness_source="mark", outline=ring_local(poly, origin), bulges=[round(b, 6) for b in bulges],
                    area_m2=round(poly.area / 1e6, 3), centroid=local(origin, *centre),
                    mark_position=local(origin, *mk[2]) if mk else local(origin, *centre),
                    top_offset_mm=float(xd.get("top_offset", 0.0) or 0.0), slope_ratio=tm.slope_ratio, direction=tm.direction,
                    cantilever=kind == "cantilever", tag_ids=[xd.get("src")] if xd.get("src") else []))

        # ---- folds -----------------------------------------------------------
        for e, poly, _b in self._polys(msp, "slab_fold"):
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            if floor is None:
                continue
            xd = self._xdata(e)
            mk = nearest_mark(self._texts(msp, "slab_mark"), poly, centre)
            tm = parse_template_mark(mk[1]) if mk else TemplateMark(text="")
            n = len([x for x in np_.folds if x.floor_id == floor.id]) + 1
            np_.folds.append(NFold(id=xd.get("id") or self._new_id(floor.id, "FD", e), floor_id=floor.id, panel_id=xd.get("panel"),
                                   outline=ring_local(poly, origin), fold_mm=tm.fold_mm or (float(xd["fold"]) if xd.get("fold") else None),
                                   vertical_thickness_mm=tm.thickness_mm, mark=tm.text, mark_position=local(origin, *mk[2]) if mk else local(origin, *centre)))

        # ---- footings, rafts, pile caps, PCC, piles --------------------------
        for key in ("footing", "raft", "pilecap"):
            marks = self._texts(msp, {"footing": "footing_mark", "raft": "raft_mark", "pilecap": "pilecap_mark"}[key])
            for e, poly, _b in self._polys(msp, key):
                centre = (poly.centroid.x, poly.centroid.y)
                floor, origin = owner(centre)
                if floor is None:
                    continue
                xd = self._xdata(e)
                shape = classify_polygon(poly)
                mk = nearest_mark(marks, poly, centre)
                tm = parse_template_mark(mk[1]) if mk else TemplateMark(text="")
                if mk:
                    used_marks.add(id(mk[0]))
                prefix = (tm.base or "F")[:2].upper()
                kind = xd.get("kind") or _FOOTING_PREFIX.get(prefix) or _FOOTING_PREFIX.get(prefix[0], "footing")
                n = len([x for x in np_.footings if x.floor_id == floor.id]) + 1
                np_.footings.append(NFooting(
                    id=xd.get("id") or self._new_id(floor.id, "F", e), floor_id=floor.id, kind=kind, mark=tm.lines[0] if tm.lines else "",
                    mark_lines=tm.lines, shape=shape.shape, center=local(origin, *centre), width_mm=round(shape.width, 1),
                    depth_mm=round(shape.depth, 1), rotation_deg=round(shape.rotation_deg, 3), thickness_mm=tm.thickness_mm,
                    fold_mm=tm.fold_mm, outline=ring_local(poly, origin), pit_depth_mm=tm.pit_depth_mm,
                    pcc_thickness_mm=tm.pcc_thickness_mm, client_mark=xd.get("client")))
        for key, kind in (("footing_fold", "fold"), ("footing_sunk", "sunk"), ("raft_fold", "fold"), ("raft_sunk", "sunk")):
            for e, poly, _b in self._polys(msp, key):
                centre = (poly.centroid.x, poly.centroid.y)
                floor, origin = owner(centre)
                if floor is None:
                    continue
                xd = self._xdata(e)
                shape = classify_polygon(poly)
                # a fold or sunk area carries its own text inside it ("1500 FOLD"); it never borrows a neighbour's mark
                inside = [m for m in self._texts(msp, "raft_mark") + self._texts(msp, "footing_mark") if poly.contains(Point(m[2]))]
                tm = parse_template_mark(inside[0][1]) if inside else TemplateMark(text="")
                n = len([x for x in np_.footings if x.floor_id == floor.id]) + 1
                np_.footings.append(NFooting(
                    id=xd.get("id") or self._new_id(floor.id, "FX", e), floor_id=floor.id, kind=kind, mark="",
                    mark_lines=tm.lines, shape=shape.shape, center=local(origin, *centre), width_mm=round(shape.width, 1),
                    depth_mm=round(shape.depth, 1), rotation_deg=round(shape.rotation_deg, 3), thickness_mm=tm.thickness_mm,
                    fold_mm=tm.fold_mm, outline=ring_local(poly, origin), stack_ids=["raft"] if key.startswith("raft") else [],
                    client_mark=xd.get("client")))
        for e, poly, _b in self._polys(msp, "pcc"):
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            xd = self._xdata(e)
            target = next((x for x in np_.footings if x.id == xd.get("id")), None)
            if target is not None:
                target.pcc_outline = ring_local(poly, origin)
                if xd.get("thk"):
                    target.pcc_thickness_mm = float(xd["thk"])
                if xd.get("proj"):
                    target.pcc_projection_mm = float(xd["proj"])
        for e, poly in self._circles(msp, "pile"):
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            if floor is None:
                continue
            xd = self._xdata(e)
            n = len([p for p in np_.piles if p.floor_id == floor.id]) + 1
            np_.piles.append(NPile(id=xd.get("id") or self._new_id(floor.id, "P", e), floor_id=floor.id, center=local(origin, *centre),
                                   diameter_mm=round(e.dxf.radius * 2, 1), pilecap_id=xd.get("cap")))

        # ---- walls, openings, stairs, joints ---------------------------------
        wall_marks = self._texts(msp, "wall_mark")
        for e, poly, _b in self._polys(msp, "wall"):
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            if floor is None:
                continue
            xd = self._xdata(e)
            shape = classify_polygon(poly)
            mk = nearest_mark(wall_marks, poly, centre)
            n = len([w for w in np_.walls if w.floor_id == floor.id]) + 1
            np_.walls.append(NWall(id=xd.get("id") or self._new_id(floor.id, "W", e), floor_id=floor.id, mark=mk[1].strip() if mk else None,
                                   outline=ring_local(poly, origin), center=local(origin, *centre),
                                   thickness_mm=round(min(shape.width, shape.depth), 1), length_mm=round(max(shape.width, shape.depth), 1),
                                   top_offset_mm=float(xd.get("top_offset", 0.0) or 0.0)))
        for e, poly, _b in self._polys(msp, "cutout"):
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            if floor is None:
                continue
            xd = self._xdata(e)
            n = len([o for o in np_.openings if o.floor_id == floor.id]) + 1
            np_.openings.append(NOpening(id=xd.get("id") or self._new_id(floor.id, "O", e), floor_id=floor.id, label=xd.get("label"),
                                         outline=ring_local(poly, origin), center=local(origin, *centre), panel_id=xd.get("panel")))
        stair_marks = self._texts(msp, "stairs_mark")
        for e, poly, _b in self._polys(msp, "stairs"):
            centre = (poly.centroid.x, poly.centroid.y)
            floor, origin = owner(centre)
            if floor is None:
                continue
            xd = self._xdata(e)
            mk = nearest_mark(stair_marks, poly, centre)
            tm = parse_template_mark(mk[1]) if mk else TemplateMark(text="")
            n = len([s for s in np_.stairs if s.floor_id == floor.id]) + 1
            np_.stairs.append(NStair(id=xd.get("id") or self._new_id(floor.id, "ST", e), floor_id=floor.id, mark=tm.text or None,
                                     waist_mm=tm.thickness_mm, outline=ring_local(poly, origin), center=local(origin, *centre)))
        for e, a, b in self._lines(msp, "joint"):
            floor, origin = owner(a)
            if floor is None:
                continue
            xd = self._xdata(e)
            n = len([j for j in np_.joints if j.floor_id == floor.id]) + 1
            np_.joints.append(NJoint(id=xd.get("id") or self._new_id(floor.id, "J", e), floor_id=floor.id, start=local(origin, *a), end=local(origin, *b)))

        # ---- grids -----------------------------------------------------------
        grid_marks = self._texts(msp, "grid_mark")
        for e, a, b in self._lines(msp, "grid"):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            floor, origin = owner(mid)
            if floor is None:
                continue
            xd = self._xdata(e)
            label = xd.get("label")
            bubbles = [m for m in grid_marks if min(math.dist(m[2], a), math.dist(m[2], b)) <= spec.placement.grid_bubble_radius_mm * 4]
            if label is None and bubbles:
                label = bubbles[0][1].strip()
            axis = "X" if abs(a[0] - b[0]) < 1.0 else ("Y" if abs(a[1] - b[1]) < 1.0 else "other")
            offset = (a[0] - origin[0]) if axis == "X" else ((a[1] - origin[1]) if axis == "Y" else 0.0)
            n = len([g for g in np_.grids if g.floor_id == floor.id]) + 1
            np_.grids.append(NGrid(id=xd.get("id") or self._new_id(floor.id, "G", e), floor_id=floor.id, label=label or "", axis=axis,
                                   offset_mm=round(offset, 1), start=local(origin, *a), end=local(origin, *b),
                                   bubble_centres=[local(origin, *m[2]) for m in bubbles]))

        # ---- levels ----------------------------------------------------------
        lv_marks = self._texts(msp, "level_mark")
        rows = []
        for e, a, b in level_lines:
            xd = self._xdata(e)
            mk = min(lv_marks, key=lambda m: abs(m[2][1] - a[1]) + abs(m[2][0] - a[0]), default=None)
            name = mk[1].strip() if mk else ""
            elev = float(xd["elevation"]) if xd.get("elevation") else None
            rows.append((a[1], name, elev, xd.get("id"), xd.get("plan")))
        rows.sort()
        if rows and all(r[2] is None for r in rows):
            base = rows[0][0]
            rows = [(y, name, y - base, lid, plan) for y, name, _e, lid, plan in rows]
            self.diag.warning("RT_LEVELS_RELATIVE", "Level lines carry no elevation data; elevations were measured from the lowest line")
        for i, (_y, name, elev, lid, plan) in enumerate(rows):
            nxt = rows[i + 1][2] - elev if i + 1 < len(rows) and elev is not None and rows[i + 1][2] is not None else None
            np_.levels.append(NLevel(id=lid or f"LV{i:02d}", index=i, name=name, elevation_mm=elev if elev is not None else 0.0,
                                     floor_to_floor_mm=nxt, plan_floor_id=plan))

        # ---- things the drafter added or orphaned -----------------------------
        for key in ("column", "beam", "slab", "footing", "raft", "cutout"):
            name = self.spec.layer(key)
            for e in list(msp.query(f'LWPOLYLINE[layer=="{name}"]')) + list(msp.query(f'CIRCLE[layer=="{name}"]')):
                if not self._xdata(e).get("id"):
                    c = Polygon(list(e.get_points("xy"))).centroid if e.dxftype() == "LWPOLYLINE" and len(list(e.get_points())) >= 3 else Point(e.dxf.center.x, e.dxf.center.y) if e.dxftype() == "CIRCLE" else None
                    floor, _o = owner((c.x, c.y)) if c is not None else (None, None)
                    self.diag.warning("RT_NO_ID", f"{key} entity {e.dxf.handle} on {name} has no C2B id; it was added or copied by hand",
                                      floor_id=floor.id if floor else None, handle=e.dxf.handle, layer=name,
                                      location=(c.x, c.y) if c is not None else None)
        for key in ("column_mark", "beam_mark", "slab_mark", "footing_mark"):
            for t, txt, pos, _r in self._texts(msp, key):
                if id(t) not in used_marks and txt.strip():
                    floor, _o = owner(pos)
                    self.diag.info("RT_ORPHAN_MARK", f"Mark '{txt.strip()[:30]}' on {self.spec.layer(key)} belongs to no element",
                                   floor_id=floor.id if floor else None, handle=t.dxf.handle, location=pos)

        np_.diagnostics = self.diag.items
        np_.recompute_summary()
        return np_


def read_template(path: str | Path, spec: TemplateSpec, diag: DiagnosticsCollector | None = None) -> NormalizedProject:
    return TemplateReader(spec, diag).read(path)
