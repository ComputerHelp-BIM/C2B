"""Reading a Revit template description, and the parameter names it really binds.

The parsing rules are pinned against `tests/data/mini-template.md`, written by hand. The
firm's own template changes whenever they edit it -- they moved the mark parameters to the
`CH-` names after the first Revit run -- so asserting its contents here would turn every
template edit into a failing test. The real file gets a smoke test instead: it parses, and it
still holds the families the mapping names.
"""

from pathlib import Path

import pytest

from c2b.revit.template import parse_shared_parameters, parse_template_md

TESTS = Path(__file__).resolve().parent
MINI = TESTS / "data" / "mini-template.md"
TEMPLATES = TESTS.parent / "templates"
TEMPLATE_MD = TEMPLATES / "R25_TEMPLATE.template.md"
SHARED_TXT = TEMPLATES / "CH-shared-parameters.txt"


@pytest.fixture(scope="module")
def mini():
    return parse_template_md(MINI)


# ------------------------------------------------------------------ the parsing rules
def test_header(mini):
    assert mini.name == "MINI_TEMPLATE"
    assert mini.source_file.endswith("MINI.rvt")
    assert mini.survey_offset_mm == 50000.0


def test_datum(mini):
    assert [lv.name for lv in mini.levels] == ["01 GROUND LVL.", "02 FIRST FLOOR LVL."]
    assert mini.levels[1].elevation_mm == 3300.0
    assert mini.grid_names == ["1", "A"]


def test_families_types_and_their_dimensions(mini):
    col = mini.family("Test-Rectangular-Column")
    assert col is not None and col.category == "Structural Columns" and not col.system
    assert col.type_names() == {"T-300 X 600", "T-400 X 400"}
    assert col.types[0].params == {"b": 300.0, "h": 600.0}

    floor = mini.family("Floor")
    assert floor is not None and floor.system
    assert floor.types[0].params == {"Default Thickness": 150.0}   # a name with a space in it

    step = mini.family("Test-Step-Beam-Bottom")
    assert step is not None and step.types[0].params == {}         # a type line with no dimensions


def test_family_parameters_come_from_the_details_blocks(mini):
    col = mini.family("Test-Rectangular-Column")
    assert {"b", "h", "Type Name", "Type Mark"} == col.param_names
    assert col.writable == {"b", "h", "Type Mark"}                 # Type Name is read-only
    assert mini.family("Test-Step-Beam-Bottom").writable == {"W", "H", "H1"}


def test_binding_is_per_category(mini):
    """A parameter only survives on the categories it is bound to."""
    assert mini.binds("BOUND_EVERYWHERE", "Structural Columns")
    assert mini.binds("BOUND_ON_ROOMS_ONLY", "Rooms")
    assert not mini.binds("BOUND_ON_ROOMS_ONLY", "Structural Columns")
    assert mini.binds("A_PROJECT_PARAM", "Structural Columns")     # project parameters count too
    assert not mini.binds("NEVER_HEARD_OF_IT")


def test_nothing_is_invented(mini):
    assert mini.family("No-Such-Family") is None
    assert not mini.has_type("Test-Rectangular-Column", "T-999 X 999")


# ------------------------------------------------------------------ the firm's own template
@pytest.mark.skipif(not TEMPLATE_MD.exists(), reason="the firm's template description is not in this checkout")
def test_the_real_template_still_holds_what_the_mapping_names():
    """A smoke test: it must not assert *values* the firm is free to change."""
    from c2b.revit.mapping import RevitMapping

    digest = parse_template_md(TEMPLATE_MD)
    counts = digest.counts()
    assert counts["families"] > 100 and counts["types"] > 300
    mapping = RevitMapping()
    for name, rule in list(mapping.loadable_rules().items()) + list(mapping.system_rules().items()):
        if rule.family:
            assert digest.family(rule.family) is not None, f"mapping.{name} names a family the template has not got"


@pytest.mark.skipif(not SHARED_TXT.exists(), reason="the shared parameter file is not in this checkout")
def test_shared_parameter_file():
    """Defined and bound are different states, and the fix for each is different."""
    shared = parse_shared_parameters(SHARED_TXT)
    assert len(shared) > 50
    assert shared["CH-ScheduleMark"].data_type == "TEXT"
    assert shared["CH-ScheduleMark"].group == "PROJECT SPECIFIC"
    assert shared["W"].data_type == "LENGTH" and shared["W"].group == "DIM"


def test_a_shared_parameter_file_is_read_whatever_its_encoding(tmp_path):
    """Revit writes UTF-16; a file round-tripped through an editor can come back UTF-8."""
    body = ("# This is a Revit shared parameter file.\n"
            "*GROUP\tID\tNAME\n"
            "GROUP\t1\tPROJECT SPECIFIC\n"
            "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\n"
            "PARAM\t165d1f09-9af8-4bf8-bdf7-72387493165a\tCH-ID\tTEXT\t\t1\t1\n")
    for name, encoding in (("u16.txt", "utf-16"), ("u8.txt", "utf-8"), ("u8bom.txt", "utf-8-sig")):
        path = tmp_path / name
        path.write_bytes(body.encode(encoding))
        params = parse_shared_parameters(path)
        assert params["CH-ID"].group == "PROJECT SPECIFIC", name
