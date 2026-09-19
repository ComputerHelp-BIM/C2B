"""The WPF storey editor, read rather than run.

WPF needs Windows and pythonnet, so this module cannot be imported here, let alone shown. It
is checked the way the Revit import script is checked: by parsing it. What that catches is
narrow but real -- a control name the layout does not define, a handler subscribed at module
scope, a Revit-style crash trap -- and each of those would otherwise be found by the person
who pressed the button.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from c2b.ui import xaml

SOURCE = Path(__file__).resolve().parents[1] / "src" / "c2b" / "ui" / "storey_wpf.py"


@pytest.fixture(scope="module")
def tree():
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def source():
    return SOURCE.read_text(encoding="utf-8")


def test_the_file_is_valid_python(tree):
    assert tree is not None


def test_every_control_it_asks_for_exists_in_the_layout(source):
    """A name the layout does not define raises at the first click, not at load."""
    asked = {node.args[1].value
             for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "find" and len(node.args) == 2
             and isinstance(node.args[1], ast.Constant)}
    declared = set(_names(xaml.layout_path("storey_editor").read_text(encoding="utf-8")))
    assert asked - declared == set(), f"the window has no {sorted(asked - declared)}"
    assert asked, "nothing is looked up, so this test proves nothing"


def _names(markup: str):
    import re
    return re.findall(r'x:Name="([^"]+)"', markup)


def test_the_buttons_it_wires_are_the_buttons_the_layout_has(source):
    import re
    declared = set(_names(xaml.layout_path("storey_editor").read_text(encoding="utf-8")))
    wired = set(re.findall(r'wpf\.find\(self\.window, "(Btn\w+)"\)\.Click', source))
    assert wired <= declared
    assert {"BtnAdd", "BtnAddBottom", "BtnSave", "BtnCancel"} <= wired


def test_the_row_commands_act_on_the_row_the_user_picked(source):
    """A DataGrid shows its selection, so select-then-act reads plainly here -- unlike a
    toolbar over a list of plain panels, where nothing says which row is current."""
    body = source.split("def _on_selected")[1].split("\n    def ")[0]
    assert "_selected_id()" in body
    assert "Click a storey in the table first." in body, "a command with no row must say so"
    wired = source.split("def _wire")[1].split("\n    def ")[0]
    for command in ("self.presenter.move", "self.presenter.remove"):
        assert command in wired, f"no button runs {command}"


def test_the_tick_column_is_bound_to_the_rows_own_dotnet_bool():
    """12.7.Q - a DataTrigger on a Python bool never fires, and a write back to a __slots__
    bool does not land. DataGridRow.IsSelected is a real bool and is the way round it."""
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    tick = markup.split('Header="Build"')[1].split("</DataGridTemplateColumn>")[0]
    assert "IsSelected, Mode=TwoWay" in tick
    assert "AncestorType=DataGridRow" in tick
    assert "GridCheckBox" in tick


def test_the_grid_lets_a_user_drag_its_column_widths():
    theme = xaml.theme_xaml()
    grid = theme.split('x:Key="DataGridStyle"')[1].split("</Style>")[0]
    assert '<Setter Property="CanUserResizeColumns" Value="True"/>' in grid


def test_selection_is_painted_in_the_brand_not_the_system_blue():
    """12.7.H - the DataGrid's visual state manager wins over a RowStyle trigger unless these
    system keys are redefined at the grid's own scope."""
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    assert "SystemColors.HighlightBrushKey" in markup
    assert "SystemColors.InactiveSelectionHighlightBrushKey" in markup


def test_the_row_object_is_slotted_with_no_property_or_inpc(tree):
    """12.7.G - a @property on an INPC class binds to empty strings under Python.NET 3."""
    row = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "StoreyRow")
    assert not row.bases, "a bound row class inherits nothing, least of all INotifyPropertyChanged"
    assert any(isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "__slots__" for t in n.targets) for n in row.body)
    assert not any(isinstance(n, ast.FunctionDef) and any(
        isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list) for n in row.body)


def test_every_slot_the_layout_binds_exists_on_the_row(source):
    """A binding path with no slot behind it renders an empty cell and says nothing."""
    import re

    from c2b.ui.storey_wpf import StoreyRow

    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    grid = markup.split("<DataGrid ")[1]
    paths = {m.split(",")[0].strip() for m in re.findall(r"\{Binding ([^}]+)\}", grid)}
    paths = {p for p in paths if p and not p.startswith(("IsSelected", "RelativeSource"))}
    assert paths, "nothing is bound, so this test proves nothing"
    assert paths <= set(StoreyRow.__slots__), f"no slot for {sorted(paths - set(StoreyRow.__slots__))}"


def test_the_grid_is_flushed_before_it_is_refilled(source):
    """12.7.G - without this the grid reuses its row containers and shows stale cells."""
    body = source.split("def refresh")[1].split("\n    def ")[0]
    assert "ItemsSource = None" in body
    assert body.index("ItemsSource = None") < body.index("ItemsSource = items")


def test_no_revit_or_wpf_import_happens_at_module_scope(tree):
    """Importing clr on a machine with no .NET is an error, and this file is imported by name
    resolution on every platform C2B runs on."""
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not str(name).startswith(("System", "clr", "Autodesk")), f"{name} at module scope"


