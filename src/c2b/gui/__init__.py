"""Desktop window for drafters: pick a drawing, press Run, read the issues.

``tkinter`` is imported only when the window is opened, so the rest of C2B works on machines
without a display toolkit (it ships with Python on Windows and macOS; on Linux install
``python3-tk``).
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["main", "run_gui"]


def run_gui(drawing: str | Path | None = None) -> int:
    try:
        from .app import run_gui as _run
    except ImportError as ex:
        print(f"The C2B window needs tkinter, which is not installed ({ex}).\n"
              f"Windows and macOS: reinstall Python from python.org (tkinter is included).\n"
              f"Linux: sudo apt install python3-tk\n"
              f"Meanwhile use the command line:  c2b run <drawing>")
        return 2
    return _run(drawing)


def main() -> int:
    import sys
    return run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
