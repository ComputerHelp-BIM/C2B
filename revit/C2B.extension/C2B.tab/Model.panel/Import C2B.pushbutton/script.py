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


def level_z_mm(level):
    """A level's elevation in millimetres, or 0 when there is no level."""
    return to_mm(level.Elevation) if level is not None else 0.0


def loop_from(points, z_mm=0.0):
    """A closed CurveLoop from a list of [x, y] in millimetres. Duplicate and tiny edges are dropped."""
    pts = []
    for p in points:
        q = point(p, z_mm)
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


#: Revit's ZJustification enum, by the name the plan uses.
Z_JUSTIFICATION = {"top": 0, "center": 1, "centre": 1, "bottom": 2, "origin": 3}


def set_bip_length(element, bip, value_mm):
    """A built-in length parameter, in millimetres."""
    p = element.get_Parameter(bip)
    if p is None or p.IsReadOnly:
        return False
    p.Set(mm(value_mm))
    return True


def set_bip_id(element, bip, element_id):
    """A built-in parameter holding an element id, such as a beam's reference level."""
    p = element.get_Parameter(bip)
    if p is None or p.IsReadOnly:
        return False
    p.Set(element_id)
    return True


def set_bip_int(element, bip, value):
    p = element.get_Parameter(bip)
    if p is None or p.IsReadOnly:
        return False
    p.Set(int(value))
    return True


#: "Height Offset From Level" as the firm's footing family shows it, with the built-ins Revit
#: uses for the same idea when the name differs.
_LEVEL_OFFSET_BIPS = (BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
                      BuiltInParameter.INSTANCE_ELEVATION_PARAM)


#: What a column is dropped to when Revit would otherwise measure it as flat. A column this
#: short is a thing to go and look at; a rolled-back import is not, because there is nothing
#: left to look at.
MIN_COLUMN_HEIGHT_MM = 300.0


def _level_elevation_mm(parameter):
    """The elevation of the level a parameter points at, or None."""
    if parameter is None:
        return None
    level = doc.GetElement(parameter.AsElementId())
    return to_mm(level.Elevation) if level is not None else None


def _offset_mm(inst, bip):
    p = inst.get_Parameter(bip)
    return to_mm(p.AsDouble()) if p is not None else 0.0


def column_height_mm(inst):
    """What Revit will measure this column as, from the levels and offsets it actually holds.

    Read back rather than taken from the plan: the plan says what was asked for, and this says
    what Revit did with it. The two were not the same, and the difference stopped a whole run.
    """
    base = _level_elevation_mm(inst.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM))
    top = _level_elevation_mm(inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM))
    if base is None or top is None:
        return None
    return ((top + _offset_mm(inst, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM))
            - (base + _offset_mm(inst, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)))


def ensure_standing(inst, action):
    """Never leave behind a column Revit will measure as having no height.

    "Change Offset Value so that Column height is not 0.0" is an ERROR and not a warning, so
    one of them refuses the whole transaction: every type, every beam, every floor, the lot.
    171 of them did that to Test17, and the report afterwards said the run was rolled back so
    nothing it made is there -- which is true and is no help at all.

    Whatever the plan asked for and whatever Revit made of it, a column that comes out flat is
    dropped to a stated minimum here and reported by name. A column 300 mm tall is a thing to
    go and fix. An import that refused to finish is not.
    """
    height = column_height_mm(inst)
    if height is None or height > 1.0:
        return
    p = inst.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)
    if p is None or p.IsReadOnly:
        note("bad", "column %s would have no height and its base offset cannot be set"
                    % (action.get("mark") or action.get("id")))
        return
    wanted = max(abs(action.get("base_offset_mm") or 0.0), MIN_COLUMN_HEIGHT_MM)
    p.Set(p.AsDouble() - mm(wanted - height))
    note("fixed", "column %s came out %.0f mm tall, which Revit refuses; its base was dropped "
                  "to make it %.0f mm so the rest of the import could finish. Check the floor "
                  "heights for this one."
                  % ((action.get("mark") or action.get("id")), height, wanted))


