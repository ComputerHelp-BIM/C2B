"""Reading the firm's Revit template description, and the parameter names it really binds.

The template is a binary `.rvt`, so what is read here is the markdown its *Extract Template*
tool writes. These tests pin the two things a wrong answer would cost most: the family and
type names the plan has to match exactly, and which parameter names actually survive a write.
"""

from pathlib import Path

import pytest

from c2b.revit.template import parse_shared_parameters, parse_template_md

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
TEMPLATE_MD = TEMPLATES / "R25_TEMPLATE.template.md"
SHARED_TXT = TEMPLATES / "CH-shared-parameters.txt"

pytestmark = pytest.mark.skipif(not TEMPLATE_MD.exists(), reason="the firm's template description is not in this checkout")


@pytest.fixture(scope="module")
def digest():
    return parse_template_md(TEMPLATE_MD)


def test_reads_the_header(digest):
    assert digest.name == "R25_TEMPLATE"
    assert digest.source_file.endswith("R25_TEMPLATE.rvt")
    assert digest.survey_offset_mm == 100000.0


def test_datum(digest):
    assert [lv.name for lv in digest.levels] == ["01 GROUND LVL.", "02 FIRST FLOOR LVL."]
    assert digest.levels[1].elevation_mm == 3300.0
    assert digest.grid_names == ["1", "2", "3", "A", "B", "C", "D", "E"]


def test_structural_families_and_their_driving_dimensions(digest):
    col = digest.family("CH-Concrete-Rectangular-Column")
    assert col is not None and col.category == "Structural Columns" and not col.system
    assert "CH-300 X 600" in col.type_names()
    assert col.types[0].params == {"b": 300.0, "h": 600.0}
    # b and h come from the <details> parameter table, not from the type line
    assert {"b", "h"} <= col.param_names and {"b", "h"} <= col.writable

    beam = digest.family("CH-Concrete-Rectangular-Beam")
    assert beam is not None and beam.category == "Structural Framing"
    assert {"b", "h"} <= beam.writable

    # a stepped beam is driven by W / H / H1, which is what a two-depth mark maps onto
    step = digest.family("CH-Concrete-Step-Beam-Bottom")
    assert step is not None and {"W", "H", "H1"} <= step.writable
    assert "CH-200 X 450/700" in step.type_names()


def test_system_families(digest):
    floor = digest.family("Floor")
    assert floor is not None and floor.system
    assert {"125 THK. RCC SLAB", "150 THK. RCC SLAB", "200 THK. RCC SLAB"} <= floor.type_names()
    assert floor.types[0].params == {"Default Thickness": 125.0}

    wall = digest.family("Basic Wall")
    assert wall is not None and "CH-SHEAR-WALL-300" in wall.type_names()

    footing = digest.family("CH-Concrete-Rectangular-Footing")
    assert footing is not None and {"Width", "Length", "Foundation Thickness"} <= footing.writable


def test_the_template_binds_its_own_names_not_the_ch_ones(digest):
    """The one mistake that cannot be seen in the finished model: a write nobody kept."""
    assert digest.binds("ID", "Structural Columns")
    assert digest.binds("S_ScheduleMark", "Structural Framing")
    assert not digest.binds("CH-ID", "Structural Columns")
    assert not digest.binds("CH-ScheduleMark", "Structural Columns")
    # bound, but only to the categories listed for it
    assert digest.binds("Occupant", "Rooms")
    assert not digest.binds("Occupant", "Structural Columns")


def test_counts_are_plausible(digest):
    c = digest.counts()
    assert c["families"] > 200 and c["types"] > 500 and c["bound_params"] >= 10


def test_unknown_family_is_not_invented(digest):
    assert digest.family("M_Concrete-Rectangular-Column") is None
    assert not digest.has_type("CH-Concrete-Rectangular-Column", "CH-999 X 999")


@pytest.mark.skipif(not SHARED_TXT.exists(), reason="the shared parameter file is not in this checkout")
def test_shared_parameter_file_defines_the_ch_names():
    """Defined and bound are different states, and the fix for each is different."""
    shared = parse_shared_parameters(SHARED_TXT)
    assert len(shared) > 50
    assert shared["CH-ScheduleMark"].data_type == "TEXT"
    assert shared["CH-ScheduleMark"].group == "PROJECT SPECIFIC"
    assert shared["W"].data_type == "LENGTH" and shared["W"].group == "DIM"
    # the names the template does bind are not in this file: they come from another one
    assert "S_ScheduleMark" not in shared
    assert "ID" not in shared
