"""Utility 5: the build plan, and what it asks of the Revit template.

Every decision the Revit script relies on is made here, so these tests are the only place
they can be checked without a Revit seat.
"""

import ast
from pathlib import Path

import pytest

from c2b.normalize.model import NBeam, NColumn, NFloor, NLevel, NormalizedProject, NPanel, Point2
from c2b.revit.mapping import RevitMapping
from c2b.revit.plan import build_plan, check_against_template
from c2b.revit.template import parse_template_md

TESTS = Path(__file__).resolve().parent
MINI = TESTS / "data" / "mini-template.md"
TEMPLATE_MD = TESTS.parent / "templates" / "R25_TEMPLATE.template.md"
SCRIPT = (TESTS.parent / "revit" / "C2B.extension" / "C2B.tab" /
          "Model.panel" / "Import C2B.pushbutton" / "script.py")


def _mini_mapping(**kw):
    """A mapping naming the fixture template's families, so the firm can edit theirs freely."""
    mapping = RevitMapping(**kw)
    mapping.column.family, mapping.column.fallback_type = "Test-Rectangular-Column", "T-300 X 600"
    mapping.column.type_name = "T-{w:.0f} X {d:.0f}"
    mapping.column_round.family, mapping.column_round.type_name = "Test-Round-Column", "T-{dia:.0f}"
    mapping.beam.family, mapping.beam.type_name = "Test-Rectangular-Beam", "T-{w:.0f} X {d:.0f}"
    mapping.floor.type_name, mapping.floor.base_type = "{thk:.0f} THK. TEST SLAB", "150 THK. TEST SLAB"
    return mapping


def _pt(x, y):
    return Point2(x=x, y=y)


def _model(columns=(), beams=(), panels=()):
    """Two levels on one plan floor: enough for anything that needs a level above."""
    floor = NFloor(id="L01", index=0, name="GROUND", title="GROUND", source_name="GROUND",
                   origin=_pt(0, 0), frame=[], plan_bottom_y=0.0)
    return NormalizedProject(
        source_file="t.dxf", source_schema_version="0.7.0", spec_name="test",
        floors=[floor],
        levels=[NLevel(id="LV1", index=0, name="01 GROUND LVL.", elevation_mm=0.0, plan_floor_id="L01"),
                NLevel(id="LV2", index=1, name="02 FIRST FLOOR LVL.", elevation_mm=3300.0, plan_floor_id=None)],
        columns=list(columns), beams=list(beams), panels=list(panels))


def _column(**kw):
    base = dict(id="C1", floor_id="L01", stack_id="STK1", mark="C1-300X600", shape="rect",
                center=_pt(1000, 2000), width_mm=300.0, depth_mm=600.0, outline=[],
                mark_position=_pt(1000, 2000))
    base.update(kw)
    return NColumn(**base)


def _beam(**kw):
    base = dict(id="B1", floor_id="L01", run_id="R1", span_index=0, mark="B1-300X600",
                start=_pt(0, 0), end=_pt(6000, 0), length_mm=6000.0, width_mm=300.0, depth_mm=600.0,
                angle_deg=0.0, outline=[], mark_position=_pt(3000, 0))
    base.update(kw)
    return NBeam(**base)


# ---------------------------------------------------------------- wall-like legs
def test_wall_like_leg_is_a_column_by_default():
    """A leg is a column in the drawing and in the schedule, so that is what it is by default."""
    plan = build_plan(_model(columns=[_column(wall_like=True, width_mm=3300.0, depth_mm=200.0)]), RevitMapping())
    assert [a.kind for a in plan.actions] == ["column"]
    assert plan.actions[0].family == "CH-Concrete-Rectangular-Column"
    assert plan.actions[0].type_name == "CH-3300 X 200"


def test_wall_like_leg_becomes_a_wall_when_asked():
    col = _column(wall_like=True, width_mm=3300.0, depth_mm=200.0, center=_pt(1000, 2000))
    plan = build_plan(_model(columns=[col]), RevitMapping(wall_like_as="wall"))
    (a,) = plan.actions
    assert a.kind == "wall" and a.category == "Walls"
    assert a.type_name == "CH-SHEAR-WALL-200" and a.thickness_mm == 200.0
    # the wall runs along the leg's longer side, centred on it
    assert a.start == [1000 - 1650, 2000] and a.end == [1000 + 1650, 2000]
    assert a.mark == "C1-300X600"


