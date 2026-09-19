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
    assert "pip install pythonnet" in text


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
