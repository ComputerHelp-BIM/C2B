"""The thread a WPF window is built on.

WPF builds a control only on a thread in a single-threaded apartment. Python's main thread is
not one, so for a release the assemblies loaded, the markup parsed, and the ``Window``
constructor threw ``InvalidOperationException: The calling thread must be STA`` -- reported as
a ``XamlParseException`` against line 20 of a layout file that had nothing wrong with it.

Two halves are tested here. :func:`c2b.ui.wpf.run_sta` itself, against a stand-in for
``System.Threading`` so it runs on the machines C2B is developed on; and the call sites, read
rather than run, because the mistake that matters is building a window on one thread and
showing it on another -- which fails later and somewhere less obvious.
"""
from __future__ import annotations

import ast
import sys
import threading
import types
from pathlib import Path

import pytest

from c2b.ui import wpf

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "c2b"


def source(*parts: str) -> str:
    return SRC.joinpath(*parts).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# A stand-in for System.Threading, so the logic can be exercised off Windows
# ---------------------------------------------------------------------------

def fake_threading(current: str = "MTA", *, starts: bool = True) -> types.ModuleType:
    """``System.Threading`` as much of it as :func:`run_sta` touches.

    ``starts=False`` is the thread that dies before it reaches Python: nothing runs, nothing
    sets the event, and the only thing that can save the caller is noticing it is not alive.
    """
    module = types.ModuleType("System.Threading")

    class ApartmentState:
        STA = "STA"
        MTA = "MTA"

    class _Current:
        def GetApartmentState(self):
            return current

        def TrySetApartmentState(self, state):
            return False                    # a thread that has already committed says no

    class Thread:
        CurrentThread = _Current()

        def __init__(self, start):
            self._start = start
            self._thread: threading.Thread | None = None
            self.IsBackground = False
            self.Name = ""
            self.apartment = ""

        def SetApartmentState(self, state):
            self.apartment = state

        def Start(self):
            if starts:
                self._thread = threading.Thread(target=self._start, daemon=True)
                self._thread.start()

        @property
        def IsAlive(self):
            return bool(self._thread and self._thread.is_alive())

    module.ApartmentState = ApartmentState
    module.Thread = Thread
    module.ThreadStart = lambda fn: fn
    return module


@pytest.fixture
def threading_module(monkeypatch):
    """Install the stand-in and keep :func:`run_sta` off the real CLR."""
    def install(current: str = "MTA", *, starts: bool = True):
        module = fake_threading(current, starts=starts)
        monkeypatch.setitem(sys.modules, "System", types.ModuleType("System"))
        monkeypatch.setitem(sys.modules, "System.Threading", module)
        monkeypatch.setattr(wpf, "_load_assemblies", lambda: None)
        monkeypatch.setattr(wpf, "_WATCH_SECONDS", 0.01)
        return module
    return install


# ---------------------------------------------------------------------------
# run_sta
# ---------------------------------------------------------------------------

def test_on_a_thread_wpf_already_accepts_nothing_is_thrown_at_a_new_one(threading_module):
    """A dialog opened from another dialog's handler must not hop threads: it is already
    on the one that owns the controls, and a hop would hand it a window it cannot touch."""
    module = threading_module("STA")
    made: list[object] = []
    module.Thread.__init__ = lambda self, start: made.append(start)

    assert wpf.run_sta(lambda: "opened") == "opened"
    assert made == [], "a window was sent to a second thread from a thread that was already STA"


def test_off_one_the_window_gets_a_thread_of_its_own_and_the_answer_comes_back(threading_module):
    threading_module("MTA")
    seen: list[str] = []

    def work():
        seen.append(threading.current_thread().name)
        return True

    assert wpf.run_sta(work) is True
    assert seen and seen[0] != threading.current_thread().name, "it ran on the calling thread"


def test_the_new_thread_is_told_to_be_sta_before_it_starts(threading_module):
    module = threading_module("MTA")
    made: list[object] = []
    original = module.Thread.Start

    def record(self):
        made.append((self.apartment, self.IsBackground))
        original(self)

    module.Thread.Start = record
    wpf.run_sta(lambda: None)
    assert made == [("STA", True)], "the window thread is not STA, or would keep C2B running"


def test_a_failure_in_the_window_is_raised_where_someone_can_report_it(threading_module):
    """An exception let out of a .NET thread ends the process. It has to come back here."""
    threading_module("MTA")

    def work():
        raise LookupError("the window has no control called 'BtnRun'")

    with pytest.raises(LookupError, match="BtnRun"):
        wpf.run_sta(work)