def test_a_wall_runs_along_the_long_side_whichever_axis_that_is():
    col = _column(wall_like=True, width_mm=200.0, depth_mm=3300.0, center=_pt(0, 0))
    (a,) = build_plan(_model(columns=[col]), RevitMapping(wall_like_as="wall")).actions
    assert a.start == pytest.approx([0, -1650], abs=1e-6)
    assert a.end == pytest.approx([0, 1650], abs=1e-6)
    assert a.thickness_mm == 200.0


def test_a_thin_leg_can_be_kept_as_a_column():
    cols = [_column(id="C1", wall_like=True, width_mm=3300.0, depth_mm=150.0),
            _column(id="C2", wall_like=True, width_mm=3300.0, depth_mm=300.0)]
    plan = build_plan(_model(columns=cols), RevitMapping(wall_like_as="wall", wall_like_min_thickness_mm=200.0))
    assert sorted(a.kind for a in plan.actions) == ["column", "wall"]


# ---------------------------------------------------------------- two-depth beams
def test_a_two_depth_beam_uses_the_stepped_family():
    (a,) = build_plan(_model(beams=[_beam(depth_mm=900.0, depth_alt_mm=600.0)]), RevitMapping()).actions
    assert a.family == "CH-Concrete-Step-Beam-Bottom"
    assert a.type_name == "CH-300 X 900/600"
    assert a.params == {"W": 300.0, "H": 900.0, "H1": 600.0}


def test_an_inverted_two_depth_beam_steps_the_other_way():
    (a,) = build_plan(_model(beams=[_beam(depth_mm=900.0, depth_alt_mm=600.0, inverted=True)]), RevitMapping()).actions
    assert a.family == "CH-Concrete-Step-Beam-Top"


def test_a_tapered_cantilever_uses_the_tapered_family():
    (a,) = build_plan(_model(beams=[_beam(depth_mm=900.0, depth_tip_mm=600.0, cantilever=True)]), RevitMapping()).actions
    assert a.family == "CH-Concrete-Tapered-Beam-Bottom"
    assert a.type_name == "CH-300 X 900/600"


def test_one_depth_beam_stays_rectangular():
    (a,) = build_plan(_model(beams=[_beam()]), RevitMapping()).actions
    assert a.family == "CH-Concrete-Rectangular-Beam"
    assert a.params == {"b": 300.0, "h": 600.0}


def test_a_second_depth_equal_to_the_first_is_not_a_step():
    (a,) = build_plan(_model(beams=[_beam(depth_mm=600.0, depth_alt_mm=600.0)]), RevitMapping()).actions
    assert a.family == "CH-Concrete-Rectangular-Beam"


# ---------------------------------------------------------------- system types
def test_a_floor_action_carries_the_thickness_its_type_needs():
    """A duplicated floor type keeps the thickness it was copied from unless it is told."""
    panel = NPanel(id="P1", floor_id="L01", mark="S1-175THK", kind="slab", thickness_mm=175.0,
                   outline=[_pt(0, 0), _pt(5000, 0), _pt(5000, 4000), _pt(0, 4000)],
                   centroid=_pt(2500, 2000), area_m2=20.0, mark_position=_pt(2500, 2000))
    (a,) = [x for x in build_plan(_model(panels=[panel]), RevitMapping()).actions if x.kind == "floor"]
    assert a.type_name == "175 THK. RCC SLAB"
    assert a.thickness_mm == 175.0
    assert a.base_type == "150 THK. RCC SLAB"


# ---------------------------------------------------------------- template check
def test_check_separates_types_the_template_has_from_types_it_must_make():
    model = _model(columns=[_column(width_mm=300.0, depth_mm=600.0),            # T-300 X 600 exists
                            _column(id="C2", width_mm=450.0, depth_mm=750.0)])   # T-450 X 750 does not
    mapping = _mini_mapping()
    plan = build_plan(model, mapping)
    check = check_against_template(plan, mapping, parse_template_md(MINI))
    by_name = {t.type_name: t for t in check.types}
    assert by_name["T-300 X 600"].exists and not by_name["T-300 X 600"].will_create
    assert by_name["T-450 X 750"].will_create and not by_name["T-450 X 750"].exists
    assert by_name["T-450 X 750"].base_type == "T-300 X 600"
    assert check.missing_families == []


