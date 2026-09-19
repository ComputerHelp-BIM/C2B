"""Which window opened, and whether anybody was told.

For three releases the plain window opened because pythonnet was missing, and nothing said
so: the Windows launcher uses ``pythonw.exe``, which has no console, and the branch that
falls back did not even print. These are the tests that stop that happening again.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def source(*parts: str) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8")


def test_the_branded_window_is_a_dependency_not_an_aspiration():
    """It is no use shipping a WPF window and leaving the machine unable to load it."""
    data = tomllib.loads(source("pyproject.toml"))
    wanted = [d for d in data["project"]["dependencies"] if d.startswith("pythonnet")]
    assert wanted, "pythonnet is not installed with C2B, so no machine gets the branded window"
    assert "sys_platform == 'win32'" in wanted[0], "a Linux install must not fail on it"


def test_falling_back_to_the_plain_window_is_never_silent():
    text = source("src", "c2b", "gui", "__init__.py")
    tree = ast.parse(text)
    run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_gui")
    body = ast.unparse(run)
    # Both ways round: WPF unavailable, and WPF present but throwing.
    assert body.count("_note(") >= 2, "one of the two fallback paths says nothing"
    assert "else:" in body, "the 'WPF is not available' branch has nothing in it"
    assert "pip install pythonnet" in body, "the message does not say how to fix it"


def test_the_reason_is_written_down_because_the_launcher_has_no_console():
    text = source("src", "c2b", "gui", "__init__.py")
    assert "LOG_FILE" in text
    note = text.split("def _note")[1].split("\ndef ")[0]
    assert "print(" in note and "LOG_FILE.open" in note
    assert "except Exception" in note, "a log that cannot be written must not stop a run"


def test_the_plain_window_says_on_itself_that_it_is_the_plain_window():
    build = source("src", "c2b", "gui", "app.py").split("def _build")[1].split("\n    def ")[0]
    assert "why_plain()" in build
    assert "PLAIN WINDOW" in build, "a banner nobody can read is not a banner"


def test_doctor_reports_which_window_would_open():
    text = source("src", "c2b", "cli.py")
    assert "branded (WPF)" in text and "plain (Tkinter)" in text
    assert "why_not_in_full()" in text, "the one-line reason is not enough to act on"


def test_there_is_a_launcher_with_a_console_behind_it():
    """C2B.bat uses pythonw.exe, so nothing printed ever reaches anybody."""
    # The commands only: the file's own REM lines explain why it does not use pythonw, and a
    # rule must not be broken by the sentence describing it.
    debug = "\n".join(line for line in source("windows", "C2B-debug.bat").splitlines()
                      if not line.strip().upper().startswith("REM"))
    assert "python.exe" in debug and "pythonw.exe" not in debug
    assert "doctor" in debug, "the first question is always which window it would open"
    assert "pause" in debug, "a console that closes with the app shows nothing"


def test_the_plain_dialogs_open_where_the_person_is_looking():
    """Tk puts a new Toplevel at the screen's top left, which for a small dialog is nowhere."""
    for module in ("elapsed_tk.py", "storey_tk.py"):
        text = source("src", "c2b", "ui", module)
        assert "_centre_on" in text, f"{module} opens wherever Tk feels like"
        body = text.split("def _centre_on")[1].split("\n    def ")[0]
        assert "winfo_rootx" in body and "winfo_screenwidth" in body


def test_a_coloured_button_in_the_plain_window_is_actually_coloured():
    """ttk's Windows themes ignore background and foreground on a TButton, so a styled
    Primary came out as a bare box with no label -- the red rectangles in the screenshots."""
    text = source("src", "c2b", "ui", "storey_tk.py")
    assert "def _filled_button" in text
    body = text.split("def _filled_button")[1].split("\n    def ")[0]
    assert "tk.Button(" in body, "a ttk button cannot be given a colour on Windows"
    assert "C2BPrimary.TButton" not in text and "C2BDanger.TButton" not in text


# --------------------------------------------- getting to WPF at all