def set_level_offset(inst, value_mm):
    """How far a point-hosted instance sits above or below the level it is on.

    A curve-driven element takes its height from the curve, but a family instance placed with a
    level takes the point's z as an offset FROM that level -- so a point built at the level's own
    elevation lands twice as low. A footing on a foundation at -2500 came out at -5000. The point
    is given no height at all now, and the offset is stated here.
    """
    p = inst.LookupParameter("Height Offset From Level")
    if p is not None and not p.IsReadOnly:
        p.Set(mm(value_mm))
        return True
    for bip in _LEVEL_OFFSET_BIPS:
        if set_bip_length(inst, bip, value_mm):
            return True
    return False


def place_across_section(inst, action):
    """State where the member sits across its own section, rather than letting the family decide.

    A loadable family carries its own z justification and offset, and they win over everything
    else until something sets them. The firm's beam family carries Top / -1500, which put every
    beam 1500 below its level on every floor whatever the plan said.
    """
    justification = action.get("z_justification")
    if not justification:
        return
    code = Z_JUSTIFICATION.get(str(justification).lower())
    if code is None:
        note("param", "%s: unknown z justification '%s'" % (action["id"], justification))
        return
    set_bip_int(inst, BuiltInParameter.Z_JUSTIFICATION, code)
    set_bip_length(inst, BuiltInParameter.Z_OFFSET_VALUE, action.get("z_offset_mm", 0.0))


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

#: (action, element, level) for everything created, so the run can read back what it made.
placed = []


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


def stamp(element, action, plan, level=None):
    """Mark, C2B id, level and note, written to every name the model carries them under.

    Also the one place every created element passes through, so it is where the run records
    what it made and on which level, for the check afterwards.
    """
    placed.append((action, element, level))
    set_text(element, plan.get("mark_params"), action.get("mark"))
    set_text(element, plan.get("id_params"), action.get("id"))
    if level is not None:
        set_text(element, plan.get("level_params"), level.Name)
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


#: Where each kind of element records the level it belongs to, when Element.LevelId cannot say.
_LEVEL_BIPS = (BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,     # structural framing
               BuiltInParameter.FAMILY_BASE_LEVEL_PARAM,            # columns, footings
               BuiltInParameter.LEVEL_PARAM,                        # floors
               BuiltInParameter.WALL_BASE_CONSTRAINT)               # walls


def level_id_of(element):
    """The level an element actually ended up on, however its category records it."""
    try:
        found = element.LevelId                      # Revit 2022 and newer
        if found is not None and found.IntegerValue > 0:
            return found
    except Exception:
        pass
    for bip in _LEVEL_BIPS:
        try:
            p = element.get_Parameter(bip)
        except Exception:
            continue
        if p is not None and p.StorageType.ToString() == "ElementId":
            found = p.AsElementId()
            if found is not None and found.IntegerValue > 0:
                return found
    return None


#: A structural column's offset from its BASE level, which is a different idea from the
#: "Height Offset From Level" a point-hosted footing carries and lives in a different
#: parameter. Reading the footing's one off a column reported 171 of them as built at 0 mm
#: when they were at -3000 -- a warning about a fault the model did not have, which costs more
#: of a person's afternoon than no warning would.
_COLUMN_OFFSET_BIPS = (BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM,)


def read_level_offset(element, bips=None):
    """An instance's offset from the level it is on, in millimetres.

    ``bips`` names where to look when the element is not point-hosted; without it the
    point-hosted parameters are used, which is right for a footing and wrong for a column.
    """
    if bips:
        for bip in bips:
            try:
                p = element.get_Parameter(bip)
            except Exception:
                p = None
            if p is not None and p.StorageType.ToString() == "Double":
                return to_mm(p.AsDouble())
        return None
    p = element.LookupParameter("Height Offset From Level")
    if p is None or p.StorageType.ToString() != "Double":
        for bip in _LEVEL_OFFSET_BIPS:
            try:
                p = element.get_Parameter(bip)
            except Exception:
                p = None
            if p is not None and p.StorageType.ToString() == "Double":
                break
    if p is None or p.StorageType.ToString() != "Double":
        return None
    return to_mm(p.AsDouble())