def test_check_names_a_family_the_template_does_not_have():
    mapping = _mini_mapping()
    mapping.column.family = "M_Concrete-Rectangular-Column"     # an Autodesk sample, not this template
    plan = build_plan(_model(columns=[_column()]), mapping)
    check = check_against_template(plan, mapping, parse_template_md(MINI))
    assert check.missing_families == ["M_Concrete-Rectangular-Column"]
    assert not check.types[0].will_create      # a type cannot be duplicated inside a family that is absent


def test_check_tells_an_unbound_name_from_one_that_exists_nowhere():
    """The two have different fixes, so the report must not call them the same thing."""
    from c2b.revit.template import SharedParam

    mapping = _mini_mapping(mark_params=["BOUND_EVERYWHERE", "DEFINED_NOT_BOUND", "NOT_A_PARAM", "Mark"],
                            id_params=["A_PROJECT_PARAM"])
    shared = {"DEFINED_NOT_BOUND": SharedParam(guid="g", name="DEFINED_NOT_BOUND", data_type="TEXT", group="x")}
    plan = build_plan(_model(columns=[_column()]), mapping)
    check = check_against_template(plan, mapping, parse_template_md(MINI), shared)
    by_name = {p.name: p for p in check.params}
    assert by_name["BOUND_EVERYWHERE"].bound and by_name["BOUND_EVERYWHERE"].survives
    assert by_name["A_PROJECT_PARAM"].survives              # a project parameter binds too
    # defined by the firm, not bound by the template: bind it
    assert by_name["DEFINED_NOT_BOUND"].defined and not by_name["DEFINED_NOT_BOUND"].bound
    assert "not bound in the template" in by_name["DEFINED_NOT_BOUND"].advice
    # nothing anywhere carries this one: take it out of the mapping
    assert not by_name["NOT_A_PARAM"].defined and not by_name["NOT_A_PARAM"].bound
    assert "remove it from the mapping" in by_name["NOT_A_PARAM"].advice
    # a Revit built-in is always there, whatever the template binds
    assert by_name["Mark"].builtin and by_name["Mark"].survives
    assert by_name["Comments"].builtin and by_name["Comments"].survives


def test_check_flags_a_wall_leg_modelled_as_a_column():
    """It is what the firm asked for, and it is still worth seeing before Revit makes the type."""
    mapping = _mini_mapping()
    plan = build_plan(_model(columns=[_column(wall_like=True, width_mm=12300.0, depth_mm=300.0)]), mapping)
    check = check_against_template(plan, mapping, parse_template_md(MINI))
    (t,) = check.types
    assert t.note and "wall leg modelled as a column" in t.note
    assert check.summary()["types_to_look_at"] == 1


def test_check_lists_the_levels_that_do_not_exist_yet():
    mapping = _mini_mapping()
    plan = build_plan(_model(columns=[_column()]), mapping)
    check = check_against_template(plan, mapping, parse_template_md(MINI))
    assert check.new_levels == []                    # both level names are in the fixture
    plan.levels[0].name = "00 BASEMENT LVL."
    check = check_against_template(plan, mapping, parse_template_md(MINI))
    assert check.new_levels == ["00 BASEMENT LVL."]


# ---------------------------------------------------------------- the Revit-side script
@pytest.mark.skipif(not SCRIPT.exists(), reason="the pyRevit extension is not in this checkout")
def test_every_created_element_is_stamped():
    """A mark written to one parameter name only was how the wall legs lost theirs."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    stamped = {node.args[0].id for node in ast.walk(tree)
               if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "stamp"
               and node.args and isinstance(node.args[0], ast.Name)}
    assert {"inst", "floor", "wall"} <= stamped, f"something is created without a mark: {stamped}"
    # the old single-parameter write must not come back
    assert "ALL_MODEL_MARK" not in SCRIPT.read_text(encoding="utf-8")


@pytest.mark.skipif(not SCRIPT.exists(), reason="the pyRevit extension is not in this checkout")
def test_a_duplicated_system_type_is_given_its_thickness():
    """Without this a type named 175 THK. RCC SLAB is 150 thick, and nothing says so."""
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "set_structure_thickness" in names
    ensure = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "ensure_system_type")
    called = {getattr(c.func, "id", "") for c in ast.walk(ensure) if isinstance(c, ast.Call)}
    assert "set_structure_thickness" in called