def test_the_runtime_is_chosen_before_pythonnet_loads_one():
    """set_runtime is a one-shot: pythonnet keeps the first CLR it is given, so nothing in
    this module may import clr at the top or the choice is already made."""
    text = source("src", "c2b", "ui", "wpf.py")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not str(name).startswith(("clr", "System", "pythonnet", "clr_loader")), name
    choose = text.split("def _choose_runtime")[1].split("\ndef ")[0]
    assert '"clr" in sys.modules' in choose, "it must not try after pythonnet has loaded one"
    assert "_RUNTIME_CHOSEN" in choose, "set_runtime twice throws"


def test_wpf_is_looked_for_in_the_framework_that_actually_has_it():
    """Revit 2025 runs on .NET 8, so a machine with Revit has Microsoft.WindowsDesktop.App --
    and WPF is part of that framework rather than of the plain .NET runtime."""
    from c2b.ui import wpf

    config = wpf.runtime_config((8, 0, 11))
    assert '"Microsoft.WindowsDesktop.App"' in config
    assert '"net8.0"' in config and '"8.0.11"' in config
    assert '"latestMinor"' in config, "a machine that gets 8.1 tomorrow must keep working"


def test_the_newest_desktop_runtime_wins(tmp_path):
    from c2b.ui import wpf

    for name in ("6.0.36", "8.0.2", "8.0.11", "not-a-version", "9.0.0"):
        (tmp_path / name).mkdir()
    assert wpf.desktop_runtimes(tmp_path)[0] == (9, 0, 0)
    assert (8, 0, 11) in wpf.desktop_runtimes(tmp_path)
    assert len(wpf.desktop_runtimes(tmp_path)) == 4, "a folder that is not a version is not one"


def test_a_machine_with_no_desktop_runtime_says_so_rather_than_failing(tmp_path):
    from c2b.ui import wpf

    assert wpf.desktop_runtimes(tmp_path / "nothing here") == []


def test_an_assembly_is_asked_for_every_way_a_dotnet_will_accept():
    """.NET Framework's Assembly.Load does not search the GAC for a partial name, which is
    what clr.AddReference("PresentationFramework") passes it. That one behaviour cost this
    project four releases of looking in the wrong place."""
    text = source("src", "c2b", "ui", "wpf.py")
    body = text.split("def _add_reference")[1].split("\ndef ")[0]
    assert "PublicKeyToken=" in body, "no strong name, so the GAC is never searched"
    assert "gac_path(" in body, "no path, so a machine without a working strong name is stuck"
    assert "Desktop Runtime" in body, "the failure does not say what to install"


def test_every_assembly_a_wpf_window_needs_carries_its_token():
    from c2b.ui.wpf import ASSEMBLIES

    names = {name for name, _token in ASSEMBLIES}
    assert names == {"PresentationFramework", "PresentationCore", "WindowsBase", "System.Xaml"}
    for name, token in ASSEMBLIES:
        assert len(token) == 16 and all(c in "0123456789abcdef" for c in token), name


def test_the_gac_is_looked_in_where_dotnet_framework_actually_puts_things(tmp_path, monkeypatch):
    from c2b.ui import wpf

    monkeypatch.setenv("WINDIR", str(tmp_path))
    folder = (tmp_path / "Microsoft.NET" / "assembly" / "GAC_MSIL" / "WindowsBase"
              / "v4.0_4.0.0.0__31bf3856ad364e35")
    folder.mkdir(parents=True)
    (folder / "WindowsBase.dll").write_bytes(b"")
    assert wpf.gac_path("WindowsBase", "31bf3856ad364e35") == folder / "WindowsBase.dll"
    assert wpf.gac_path("WindowsBase", "b77a5c561934e089") is None, "the wrong token is not a match"
    assert wpf.gac_path("NotThere", "31bf3856ad364e35") is None


def test_the_xaml_is_parsed_from_a_stream_the_way_the_suite_does():
    body = source("src", "c2b", "ui", "wpf.py").split("def load_window")[1].split("\ndef ")[0]
    assert "MemoryStream" in body and "Encoding.UTF8" in body
    assert "stream.Close()" in body


def test_doctor_names_the_dotnet_behind_the_windows():
    text = source("src", "c2b", "cli.py")
    assert "_wpf.runtime()" in text
    assert "desktop_runtimes()" in text, "the first thing to check is whether WPF is installed"
