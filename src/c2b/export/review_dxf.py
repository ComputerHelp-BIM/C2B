"""Review DXF: the extracted elements drawn back in drawing coordinates.

Open it on top of the client drawing (or XREF it) to see at a glance what was
recognised and what was not. Every element carries its id so the Excel rows and
the drawing match. This is also the seed of the template-DXF writer (step 3).
"""
from __future__ import annotations

from pathlib import Path

import ezdxf

from ..schema import Project

LAYERS = {
    "C2B-GRID": 8, "C2B-GRID-TAG": 8,
    "C2B-COLUMN": 1, "C2B-COLUMN-TAG": 1, "C2B-COLUMN-WALL": 30,
    "C2B-BEAM": 3, "C2B-BEAM-CL": 3, "C2B-BEAM-TAG": 3,
    "C2B-SLAB": 4, "C2B-SLAB-TAG": 4,
    "C2B-FOOTING": 2, "C2B-FOOTING-TAG": 2,
    "C2B-OPENING": 6, "C2B-WALL": 30,
    "C2B-FLOOR": 40, "C2B-DIAG-ERROR": 1, "C2B-DIAG-WARNING": 2, "C2B-DIAG-INFO": 5,
}


def _fmt(v: float | None) -> str:
    return f"{v:.0f}" if v is not None else "?"


def write_review_dxf(project: Project, path: str | Path, text_height: float = 150.0) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    origins = {f.id: (f.origin.x, f.origin.y) for f in project.floors}

    def g(fid: str, p) -> tuple[float, float]:
        ox, oy = origins.get(fid, (0.0, 0.0))
        return (p.x + ox, p.y + oy)

    def text(layer: str, fid: str, p, s: str, rot: float = 0.0, h: float = text_height):
        msp.add_mtext(s, dxfattribs={"layer": layer, "char_height": h, "rotation": rot, "attachment_point": 5}).set_location(g(fid, p))

    for f in project.floors:
        if f.boundary:
            msp.add_lwpolyline([(p.x, p.y) for p in f.boundary], close=True, dxfattribs={"layer": "C2B-FLOOR"})
            minx = min(p.x for p in f.boundary)
            miny = min(p.y for p in f.boundary)
            msp.add_mtext(f"{f.id}: {f.name}\ncolumns {f.counts.get('columns', 0)}  beams {f.counts.get('beams', 0)}  footings {f.counts.get('footings', 0)}",
                          dxfattribs={"layer": "C2B-FLOOR", "char_height": text_height * 3}).set_location((minx, miny - text_height * 4))
        msp.add_point((f.origin.x, f.origin.y), dxfattribs={"layer": "C2B-FLOOR"})

    for gr in project.grids:
        msp.add_line(g(gr.floor_id, gr.start), g(gr.floor_id, gr.end), dxfattribs={"layer": "C2B-GRID"})
        if gr.label:
            text("C2B-GRID-TAG", gr.floor_id, gr.start, gr.label, h=text_height * 1.5)

    for c in project.columns:
        layer = "C2B-COLUMN-WALL" if c.wall_like else "C2B-COLUMN"
        msp.add_lwpolyline([g(c.floor_id, p) for p in c.outline], close=True, dxfattribs={"layer": layer})
        size = f"D{_fmt(c.diameter_mm)}" if c.shape == "circle" else f"{_fmt(c.width_mm)}x{_fmt(c.depth_mm)}"
        label = " ".join(x for x in [c.mark or "", size, f"[{c.size_source}]" if c.size_source != "tag" else ""] if x)
        text("C2B-COLUMN-TAG", c.floor_id, c.center, f"{c.id}\n{label}")

    for b in project.beams:
        msp.add_lwpolyline([g(b.floor_id, p) for p in b.outline], close=True, dxfattribs={"layer": "C2B-BEAM"})
        msp.add_line(g(b.floor_id, b.start), g(b.floor_id, b.end), dxfattribs={"layer": "C2B-BEAM-CL"})
        mid = type(b.start)(x=(b.start.x + b.end.x) / 2, y=(b.start.y + b.end.y) / 2)
        label = " ".join(x for x in [b.mark or "", f"{_fmt(b.width_mm)}x{_fmt(b.depth_mm)}", "INV" if b.inverted else "", f"[{b.depth_source}]" if b.depth_source != "tag" else ""] if x)
        text("C2B-BEAM-TAG", b.floor_id, mid, f"{b.id} {label}", rot=b.angle_deg if b.angle_deg <= 90 else b.angle_deg - 180, h=text_height * 0.8)

    for s in project.slabs:
        if s.outline:
            msp.add_lwpolyline([g(s.floor_id, p) for p in s.outline], close=True, dxfattribs={"layer": "C2B-SLAB"})
        text("C2B-SLAB-TAG", s.floor_id, s.position, f"{s.id} {s.mark or ''} THK {_fmt(s.thickness_mm)} [{s.thickness_source}]")

    for ft in project.footings:
        msp.add_lwpolyline([g(ft.floor_id, p) for p in ft.outline], close=True, dxfattribs={"layer": "C2B-FOOTING"})
        text("C2B-FOOTING-TAG", ft.floor_id, ft.center, f"{ft.id} {ft.mark or ''}\n{_fmt(ft.width_mm)}x{_fmt(ft.depth_mm)} THK {_fmt(ft.thickness_mm)}")

    for o in project.openings:
        msp.add_lwpolyline([g(o.floor_id, p) for p in o.outline], close=True, dxfattribs={"layer": "C2B-OPENING"})
        text("C2B-OPENING", o.floor_id, o.center, f"{o.id} {o.label or 'OPENING'}")

    for w in project.walls:
        msp.add_lwpolyline([g(w.floor_id, p) for p in w.outline], close=True, dxfattribs={"layer": "C2B-WALL"})

    for d in project.diagnostics:
        if d.location is None or d.severity == "INFO":
            continue
        fid = d.floor_id
        p = g(fid, d.location) if fid else (d.location.x, d.location.y)
        layer = f"C2B-DIAG-{d.severity}"
        msp.add_circle(p, text_height * 2, dxfattribs={"layer": layer})
        msp.add_mtext(f"{d.code}", dxfattribs={"layer": layer, "char_height": text_height * 0.8}).set_location((p[0] + text_height * 2.2, p[1]))

    doc.saveas(str(path))
    return Path(path)
