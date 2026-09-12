from __future__ import annotations

import json
from pathlib import Path

from ..schema import Project


def write_json(project: Project, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(project.model_dump_json(indent=2, exclude_none=False), encoding="utf-8")
    return path


def read_json(path: str | Path) -> Project:
    return Project.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
