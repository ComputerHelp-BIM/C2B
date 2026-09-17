"""Two structures either side of an expansion joint are two structures.

The joint is 175 mm wide. Beams merge across gaps up to 800 mm, and two 200 mm beams either side
of the joint present their outer faces 575 mm apart -- a perfectly plausible beam width. So the
client's two beams came out as one wrong beam straddling the joint, and the B6s beside it were
replaced by a B1 running through.
"""
from __future__ import annotations

import ezdxf
import pytest
from shapely.geometry import LineString

from c2b.geometry import Segment, merge_collinear, pair_parallel
from c2b.pipeline import extract

JOINT_MM = 175.0


def test_pairing_does_not_reach_over_a_joint():
    """Faces at 0, 200, 375, 575: two beams, not a 575 straddle and a 175 gap."""
    segs = [Segment((0, o), (5000, o), ["h"], "L") for o in (0, 200, 200 + JOINT_MM, 400 + JOINT_MM)]
    assert sorted(round(r.width) for r in pair_parallel(segs, 100, 1500, 300)[0]) == [175, 575]
    joints = [LineString([(0, 200), (5000, 200)]), LineString([(0, 200 + JOINT_MM), (5000, 200 + JOINT_MM)])]
    assert sorted(round(r.width) for r in pair_parallel(segs, 100, 1500, 300, barriers=joints)[0]) == [200, 200]


def test_merging_does_not_run_through_a_joint():
    """Two collinear runs 175 mm apart are two runs, not one."""
    segs = [Segment((0, 0), (1000, 0), ["a"], "L"), Segment((1000 + JOINT_MM, 0), (2175, 0), ["b"], "L")]
    assert len(merge_collinear(segs, gap_tol=800)) == 1
    joint = [LineString([(1000 + JOINT_MM / 2, -500), (1000 + JOINT_MM / 2, 500)])]
    assert len(merge_collinear(segs, gap_tol=800, barriers=joint)) == 2
    # a joint somewhere else changes nothing
    assert len(merge_collinear(segs, gap_tol=800, barriers=[LineString([(9000, -500), (9000, 500)])])) == 1


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    path = tmp_path_factory.mktemp("ej") / "joint.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Boundary", "Origin", "S-BEAM", "EXP JOINT", "G-ANNO-TEXT"):
        doc.layers.add(name)
    msp.add_lwpolyline([(-4000, -4000), (16000, -4000), (16000, 14000), (-4000, 14000)],
                       close=True, dxfattribs={"layer": "Boundary"})
    msp.add_point((0, 0), dxfattribs={"layer": "Origin"})
    msp.add_text("GROUND FLOOR LEVEL", dxfattribs={"layer": "G-ANNO-TEXT", "height": 400}).set_placement((6000, -3000))

    # a beam each side of the joint, running up the page, each 200 wide
    left, right = 5000.0, 5000.0 + 200.0 + JOINT_MM
    for x0 in (left, right):
        for dx in (0.0, 200.0):
            msp.add_line((x0 + dx, 0), (x0 + dx, 9000), dxfattribs={"layer": "S-BEAM"})
    # the joint itself: the two faces of the gap
    for x in (left + 200.0, right):
        msp.add_line((x, 0), (x, 9000), dxfattribs={"layer": "EXP JOINT"})
    doc.saveas(str(path))
    return extract(path).project


def test_the_client_gets_both_beams_not_one_across_the_joint(project):
    assert project.joints, "the expansion joint lines were not recognised"
    beams = project.beams
    assert len(beams) == 2, f"expected the two beams, got {[(b.width_mm, b.drawn_width_mm) for b in beams]}"
    assert all(b.drawn_width_mm == pytest.approx(200, abs=1) for b in beams)
    assert not [b for b in beams if b.drawn_width_mm > 400], "a beam straddles the joint"
