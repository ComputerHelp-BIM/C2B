"""Template DXF writer.

Draws a :class:`NormalizedProject` in the firm's template conventions. When a
seed template DXF is given its layers, text styles, dimension style, linetypes
and legend are reused, so the output is guaranteed to look like the template.
Every entity carries XDATA (app id ``C2B``) with the element id, so the file
round-trips losslessly into utility 4.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.math import Matrix44

from ..normalize.model import NormalizedProject
from ..normalize.spec import TemplateSpec


class TemplateWriter:
    def __init__(self, spec: TemplateSpec, seed: str | Path | None = None, diag=None):
        self.spec = spec
        self.diag = diag
        self.seed_path = Path(seed) if seed else (Path(spec.seed_dxf) if spec.seed_dxf else None)
        self.legend_entities = []
        self.legend_anchor = None
        self.used_meanings: dict[tuple[str, float | None], str] = {}
        self._sunk_patterns: dict[float, str] = {}
        if self.seed_path and self.seed_path.exists():
            self.doc = ezdxf.readfile(str(self.seed_path))
            self._harvest_legend()
            self.doc.modelspace().delete_all_entities()
            for layout in list(self.doc.layouts):
                if layout.name.lower() != "model":
                    try:
                        layout.delete_all_entities()
                    except Exception:
                        pass
        else:
            if self.seed_path and self.diag is not None:
                self.diag.warning("SEED_MISSING", f"Seed template {self.seed_path} not found; layers and styles created from the spec")
            self.doc = ezdxf.new("R2018", setup=True)
        self.doc.header["$INSUNITS"] = 4
        self.doc.header["$LTSCALE"] = 1.0
        self._ensure_tables()
        self.msp = self.doc.modelspace()

    # ------------------------------------------------------------------ setup
    def _ensure_tables(self) -> None:
        doc, spec = self.doc, self.spec
        if spec.xdata_appid not in doc.appids:
            doc.appids.add(spec.xdata_appid)
        for key, ld in spec.layers.items():
            if ld.name not in doc.layers:
                lt = ld.linetype if ld.linetype in doc.linetypes else "Continuous"
                doc.layers.add(ld.name, color=ld.color, lineweight=ld.lineweight, linetype=lt)
        if spec.grid_linetype not in doc.linetypes:
            doc.linetypes.add(spec.grid_linetype, pattern=[40.0, 30.0, -4.0, 1.0, -4.0, 1.0, -4.0], description="Grid line ____ . . ____")
        if spec.text.style not in doc.styles:
            doc.styles.add(spec.text.style, font=spec.text.font)
        if spec.dimstyle not in doc.dimstyles:
            ds = doc.dimstyles.add(spec.dimstyle)
            ds.dxf.dimtxt = spec.text.mark_height * 1.4
            ds.dxf.dimasz = 100.0
            ds.dxf.dimexe = 100.0
            ds.dxf.dimexo = 60.0
            ds.dxf.dimdec = 0
            ds.dxf.dimtad = 1
            ds.dxf.dimtih = 0
            ds.dxf.dimtxsty = spec.text.style

    def _harvest_legend(self) -> None:
        """Copy the legend (boxes, hatches, texts) of the seed's left-most plan frame."""
        spec = self.spec
        msp = self.doc.modelspace()
        legend_layers = {spec.layer("legend"), spec.layer("hatch")}
        items = [e for e in msp if e.dxf.layer in legend_layers]
        if not items:
            return
        boundaries = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == spec.layer("boundary")]
        from shapely.geometry import Point, Polygon
        frames = [Polygon(list(b.get_points("xy"))) for b in boundaries if b.closed]

        def anchor_of(e):
            if e.dxftype() == "MTEXT":
                return (e.dxf.insert.x, e.dxf.insert.y)
            if e.dxftype() == "LWPOLYLINE":
                pts = list(e.get_points("xy"))
                return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            if e.dxftype() == "HATCH":
                try:
                    from ezdxf import path as ezpath
                    pts = [(v.x, v.y) for p in ezpath.from_hatch(e) for v in p.flattening(5)]
                    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
                except Exception:
                    return None
            return None

        # pick the frame with the most legend items
        best, best_items = None, []
        for fr in frames:
            inside = [e for e in items if anchor_of(e) and fr.contains(Point(anchor_of(e)))]
            if len(inside) > len(best_items):
                best, best_items = fr, inside
        if best is None:
            return
        minx, miny, maxx, maxy = best.bounds
        # the seed frame includes the bottom band: the plan bottom is band height above it
        plan_bottom = miny + spec.frame.bottom_band_mm
        self.legend_anchor = (maxx, plan_bottom)
        self.legend_entities = [e.copy() for e in best_items]

    def sunk_pattern(self, depth: float) -> str:
        """One hatch pattern per sunk depth, taken from the palette in the order the depths appear."""
        depth = float(depth)
        if depth not in self._sunk_patterns:
            used = set(self._sunk_patterns.values())
            palette = [p for p in self.spec.hatch.sunk_patterns if p not in used]
            self._sunk_patterns[depth] = palette[0] if palette else self.spec.hatch.slab_sunk_75
        return self._sunk_patterns[depth]

    # --------------------------------------------------------------- helpers
    def _xdata(self, entity, **fields) -> None:
        entity.set_xdata(self.spec.xdata_appid, [(1000, f"{k}={v}") for k, v in fields.items() if v is not None])

    def _mtext(self, layer_key: str, text: str, pos, height: float, attachment: int = 5, rotation: float = 0.0, width: float = 0.0, **xd):
        m = self.msp.add_mtext(text, dxfattribs={"layer": self.spec.layer(layer_key), "char_height": height, "style": self.spec.text.style,
                                                 "attachment_point": attachment, "rotation": rotation})
        m.set_location(pos)
        if width:
            m.dxf.width = width
        if xd:
            self._xdata(m, **xd)
        return m

    def _poly(self, layer_key: str, points, closed: bool = True, **xd):
        p = self.msp.add_lwpolyline([(pt.x, pt.y) if hasattr(pt, "x") else pt for pt in points], close=closed, dxfattribs={"layer": self.spec.layer(layer_key)})
        if xd:
            self._xdata(p, **xd)
        return p

    def _hatch(self, layer_key: str, rings: list[list[tuple[float, float]]], pattern: str, **xd):
        h = self.msp.add_hatch(dxfattribs={"layer": self.spec.layer(layer_key)})
        h.set_pattern_fill(pattern, scale=self.spec.hatch.scale)
        for ring in rings:
            h.paths.add_polyline_path(ring, is_closed=True)
        if xd:
            self._xdata(h, **xd)
        return h

    # ----------------------------------------------------------------- write
    def write(self, np_: NormalizedProject, path: str | Path) -> Path:
        spec = self.spec
        origins = {f.id: (f.origin.x, f.origin.y) for f in np_.floors}

        def g(fid, p):
            ox, oy = origins[fid]
            return (p.x + ox, p.y + oy)

        for f in np_.floors:
            # the origin is carried on the frame as well as drawn, so a floor whose origin falls
            # outside its frame (a drawing without client Boundary rectangles) still reads back exactly
            self._poly("boundary", f.frame, floor=f.id, origin=f"{f.origin.x:.3f},{f.origin.y:.3f}", name=f.name)
            pnt = self.msp.add_point((f.origin.x, f.origin.y), dxfattribs={"layer": spec.layer("origin")})
            self._xdata(pnt, floor=f.id)
            left, right = min(p.x for p in f.frame), max(p.x for p in f.frame)
            cx = (left + right) / 2
            fr = spec.frame
            self._mtext("text", f.title, (cx, f.plan_bottom_y + fr.title_above_band_mm), spec.text.title_height, 5, floor=f.id, kind="title")
            y = f.plan_bottom_y - fr.notes_first_line_below_mm
            for i, note in enumerate(list(f.notes) + list(np_.notes), start=1):
                self._mtext("text", f"{i}) {note}", (cx + fr.notes_offset_x_mm, y), spec.text.note_height, 4, width=12300.0, floor=f.id, kind="note")
                y -= fr.notes_line_spacing_mm

        for gr in np_.grids:
            line = self.msp.add_line(g(gr.floor_id, gr.start), g(gr.floor_id, gr.end), dxfattribs={"layer": spec.layer("grid"), "linetype": spec.grid_linetype, "ltscale": spec.grid_ltscale})
            self._xdata(line, id=gr.id, label=gr.label, axis=gr.axis)
            for b in gr.bubble_centres:
                c = self.msp.add_circle(g(gr.floor_id, b), spec.placement.grid_bubble_radius_mm, dxfattribs={"layer": spec.layer("grid_mark")})
                self._xdata(c, id=gr.id)
                self._mtext("grid_mark", gr.label, g(gr.floor_id, b), spec.text.mark_height, 5, id=gr.id)

        stop_rings: dict[str, list] = {}
        for c in np_.columns:
            pts = [g(c.floor_id, p) for p in c.outline]
            if c.shape == "circle" and c.diameter_mm:
                e = self.msp.add_circle(g(c.floor_id, c.center), c.diameter_mm / 2, dxfattribs={"layer": spec.layer("column")})
            else:
                e = self.msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": spec.layer("column")})
            self._xdata(e, id=c.id, stack=c.stack_id, mark=c.mark, client=c.client_mark, src=",".join(c.source_ids))
            # the normaliser decided the text, its lines and where it sits; XDATA keeps the full
            # mark so utility 4 recovers it even when the drawing shows it on two lines
            self._mtext("column_mark", "\\P".join(c.mark_lines or [c.mark]), g(c.floor_id, c.mark_position),
                        spec.text.mark_height, 5, rotation=c.mark_rotation_deg, id=c.id, mark=c.mark)
            if spec.hatch.hatch_all_columns or c.stops_here:
                stop_rings.setdefault(c.floor_id, []).append(pts if c.shape != "circle" else _circle_ring(g(c.floor_id, c.center), (c.diameter_mm or 300) / 2))
        for fid, rings in stop_rings.items():
            self._hatch("column_hatch", rings, spec.hatch.column_stop, floor=fid, meaning="column_stop")
        if stop_rings:
            self.used_meanings[("column_stop", None)] = spec.hatch.column_stop

        for w in np_.walls:
            if not w.structural:
                continue   # answer 6B: masonry / non-structural walls are not drawn
            e = self._poly("wall", [g(w.floor_id, p) for p in w.outline], id=w.id, src=w.source_id, top_offset=w.top_offset_mm)
            if w.mark:
                self._mtext("wall_mark", w.mark, g(w.floor_id, w.center), spec.text.mark_height, 5, id=w.id)

        for b in np_.beams:
            stub = "1" if (b.width_mm and b.length_mm and b.length_mm < b.width_mm) else None
            e = self._poly("beam", [g(b.floor_id, p) for p in b.outline], id=b.id, run=b.run_id, mark=b.mark, client=b.client_mark, stub=stub)
            if spec.beam_centreline:
                cl = self.msp.add_line(g(b.floor_id, b.start), g(b.floor_id, b.end), dxfattribs={"layer": spec.layer("beam_cl")})
                self._xdata(cl, id=b.id, kind="centreline")
            text = self._beam_mark(b)
            self._mtext("beam_mark", text, g(b.floor_id, b.mark_position), spec.text.mark_height, 5, rotation=b.mark_rotation_deg, id=b.id, mark=b.mark)

        for s in np_.panels:
            if s.kind not in ("slab", "cantilever", "ramp"):
                continue   # cut-outs and stairs are drawn from their own records
            layer_key, mark_key = ("ramp", "ramp_mark") if s.kind == "ramp" else ("slab", "slab_mark")
            if s.bulges and any(abs(bv) > 1e-9 for bv in s.bulges):
                pts_b = [(*g(s.floor_id, p), bv) for p, bv in zip(s.outline, s.bulges)]
                e = self.msp.add_lwpolyline(pts_b, format="xyb", close=True, dxfattribs={"layer": spec.layer(layer_key)})
                self._xdata(e, id=s.id, mark=s.mark, thk=s.thickness_mm, kind=s.kind, top_offset=s.top_offset_mm, src=",".join(s.tag_ids))
            else:
                self._poly(layer_key, [g(s.floor_id, p) for p in s.outline], id=s.id, mark=s.mark, thk=s.thickness_mm, kind=s.kind, top_offset=s.top_offset_mm, src=",".join(s.tag_ids))
            self._mtext(mark_key, s.mark, g(s.floor_id, s.mark_position), spec.text.mark_height, 5, id=s.id)
            if s.sunk_mm:
                self._hatch("slab_sunk", [[g(s.floor_id, q) for q in s.outline]], self.sunk_pattern(s.sunk_mm), id=s.id, sunk=s.sunk_mm)
                self.used_meanings[("sunk", float(s.sunk_mm))] = self.sunk_pattern(s.sunk_mm)
            if s.top_offset_rule in ("beam_bottom", "projection"):
                self.used_meanings[("beam_bottom", None)] = spec.hatch.slab_at_beam_bottom
            if s.kind == "ramp" and len(s.arrow) == 2:
                a, b = g(s.floor_id, s.arrow[0]), g(s.floor_id, s.arrow[1])
                ln = self.msp.add_line(a, b, dxfattribs={"layer": spec.layer("ramp")})
                self._xdata(ln, id=s.id, kind="arrow", direction=s.direction)
                # arrow head at the end
                import math as _m
                ang = _m.atan2(b[1] - a[1], b[0] - a[0])
                L = spec.text.mark_height * 1.5
                for da in (2.6, -2.6):
                    self.msp.add_line(b, (b[0] + L * _m.cos(ang + da), b[1] + L * _m.sin(ang + da)), dxfattribs={"layer": spec.layer("ramp")})
        for fd in np_.folds:
            pts = [g(fd.floor_id, p) for p in fd.outline]
            self._poly("slab_fold", pts, id=fd.id, panel=fd.panel_id, fold=fd.fold_mm)
            self._hatch("slab_fold", [pts], spec.hatch.raft_fold_sunk, id=fd.id, meaning="fold")
            self._mtext("slab_mark", fd.mark, g(fd.floor_id, fd.mark_position), spec.text.mark_height, 5, id=fd.id)
            self.used_meanings[("fold", None)] = spec.hatch.raft_fold_sunk

        for x in np_.footings:
            in_raft = "raft" in x.stack_ids
            layer_key = {"footing": "footing", "combined": "footing", "pilecap": "pilecap", "pit": "footing", "raft": "raft",
                         "fold": "raft_fold" if in_raft else "footing_fold", "sunk": "raft_sunk" if in_raft else "footing_sunk"}[x.kind]
            pts = [g(x.floor_id, p) for p in x.outline]
            self._poly(layer_key, pts, id=x.id, mark=x.mark, client=x.client_mark, kind=x.kind, pit_depth=x.pit_depth_mm)
            if x.pcc_outline:
                self._poly("pcc", [g(x.floor_id, p) for p in x.pcc_outline], id=x.id, kind="pcc", thk=x.pcc_thickness_mm, proj=x.pcc_projection_mm)
            if x.kind in ("fold", "sunk"):
                self._hatch(layer_key, [pts], spec.hatch.raft_fold_sunk, id=x.id, meaning=x.kind)
            if x.mark_lines:
                mk = "raft_mark" if (x.kind == "raft" or in_raft) else ("pilecap_mark" if x.kind == "pilecap" else "footing_mark")
                self._mtext(mk, "\\P".join(x.mark_lines), g(x.floor_id, x.center), spec.text.mark_height, 5, id=x.id)
        for pl in np_.piles:
            if not pl.diameter_mm:
                continue   # piles are drawn only as the client drew them; no assumed diameter
            c = self.msp.add_circle(g(pl.floor_id, pl.center), pl.diameter_mm / 2, dxfattribs={"layer": spec.layer("pile")})
            self._xdata(c, id=pl.id, cap=pl.pilecap_id, dia=pl.diameter_mm)

        for o in np_.openings:
            pts = [g(o.floor_id, p) for p in o.outline]
            self._poly("cutout", pts, id=o.id, label=o.label)
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            for a, b in (((min(xs), min(ys)), (max(xs), max(ys))), ((min(xs), max(ys)), (max(xs), min(ys)))):
                ln = self.msp.add_line(a, b, dxfattribs={"layer": spec.layer("cutout")})
                self._xdata(ln, id=o.id)

        for st in np_.stairs:
            if st.outline:
                self._poly("stairs", [g(st.floor_id, p) for p in st.outline], id=st.id, src=st.source_id)
            if st.mark and (st.outline or not any(x.outline for x in np_.stairs if x.floor_id == st.floor_id)):
                self._mtext("stairs_mark", st.mark, g(st.floor_id, st.center), spec.text.mark_height, 5, id=st.id)
        for j in np_.joints:
            ln = self.msp.add_line(g(j.floor_id, j.start), g(j.floor_id, j.end), dxfattribs={"layer": spec.layer("joint")})
            self._xdata(ln, id=j.id)
            for a, b in st.lines:
                ln = self.msp.add_line(g(st.floor_id, a), g(st.floor_id, b), dxfattribs={"layer": spec.layer("stairs")})
                self._xdata(ln, id=st.id)

        # the legend lists what this drawing actually uses, so it is drawn once every element is in
        for f in np_.floors:
            right = max(p.x for p in f.frame)
            if spec.legend_from_seed and self.legend_entities:
                self._place_legend(right, f.plan_bottom_y)
            else:
                self._draw_legend(right, f.plan_bottom_y)

        if np_.levels:
            self._write_elevation_frame(np_)

        self.doc.saveas(str(path))
        return Path(path)

    def _draw_legend(self, frame_right: float, plan_bottom: float) -> None:
        """Legend built from the meanings this drawing actually uses, in the template's layout."""
        spec, fr = self.spec, self.spec.frame
        rows = self._legend_rows()
        if not rows:
            return
        box_w, box_h = 700.0, 300.0
        x1 = frame_right - fr.legend_from_right_mm
        y_top = plan_bottom - fr.legend_top_above_mm
        for i, (pattern, text) in enumerate(rows):
            y = y_top - i * fr.legend_row_mm
            ring = [(x1, y - box_h), (x1 + box_w, y - box_h), (x1 + box_w, y), (x1, y)]
            self._poly("legend", ring, kind="legend")
            self._hatch("hatch", [ring], pattern, kind="legend")
            self._mtext("legend", text, (x1 + box_w + spec.text.mark_height * 1.6, y - box_h / 2), spec.text.mark_height, 4, width=4624.0, kind="legend")

    def _legend_rows(self) -> list[tuple[str, str]]:
        spec = self.spec
        rows: list[tuple[str, str]] = []
        for (meaning, value), pattern in sorted(self.used_meanings.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
            text = spec.legend_texts.get(meaning)
            if not text:
                continue
            rows.append((pattern, text.format(value=value or 0)))
        return rows

    def _beam_mark(self, beam) -> str:
        """The full mark when it fits along the span, otherwise the mark alone.

        The size stays in the schedule and in the data; a 650 mm bracket simply cannot carry
        "BK1-200X650" without covering its neighbours.

        Unlike a shear wall's two-line mark this stays in the writer on purpose: it abbreviates
        the text without moving it, so nothing downstream sees a different answer. A wall mark
        changes where the mark *sits*, which the normalised model records and Revit reads, so
        that one is decided in the normaliser instead.
        """
        spec = self.spec
        if not spec.placement.beam_mark_shorten:
            return beam.mark
        width = len(beam.mark) * spec.text.mark_height * spec.text.width_factor
        if width <= (beam.length_mm or 0) * 0.95:
            return beam.mark
        base = beam.mark.rsplit("-", 1)[0] if "-" in beam.mark else beam.mark
        return spec.marks.beam_short.format(base=base)

    def _place_legend(self, frame_right: float, plan_bottom: float) -> None:
        if not (self.spec.legend_from_seed and self.legend_entities and self.legend_anchor):
            return
        dx = frame_right - self.legend_anchor[0]
        dy = plan_bottom - self.legend_anchor[1]
        m = Matrix44.translate(dx, dy, 0)
        for e in self.legend_entities:
            if e.dxftype() == "HATCH":
                self._copy_hatch_translated(e, dx, dy)
                continue
            c = e.copy()
            try:
                c.transform(m)
            except Exception:
                continue
            self.msp.add_entity(c)

    def _copy_hatch_translated(self, src, dx: float, dy: float) -> None:
        """Rebuild a hatch at an offset; a plain transform() rescales the pattern definition in ezdxf."""
        from ezdxf import path as ezpath
        h = self.msp.add_hatch(color=src.dxf.color, dxfattribs={"layer": src.dxf.layer})
        if src.dxf.solid_fill:
            h.set_solid_fill(color=src.dxf.color)
        else:
            h.set_pattern_fill(src.dxf.pattern_name, color=src.dxf.color, angle=src.dxf.pattern_angle, scale=src.dxf.pattern_scale)
        try:
            for pth in ezpath.from_hatch(src):
                pts = [(v.x + dx, v.y + dy) for v in pth.flattening(5.0)]
                if len(pts) >= 3:
                    h.paths.add_polyline_path(pts, is_closed=True)
        except Exception:
            pass

    def _write_elevation_frame(self, np_: NormalizedProject) -> None:
        spec, fr = self.spec, self.spec.frame
        plans = sorted(np_.floors, key=lambda f: min(p.x for p in f.frame))
        first = plans[0]
        left0 = min(p.x for p in first.frame)
        bottom = min(p.y for p in first.frame)
        top = max(p.y for p in first.frame)
        width = max(p.x for p in first.frame) - left0
        right = left0 - fr.elevation_frame_gap_mm
        left = right - width
        self.msp.add_lwpolyline([(left, bottom), (right, bottom), (right, top), (left, top)], close=True, dxfattribs={"layer": spec.layer("boundary")})
        cx = (left + right) / 2
        self._mtext("text", spec.marks.elevation_title, (cx, first.plan_bottom_y + fr.title_above_band_mm), spec.text.title_height, 5, kind="title")
        x1 = left + fr.level_line_inset_left_mm
        x2 = x1 + fr.level_line_length_mm
        base_y = bottom + fr.level_base_above_bottom_mm
        e0 = np_.levels[0].elevation_mm
        prev = None
        for lv in np_.levels:
            y = base_y + (lv.elevation_mm - e0)
            line = self.msp.add_line((x1, y), (x2, y), dxfattribs={"layer": spec.layer("level")})
            self._xdata(line, id=lv.id, elevation=lv.elevation_mm, plan=lv.plan_floor_id)
            self._mtext("level_mark", lv.name, (x1 - 350, y + 50), spec.text.mark_height, 7, width=2400.0, id=lv.id)
            if prev is not None:
                # the seed dimstyle (a Revit export) carries an inch scale factor; override so the rendered text is 2.5 mm at 1:100
                override = {"dimscale": 1.0, "dimtxt": spec.text.mark_height * 1.4, "dimasz": spec.text.mark_height * 0.8, "dimexe": spec.text.mark_height * 0.8,
                            "dimexo": spec.text.mark_height * 0.5, "dimgap": spec.text.mark_height * 0.3, "dimtxsty": spec.text.style, "dimdec": 0, "dimtad": 1, "dimtih": 0, "dimtoh": 0}
                dim = self.msp.add_linear_dim(base=(x1 + fr.level_dim_offset_mm, (prev[1] + y) / 2), p1=(x1 + fr.level_dim_offset_mm, prev[1]), p2=(x1 + fr.level_dim_offset_mm, y), angle=90,
                                              dimstyle=spec.dimstyle, override=override, dxfattribs={"layer": spec.layer("dim")})
                try:
                    dim.render()
                except Exception:
                    pass
            prev = (lv, y)


def _circle_ring(c, r, n=24):
    import math
    return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def write_template_dxf(np_: NormalizedProject, path: str | Path, spec: TemplateSpec, seed: str | Path | None = None, diag=None) -> Path:
    return TemplateWriter(spec, seed, diag).write(np_, path)
