"""Shared fixtures. The demo drawing itself lives in ``c2b.demo`` so it ships with the tool."""
from __future__ import annotations

from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


from c2b.demo import build_demo_drawing

@pytest.fixture(scope="session")
def synthetic_dxf(tmp_path_factory) -> Path:
    return build_demo_drawing(tmp_path_factory.mktemp("dxf") / "synthetic.dxf")


@pytest.fixture(scope="session")
def synthetic_result(synthetic_dxf):
    from c2b.pipeline import extract
    return extract(synthetic_dxf)