def check_offsets_of(placed, rows):
    """Did each element end up as far above or below its level as the plan said?

    A family instance placed with a level reads the point's height as an offset FROM that level,
    so an element built at its level's own elevation lands twice as low. A footing on a
    foundation at -2500 came out at -5000, and nothing in a count or a level name shows it.
    """
    wrong = {}
    for action, element, level in placed:
        if level is None or not alive(element) or action.get("kind") not in ("footing", "column", "pile"):
            continue
        want = action.get("base_offset_mm", 0.0)
        try:
            got = read_level_offset(
                element, _COLUMN_OFFSET_BIPS if action.get("kind") in ("column", "pile") else None)
        except Exception:
            continue
        if got is None or abs(got - want) <= 1.0:
            continue
        key = (action.get("kind"), round(want), round(got))
        wrong[key] = wrong.get(key, 0) + 1
    for (kind, want, got), count in sorted(wrong.items()):
        rows.append((False, "%d %ss offset from their level" % (count, kind), "%d mm" % want, "%d mm" % got,
                     "they are built at the wrong height, which no count or level name shows"))


def check_levels_of(placed, rows):
    """Did each element land on the level the plan gave it?

    Revit picks a beam's reference level from the curve it is drawn on, so a curve at the wrong
    height is silently hosted on the wrong level -- every floor's beams at the ground, in one
    place, counted twice in every schedule. The plan being right is not evidence that the model
    is: the two have to be compared.
    """
    wrong = {}
    for action, element, level in placed:
        if level is None or not alive(element):
            continue
        try:
            actual = level_id_of(element)
        except Exception:
            continue
        if actual is None or actual.IntegerValue == level.Id.IntegerValue:
            continue
        key = (action.get("kind"), level.Name)
        wrong.setdefault(key, [0, actual])
        wrong[key][0] += 1
    for (kind, wanted), (count, actual_id) in sorted(wrong.items()):
        try:
            found = doc.GetElement(actual_id).Name
        except Exception:
            found = "another level"
        rows.append((False, "%d %ss meant for %s" % (count, kind, wanted), wanted, found,
                     "Revit hosted them elsewhere, so they are in the wrong place and counted twice"))


def alive(element):
    """Is this handle still a real element? After a rollback, nothing created in the run is."""
    try:
        return element is not None and element.IsValidObject
    except Exception:
        return False


