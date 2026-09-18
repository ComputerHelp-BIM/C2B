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

from Autodesk.Revit.DB import (BuiltInParameter, CurveArray, CurveLoop, Floor, FilteredElementCollector,
                               FamilySymbol, FloorType, Grid, Level, Line, SpecTypeId, Structure, Transaction,
                               UnitUtils, Wall, WallType, XYZ)
from pyrevit import forms, revit, script

# ---------------------------------------------------------------------- units
# Revit stores every length internally in DECIMAL FEET, whatever the project's display unit is
# set to. A plan is in millimetres, so every length crossing into the API goes through mm() and
# every length read back out goes through to_mm(). A raw millimetre value handed to Revit is
# read as feet: 300 becomes 91.4 metres, and nothing complains.
#
# The project's own unit setting changes what a user SEES and nothing else, so an imperial
# project imports exactly the same model. The run reports the setting anyway, so the log is
# never ambiguous about it.
try:                                  # Revit 2021 and newer
    from Autodesk.Revit.DB import UnitTypeId

    def mm(value):
        """Millimetres -> Revit's internal feet."""
        return UnitUtils.ConvertToInternalUnits(float(value), UnitTypeId.Millimeters)

    def to_mm(value):
        """Revit's internal feet -> millimetres."""
        return UnitUtils.ConvertFromInternalUnits(float(value), UnitTypeId.Millimeters)
except ImportError:                   # Revit 2020 and older
    from Autodesk.Revit.DB import DisplayUnitType

    def mm(value):
        """Millimetres -> Revit's internal feet."""
        return UnitUtils.ConvertToInternalUnits(float(value), DisplayUnitType.DUT_MILLIMETERS)

    def to_mm(value):
        """Revit's internal feet -> millimetres."""
        return UnitUtils.ConvertFromInternalUnits(float(value), DisplayUnitType.DUT_MILLIMETERS)

doc = revit.doc
output = script.get_output()
log = []


def note(kind, message):
    log.append((kind, message))


def point(xy, z_mm=0.0):
    """A plan point in millimetres -> an internal-unit XYZ. Every argument is millimetres."""
    return XYZ(mm(xy[0]), mm(xy[1]), mm(z_mm))


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


def set_length(element, name, value_mm):
    p = element.LookupParameter(name)
    if p is None or p.IsReadOnly:
        return False
    p.Set(mm(value_mm))
    return True


# Which of the plan's candidate parameter names this model actually has. The firm's template
# and its shared parameter file disagree on the names (ID / CH-ID, S_ScheduleMark /
# CH-ScheduleMark), so the plan lists every candidate and this records which ones took. A name
# that never takes is a parameter nobody bound: the value would have vanished silently.
param_hits = {}
param_misses = {}


def set_text(element, names, value):
    """Write a text value to every named parameter the element has. Returns how many took."""
    if value is None:
        return 0
    taken = 0
    for name in names or []:
        p = element.LookupParameter(name)
        if p is None or p.IsReadOnly or p.StorageType.ToString() != "String":
            param_misses[name] = param_misses.get(name, 0) + 1
            continue
        p.Set(str(value))
        param_hits[name] = param_hits.get(name, 0) + 1
        taken += 1
    return taken


def stamp(element, action, plan):
    """Mark, C2B id and note, written to every name the model carries them under."""
    set_text(element, plan.get("mark_params"), action.get("mark"))
    set_text(element, plan.get("id_params"), action.get("id"))
    comment = plan.get("comment_param")
    if comment and action.get("comment"):
        set_text(element, [comment], action.get("comment"))


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
            if not set_length(symbol, name, value):
                note("param", "%s: could not set '%s' on type %s" % (action["id"], name, wanted))
        pool[wanted] = symbol
        note("created", "type %s : %s" % (family, wanted))
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()
    return symbol


