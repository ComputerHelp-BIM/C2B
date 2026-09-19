"""The WPF C2B window, read rather than run.

The window cannot be opened here, so it is checked the way the Revit script is: by parsing
it. The failure worth catching is not cosmetic -- WPF owns its controls from one thread, and
a progress line written straight from the pipeline's worker thread is an exception, not a
race that happens sometimes.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from c2b.gui.session import FIELDS
from c2b.ui import xaml

SOURCE = Path(__file__).resolve().parents[1] / "src" / "c2b" / "gui" / "main_wpf.py"


@pytest.fixture(scope="module")
def source():
    return SOURCE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tree(source):
    return ast.parse(source)


def _names(markup: str):
    return set(re.findall(r'x:Name="([^"]+)"', markup))


def test_every_control_it_asks_for_exists_in_the_layout(source):
    asked = {node.args[1].value
             for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "find" and len(node.args) == 2
             and isinstance(node.args[1], ast.Constant)}
    declared = _names(xaml.layout_path("main_window").read_text(encoding="utf-8"))
    assert asked - declared == set(), f"the window has no {sorted(asked - declared)}"
    assert len(asked) > 8, "nothing is looked up, so this test proves nothing"


def test_no_dotnet_import_happens_at_module_scope(tree):
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not str(name).startswith(("System", "clr", "Microsoft")), f"{name} at module scope"


# ------------------------------------------------ the thread rule, which bites

def test_the_pipeline_runs_off_the_window_thread(source):
    """A 25 MB drawing takes a minute; a window that stops repainting looks broken."""
    assert "threading.Thread" in source
    body = source.split("def _start")[1].split("\n    def ")[0]
    assert "daemon=True" in body, "a worker that outlives the window keeps the process alive"


def test_the_worker_touches_no_control_of_its_own(source, tree):
    """WPF owns its controls from one thread. This is an exception, not a flaky race."""
    work = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_work")
    text = ast.unparse(work)
    assert "wpf.find" not in text, "the worker reaches straight into the window"
    assert "_on_ui(" in text, "the worker never hops back to the window thread"

    report = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_report")
    assert "_on_ui(" in ast.unparse(report)


def test_the_hop_back_goes_through_the_dispatcher(source):
    body = source.split("def _on_ui")[1].split("\n    def ")[0]
    assert "Dispatcher.BeginInvoke" in body
    # Send would make the pipeline wait for the window to paint, once per progress line.
    assert "DispatcherPriority.Background" in body
    assert ".Invoke(" not in body


def test_a_pipeline_that_throws_still_finishes_the_run(source):
    """run_job never raises, but the window must not hang on the day something else does."""
    body = source.split("def _work")[1].split("\n    def ")[0]
    assert "except Exception" in body
    assert body.index("except Exception") < body.index("_on_ui(")


def test_the_run_button_goes_inert_and_says_what_it_is_doing(source):
    """11.2 - disable the trigger and show its label as the running verb."""
    body = source.split("def _start")[1].split("\n    def ")[0]
    assert "IsEnabled = False" in body and "Running" in body
    back = source.split("def _finish")[1].split("\n    def ")[0]
    assert "IsEnabled = True" in back, "a finished run must give the button back"


# --------------------------------------------------- the fields, from one list

def test_the_file_rows_are_built_from_the_shared_field_list(source):
    """So a row cannot exist in this window and be missing from the Tkinter one."""
    assert "for n, f in enumerate(FIELDS)" in source
    assert len(FIELDS) == 5


def test_a_row_button_binds_its_own_field(source):
    """A handler closing over the loop variable would give every row the last field."""
    body = source.split("def _picker")[1].split("\n    def ")[0]
    assert "f.key" in body and "f.kind" in body


def test_what_is_typed_is_read_back_before_a_run(source):
    body = source.split("def _on_run")[1].split("\n    def ")[0]
    assert body.index("_read_back()") < body.index("job_settings()")
    assert body.index("_read_back()") < body.index("problem()")


def test_a_combo_box_is_read_by_its_selection_not_its_text(source):
    body = source.split("def _read_back")[1].split("\n    def ")[0]
    assert "SelectedItem" in body


def test_saving_storeys_drops_a_level_workbook_chosen_earlier(source):
    """Otherwise the workbook would contradict the storeys on the very next run."""
    body = source.split("def _on_storeys")[1].split("\n    def ")[0]
    assert 'self.inputs["levels"].Text = ""' in body
    assert body.index("schedule.save(path)") < body.index("_on_run(")


def test_no_message_box_anywhere(source):
    """11.5, 13.4 - everything is said in the window's own footer."""
    assert "MessageBox" not in source and "TaskDialog" not in source


def test_the_things_to_check_table_is_not_bound_to_python_objects(tree):
    """12.7.G, Q - the same reason the storey editor builds its rows."""
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert used.isdisjoint({"DataGrid", "ItemsSource", "ArrayList"})


def test_the_dispatcher_delegate_is_a_real_clr_type(source):
    """12.8.7.1 - pythonnet needs __namespace__ to build a type from a .NET delegate."""
    assert '__namespace__ = "AnonGee"' in source


def test_the_folder_picker_works_on_a_runtime_without_the_new_dialog(source):
    """OpenFolderDialog arrived in .NET 8; the machines this runs on are not all new."""
    body = source.split("def _ask_for_folder")[1].split("\ndef ")[0]
    assert "OpenFolderDialog" in body and "except ImportError" in body
    assert "OpenFileDialog" in body
