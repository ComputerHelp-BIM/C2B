from c2b.units import guess_units_from_extent, parse_unit_name, resolve_units


def test_insunits_wins():
    r = resolve_units(4, 100.0)
    assert r.scale_to_mm == 1.0 and r.confidence == "high"
    assert resolve_units(6, 100.0).scale_to_mm == 1000.0
    assert resolve_units(1, 100.0).scale_to_mm == 25.4


def test_override_wins():
    assert resolve_units(4, 100.0, override="ft").scale_to_mm == 304.8


def test_heuristic_is_low_confidence():
    r = resolve_units(0, 250000.0)
    assert r.name == "millimetres" and r.confidence == "low"
    assert guess_units_from_extent(120.0).name == "metres"
    assert guess_units_from_extent(120.0, imperial_text_hits=3).name == "feet"
    assert guess_units_from_extent(5000.0).name == "inches"


def test_unknown_unit_name():
    import pytest
    with pytest.raises(ValueError):
        parse_unit_name("furlong")
