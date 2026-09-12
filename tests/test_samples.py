"""Integration checks on real client drawings placed in samples/ (skipped when absent)."""
from pathlib import Path

import pytest

from tests.conftest import SAMPLES

SAMPLE_FILES = sorted(SAMPLES.glob("*.dxf")) if SAMPLES.exists() else []


@pytest.mark.skipif(not SAMPLE_FILES, reason="no client DXF files in samples/")
@pytest.mark.parametrize("path", SAMPLE_FILES, ids=[p.stem for p in SAMPLE_FILES])
def test_sample_extracts(path: Path):
    from c2b.pipeline import extract

    result = extract(path)
    p = result.project
    assert p.summary.errors == 0
    assert p.summary.floors >= 1
    assert p.summary.columns > 0
    # every column must carry an outline and a floor
    assert all(len(c.outline) >= 3 for c in p.columns)
    # coordinates are floor-local, so no element should be at georeferenced magnitudes
    assert all(abs(c.center.x) < 5e5 and abs(c.center.y) < 5e5 for c in p.columns)
    # beams only when the drawing has beam layers
    if any(e.geometry_role == "BEAM" for e in p.layer_map):
        assert p.summary.beams > 0
