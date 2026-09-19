"""The C2B window: pick a drawing, press Run, read what needs checking.

There are two of it. The **WPF** window is the one the firm ships -- branded, and the same
toolkit as the storey editor and the pyRevit side. The **Tkinter** one is what opens where WPF
cannot: a machine without pythonnet, or one that is not Windows.

They share :mod:`c2b.gui.session`, so the fields, what is remembered, how a run is assembled
and what the footer says are one implementation with two faces rather than two that drift.

**Which one opened is never a silent fact.** ``windows\\C2B.bat`` starts C2B with
``pythonw.exe``, which has no console, so a message printed here reaches nobody -- for three
releases the plain window opened because pythonnet was missing and nothing anywhere said so.
The reason is written to :data:`LOG_FILE` and shown on the window itself.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["LOG_FILE", "main", "run_gui", "toolkit", "why_plain"]

#: Where a window that would not open says why. Somewhere a person can be pointed at, because
#: the launcher has no console to print to.
LOG_FILE = Path.home() / ".c2b" / "window.log"

#: Filled in by :func:`run_gui` when the plain window opens, so the window itself can say why.
_WHY_PLAIN: str = ""


def why_plain() -> str:
    """Why the plain window opened instead of the branded one, or an empty string."""
    return _WHY_PLAIN


def toolkit() -> str:
    """Which window ``run_gui`` would open: ``"wpf"`` or ``"tk"``."""
    from ..ui import wpf

    return "wpf" if wpf.available() else "tk"


def _note(message: str) -> None:
    """Say it on the console *and* in the log, because the launcher has neither."""
    global _WHY_PLAIN
    _WHY_PLAIN = message.strip()
    print(message)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} ---\n{message}\n")
    except Exception:
        pass                                  # a log that cannot be written must not stop a run


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
        except Exception as ex:
            import traceback

            _note(f"The branded window would not open, so the plain one did.\n"
                  f"  {type(ex).__name__}: {ex}\n"
                  f"{traceback.format_exc()}"
                  f"Please send the lines above to whoever maintains C2B.")
    else:
        _note(f"The branded window is not available on this machine, so the plain one opened.\n"
              f"  {wpf.why_not()}\n"
              f"Fix it with:   .venv\\Scripts\\pip install pythonnet\n"
              f"then start C2B again.")

    try:
        from .app import run_gui as _run
    except ImportError as ex:
        _note(f"The C2B window needs either pythonnet (for the branded window) or tkinter, and\n"
              f"this machine has neither.\n"
              f"  WPF:     {wpf.why_not()}\n"
              f"  tkinter: {ex}\n"
              f"Windows and macOS: reinstall Python from python.org (tkinter is included).\n"
              f"Linux: sudo apt install python3-tk\n"
              f"Meanwhile use the command line:  c2b run <drawing>")
        return 2
    return _run(drawing)


def main() -> int:
    import sys

    return run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
