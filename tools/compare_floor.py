"""Render one floor from the client drawing and from the generated template, side by side.

Numbers hide layout problems; a picture of the same bays from both files does not.

Usage: python tools/compare_floor.py <client.dxf> <template.dxf> <extract.json> <floor id> <out.png> [bays]
"""
from __future__ import annotations

import sys

import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration


def draw(ax, path, window, title):
    doc = ezdxf.readfile(path)
    ctx = RenderContext(doc)
    Frontend(ctx, MatplotlibBackend(ax), config=Configuration(lineweight_scaling=0.7)).draw_layout(doc.modelspace(), finalize=False)
    ax.set_aspect("equal", adjustable="box")      # 'box' keeps the window we asked for
    ax.set_xlim(window[0], window[2])
    ax.set_ylim(window[1], window[3])
    ax.set_title(title, fontsize=11, color="white")
    ax.set_facecolor("#20242A")
    ax.set_xticks([]); ax.set_yticks([])


def main(client, template, extract_json, floor_id, out, bays="3"):
    import json
    project = json.loads(open(extract_json).read())
    floor = next(f for f in project["floors"] if f["id"] == floor_id)
    ox, oy = floor["origin"]["x"], floor["origin"]["y"]
    xs = [p["x"] for p in floor["boundary"]]
    ys = [p["y"] for p in floor["boundary"]]
    # a window of a few bays in the middle of the plan, in drawing coordinates
    span = (max(xs) - min(xs)) / max(float(bays), 1.0)
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2 + (max(ys) - min(ys)) * 0.12
    window = (cx - span / 2, cy - span * 0.42, cx + span / 2, cy + span * 0.42)
    fig, axes = plt.subplots(2, 1, figsize=(15, 16), dpi=115, facecolor="#20242A")
    draw(axes[0], client, window, f"client drawing — {floor['name']}")
    draw(axes[1], template, window, f"C2B template — {floor['name']}")
    fig.tight_layout()
    fig.savefig(out, facecolor="#20242A", bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main(*sys.argv[1:7])