def set_structure_thickness(type_element, thickness_mm):
    """Set a system type's thickness: the core layer of its compound structure.

    A duplicated floor or wall type keeps the thickness of the type it was copied from, so a
    type named "175 THK. RCC SLAB" would be 150 thick unless this runs. A type with several
    layers has only its core layer resized -- a finish on a slab is not structure and is not
    the dimension the drawing states.
    """
    try:
        structure = type_element.GetCompoundStructure()
        if structure is None:
            return False
        index = structure.GetFirstCoreLayerIndex() if structure.LayerCount > 1 else 0
        structure.SetLayerWidth(index, mm(thickness_mm))
        type_element.SetCompoundStructure(structure)
        return True
    except Exception as ex:
        note("param", "could not set the thickness of %s: %s" % (type_element.Name, ex))
        return False


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
    thickness = action.get("thickness_mm")
    if thickness and set_structure_thickness(new, thickness):
        note("created", "%s type %s, %.0f mm thick" % (cls.__name__, wanted, thickness))
    else:
        note("created", "%s type %s (COPY OF %s: check its thickness)" % (cls.__name__, wanted, source.Name))
    return new


# ------------------------------------------------------------------- checking
def read_length(element, name):
    """A length parameter read back in millimetres, or None when the element has not got it."""
    p = element.LookupParameter(name)
    if p is None or p.StorageType.ToString() != "Double":
        return None
    return to_mm(p.AsDouble())


