"""Render a DXF to PNG with ezdxf's matplotlib backend (development aid).

Usage: python tools/render_dxf.py <file.dxf> <out.png> [xmin ymin xmax ymax]
"""
from __future__ import annotations

import sys

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend


def main(path, out, window=None, dpi=150):
    doc = ezdxf.readfile(path)
    fig = plt.figure(figsize=(20, 14))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(doc.modelspace(), finalize=True)
    if window:
        ax.set_xlim(window[0], window[2])
        ax.set_ylim(window[1], window[3])
    fig.savefig(out, dpi=dpi, facecolor="white")
    print("rendered", out)


if __name__ == "__main__":
    w = [float(v) for v in sys.argv[3:7]] if len(sys.argv) >= 7 else None
    main(sys.argv[1], sys.argv[2], w)
