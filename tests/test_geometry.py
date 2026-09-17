
from shapely.geometry import LineString, Polygon

from c2b.geometry import Segment, classify_polygon, merge_collinear, pair_parallel, polygon_from_points, polygonize_lines, rectangle_polygon


def test_classify_rect_and_rotation():
    s = classify_polygon(Polygon([(0, 0), (300, 0), (300, 900), (0, 900)]))
    assert s.shape == "rect" and (round(s.width), round(s.depth)) == (300, 900) and s.rotation_deg == 0
    r = classify_polygon(rectangle_polygon((0, 0), 300, 900, 30))
    assert r.shape == "rect" and abs(r.rotation_deg - 30) < 1e-6 and (round(r.width), round(r.depth)) == (300, 900)


def test_classify_circle_and_polygon():
    from shapely.geometry import Point
    c = classify_polygon(Point(0, 0).buffer(300, quad_segs=16))
    assert c.shape == "circle" and abs(c.diameter - 600) < 5
    L = Polygon([(0, 0), (1000, 0), (1000, 200), (200, 200), (200, 1000), (0, 1000)])
    assert classify_polygon(L).shape == "polygon"


def test_polygon_from_points_closes_small_gap():
    assert polygon_from_points([(0, 0), (100, 0), (100, 100), (0, 100), (0, 3)], close_tol=5) is not None
    assert polygon_from_points([(0, 0), (100, 0), (100, 100), (0, 100), (0, 30)], close_tol=5) is None


def test_polygonize_lines_closes_drafting_gaps():
    lines = [LineString([(0, 0), (300, 0)]), LineString([(300, 0.4), (300, 450)]), LineString([(300, 450), (0, 450)]), LineString([(0, 450), (0, 0.5)])]
    polys = polygonize_lines(lines, grid_size=1.0)
    assert len(polys) == 1 and abs(polys[0].area - 300 * 450) < 500


def test_merge_collinear_across_gap():
    segs = [Segment((0, 0), (1000, 0), ["a"]), Segment((1300, 0), (2000, 0), ["b"]), Segment((0, 500), (2000, 500), ["c"])]
    merged = merge_collinear(segs, gap_tol=400)
    assert len(merged) == 2
    long = max(merged, key=lambda s: s.length)
    assert long.length == 2000 and sorted(long.handles) in (["a", "b"], ["c"])


def test_pair_parallel_finds_beam():
    segs = [Segment((0, 0), (6000, 0)), Segment((0, 230), (6000, 230)), Segment((0, 3000), (6000, 3000))]
    rects, unpaired = pair_parallel(segs, 100, 1500, 300)
    assert len(rects) == 1 and abs(rects[0].width - 230) < 1e-6 and abs(rects[0].length - 6000) < 1e-6
    assert len(unpaired) == 1
    assert abs(rects[0].start[1] - 115) < 1e-6


def test_pair_parallel_prefers_true_edges():
    # a wall line 230 from the beam edge must not steal the beam's far edge
    segs = [Segment((0, 0), (6000, 0)), Segment((0, 300), (6000, 300)), Segment((2000, 530), (4000, 530))]
    rects, _ = pair_parallel(segs, 100, 1500, 300)
    widths = sorted(round(r.width) for r in rects)
    assert widths[0] == 300
