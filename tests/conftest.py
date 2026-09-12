"""Shared fixtures: a synthetic client-style drawing built with ezdxf.

The drawing deliberately mixes conventions seen in real client files:
columns as closed polylines with hatches, one column as four LINEs, beams as
pairs of parallel LINEs, a circular column, tags on separate layers, a
schedule table, a general note with a default depth, and two floors side by
side with Boundary / Origin markers.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _rect(msp, layer, x, y, w, h, hatch=True):
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    if hatch:
        hp = msp.add_hatch(color=7, dxfattribs={"layer": layer})
        hp.paths.add_polyline_path(pts, is_closed=True)


def _beam(msp, layer, x1, y1, x2, y2, width):
    """Two parallel lines around the centreline."""
    import math
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    nx, ny = -dy / L * width / 2, dx / L * width / 2
    msp.add_line((x1 + nx, y1 + ny), (x2 + nx, y2 + ny), dxfattribs={"layer": layer})
    msp.add_line((x1 - nx, y1 - ny), (x2 - nx, y2 - ny), dxfattribs={"layer": layer})


def build_synthetic_drawing(path: Path) -> Path:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-GRID", "S-GRID-IDEN", "S-COLS", "S-COLS-IDEN", "S-BEAM", "S-BEAM-IDEN", "S-FND", "S-FND-IDEN",
                 "A-FLOR-IDEN", "A-CUTOUT", "G-ANNO-TEXT", "G-ANNO-SCHD", "BEAM NO", "BEAM SIZES"):
        doc.layers.add(name)

    def floor(ox: float, name: str, with_beams: bool, with_footings: bool):
        # boundary 30 m x 20 m with origin at grid 1/A
        msp.add_lwpolyline([(ox - 3000, -3000), (ox + 27000, -3000), (ox + 27000, 17000), (ox - 3000, 17000)], close=True, dxfattribs={"layer": "Boundary"})
        msp.add_point((ox, 0), dxfattribs={"layer": "Origin"})
        msp.add_text(name, dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((ox + 8000, -2500))
        xs, ys = [0, 6000, 12000, 18000], [0, 5000, 10000]
        for i, gx in enumerate(xs):
            msp.add_line((ox + gx, -1500), (ox + gx, 11500), dxfattribs={"layer": "S-GRID"})
            msp.add_text(str(i + 1), dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((ox + gx, -2000))
        for j, gy in enumerate(ys):
            msp.add_line((ox - 1500, gy), (ox + 19500, gy), dxfattribs={"layer": "S-GRID"})
            msp.add_text("ABC"[j], dxfattribs={"layer": "S-GRID-IDEN", "height": 250}).set_placement((ox - 2000, gy))
        n = 0
        for gx in xs:
            for gy in ys:
                n += 1
                if (gx, gy) == (18000, 10000):
                    msp.add_circle((ox + gx, gy), 300, dxfattribs={"layer": "S-COLS"})
                    msp.add_text("C_600D", dxfattribs={"layer": "S-COLS-IDEN", "height": 125}).set_placement((ox + gx + 350, gy + 100))
                elif (gx, gy) == (0, 10000):
                    # column drawn with four LINEs, tagged with a mark only (schedule gives the size)
                    x, y = ox + gx - 150, gy - 225
                    for a, b in (((x, y), (x + 300, y)), ((x + 300, y), (x + 300, y + 450)), ((x + 300, y + 450), (x, y + 450)), ((x, y + 450), (x, y))):
                        msp.add_line(a, b, dxfattribs={"layer": "S-COLS"})
                    msp.add_text("C1", dxfattribs={"layer": "S-COLS-IDEN", "height": 125}).set_placement((ox + gx + 250, gy + 300))
                else:
                    _rect(msp, "S-COLS", ox + gx - 150, gy - 225, 300, 450)
                    msp.add_text("C_300 X 450", dxfattribs={"layer": "S-COLS-IDEN", "height": 125}).set_placement((ox + gx + 250, gy + 300))
                if with_footings:
                    _rect(msp, "S-FND", ox + gx - 900, gy - 900, 1800, 1800, hatch=False)
                    msp.add_text("F1_500MM THK", dxfattribs={"layer": "S-FND-IDEN", "height": 125}).set_placement((ox + gx - 800, gy - 1150))
        if with_beams:
            for gy in ys:
                _beam(msp, "S-BEAM", ox + 0, gy, ox + 18000, gy, 230)
                msp.add_text("B_230 X 450", dxfattribs={"layer": "S-BEAM-IDEN", "height": 125}).set_placement((ox + 2500, gy + 200))
            for gx in xs:
                _beam(msp, "S-BEAM", ox + gx, 0, ox + gx, 10000, 230)
                # mark on one layer, size on another, stacked
                msp.add_text("MB", dxfattribs={"layer": "BEAM NO", "height": 125, "rotation": 90}).set_placement((ox + gx - 250, 2000))
                msp.add_text("230X600", dxfattribs={"layer": "BEAM SIZES", "height": 125, "rotation": 90}).set_placement((ox + gx - 450, 2000))
            # one beam without any tag -> depth from note
            _beam(msp, "S-BEAM", ox + 6000, 2500, ox + 12000, 2500, 230)
            for gx in (3000, 9000, 15000):
                for gy in (2500, 7500):
                    msp.add_text("150 THK.", dxfattribs={"layer": "A-FLOR-IDEN", "height": 125}).set_placement((ox + gx, gy))
            msp.add_lwpolyline([(ox + 13000, 6000), (ox + 15000, 6000), (ox + 15000, 8500), (ox + 13000, 8500)], close=True, dxfattribs={"layer": "A-CUTOUT"})
            msp.add_text("LIFT", dxfattribs={"layer": "A-CUTOUT", "height": 125}).set_placement((ox + 13800, 7200))
            msp.add_text("NOTE: ALL BEAMS ARE 450MM IN DEPTH U.N.O.", dxfattribs={"layer": "G-ANNO-TEXT", "height": 150}).set_placement((ox + 1000, 14000))

    floor(0, "FOUNDATION LEVEL", with_beams=False, with_footings=True)
    floor(40000, "GROUND FLOOR LEVEL", with_beams=True, with_footings=False)

    # schedule: Mark | b | h  (classic text grid)
    sx, sy = 90000, 10000
    msp.add_text("Structural Column Schedule", dxfattribs={"layer": "G-ANNO-SCHD", "height": 250}).set_placement((sx, sy + 600))
    for x, txt in ((sx, "Mark"), (sx + 3000, "b"), (sx + 5500, "h")):
        msp.add_text(txt, dxfattribs={"layer": "G-ANNO-SCHD", "height": 250}).set_placement((x, sy))
    for r, (mark, b, h) in enumerate((("C1", "300", "450"), ("C2", "400", "600"))):
        for x, txt in ((sx, mark), (sx + 3000, b), (sx + 5500, h)):
            msp.add_text(txt, dxfattribs={"layer": "G-ANNO-SCHD", "height": 250}).set_placement((x, sy - 600 * (r + 1)))
    doc.saveas(str(path))
    return path


@pytest.fixture(scope="session")
def synthetic_dxf(tmp_path_factory) -> Path:
    return build_synthetic_drawing(tmp_path_factory.mktemp("dxf") / "synthetic.dxf")


@pytest.fixture(scope="session")
def synthetic_result(synthetic_dxf):
    from c2b.pipeline import extract
    return extract(synthetic_dxf)
