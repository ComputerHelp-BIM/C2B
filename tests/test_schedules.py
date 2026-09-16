from c2b.diagnostics import DiagnosticsCollector
from c2b.dxfio import Prim
from c2b.schedules import ScheduleIndex, parse_schedules
from shapely.geometry import Point


def _t(text, x, y, h=250):
    return Prim("text", "G-ANNO-SCHD", f"h{x}{y}", Point(x, y), text=text, text_height=h, text_center=(x, y))


def test_classic_grid_schedule():
    texts = [_t("Structural Column Schedule", 0, 600), _t("Mark", 0, 0), _t("b", 3000, 0), _t("h", 5500, 0),
             _t("C1", 0, -600), _t("300", 3000, -600), _t("450", 5500, -600),
             _t("C2", 0, -1200), _t("400", 3000, -1200), _t("600", 5500, -1200),
             _t("Footing Schedule", 12000, 600), _t("Mark", 12000, 0), _t("b", 15000, 0), _t("h", 17500, 0), _t("Thk", 20000, 0),
             _t("F1", 12000, -600), _t("1500", 15000, -600), _t("1500", 17500, -600), _t("450", 20000, -600)]
    tables = parse_schedules(texts, DiagnosticsCollector())
    assert len(tables) == 2
    idx = ScheduleIndex(tables)
    assert idx.find("C2", "column") == {"mark": "C2", "width": 400.0, "depth": 600.0}
    assert idx.find("F1")["thickness"] == 450.0
    assert idx.find("C9") is None


def test_size_to_marks_list():
    texts = [_t("SCHEDULE OF RCC BEAM SIZES", 1000, 800), _t("BEAM SIZE", 0, 0), _t("BEAM NO.", 4000, 0),
             _t("200X650", 0, -600), _t("B1,BK1", 4000, -600), _t("300X650", 0, -1200), _t("B2", 4000, -1200)]
    tables = parse_schedules(texts, DiagnosticsCollector())
    assert len(tables) == 1 and tables[0].category == "beam"
    idx = ScheduleIndex(tables)
    assert idx.find("BK1")["width"] == 200 and idx.find("B2")["depth"] == 650


def test_size_list_keeps_a_symbolic_depth():
    """Test17's beam schedule has nine rows; two state a rule instead of a depth.

    Dropping them left SB and B2 with no schedule entry at all -- 414 of that drawing's 575
    depth-less beams. The width is still real and the rule has to survive to be resolved later.
    """
    from c2b.schedules import _build_table

    table = _build_table("SCH01", "SCHEDULE OF RCC BEAM SIZES", ["mark", "width", "depth", "depth_rule"], [
        {"mark": "B1", "width": 200.0, "depth": 650.0, "size": "200X650"},
        {"mark": "SB", "width": 300.0, "depth": None, "size": "300XSLB THK.", "depth_rule": "slab_thickness"},
        {"mark": "B2", "width": 200.0, "depth": None, "size": "200XAS/LAYOUT", "depth_rule": "layout"},
    ], "G-ANNO-SCHD")

    assert [r["mark"] for r in table.rows] == ["B1", "SB", "B2"]
    sb = table.lookup["SB"]
    assert sb["width"] == 300.0 and sb["depth"] is None and sb["depth_rule"] == "slab_thickness"
    assert table.lookup["B2"]["depth_rule"] == "layout"
    assert "depth_rule" not in table.lookup["B1"]      # an ordinary row is untouched
