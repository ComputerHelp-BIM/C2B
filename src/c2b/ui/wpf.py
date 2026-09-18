"""Python drives WPF: loading a branded window from Python, and saying so when it cannot.

C2B's windows are WPF and Python is what drives them, through **pythonnet**. That keeps one
language across the whole tool -- the pipeline, the window and the pyRevit script are the same
Python -- and it keeps the markup declarative in a ``.xaml`` file rather than assembled control
by control in code.

WPF is Windows-only. This module is the single place that knows it, so every caller can ask
:func:`available` and fall back without a try/except around an import. Nothing here is imported
at module scope: importing ``clr`` on a machine without .NET is an error, and a tool that
cannot start on Linux is no use to the people who develop it.
"""
from __future__ import annotations

import sys
from typing import Any

from . import xaml

#: Filled in by :func:`available` so the reason is reported once, not guessed at.
_WHY_NOT: str = ""


def available() -> bool:
    """Whether this machine can show a WPF window.

    Answered by loading the assemblies, not by looking at the platform: a machine can be
    Windows and still be missing pythonnet, and that is the same "no" with a different fix.
    """
    global _WHY_NOT
    if sys.platform != "win32":
        _WHY_NOT = f"WPF needs Windows; this is {sys.platform}"
        return False
    try:
        import clr  # noqa: F401  (pythonnet)
    except Exception as ex:
        _WHY_NOT = f"pythonnet is not installed ({type(ex).__name__}). Install it with: pip install pythonnet"
        return False
    try:
        _load_assemblies()
    except Exception as ex:
        _WHY_NOT = f"the .NET desktop assemblies would not load ({type(ex).__name__}: {ex})"
        return False
    _WHY_NOT = ""
    return True


def why_not() -> str:
    """Why :func:`available` said no, in words worth putting in front of a person."""
    if not _WHY_NOT:
        available()
    return _WHY_NOT


def _load_assemblies() -> None:
    """The four assemblies a WPF window needs, in the order the brand guide gives (§12.1).

    ``XamlReader`` then works identically under CPython 3 and IronPython 2, which is the only
    supported way to build a window and the reason the same code serves the pyRevit side.
    """
    import clr

    for assembly in ("PresentationFramework", "PresentationCore", "WindowsBase", "System.Xaml"):
        clr.AddReference(assembly)


def load_window(name: str) -> Any:
    """Load a layout file, theme and all, and return the WPF ``Window``.

    The theme is generated from the tokens and spliced in before the parse, so the window's
    resources are inline -- which is the only strategy that resolves reliably inside Revit's
    sandbox (§12.7.B) -- without a second copy of the palette existing anywhere.
    """
    _load_assemblies()
    from System.IO import StringReader
    from System.Windows.Markup import XamlReader
    from System.Xml import XmlReader

    return XamlReader.Load(XmlReader.Create(StringReader(xaml.window_xaml(name))))


def find(window: Any, name: str) -> Any:
    """A named control from a loaded window, or a clear failure rather than ``None``.

    ``FindName`` returning ``None`` for a typo shows up later as an ``AttributeError`` on
    something unrelated; this says which control is missing, while the name is still in hand.
    """
    control = window.FindName(name)
    if control is None:
        raise LookupError(f"the window has no control called {name!r}")
    return control


def show_dialog(window: Any, owner_handle: int | None = None) -> bool:
    """Show a window modally and report whether it was accepted.

    ``owner_handle`` is Revit's main window when C2B is running inside it, so the dialog cannot
    end up behind its host (§12.4). Outside Revit there is nothing to own it and it is left
    alone rather than parented to something arbitrary.
    """
    if owner_handle:
        from System.Windows.Interop import WindowInteropHelper

        WindowInteropHelper(window).Owner = owner_handle
    return bool(window.ShowDialog())