def test_a_thread_that_dies_before_it_reaches_python_does_not_hang_the_tool(threading_module):
    threading_module("MTA", starts=False)
    with pytest.raises(RuntimeError, match="stopped before the window could open"):
        wpf.run_sta(lambda: None)


def test_the_wait_is_pythons_so_the_window_thread_can_call_back_into_python():
    """``Thread.Join`` blocks in .NET; the window thread needs the GIL to build the window."""
    body = source("ui", "wpf.py").split("def run_sta")[1].split("\ndef ")[0]
    assert "done.wait(" in body, "the caller waits in .NET, which is how this deadlocks"
    assert ".Join(" not in body


# ---------------------------------------------------------------------------
# _ensure_sta
# ---------------------------------------------------------------------------

def test_the_calling_thread_is_asked_first_because_it_is_the_cheapest_answer():
    """One thread means every control is reachable from the code that made it."""
    loading = source("ui", "wpf.py").split("def _load_assemblies")[1].split("\ndef ")[0]
    assert "_ensure_sta()" in loading, "nothing puts the main thread in the apartment WPF needs"


def test_the_apartment_is_tried_not_set_because_set_throws():
    body = source("ui", "wpf.py").split("def _ensure_sta")[1].split("\ndef ")[0]
    assert "TrySetApartmentState" in body
    assert "current.SetApartmentState" not in body, "a refusal would take available() down with it"


def test_a_dialog_that_wanted_an_owner_and_got_none_is_not_left_in_the_corner():
    """WindowStartupLocation=CenterOwner with no owner does not centre on anything: the
    window opens at 0,0. That is the top-left corner the storey editor kept appearing in."""
    body = source("ui", "wpf.py").split("def show_dialog")[1].split("\ndef ")[0]
    assert "CenterOwner" in body and "CenterScreen" in body
    assert body.index("owner_handle:") < body.index("CenterOwner"), "the owner still wins"


def test_a_window_never_opens_bigger_than_the_screen_it_opens_on():
    """The storey editor opens tall enough to show a building's worth of storeys. A drafting
    laptop is 768 pixels high, and a dialog taller than that hides its own Save button."""
    body = source("ui", "wpf.py").split("def fit_to_screen")[1].split("\ndef ")[0]
    assert "SystemParameters.WorkArea" in body
    assert "MinWidth" in body or 'f"Min{axis}"' in body, "a minimum bigger than the screen wins"
    assert "wanted == wanted" in body, "SizeToContent leaves an axis NaN, and NaN beats every >"
    load = source("ui", "wpf.py").split("def load_window")[1].split("\ndef ")[0]
    assert "fit_to_screen(window)" in load, "nothing calls it, so no window is ever clamped"


def test_doctor_says_which_thread_the_window_will_open_on():
    text = source("cli.py")
    assert "apartment()" in text and "window thread" in text


# ---------------------------------------------------------------------------
# The call sites: the whole window on the thread, not just the constructor
# ---------------------------------------------------------------------------

def _function(text: str, name: str) -> ast.AST:
    tree = ast.parse(text)
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_every_module_that_builds_a_window_is_one_of_the_three_that_are_wired_up():
    """A fourth window added without a run_sta around it fails on a machine, not in here."""
    builders = {path.relative_to(SRC).as_posix()
                for path in SRC.rglob("*.py")
                if "load_window(" in path.read_text(encoding="utf-8")}
    assert builders == {"ui/wpf.py", "gui/main_wpf.py", "ui/storey_wpf.py", "ui/elapsed_wpf.py"}


@pytest.mark.parametrize(("parts", "name"), [
    (("gui", "__init__.py"), "run_gui"),
    (("gui", "main_wpf.py"), "main"),
    (("ui", "__init__.py"), "edit_storeys"),
    (("ui", "__init__.py"), "show_elapsed"),
])
def test_no_window_is_opened_without_asking_for_a_thread_wpf_accepts(parts, name):
    body = ast.unparse(_function(source(*parts), name))
    assert "run_sta(" in body, f"{name} opens a WPF window on whatever thread it is called on"


def test_the_main_window_is_built_and_shown_inside_the_same_piece_of_work():
    """Built on one thread and shown from another is the bug this whole module is about."""
    run_gui = _function(source("gui", "__init__.py"), "run_gui")
    inner = [n for n in ast.walk(run_gui)
             if isinstance(n, ast.FunctionDef) and n is not run_gui]
    assert len(inner) == 1, "the work handed to run_sta is not one piece"
    body = ast.unparse(inner[0])
    assert "C2BWindow()" in body, "the window is constructed outside the thread that shows it"
    assert ".show()" in body