def check_what_was_built(plan, symbols, floor_types, wall_types, levels_by_id, made, placed):
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
        if not alive(element):
            rows.append((False, "type %s" % name, "exists", "no longer in the model",
                         "the run was rolled back, so nothing it made is there"))
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

    # -- did every element land on the level it was given, and at the right height? --
    check_levels_of(placed, rows)
    check_offsets_of(placed, rows)

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
# ------------------------------------------------------------------- the picker
class BuildPicker(forms.WPFWindow):
    """Which storeys and which kinds of member. Ticks only, and a count beside each.

    The markup is written next to the plan by C2B, themed from the same tokens as every other
    window in the suite -- there is no C2B on this side of the fence to generate it here, and a
    second copy of the palette living in the extension is how two surfaces drift apart.

    The rows are real CheckBox controls built here rather than an ItemsSource bound to
    anything. Twenty rows is not a data grid, and a binding is one more thing between a tick
    and what it means.
    """

    def __init__(self, xaml_path, picker, title):
        forms.WPFWindow.__init__(self, xaml_path)
        self.chosen = None
        self._levels = []
        self._kinds = []
        self.VersionBadge.Text = picker.get("generator", "")
        self.HeaderSubtitle.Text = title
        for row in picker.get("levels", []):
            self._levels.append(self._row(self.LevelsHost, row["id"], row["name"], row["total"],
                                          describe(row.get("counts", {}))))
        for row in picker.get("kinds", []):
            self._kinds.append(self._row(self.KindsHost, row["kind"], row["label"], row["total"], ""))
        self.BtnBuild.Click += self.on_build
        self.BtnCancel.Click += self.on_cancel
        self.BtnLevelsAll.Click += lambda s, e: self._set(self._levels, True)
        self.BtnLevelsNone.Click += lambda s, e: self._set(self._levels, False)
        self.BtnKindsAll.Click += lambda s, e: self._set(self._kinds, True)
        self.BtnKindsNone.Click += lambda s, e: self._set(self._kinds, False)
        self.say()

    def _row(self, host, key, label, count, detail):
        """A tick, a name, and the count it stands for, lined up down the right."""
        from System.Windows import (GridLength, GridUnitType, TextTrimming, Thickness,
                                    VerticalAlignment)
        from System.Windows.Controls import CheckBox, ColumnDefinition, Grid, TextBlock

        grid = Grid()
        for width in (None, 78.0):
            column = ColumnDefinition()
            column.Width = (GridLength(1, GridUnitType.Star) if width is None
                            else GridLength(width, GridUnitType.Pixel))
            grid.ColumnDefinitions.Add(column)
        name = TextBlock()
        name.Text = label if not detail else "%s    %s" % (label, detail)
        name.TextTrimming = TextTrimming.CharacterEllipsis
        name.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(name, 0)
        grid.Children.Add(name)
        number = TextBlock()
        number.Text = "{:,}".format(count)
        number.Style = self.Resources["GridNumber"]
        number.Margin = Thickness(8, 0, 0, 0)
        Grid.SetColumn(number, 1)
        grid.Children.Add(number)

        box = CheckBox()
        box.Style = self.Resources["RowCheckBox"]
        box.Content = grid
        box.IsChecked = count > 0
        box.IsEnabled = count > 0
        box.Click += self.on_tick
        host.Children.Add(box)
        return (key, box, count)

    def _set(self, rows, ticked):
        for _key, box, count in rows:
            if count:
                box.IsChecked = ticked
        self.say()

    def on_tick(self, sender, args):
        self.say()

    def picked(self):
        levels = set(k for k, box, _n in self._levels if box.IsChecked)
        kinds = set(k for k, box, _n in self._kinds if box.IsChecked)
        return levels, kinds

    def say(self):
        """What is about to be built, in the words of what was ticked."""
        levels, kinds = self.picked()
        self.SelectionText.Text = (
            "%d of %d storeys, %d of %d kinds of member" %
            (len(levels), len(self._levels), len(kinds), len(self._kinds)))
        self.BtnBuild.IsEnabled = bool(levels and kinds) or bool(kinds and not self._levels)

    def on_build(self, sender, args):
        self.chosen = self.picked()
        self.Close()

    def on_cancel(self, sender, args):
        self.chosen = None
        self.Close()


def describe(counts):
    """"161 columns, 362 beams" -- the biggest few, so a row stays one line."""
    parts = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    return ", ".join("%d %s" % (n, kind + ("" if n == 1 else "s")) for kind, n in parts)


