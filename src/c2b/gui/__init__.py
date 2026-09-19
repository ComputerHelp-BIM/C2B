"""The C2B window: pick a drawing, press Run, read what needs checking.

There are two of it. The **WPF** window is the one the firm ships -- branded, and the same
toolkit as the storey editor and the pyRevit side. The **Tkinter** one is what opens where
WPF cannot: a machine without pythonnet, or one that is not Windows, which is every machine
C2B is developed on.

They share :mod:`c2b.gui.session`, so the fields, what is remembered, how a run is assembled
and what the footer says are one implementation with two faces rather than two that drift.

Neither toolkit is imported until a window is actually opened, so the rest of C2B works on a
machine with neither.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["main", "run_gui", "toolkit"]


def toolkit() -> str:
    """Which window ``run_gui`` would open: ``"wpf"`` or ``"tk"``."""
    from ..ui import wpf

    return "wpf" if wpf.available() else "tk"


def run_gui(drawing: str | Path | None = None) -> int:
    """Open the C2B window. WPF where it can be shown, Tkinter where it cannot."""
    from ..ui import wpf

    if wpf.available():
        try:
            from .main_wpf import C2BWindow

            window = C2BWindow()
            if drawing:
                window.inputs["drawing"].Text = str(drawing)
            window.show()
            return 0
        except Exception as ex:                  # a broken WPF is a reason to fall back, not to stop
            # Loudly. The first build of the WPF window threw during construction and this
            # fallback swallowed it, so the branded window simply never appeared and the plain
            # one did -- which looks like the feature was never built rather than like a bug.
            import traceback

            print(f"The WPF window would not open: {type(ex).__name__}: {ex}")
            traceback.print_exc()
            print("Falling back to the plain window. Please report the traceback above.")

    try:
        from .app import run_gui as _run
    except ImportError as ex:
        from ..ui import wpf as _wpf

        print(f"The C2B window needs either pythonnet (for the WPF window) or tkinter, and this\n"
              f"machine has neither.\n"
              f"  WPF:     {_wpf.why_not()}\n"
              f"  tkinter: {ex}\n"
              f"Windows and macOS: reinstall Python from python.org (tkinter is included).\n"
              f"Linux: sudo apt install python3-tk\n"
              f"Meanwhile use the command line:  c2b run <drawing>")
        return 2
    return _run(drawing)


def main() -> int:
    import sys

    return run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
