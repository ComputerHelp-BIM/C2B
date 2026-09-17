# -*- coding: utf-8 -*-
"""Build a Revit model from a C2B build plan (``<name>.revit.json``).

Every decision was already made by C2B: which level, which family and type, which offset,
which loop is a hole. This script only creates what the plan lists, so the part that runs
inside Revit stays small enough to read.

Run it from the C2B tab. It asks for the plan file, shows what it is about to create, and
then builds it in a few transactions. Nothing is deleted: running it twice creates a second
set of elements, so undo (or work in a fresh model) if you want to re-run.
"""
__title__ = "Import\nC2B model"
__author__ = "C2B"

import json
import os
import traceback

from Autodesk.Revit.DB import (BuiltInParameter, Curve, CurveArray, CurveLoop, ElementId, Floor, FilteredElementCollector,
                               FamilySymbol, FloorType, Grid, Level, Line, Structure, Transaction, UnitUtils, Wall, WallType,
                               XYZ)
from pyrevit import forms, revit, script

try:                                  # Revit 2021 and newer
    from Autodesk.Revit.DB import UnitTypeId
    def mm(value):
        return UnitUtils.ConvertToInternalUnits(float(value), UnitTypeId.Millimeters)
except ImportError:                   # Revit 2020 and older
    from Autodesk.Revit.DB import DisplayUnitType
    def mm(value):
        return UnitUtils.ConvertToInternalUnits(float(value), DisplayUnitType.DUT_MILLIMETERS)

doc = revit.doc
output = script.get_output()
log = []


def note(kind, message):
    log.append((kind, message))


def point(xy, z=0.0):
    return XYZ(mm(xy[0]), mm(xy[1]), z)


def loop_from(points):
    """A closed CurveLoop from a list of [x, y] in millimetres. Duplicate and tiny edges are dropped."""
    pts = []
    for p in points:
        q = point(p)
        if not pts or q.DistanceTo(pts[-1]) > mm(1.0):
            pts.append(q)
    if len(pts) > 2 and pts[0].DistanceTo(pts[-1]) <= mm(1.0):
        pts.pop()
    if len(pts) < 3:
        return None
    curves = CurveLoop()
    for i in range(len(pts)):
        curves.Append(Line.CreateBound(pts[i], pts[(i + 1) % len(pts)]))
    return curves


# ---------------------------------------------------------------- collectors
def all_of(cls):
    return list(FilteredElementCollector(doc).OfClass(cls))


def symbols_by_family():
    found = {}
    for s in all_of(FamilySymbol):
        family = s.Family.Name
        name = s.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        found.setdefault(family, {})[name] = s
    return found


def types_by_name(cls):
    found = {}
    for t in all_of(cls):
        try:
            found[t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()] = t
        except Exception:
            found[getattr(t, "Name", "")] = t
    return found


def set_param(element, name, value_mm):
    p = element.LookupParameter(name)
    if p is None or p.IsReadOnly:
        return False
    p.Set(mm(value_mm))
    return True


def ensure_symbol(action, symbols):
    """Find the family type the action asks for, duplicating and resizing one when it is missing."""
    family, wanted = action.get("family"), action.get("type_name")
    pool = symbols.get(family)
    if pool is None:
        note("missing", "family not in the project: %s (for %s)" % (family, action["id"]))
        return None
    if wanted in pool:
        symbol = pool[wanted]
    else:
        source = pool.get(action.get("base_type")) or list(pool.values())[0]
        symbol = source.Duplicate(wanted)
        for name, value in (action.get("params") or {}).items():
            if not set_param(symbol, name, value):
                note("param", "%s: could not set '%s' on type %s" % (action["id"], name, wanted))
        pool[wanted] = symbol
        note("created", "type %s : %s" % (family, wanted))
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()
    return symbol


def ensure_system_type(action, pool, cls):
    wanted = action.get("type_name")
    if wanted in pool:
        return pool[wanted]
    source = pool.get(action.get("base_type")) or (list(pool.values())[0] if pool else None)
    if source is None:
        note("missing", "no %s type to copy for %s" % (cls.__name__, wanted))
        return None
    new = source.Duplicate(wanted)
    pool[wanted] = new
    note("created", "%s type %s (thickness must be set once in the project)" % (cls.__name__, wanted))
    return new


