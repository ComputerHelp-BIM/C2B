"""Python drives WPF: loading a branded window from Python, and saying so when it cannot.

C2B's windows are WPF and Python is what drives them, through **pythonnet**. That keeps one
language across the whole tool -- the pipeline, the window and the pyRevit script are the same
Python -- and it keeps the markup declarative in a ``.xaml`` file rather than assembled control
by control in code.

**Getting to WPF is the hard part, and it is two decisions deep.**

pythonnet 3 on Windows loads the **.NET Framework 4.x** CLR unless it is told otherwise, and
there ``Assembly.Load`` with a *partial* name -- which is what ``clr.AddReference("Presentation
Framework")`` does -- never searches the GAC. It fails with ``FileNotFoundException: Could not
load file or assembly 'PresentationFramework'`` on a machine that has WPF installed and
working, which is a message that sends you looking in entirely the wrong place. It cost this
project four releases.

So, in order:

1. **.NET 8 with the Windows Desktop framework**, which is what Revit 2025 runs on and is
   therefore already on a machine that has Revit. WPF is part of that framework, so the
   assemblies resolve by name with nothing special asked of them. ``set_runtime`` has to be
   called before pythonnet loads a CLR, which is why nothing in this module imports ``clr`` at
   the top.
2. **.NET Framework 4.x**, where an assembly is asked for by its *full strong name*, and
   failing that by its path in the GAC. Both of those do find it.

Everything else in C2B asks :func:`available` and falls back to Tkinter. Nothing here is
imported at module scope: importing ``clr`` on a machine without .NET is an error, and a tool
that cannot start on Linux is no use to the people who develop it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import xaml

#: The four assemblies a WPF window needs, in the order the brand guide gives (§12.1), with
#: the public key token each is signed with -- needed for the strong name on .NET Framework.
ASSEMBLIES: tuple[tuple[str, str], ...] = (
    ("PresentationFramework", "31bf3856ad364e35"),
    ("PresentationCore", "31bf3856ad364e35"),
    ("WindowsBase", "31bf3856ad364e35"),
    ("System.Xaml", "b77a5c561934e089"),
)

#: Filled in by :func:`available` so the reason is reported once, not guessed at.
_WHY_NOT: str = ""
#: Which .NET was loaded, for :func:`doctor` to report.
_RUNTIME: str = ""
#: ``set_runtime`` is a one-shot: pythonnet keeps the first CLR it is given.
_RUNTIME_CHOSEN = False


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
        _WHY_NOT = (f"pythonnet is not installed ({type(ex).__name__}). "
                    f"Install it with: pip install pythonnet")
        return False
    try:
        _load_assemblies()
    except Exception as ex:
        _WHY_NOT = str(ex)
        return False
    _WHY_NOT = ""
    return True


def why_not() -> str:
    """Why :func:`available` said no, in one line worth putting in front of a person."""
    if not _WHY_NOT:
        available()
    return _WHY_NOT.splitlines()[0] if _WHY_NOT else ""


def why_not_in_full() -> str:
    """The whole of it, for a log."""
    if not _WHY_NOT:
        available()
    return _WHY_NOT


def runtime() -> str:
    """Which .NET is behind the windows, once one has been loaded."""
    if not _RUNTIME:
        available()
    return _RUNTIME


# ---------------------------------------------------------------------------
# Picking a .NET that has WPF in it
# ---------------------------------------------------------------------------

def desktop_runtimes(root: Path | None = None) -> list[tuple[int, ...]]:
    """Every ``Microsoft.WindowsDesktop.App`` on this machine, newest first.

    This is the framework WPF lives in on modern .NET. Revit 2025 runs on .NET 8, so a machine
    with Revit on it has one.
    """
    import os

    if root is None:
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        root = Path(program_files) / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App"
    if not root.is_dir():
        return []
    found = []
    for entry in root.iterdir():
        parsed = _parse_version(entry.name)
        if entry.is_dir() and parsed:
            found.append(parsed)
    return sorted(found, reverse=True)


def _parse_version(name: str) -> tuple[int, ...] | None:
    """``"8.0.11"`` -> ``(8, 0, 11)``. A preview suffix is dropped rather than refused."""
    parts = name.split("-")[0].split(".")
    try:
        return tuple(int(p) for p in parts[:3]) if parts else None
    except ValueError:
        return None


def runtime_config(version: tuple[int, ...]) -> str:
    """The ``runtimeconfig.json`` that asks for WPF, as text.

    ``rollForward: latestMinor`` so a machine that gets 8.1 tomorrow keeps working without
    this file being regenerated.
    """
    import json

    return json.dumps({"runtimeOptions": {
        "tfm": f"net{version[0]}.0",
        "framework": {"name": "Microsoft.WindowsDesktop.App",
                      "version": ".".join(str(p) for p in version)},
        "rollForward": "latestMinor",
    }}, indent=2)


def _choose_runtime() -> None:
    """Point pythonnet at a .NET that has WPF, before it loads one of its own.

    Silent when it cannot: .NET Framework is the fallback and :func:`_add_reference` knows how
    to find WPF there too.
    """
    global _RUNTIME_CHOSEN, _RUNTIME
    if _RUNTIME_CHOSEN or "clr" in sys.modules:
        return
    _RUNTIME_CHOSEN = True
    versions = desktop_runtimes()
    if not versions:
        _RUNTIME = ".NET Framework (no Microsoft.WindowsDesktop.App installed)"
        return
    newest = versions[0]
    try:
        import tempfile

        from clr_loader import get_coreclr
        from pythonnet import set_runtime

        config = Path(tempfile.gettempdir()) / "c2b-wpf.runtimeconfig.json"
        config.write_text(runtime_config(newest), encoding="utf-8")
        set_runtime(get_coreclr(runtime_config=str(config)))
        _RUNTIME = ".NET " + ".".join(str(p) for p in newest) + " (Windows Desktop)"
    except Exception as ex:
        _RUNTIME = f".NET Framework (could not load .NET {newest[0]}: {type(ex).__name__})"


def _load_assemblies() -> None:
    """Every assembly a WPF window needs, however this .NET wants to be asked."""
    global _RUNTIME
    _choose_runtime()
    import clr

    for name, token in ASSEMBLIES:
        _add_reference(clr, name, token)
    if not _RUNTIME:
        _RUNTIME = ".NET Framework"


def _add_reference(clr: Any, name: str, token: str) -> None:
    """Load one assembly, trying each way a .NET will accept.

    The plain name is all .NET (Core) needs. .NET Framework's ``Assembly.Load`` does not search
    the GAC for a partial name, so it is asked again by strong name, and then by the path the
    assembly actually sits at.
    """
    attempts: list[str] = [
        name,
        f"{name}, Version=4.0.0.0, Culture=neutral, PublicKeyToken={token}",
    ]
    found = gac_path(name, token)
    if found:
        attempts.append(str(found))

    problems = []
    for attempt in attempts:
        try:
            clr.AddReference(attempt)
            return
        except Exception as ex:
            problems.append(f"{attempt.split(',')[0]}: {type(ex).__name__}")
    raise RuntimeError(
        f"{name} would not load, so the branded window cannot open.\n"
        f"  Tried: {'; '.join(problems)}\n"
        f"  WPF needs the .NET Desktop Runtime. Install it from "
        f"https://dotnet.microsoft.com/download/dotnet (the 'Desktop Runtime' download), "
        f"then start C2B again.")


def gac_path(name: str, token: str) -> Path | None:
    """Where .NET Framework keeps this assembly, if it keeps it at all."""
    import os

    root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "assembly" / "GAC_MSIL" / name
    if not root.is_dir():
        return None
    for folder in sorted(root.iterdir(), reverse=True):
        candidate = folder / f"{name}.dll"
        if candidate.is_file() and token in folder.name:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def load_window(name: str) -> Any:
    """Load a layout file, theme and all, and return the WPF ``Window``.

    The theme is generated from the tokens and spliced in before the parse, so the window's
    resources are inline -- which is the only strategy that resolves reliably inside Revit's
    sandbox (§12.7.B) -- without a second copy of the palette existing anywhere.

    Parsed from a ``MemoryStream``, which is what every tool in the suite does.
    """
    _load_assemblies()
    from System.IO import MemoryStream
    from System.Text import Encoding
    from System.Windows.Markup import XamlReader

    markup = xaml.window_xaml(name)
    stream = MemoryStream(Encoding.UTF8.GetBytes(markup))
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


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
