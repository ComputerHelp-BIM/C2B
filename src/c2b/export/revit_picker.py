"""The build window's markup, written out for the side of the fence that cannot import C2B.

The pyRevit script runs inside Revit's own engine against the plan file alone -- there is no
C2B on its path and no reason there should be. So the window it shows is generated here,
themed from :mod:`c2b.ui.theme` like every other C2B window, and written next to the plan it
belongs to. The script loads it from there.

One theme, one brand, whichever side the window opens on. The alternative is a second copy of
the palette living inside the Revit extension, which is how two surfaces drift apart.
"""
from __future__ import annotations

from pathlib import Path

#: What the file is called, beside ``<stem>.revit.json``.
SUFFIX = ".revit.xaml"


def picker_path(plan_json: Path) -> Path:
    """Where the window goes for a given plan: the same name, the other extension."""
    return plan_json.with_name(plan_json.name.replace(".revit.json", SUFFIX))


def write_picker_window(plan_json: Path) -> Path:
    """Write the build window beside the plan and return where it went."""
    from ..ui import xaml

    path = picker_path(plan_json)
    path.write_text(xaml.window_xaml("build_picker"), encoding="utf-8")
    return path