def test_nothing_subscribes_a_handler_at_module_scope(source, tree):
    """12.9.2 - a handler added at module scope in a persistent engine fires once per press it
    has ever seen, against objects that may already be dead."""
    for node in tree.body:
        assert not isinstance(node, ast.AugAssign), "a += at module scope subscribes forever"


def test_the_window_is_built_per_opening_not_held_on_the_module(tree):
    """12.9.2 again - state lives in the instance, so nothing survives to the next press."""
    module_names = {target.id for node in tree.body if isinstance(node, ast.Assign)
                    for target in node.targets if isinstance(target, ast.Name)}
    assert not {n for n in module_names if not n.isupper() and not n.startswith("_")}


def test_the_editor_reads_its_fields_back_before_every_command(source, tree):
    """A command that runs before the typed text is taken silently loses the edit.

    One place does it -- ``_command`` -- and every button goes through it, so a new command
    cannot be added that forgets. ``_on_save`` reads back on its own because it does not
    route through ``_command``.
    """
    body = source.split("def _command")[1].split("\n    def ")[0]
    assert body.index("_read_back()") < body.index("run(*args)")
    assert "def _read_back" in source
    # A cell still being edited has not written to its bound object yet.
    assert "CommitEdit()" in source.split("def _read_back")[1].split("\n    def ")[0]

    handlers = [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name.startswith("_on_")]
    assert handlers, "no button handlers at all"
    for handler in handlers:
        text = ast.unparse(handler)
        if handler.name in ("_on_cancel", "_on_selection_changed"):
            # Cancel throws the edits away on purpose, so it is the one handler that must
            # NOT read them back first.
            assert "_read_back()" not in text
            continue
        assert "_read_back()" in text or "self._command(" in text, f"{handler.name} acts blind"


def test_heights_are_read_back_lowest_storey_first(source):
    """Elevations are the heights added up, so the order they are applied in decides the answer."""
    body = source.split("def _read_back")[1].split("\n    def ")[0]
    assert body.index("row.Height") < body.index("row.Elevation")
    ordered = source.split("def _ordered_rows")[1].split("\n    def ")[0]
    assert "self.presenter.schedule.storeys" in ordered


def test_a_field_is_only_applied_when_it_changed(source):
    """Re-applying an unchanged elevation would pin a storey that a height edit just moved."""
    body = source.split("def _read_back")[1].split("\n    def ")[0]
    assert 'row_was(row, "height")' in body and 'row_was(row, "elevation")' in body


def test_filling_the_table_does_not_count_as_typing(source):
    """Setting .Text in code raises the same events a person typing does."""
    assert "self._filling" in source
    body = source.split("def _read_back")[1].split("\n    def ")[0]
    assert "if self._filling:" in body


def test_a_stack_with_an_error_cannot_be_saved(source):
    body = source.split("def _on_save")[1].split("\n    def ")[0]
    assert "can_save()" in body and "DialogResult" in body
    assert body.index("can_save()") < body.index("self.saved = True")


def test_the_severity_is_written_beside_the_message_not_only_coloured(source):
    """10.4 - state is never signalled by colour alone."""
    body = source.split("def _show_problems")[1].split("\n    def ")[0]
    assert "{severity}" in body


def test_no_message_box_anywhere(source):
    """11.5, 13.4 - validation is inline, never a blocking dialog."""
    assert "MessageBox" not in source and "TaskDialog" not in source


def test_the_rows_bind_the_way_the_suite_proved_and_no_other(tree):
    """A DataGrid's text columns over a slotted object is the pattern the suite ships and it
    works. The ways it does not -- an INPC class, a Python @property, a DataTrigger on a
    Python bool -- are 12.7.G, J and Q, and none of them appear here."""
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in n.names}
    assert used.isdisjoint({"INotifyPropertyChanged", "PropertyChangedEventHandler",
                            "ObservableCollection"})
    assert "ArrayList" in used, "12.7.G asks for an ArrayList, not a Python list"


def test_a_datatrigger_on_a_python_bool_is_never_used():
    """12.7.Q, the one that looks correct and silently does nothing."""
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    for trigger in markup.split("<DataTrigger ")[1:]:
        binding = trigger.split(">")[0]
        assert "IsSelected" in binding, f"a DataTrigger on a Python value: {binding}"


def _unused_test_the_row_columns_match_the_header_the_layout_draws():
    """A column widened in the header and left narrow in the rows is a table that does not
    line up, and it is invisible until somebody opens the window."""
    import re

    from c2b.ui.storey_wpf import _COLUMNS

    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    header = markup.split('x:Name="HeaderRow"')[1].split("</Grid.ColumnDefinitions>")[0]
    widths = re.findall(r'<ColumnDefinition Width="([^"]+)"', header)
    assert len(widths) == len(_COLUMNS), "the header and the rows have different column counts"
    for declared, built in zip(widths, _COLUMNS):
        if declared == "*":
            assert built is None, "the header's stretching column is fixed in the rows"
        else:
            assert float(declared) == built, f"header {declared} vs row {built}"


def _unused_test_every_column_the_header_names_is_filled_by_a_row(source):
    """A header with seven columns over rows that place six leaves one silently blank."""
    from c2b.ui.storey_wpf import _COLUMNS

    placed = source.split("def refresh")[1].split("\n    def _row_actions")[0]
    columns = {int(n) for n in __import__("re").findall(r"grid, \w+, (\d)\)", placed)}
    columns |= {6}                       # the action cluster, placed by its own call
    assert columns == set(range(len(_COLUMNS)))