def check_what_was_built(plan, symbols, floor_types, wall_types, levels_by_id, made):
    """Read the model back and compare it with the plan, without leaving Revit.

    The import saying "finished" is not evidence. Three things go wrong quietly and none of
    them look wrong in the project browser: elements that failed while the rest carried on, a
    type that was duplicated but kept the size it was copied from, and a level that already
    existed at a different height so everything on it sits at the wrong elevation.
    """
    rows = []          # (ok, what, planned, found, why it matters)

    # -- did everything get built? -------------------------------------------
    planned = {}
    for action in plan.get("actions", []):
        kind = "floors" if action.get("kind") == "floor" else action.get("kind") + "s"
        planned[kind] = planned.get(kind, 0) + 1
    planned["levels"] = len(plan.get("levels", []))
    for kind in sorted(planned):
        want, got = planned[kind], made.get(kind, 0)
        rows.append((got >= want, kind, want, got,
                     "" if got >= want else "%d were not created -- see the failures above" % (want - got)))

    # -- is every type the size the plan asked for? --------------------------
    wanted_types = {}
    for action in plan.get("actions", []):
        name = action.get("type_name")
        if not name:
            continue
        want = dict(action.get("params") or {})
        if not want and action.get("thickness_mm"):
            want = {"__thickness__": action["thickness_mm"]}
        wanted_types.setdefault((action.get("family"), name), want)

    for (family, name), want in sorted(wanted_types.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        element = None
        if family and family in symbols:
            element = symbols[family].get(name)
        else:
            element = floor_types.get(name) or wall_types.get(name)
        if element is None:
            rows.append((False, "type %s" % name, "exists", "missing",
                         "everything of this type failed"))
            continue
        for param, value in want.items():
            if param == "__thickness__":
                structure = element.GetCompoundStructure()
                if structure is None:
                    continue
                index = structure.GetFirstCoreLayerIndex() if structure.LayerCount > 1 else 0
                got = to_mm(structure.GetLayerWidth(index))
                label = "thickness"
            else:
                got = read_length(element, param)
                label = param
            if got is None:
                rows.append((False, "type %s" % name, "%s %.0f" % (label, value), "no such parameter",
                             "the family does not carry it, so the size was never set"))
            elif abs(got - value) > 1.0:
                rows.append((False, "type %s" % name, "%s %.0f" % (label, value), "%s %.0f" % (label, got),
                             "it kept the size of the type it was copied from -- every element of it is wrong"))

    # -- are the levels where the plan put them? -----------------------------
    for row in plan.get("levels", []):
        level = levels_by_id.get(row["id"])
        if level is None:
            rows.append((False, "level %s" % row["name"], "%.0f mm" % row["elevation_mm"], "missing",
                         "nothing hosted on it was built"))
            continue
        got = to_mm(level.Elevation)
        if abs(got - row["elevation_mm"]) > 1.0:
            rows.append((False, "level %s" % row["name"], "%.0f mm" % row["elevation_mm"], "%.0f mm" % got,
                         "it already existed at another height, so everything on it is at the wrong level"))
    return rows


# ---------------------------------------------------------------------- run
def pick_plan():
    """The build plan, opening where the last one was picked so nobody hunts for the folder."""
    config = script.get_config()
    last = getattr(config, "last_folder", None)
    path = forms.pick_file(file_ext="json", title="Pick the C2B build plan (*.revit.json)",
                           init_dir=last if last and os.path.isdir(last) else None)
    if path:
        config.last_folder = os.path.dirname(path)
        script.save_config()
    return path


def main():
    path = pick_plan()
    if not path:
        return
    with open(path, "r") as handle:
        plan = json.load(handle)

    counts = plan.get("counts", {})
    summary = "\n".join("  %-10s %s" % (k, v) for k, v in sorted(counts.items()))
    # Revit works in decimal feet internally whatever this says; it changes only what is shown.
    try:
        unit_name = doc.GetUnits().GetFormatOptions(SpecTypeId.Length).GetUnitTypeId().TypeId.split(":")[-1]
    except Exception:
        unit_name = "unknown"
    if not forms.alert("C2B plan: %s\n\n%s\n\nThis model displays lengths in %s.\n"
                       "Build this in the current model?" % (os.path.basename(path), summary, unit_name),
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
                    axis = Line.CreateBound(point(action["point"]), point(action["point"], 1000.0))
                    ElementTransformUtils.RotateElement(doc, inst.Id, axis, rotation * 3.141592653589793 / 180.0)
                stamp(inst, action, plan)
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
                stamp(inst, action, plan)
                tally("beams")
            # a raft, pile cap or pit comes with an outline and is built as a slab; an isolated
            # footing comes with a point and is built from its family, in the branch below
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
                stamp(floor, action, plan)
                tally("floors" if kind == "floor" else kind)
            elif kind == "footing":
                symbol = ensure_symbol(action, symbols)
                if symbol is None or level is None:
                    continue
                inst = doc.Create.NewFamilyInstance(point(action["point"]), symbol, level, Structure.StructuralType.Footing)
                stamp(inst, action, plan)
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
                stamp(wall, action, plan)
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

    # ---- check what was built, without leaving Revit ----------------------
    checked = check_what_was_built(plan, symbols, floor_types, wall_types, levels_by_id, made)
    wrong = [row for row in checked if not row[0]]

    # ---- report ----------------------------------------------------------
    if wrong:
        output.print_md("# C2B import finished, with %d things to look at" % len(wrong))
        output.print_md("| What | Should be | In the model | Why it matters |")
        output.print_md("| --- | --- | --- | --- |")
        for _ok, what, planned_value, found, why in wrong[:200]:
            output.print_md("| %s | %s | %s | %s |" % (what, planned_value, found, why))
    else:
        output.print_md("# C2B import finished — the model matches the plan")

    output.print_md("## What was created")
    output.print_md("\n".join("* **%s**: %s" % (k, v) for k, v in sorted(made.items())) or "* nothing was created")
    problems = [row for row in log if row[0] in ("failed", "missing")]
    if problems:
        output.print_md("### %d failures" % len(problems))
        for kind, message in problems[:200]:
            output.print_md("* `%s` %s" % (kind, message))
    created = [row for row in log if row[0] == "created"]
    if created:
        output.print_md("### %d types created" % len(created))
        for _kind, message in created[:100]:
            output.print_md("* %s" % message)

    # which of the candidate parameter names exist here. A name with no writes at all is one
    # nobody bound in this template: anything C2B meant for it never arrived.
    output.print_md("### Where the marks went")
    for name in (plan.get("mark_params") or []) + (plan.get("id_params") or []):
        hits = param_hits.get(name, 0)
        if hits:
            output.print_md("* `%s` - written on %d elements" % (name, hits))
        else:
            output.print_md("* `%s` - **not in this model**, nothing was written to it" % name)


try:
    main()
except Exception:
    forms.alert("C2B import stopped:\n\n%s" % traceback.format_exc(), title="C2B")
