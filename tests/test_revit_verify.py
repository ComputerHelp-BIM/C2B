"""Utility 5, step 2: what Revit built, against what the plan asked for.

The comparison is between two files -- the build plan, and an *Extract Template* description of
the project after the import -- so all of it can be tested without Revit.
"""

from pathlib import Path

import pytest

from c2b.revit.plan import RevitAction, RevitLevel, RevitPlan
from c2b.revit.template import parse_template_md
from c2b.revit.verify import verify_after_import, write_import_report


def _plan() -> RevitPlan:
    plan = RevitPlan(source_file="t.dxf", mapping_name="test")
    plan.levels = [RevitLevel(id="LV1", name="01 GROUND LVL.", elevation_mm=0.0),
                   RevitLevel(id="LV2", name="02 FIRST FLOOR LVL.", elevation_mm=3300.0)]
    plan.actions = [
        RevitAction(id="C1", kind="column", category="Structural Columns",
                    family="Test-Rectangular-Column", type_name="T-300 X 600",
                    params={"b": 300.0, "h": 600.0}, level_id="LV1"),
        RevitAction(id="C2", kind="column", category="Structural Columns",
                    family="Test-Rectangular-Column", type_name="T-400 X 400",
                    params={"b": 400.0, "h": 400.0}, level_id="LV1"),
        RevitAction(id="P1", kind="floor", category="Floors", type_name="175 THK. TEST SLAB",
                    base_type="150 THK. TEST SLAB", thickness_mm=175.0, level_id="LV1"),
        RevitAction(id="G1", kind="grid", category="Grids", mark="1"),
        RevitAction(id="G2", kind="grid", category="Grids", mark="A"),
    ]
    plan.recount()
    return plan


def _built(tmp_path: Path, *, columns=2, floors=1, slab_thickness=175.0,
           slab_type="175 THK. TEST SLAB", grids=("1", "A"), first_floor_mm=3300.0) -> Path:
    """An Extract Template description of a project, written the way the firm's tool writes one."""
    grid_rows = "\n".join(f"| `{g}` | 0, 0 | 1, 1 |" for g in grids)
    path = tmp_path / "built.md"
    path.write_text(f"""# BUILT_PROJECT

- **File** — `D:\\jobs\\BUILT.rvt`

## Datum

### Levels

| Name | Elevation (mm) |
| --- | ---: |
| `01 GROUND LVL.` | 0 |
| `02 FIRST FLOOR LVL.` | {first_floor_mm:.0f} |

### Grids

| Name | From | To |
| --- | --- | --- |
{grid_rows}

## Categories

| Category | Types | Instances |
| --- | ---: | ---: |
| Floors | 2 | {floors} |
| Grids | 1 | {len(grids)} |
| Levels | 1 | 2 |
| Structural Columns | 2 | {columns} |

## Families and types

### Structural Columns

- **Test-Rectangular-Column** _(loadable)_
  - `T-300 X 600` — b 300.000, h 600.000
  - `T-400 X 400` — b 400.000, h 400.000

### Floors

- **Floor** _(system)_
  - `150 THK. TEST SLAB` — Default Thickness 150.000
  - `{slab_type}` — Default Thickness {slab_thickness:.3f}
""", encoding="utf-8")
    return path


def test_a_clean_import_reports_nothing_wrong(tmp_path):
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path)))
    assert check.problems() == []
    assert check.summary()["not as planned"] == 0
    assert check.model_name == "BUILT_PROJECT"


def test_elements_that_failed_quietly_are_counted(tmp_path):
    """Revit creating 2 of 3 columns and saying nothing is the failure this exists to catch."""
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, columns=1)))
    (row,) = [r for r in check.problems() if r.what == "Structural Columns"]
    assert row.planned == "2" and row.found == "1"
    assert "1 missing" in row.note


def test_a_duplicated_type_that_kept_the_wrong_size_is_caught(tmp_path):
    """A 175 THK. TEST SLAB that is 150 thick looks entirely normal in the project browser."""
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, slab_thickness=150.0)))
    (row,) = [r for r in check.problems() if r.kind == "type"]
    assert row.what == "Floor / 175 THK. TEST SLAB"
    assert row.planned == "Default Thickness 175" and row.found == "Default Thickness 150"
    assert "every element of this type is the wrong size" in row.note


def test_a_type_that_was_never_created_is_caught(tmp_path):
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, slab_type="SOMETHING ELSE")))
    (row,) = [r for r in check.problems() if r.kind == "type"]
    assert row.found == "missing" and "never created" in row.note


def test_a_missing_grid_is_named(tmp_path):
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, grids=("1",))))
    (row,) = [r for r in check.problems() if r.kind == "grid"]
    assert row.planned == "2" and row.found == "1" and "missing: A" in row.note


def test_a_level_that_already_existed_at_another_height_is_caught(tmp_path):
    """The import keeps an existing level, so everything on it is built at the wrong elevation."""
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, first_floor_mm=3000.0)))
    (row,) = [r for r in check.problems() if r.kind == "level"]
    assert row.what == "02 FIRST FLOOR LVL."
    assert row.planned == "3300 mm" and row.found == "3000 mm"


def test_more_than_planned_is_reported_but_is_not_a_failure(tmp_path):
    """Importing into a project that already held elements is legitimate, and worth saying."""
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, columns=5)))
    (row,) = [r for r in check.rows if r.what == "Structural Columns"]
    assert row.ok and "3 more than planned" in row.note


def test_the_report_names_the_problems(tmp_path):
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, columns=1, slab_thickness=150.0)))
    text = write_import_report(check, tmp_path / "check.md")
    assert "## What is not as planned" in text
    assert "Structural Columns" in text and "Floor / 175 THK. TEST SLAB" in text
    assert (tmp_path / "check.md").exists()


@pytest.mark.parametrize("thickness", [175.0, 175.4, 174.6])
def test_three_decimals_of_rounding_are_not_a_difference(tmp_path, thickness):
    check = verify_after_import(_plan(), parse_template_md(_built(tmp_path, slab_thickness=thickness)))
    assert [r for r in check.problems() if r.kind == "type"] == []
