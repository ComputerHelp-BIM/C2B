"""DXF reading.

Turns every model-space entity (including block content, recursively) into a
small :class:`Prim` record with a Shapely geometry in millimetres. Everything
downstream works on these records and never touches ezdxf again, which keeps
the extractors testable with synthetic data.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import ezdxf
import shapely
from ezdxf import path as ezpath
from ezdxf.math import Vec3
from shapely.geometry import LineString, Point, Polygon, base

from .geometry import polygon_from_points, rectangle_polygon

FLATTEN_DISTANCE_MM = 1.0
TEXT_WIDTH_FACTOR = 0.7


@dataclass
class Prim:
    """One drawing primitive in millimetres."""

    kind: str                      # line | polyline | polygon | circle | arc | curve | hatch | text | point | insert | dimension | solid | other
    layer: str
    handle: str
    geom: base.BaseGeometry
    closed: bool = False
    text: str | None = None
    text_height: float = 0.0
    rotation: float = 0.0
    text_center: tuple[float, float] | None = None
    attribs: dict[str, str] = field(default_factory=dict)
    block_path: tuple[str, ...] = ()
    zmax: float = 0.0
    ring_gap: float = 0.0          # for open polylines: distance between end points
    extra: dict = field(default_factory=dict)

    @property
    def dxftype(self) -> str:
        return self.extra.get("dxftype", self.kind.upper())

    def rep_point(self) -> tuple[float, float]:
        if self.text_center:
            return self.text_center
        if self.geom.geom_type == "Point":
            return (self.geom.x, self.geom.y)
        if self.geom.geom_type == "LineString":
            p = self.geom.interpolate(0.5, normalized=True)
            return (p.x, p.y)
        p = self.geom.representative_point()
        return (p.x, p.y)


@dataclass
class DxfMeta:
    file: str
    dxf_version: str
    insunits: int | None
    layouts: list[str]
    extmin: tuple[float, float] | None
    extmax: tuple[float, float] | None
    layer_colors: dict[str, int]
    entity_count: int


def load_document(path: str | Path):
    doc = ezdxf.readfile(str(path))
    return doc


def read_meta(doc, path: str | Path) -> DxfMeta:
    header = doc.header
    extmin = header.get("$EXTMIN")
    extmax = header.get("$EXTMAX")
    layer_colors = {}
    for layer in doc.layers:
        try:
            layer_colors[layer.dxf.name] = int(layer.color)
        except Exception:
            layer_colors[layer.dxf.name] = 7
    msp = doc.modelspace()
    return DxfMeta(
        file=Path(path).name,
        dxf_version=doc.dxfversion,
        insunits=header.get("$INSUNITS"),
        layouts=[l.name for l in doc.layouts],
        extmin=(float(extmin[0]), float(extmin[1])) if extmin is not None else None,
        extmax=(float(extmax[0]), float(extmax[1])) if extmax is not None else None,
        layer_colors=layer_colors,
        entity_count=len(msp),
    )


def raw_layer_stats(doc) -> dict[str, dict[str, int]]:
    """Entity type counts per layer of model space (blocks not exploded)."""
    stats: dict[str, Counter] = {}
    for e in doc.modelspace():
        stats.setdefault(e.dxf.layer, Counter())[e.dxftype()] += 1
    return {k: dict(v) for k, v in stats.items()}


def modelspace_extent(doc) -> float:
    """Largest drawing extent dimension in drawing units (fast, from header or bbox)."""
    extmin = doc.header.get("$EXTMIN")
    extmax = doc.header.get("$EXTMAX")
    if extmin is not None and extmax is not None and abs(extmax[0]) < 1e99:
        return max(float(extmax[0] - extmin[0]), float(extmax[1] - extmin[1]))
    from ezdxf import bbox
    bb = bbox.extents(doc.modelspace(), fast=True)
    return max(bb.size.x, bb.size.y) if bb.has_data else 0.0


# ---------------------------------------------------------------------------
# Entity conversion
# ---------------------------------------------------------------------------

def _xy(v, scale: float) -> tuple[float, float]:
    return (float(v[0]) * scale, float(v[1]) * scale)


def _flatten(entity, scale: float) -> list[tuple[float, float]]:
    try:
        p = ezpath.make_path(entity)
        return [_xy(v, scale) for v in p.flattening(FLATTEN_DISTANCE_MM / scale if scale else FLATTEN_DISTANCE_MM)]
    except Exception:
        return []


def _text_anchor_offset(attachment: int, w: float, h: float) -> tuple[float, float]:
    """Vector from the anchor point to the text box centre, in text-local axes."""
    col = (attachment - 1) % 3     # 0 left, 1 centre, 2 right
    row = (attachment - 1) // 3    # 0 top, 1 middle, 2 bottom
    dx = (w / 2, 0.0, -w / 2)[col]
    dy = (-h / 2, 0.0, h / 2)[row]
    return dx, dy


def _text_center(anchor: tuple[float, float], text: str, height: float, rotation_deg: float, attachment: int) -> tuple[tuple[float, float], float, float]:
    lines = text.split("\n") if text else [""]
    w = max(len(l) for l in lines) * height * TEXT_WIDTH_FACTOR
    h = height * (1.0 + 1.5 * (len(lines) - 1))
    dx, dy = _text_anchor_offset(attachment, w, h)
    c, s = math.cos(math.radians(rotation_deg)), math.sin(math.radians(rotation_deg))
    return (anchor[0] + dx * c - dy * s, anchor[1] + dx * s + dy * c), w, h


def _text_attachment_for_text_entity(e) -> int:
    halign = int(e.dxf.get("halign", 0))
    valign = int(e.dxf.get("valign", 0))
    col = {0: 0, 3: 1, 5: 1, 1: 1, 4: 1, 2: 2}.get(halign, 0)
    row = {0: 2, 1: 2, 2: 1, 3: 0}.get(valign, 2)
    return row * 3 + col + 1


def _make_text_prim(kind_entity, layer, handle, text, anchor, height, rotation, attachment, block_path, zmax, scale, dxftype) -> Prim:
    center, w, h = _text_center(anchor, text, height, rotation, attachment)
    return Prim(
        kind="text", layer=layer, handle=handle, geom=Point(center), text=text, text_height=height,
        rotation=rotation, text_center=center, block_path=block_path, zmax=zmax,
        extra={"dxftype": dxftype, "anchor": anchor, "box_w": w, "box_h": h},
    )


def _entity_to_prims(e, layer: str, scale: float, block_path: tuple[str, ...]) -> list[Prim]:
    t = e.dxftype()
    handle = e.dxf.handle or ""
    prims: list[Prim] = []
    try:
        if t == "LINE":
            z = max(abs(float(e.dxf.start.z)), abs(float(e.dxf.end.z))) * scale
            p1, p2 = _xy(e.dxf.start, scale), _xy(e.dxf.end, scale)
            if math.dist(p1, p2) > 1e-9:
                prims.append(Prim("line", layer, handle, LineString([p1, p2]), zmax=z, extra={"dxftype": t, "linetype": e.dxf.get("linetype", "")}))
        elif t in ("LWPOLYLINE", "POLYLINE"):
            if t == "POLYLINE" and not e.is_2d_polyline:
                return prims
            pts = _flatten(e, scale)
            z = abs(float(e.dxf.get("elevation", 0.0)) if t == "LWPOLYLINE" else float(e.dxf.elevation.z)) * scale
            if len(pts) < 2:
                return prims
            closed_flag = bool(e.closed if t == "LWPOLYLINE" else e.is_closed)
            gap = math.dist(pts[0], pts[-1])
            if closed_flag or gap <= 1e-6:
                poly = polygon_from_points(pts)
                if poly is not None and len(pts) >= 3:
                    prims.append(Prim("polygon", layer, handle, poly, closed=True, zmax=z, extra={"dxftype": t, "n_vertices": len(pts)}))
                else:
                    prims.append(Prim("polyline", layer, handle, LineString(pts), closed=False, zmax=z, ring_gap=gap, extra={"dxftype": t}))
            else:
                prims.append(Prim("polyline", layer, handle, LineString(pts), closed=False, zmax=z, ring_gap=gap, extra={"dxftype": t, "n_vertices": len(pts)}))
        elif t == "CIRCLE":
            c = _xy(e.dxf.center, scale)
            r = float(e.dxf.radius) * scale
            if r > 0:
                prims.append(Prim("circle", layer, handle, Point(c).buffer(r, quad_segs=16), closed=True,
                                  zmax=abs(float(e.dxf.center.z)) * scale, extra={"dxftype": t, "radius": r, "center": c}))
        elif t in ("ARC", "ELLIPSE", "SPLINE"):
            pts = _flatten(e, scale)
            if len(pts) >= 2:
                prims.append(Prim("arc" if t == "ARC" else "curve", layer, handle, LineString(pts), extra={"dxftype": t}))
        elif t == "HATCH":
            pattern = e.dxf.get("pattern_name", "")
            solid = bool(e.dxf.get("solid_fill", 0))
            try:
                paths = list(ezpath.from_hatch(e))
            except Exception:
                paths = []
            for i, p in enumerate(paths):
                pts = [_xy(v, scale) for v in p.flattening(FLATTEN_DISTANCE_MM / scale if scale else FLATTEN_DISTANCE_MM)]
                poly = polygon_from_points(pts)
                if poly is not None:
                    prims.append(Prim("hatch", layer, handle, poly, closed=True, zmax=abs(float(e.dxf.get("elevation", Vec3()).z if hasattr(e.dxf.get("elevation", Vec3()), 'z') else 0.0)) * scale,
                                      extra={"dxftype": t, "pattern": pattern, "solid": solid, "path_index": i, "n_paths": len(paths)}))
        elif t == "TEXT":
            text = e.dxf.text or ""
            attachment = _text_attachment_for_text_entity(e)
            anchor_src = e.dxf.align_point if (attachment != 7 and e.dxf.hasattr("align_point")) else e.dxf.insert
            anchor = _xy(anchor_src, scale)
            prims.append(_make_text_prim(e, layer, handle, text, anchor, float(e.dxf.height) * scale, float(e.dxf.get("rotation", 0.0)), attachment, block_path, abs(float(e.dxf.insert.z)) * scale, scale, t))
        elif t == "MTEXT":
            text = e.plain_text()
            anchor = _xy(e.dxf.insert, scale)
            prims.append(_make_text_prim(e, layer, handle, text, anchor, float(e.dxf.char_height) * scale, float(e.dxf.get("rotation", 0.0)), int(e.dxf.get("attachment_point", 1)), block_path, abs(float(e.dxf.insert.z)) * scale, scale, t))
        elif t == "ATTRIB":
            text = e.dxf.text or ""
            attachment = _text_attachment_for_text_entity(e)
            anchor_src = e.dxf.align_point if (attachment != 7 and e.dxf.hasattr("align_point")) else e.dxf.insert
            anchor = _xy(anchor_src, scale)
            p = _make_text_prim(e, layer, handle, text, anchor, float(e.dxf.height) * scale, float(e.dxf.get("rotation", 0.0)), attachment, block_path, 0.0, scale, t)
            p.extra["attrib_tag"] = e.dxf.tag
            prims.append(p)
        elif t == "POINT":
            prims.append(Prim("point", layer, handle, Point(_xy(e.dxf.location, scale)), zmax=abs(float(e.dxf.location.z)) * scale, extra={"dxftype": t}))
        elif t == "SOLID" or t == "TRACE":
            pts = [_xy(e.dxf.vtx0, scale), _xy(e.dxf.vtx1, scale), _xy(e.dxf.vtx3, scale), _xy(e.dxf.vtx2, scale)]
            poly = polygon_from_points(pts)
            if poly is not None:
                prims.append(Prim("solid", layer, handle, poly, closed=True, extra={"dxftype": t}))
        elif t == "DIMENSION":
            try:
                loc = _xy(e.dxf.defpoint, scale)
            except Exception:
                loc = (0.0, 0.0)
            prims.append(Prim("dimension", layer, handle, Point(loc), text=e.dxf.get("text", ""), extra={"dxftype": t, "measurement": e.dxf.get("actual_measurement", None)}))
        elif t in ("LEADER", "MLEADER", "MULTILEADER"):
            return prims
        else:
            return prims
    except Exception as ex:  # never let one bad entity kill the run
        prims.append(Prim("other", layer, handle, Point(0, 0), extra={"dxftype": t, "error": str(ex)}))
    for p in prims:
        p.block_path = block_path
    return prims


def iter_prims(doc, scale: float, explode_blocks: bool = True, max_depth: int = 4) -> tuple[list[Prim], list[dict]]:
    """Convert model space to prims. Returns (prims, exploded_block_log)."""
    prims: list[Prim] = []
    block_log: list[dict] = []
    msp = doc.modelspace()

    def visit(entities: Iterable, depth: int, block_path: tuple[str, ...], parent_layer: str | None):
        for e in entities:
            t = e.dxftype()
            layer = e.dxf.layer if hasattr(e.dxf, "layer") else "0"
            if parent_layer is not None and layer == "0":
                layer = parent_layer
            if t == "INSERT":
                attribs = {}
                try:
                    attribs = {a.dxf.tag: a.dxf.text for a in e.attribs}
                except Exception:
                    pass
                ins_pt = _xy(e.dxf.insert, scale)
                prims.append(Prim("insert", layer, e.dxf.handle or "", Point(ins_pt), attribs=attribs, block_path=block_path + (e.dxf.name,),
                                  rotation=float(e.dxf.get("rotation", 0.0)), extra={"dxftype": t, "block": e.dxf.name, "xscale": float(e.dxf.get("xscale", 1.0)), "yscale": float(e.dxf.get("yscale", 1.0))}))
                # attributes are text belonging to the insert's layer
                try:
                    for a in e.attribs:
                        for p in _entity_to_prims(a, layer if a.dxf.layer == "0" else a.dxf.layer, scale, block_path + (e.dxf.name,)):
                            prims.append(p)
                except Exception:
                    pass
                if explode_blocks and depth < max_depth:
                    if e.dxf.name.lower().startswith("*") is False:
                        block_log.append({"block": e.dxf.name, "layer": layer, "handle": e.dxf.handle, "depth": depth})
                    try:
                        visit(e.virtual_entities(), depth + 1, block_path + (e.dxf.name,), layer)
                    except Exception as ex:
                        block_log.append({"block": e.dxf.name, "layer": layer, "handle": e.dxf.handle, "depth": depth, "error": str(ex)})
                continue
            for p in _entity_to_prims(e, layer, scale, block_path):
                prims.append(p)

    visit(msp, 0, (), None)
    return prims, block_log


# ---------------------------------------------------------------------------
# Post processing
# ---------------------------------------------------------------------------

def dedupe_prims(prims: list[Prim], round_mm: float = 0.1) -> tuple[list[Prim], dict[str, int]]:
    """Drop exact duplicates (same layer, kind, geometry and text). Returns kept prims and per-layer counts."""
    seen: set = set()
    kept: list[Prim] = []
    dropped: Counter = Counter()
    for p in prims:
        try:
            g = shapely.set_precision(p.geom, round_mm)
            key = (p.layer, p.kind, p.text, shapely.to_wkb(g))
        except Exception:
            key = (p.layer, p.kind, p.text, p.handle)
        if key in seen:
            dropped[p.layer] += 1
            continue
        seen.add(key)
        kept.append(p)
    return kept, dict(dropped)


def layer_stats(prims: list[Prim]) -> dict[str, dict[str, int]]:
    stats: dict[str, Counter] = {}
    for p in prims:
        stats.setdefault(p.layer, Counter())[p.dxftype] += 1
    return {k: dict(v) for k, v in stats.items()}


def translate(prim_geom: base.BaseGeometry, dx: float, dy: float) -> base.BaseGeometry:
    return shapely.affinity.translate(prim_geom, xoff=dx, yoff=dy)