def choose_what_to_build(plan, plan_path):
    """The build window, or the plain list when it cannot be shown.

    Returns ``(levels, kinds)``, or None when the run was called off. Only what is ticked on
    both sides is built -- but every LEVEL is still created, because a member on a ticked
    storey is measured from the level under it.
    """
    picker = plan.get("picker") or {}
    if not picker.get("kinds"):
        return (set(lv["id"] for lv in plan.get("levels", [])),
                set(a.get("kind") for a in plan.get("actions", [])))
    picker = dict(picker, generator=plan.get("generator", ""))
    xaml_path = plan_path.replace(".revit.json", ".revit.xaml")
    title = "%s  %s" % (os.path.basename(plan_path).replace(".revit.json", ""),
                        describe(plan.get("counts", {})))
    if os.path.isfile(xaml_path):
        try:
            window = BuildPicker(xaml_path, picker, title)
            window.ShowDialog()
            return window.chosen
        except Exception as ex:
            note("warn", "the build window would not open (%s), so the plain list was used "
                         "instead" % type(ex).__name__)
    wanted = forms.SelectFromList.show(
        [("%s  (%d)" % (r["label"], r["total"])) for r in picker["kinds"]],
        title="C2B: what to build", multiselect=True, button_name="Build these")
    if not wanted:
        return None
    labels = dict(("%s  (%d)" % (r["label"], r["total"]), r["kind"]) for r in picker["kinds"])
    return (set(lv["id"] for lv in picker.get("levels", [])),
            set(labels[w] for w in wanted if w in labels))


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

    chosen = choose_what_to_build(plan, path)
    if chosen is None:
        return
    wanted_levels, wanted_kinds = chosen
    everything = plan.get("actions", [])
    # Only what was ticked on BOTH sides. An action belonging to no level -- a grid -- is
    # governed by its kind alone, because there is no storey to leave it out of.
    plan["actions"] = [a for a in everything
                       if a.get("kind") in wanted_kinds
                       and (not a.get("level_id") or a.get("level_id") in wanted_levels)]
    left_out = len(everything) - len(plan["actions"])
    if left_out:
        note("skip", "%d of %d elements were left out of this run because their storey or their "
                     "kind was unticked. Every level is still created: a member on a storey you "
                     "did tick is measured from the level under it." % (left_out, len(everything)))

    levels_by_id = {}
    existing_grids = dict((g.Name, g) for g in all_of(Grid))
    symbols = symbols_by_family()
    floor_types = types_by_name(FloorType)
    wall_types = types_by_name(WallType)
    made = {}

    def tally(kind):
        # one rule in one place: the check derives the same key from the action's kind, and a
        # call site spelling it differently is how 320 created columns were reported as none
        key = kind if kind.endswith("s") else kind + "s"
        made[key] = made.get(key, 0) + 1

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
                # A project started from the firm's template already holds its sample grids
                # (1, 2, 3, A-E). Revit will not have two grids of one name, so the client's
                # grid is refused outright and simply lost -- thirteen of seventeen, on the
                # first real run. The placeholder is moved out of the way instead.
                name = action.get("mark") or ""
                clash = existing_grids.get(name)
                if clash is not None:
                    policy = plan.get("grid_name_clash") or "rename_existing"
                    if policy == "skip":
                        note("skip", "grid %s already exists; the client's grid was not created" % name)
                        continue
                    if policy == "reuse":
                        note("reused", "grid %s already existed and was left where it was" % name)
                        tally("grids")
                        continue
                    spare, n = "%s (template)" % name, 2
                    while spare in existing_grids:
                        spare, n = "%s (template %d)" % (name, n), n + 1
                    clash.Name = spare
                    existing_grids[spare] = clash
                    note("renamed", "the project already had grid %s from the template; it is now "
                                    "%s, and the client's grid %s was created" % (name, spare, name))
                grid = Grid.Create(doc, Line.CreateBound(point(action["start"]), point(action["end"])))
                grid.Name = name
                existing_grids[name] = grid
                tally("grids")
            elif kind in ("column", "pile"):
                symbol = ensure_symbol(action, symbols)
                if symbol is None or level is None:
                    continue
                inst = doc.Create.NewFamilyInstance(point(action["point"]), symbol, level,
                                                    Structure.StructuralType.Column)
                # The base offset goes on FIRST. A column on the lowest plan has nothing under
                # it, so the plan gives it its own level as its top and hangs it below on an
                # offset -- and asking Revit to put the top level on the base level while the
                # offsets still read zero is asking for a column of no height, which is a thing
                # it is entitled to refuse or to fix in its own way. Stated in the order that
                # never asks for one. Through set_bip_length, because a parameter that will not
                # take a value says so, and the raw Set that was here did not.
                set_bip_length(inst, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM,
                               action.get("base_offset_mm", 0.0))
                if top is not None:
                    set_bip_id(inst, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM, top.Id)
                    set_bip_length(inst, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM,
                                   action.get("top_offset_mm", 0.0))
                    # Again: moving the top level can move the base offset with it.
                    set_bip_length(inst, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM,
                                   action.get("base_offset_mm", 0.0))
                ensure_standing(inst, action)
                rotation = action.get("rotation_deg") or 0.0
                if abs(rotation) > 1e-6:
                    from Autodesk.Revit.DB import ElementTransformUtils
                    axis = Line.CreateBound(point(action["point"]), point(action["point"], 1000.0))
                    ElementTransformUtils.RotateElement(doc, inst.Id, axis, rotation * 3.141592653589793 / 180.0)
                stamp(inst, action, plan, level)
                tally(kind)
            elif kind == "beam":
                symbol = ensure_symbol(action, symbols)
                if symbol is None or level is None:
                    continue
                # The curve decides where the beam physically is, and Revit picks the
                # reference level from it. Drawn at z = 0 every floor's beams landed on top of
                # each other at the ground: one place, 779 "identical instances" warnings, and
                # a reference level of 01 GROUND LVL. on a beam whose own CH-LEVEL said the
                # fifth floor. It is drawn at its level's elevation, and the reference level is
                # then stated rather than inferred.
                z = level_z_mm(level)
                curve = Line.CreateBound(point(action["start"], z), point(action["end"], z))
                inst = doc.Create.NewFamilyInstance(curve, symbol, level, Structure.StructuralType.Beam)
                set_bip_id(inst, BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM, level.Id)
                # the reference line sits on the level; where the section sits about that line is
                # the z offset's job, and setting both put the beam at twice its own offset
                for bip in (BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION, BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION):
                    p = inst.get_Parameter(bip)
                    if p is not None and not p.IsReadOnly:
                        p.Set(mm(0.0))
                place_across_section(inst, action)
                stamp(inst, action, plan, level)
                tally("beams")
            # a raft, pile cap or pit comes with an outline and is built as a slab; an isolated
            # footing comes with a point and is built from its family, in the branch below
            elif kind in ("floor", "pcc", "footing") and action.get("loops"):
                ftype = ensure_system_type(action, floor_types, FloorType)
                if ftype is None or level is None:
                    continue
                loops = []
                for ring in action["loops"]:
                    made_loop = loop_from(ring, level_z_mm(level))
                    if made_loop is not None:
                        loops.append(made_loop)
                if not loops:
                    note("skip", "%s has no usable outline" % action["id"])
                    continue
                floor = Floor.Create(doc, loops, ftype.Id, level.Id)
                p = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                if p is not None and not p.IsReadOnly:
                    p.Set(mm(action.get("top_offset_mm", 0.0) + action.get("base_offset_mm", 0.0)))
                stamp(floor, action, plan, level)
                tally(kind)
            elif kind == "footing":
                symbol = ensure_symbol(action, symbols)
                if symbol is None or level is None:
                    continue
                inst = doc.Create.NewFamilyInstance(point(action["point"]), symbol, level,
                                                    Structure.StructuralType.Footing)
                set_level_offset(inst, action.get("base_offset_mm", 0.0))
                stamp(inst, action, plan, level)
                tally("footings")
            elif kind == "wall":
                wtype = ensure_system_type(action, wall_types, WallType)
                if wtype is None or level is None:
                    continue
                z = level_z_mm(level)
                curve = Line.CreateBound(point(action["start"], z), point(action["end"], z))
                height = mm(3000.0)
                if top is not None:
                    height = top.Elevation - level.Elevation + mm(action.get("top_offset_mm", 0.0))
                wall = Wall.Create(doc, curve, wtype.Id, level.Id, height, 0.0, False, True)
                # stated both ways round, because the curve's height and the level argument can
                # each be the one Revit believes and only one of them is right
                set_bip_id(wall, BuiltInParameter.WALL_BASE_CONSTRAINT, level.Id)
                set_bip_length(wall, BuiltInParameter.WALL_BASE_OFFSET, action.get("base_offset_mm", 0.0))
                if top is not None:
                    wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(top.Id)
                    wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(mm(action.get("top_offset_mm", 0.0)))
                stamp(wall, action, plan, level)
                tally("walls")
            elif kind == "shaft" and action.get("loops"):
                ring = loop_from(action["loops"][0], level_z_mm(level))
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
    try:
        checked = check_what_was_built(plan, symbols, floor_types, wall_types, levels_by_id, made, placed)
    except Exception as ex:
        checked = []
        note("failed", "the check could not run: %s" % ex)
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