# ---------------------------------------------------------------------- run
def main():
    path = forms.pick_file(file_ext="json", title="Pick the C2B build plan (*.revit.json)")
    if not path:
        return
    with open(path, "r") as handle:
        plan = json.load(handle)

    counts = plan.get("counts", {})
    summary = "\n".join("  %-10s %s" % (k, v) for k, v in sorted(counts.items()))
    if not forms.alert("C2B plan: %s\n\n%s\n\nBuild this in the current model?" % (os.path.basename(path), summary),
                       title="C2B", ok=False, yes=True, no=True):
        return

    levels_by_id = {}
    symbols = symbols_by_family()
    floor_types = types_by_name(FloorType)
    wall_types = types_by_name(WallType)
    made = {}

    def tally(kind):
        made[kind] = made.get(kind, 0) + 1

    # ---- levels ---------------------------------------------------------
    existing_levels = dict((l.Name, l) for l in all_of(Level))
    t = Transaction(doc, "C2B: levels")
    t.Start()
    try:
        for row in plan.get("levels", []):
            level = existing_levels.get(row["name"])
            if level is None:
                level = Level.Create(doc, mm(row["elevation_mm"]))
                level.Name = row["name"]
                tally("levels")
            levels_by_id[row["id"]] = level
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert("Levels failed: %s" % ex, title="C2B")
        return

    # ---- everything else -------------------------------------------------
    t = Transaction(doc, "C2B: model")
    t.Start()
    for action in plan.get("actions", []):
        kind = action.get("kind")
        try:
            level = levels_by_id.get(action.get("level_id"))
            top = levels_by_id.get(action.get("top_level_id"))
            if kind == "grid":
                Grid.Create(doc, Line.CreateBound(point(action["start"]), point(action["end"]))).Name = action.get("mark") or ""
                tally("grids")
            elif kind in ("column", "pile"):
                symbol = ensure_symbol(action, symbols)
                if symbol is None or level is None:
                    continue
                inst = doc.Create.NewFamilyInstance(point(action["point"]), symbol, level, Structure.StructuralType.Column)
                if top is not None:
                    inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM).Set(top.Id)
                    inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM).Set(mm(action.get("top_offset_mm", 0.0)))
                inst.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM).Set(mm(action.get("base_offset_mm", 0.0)))
                rotation = action.get("rotation_deg") or 0.0
                if abs(rotation) > 1e-6:
                    from Autodesk.Revit.DB import ElementTransformUtils
                    axis = Line.CreateBound(point(action["point"]), point(action["point"], mm(1000.0)))
                    ElementTransformUtils.RotateElement(doc, inst.Id, axis, rotation * 3.141592653589793 / 180.0)
                if action.get("mark"):
                    inst.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).Set(action["mark"])
                tally(kind)
            elif kind == "beam":
                symbol = ensure_symbol(action, symbols)
                if symbol is None or level is None:
                    continue
                curve = Line.CreateBound(point(action["start"]), point(action["end"]))
                inst = doc.Create.NewFamilyInstance(curve, symbol, level, Structure.StructuralType.Beam)
                offset = action.get("top_offset_mm", 0.0)
                for bip in (BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION, BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION):
                    p = inst.get_Parameter(bip)
                    if p is not None and not p.IsReadOnly:
                        p.Set(mm(offset))
                if action.get("mark"):
                    inst.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).Set(action["mark"])
                tally("beams")
            elif kind in ("floor", "pcc", "footing") and action.get("loops"):
                ftype = ensure_system_type(action, floor_types, FloorType)
                if ftype is None or level is None:
                    continue
                loops = []
                for ring in action["loops"]:
                    made_loop = loop_from(ring)
                    if made_loop is not None:
                        loops.append(made_loop)
                if not loops:
                    note("skip", "%s has no usable outline" % action["id"])
                    continue
                floor = Floor.Create(doc, loops, ftype.Id, level.Id)
                p = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                if p is not None and not p.IsReadOnly:
                    p.Set(mm(action.get("top_offset_mm", 0.0) + action.get("base_offset_mm", 0.0)))
                if action.get("mark"):
                    floor.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).Set(action["mark"])
                tally("floors" if kind == "floor" else kind)
            elif kind == "footing":
                symbol = ensure_symbol(action, symbols)
                if symbol is None or level is None:
                    continue
                inst = doc.Create.NewFamilyInstance(point(action["point"]), symbol, level, Structure.StructuralType.Footing)
                if action.get("mark"):
                    inst.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).Set(action["mark"])
                tally("footings")
            elif kind == "wall":
                wtype = ensure_system_type(action, wall_types, WallType)
                if wtype is None or level is None:
                    continue
                curve = Line.CreateBound(point(action["start"]), point(action["end"]))
                height = mm(3000.0)
                if top is not None:
                    height = top.Elevation - level.Elevation + mm(action.get("top_offset_mm", 0.0))
                wall = Wall.Create(doc, curve, wtype.Id, level.Id, height, 0.0, False, True)
                if top is not None:
                    wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(top.Id)
                    wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(mm(action.get("top_offset_mm", 0.0)))
                tally("walls")
            elif kind == "shaft" and action.get("loops"):
                ring = loop_from(action["loops"][0])
                if ring is None or level is None:
                    continue
                arr = CurveArray()
                for curve in ring:
                    arr.Append(curve)
                doc.Create.NewOpening(level, top or level, arr)
                tally("shafts")
        except Exception as ex:
            note("failed", "%s %s: %s" % (kind, action.get("id"), ex))
    t.Commit()

    # ---- report ----------------------------------------------------------
    output.print_md("## C2B import finished")
    output.print_md("\n".join("* **%s**: %s" % (k, v) for k, v in sorted(made.items())) or "* nothing was created")
    problems = [row for row in log if row[0] in ("failed", "missing")]
    if problems:
        output.print_md("### %d problems" % len(problems))
        for kind, message in problems[:200]:
            output.print_md("* `%s` %s" % (kind, message))
    created = [row for row in log if row[0] == "created"]
    if created:
        output.print_md("### %d types created" % len(created))
        for _kind, message in created[:100]:
            output.print_md("* %s" % message)


try:
    main()
except Exception:
    forms.alert("C2B import stopped:\n\n%s" % traceback.format_exc(), title="C2B")
