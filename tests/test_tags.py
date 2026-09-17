import pytest

from c2b.tags import clean_text, parse_length_mm, parse_size_from_name, parse_tag


@pytest.mark.parametrize("text,expected", [
    ("300", 300.0), ("300mm", 300.0), ("0.3m", 300.0), ("30cm", 300.0),
    ("12\"", 304.8), ("1'-6\"", 457.2), ("1'6", 457.2), ("2' 0 1/2\"", 622.3), ("18in", 457.2), ("3ft", 914.4),
    ("abc", None), ("", None),
])
def test_parse_length(text, expected):
    got = parse_length_mm(text)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected, abs=0.1)


def test_column_size_tag():
    t = parse_tag("C_300 X 900")
    assert (t.width_mm, t.depth_mm) == (300, 900)
    assert t.mark is None and t.category_hint == "column"


def test_beam_with_mark_and_variable_depth():
    t = parse_tag("B6 (200X900/600)")
    assert t.mark == "B6" and t.width_mm == 200 and t.depth_mm == 900 and t.depth_alt_mm == 600
    assert t.category_hint == "beam"


def test_inverted_and_marks():
    assert parse_tag("B6(INV.)").inverted is True
    assert parse_tag("MB").mark == "MB"
    assert parse_tag("T1SW125a").mark == "T1SW125a"
    assert parse_tag("BK1").category_hint == "beam"


def test_footing_thickness_and_fold():
    t = parse_tag("F3_750MM THK\\P1500MM FOLD")
    assert t.mark == "F3" and t.thickness_mm == 750 and t.fold_mm == 1500 and t.category_hint == "footing"


def test_slab_thickness_variants():
    assert parse_tag("150 THK.").thickness_mm == 150
    assert parse_tag("150THK.\nSLAB").thickness_mm == 150
    assert parse_tag("%%U150THK").thickness_mm == 150


def test_circular_column():
    t = parse_tag("C_600D")
    assert t.diameter_mm == 600 and t.category_hint == "column"


def test_imperial_size():
    t = parse_tag("1'-0\" x 2'-0\"")
    assert t.width_mm == pytest.approx(304.8) and t.depth_mm == pytest.approx(609.6)


def test_note_defaults():
    assert parse_tag("NOTE - 1) ALL BEAMS ARE 750MM IN DEPTH U.N.O.").note_default == ("beam", 750)
    assert parse_tag("2) ALL SALB ARE 125MM  U.N.O.").note_default == ("slab", 125)
    assert parse_tag("%%U* ALL SLABS 150THK. R.C.C. SLAB UNLESS OTHERWISE SPECIFIED.").note_default == ("slab", 150)


def test_sunk():
    assert parse_tag("INDICATES SLAB/BEAM SUNK BY 75MM.").sunk_mm == 75


def test_unparsed():
    assert parse_tag("TUNNEL FORM DIRECTION").unparsed is True
    assert parse_tag("LIFT").unparsed is True


def test_layer_size():
    assert parse_size_from_name("B-200x400") == (200, 400)
    assert parse_size_from_name("500X750") == (500, 750)
    assert parse_size_from_name("E-BSMT-2-COL") is None


def test_clean_text():
    assert clean_text("%%UTHUS MARKED\\PCUT-OUT") == "THUS MARKED\nCUT-OUT"


def test_parse_symbolic_size():
    """A schedule may state a depth no number fits: the rule is carried, not discarded."""
    from c2b.tags import parse_symbolic_size

    assert parse_symbolic_size("300XSLB THK.") == (300.0, "slab_thickness")
    assert parse_symbolic_size("300 X SLAB THK") == (300.0, "slab_thickness")
    assert parse_symbolic_size("200XAS/LAYOUT") == (200.0, "layout")
    assert parse_symbolic_size("200XAS PER LAYOUT") == (200.0, "layout")
    assert parse_symbolic_size("200X650") is None      # an ordinary size; the numeric parser has it
    assert parse_symbolic_size("SB") is None
    assert parse_symbolic_size("") is None


def test_a_mark_is_not_a_diameter():
    """"C_600D" is a 600 dia column; "T1SW136d" is tower 1, shear wall 136, leg d.

    Reading the second as a diameter gave thirteen of Test17's shear wall legs a 136 mm
    diameter, no width and no depth, and dropped every one of them from the Revit model.
    """
    from c2b.tags import parse_tag

    assert parse_tag("C_600D").diameter_mm == 600
    assert parse_tag("900 DIA").diameter_mm == 900
    assert parse_tag("1200D").diameter_mm == 1200
    # the digits run on from the letters, so they belong to the mark
    for mark in ("T1SW136d", "T1SW135a", "T1SW1200d", "B6D"):
        assert parse_tag(mark).diameter_mm is None, mark


def test_a_rectangle_does_not_take_a_tag_diameter():
    """Defence in depth: whatever a tag says, a drawn rectangle is not round."""
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "src" / "c2b" / "extract" / "columns.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tests = [ast.unparse(n.test) for n in ast.walk(tree) if isinstance(n, ast.If)]
    assert any("merged.diameter_mm is not None" in t and "shape != 'rect'" in t for t in tests), \
        "the tag diameter is accepted without checking the drawn shape"
