"""The WPF storey editor, read rather than run.

WPF needs Windows and pythonnet, so this module cannot be imported here, let alone shown. It
is checked the way the Revit import script is checked: by parsing it. What that catches is
narrow but real -- a control name the layout does not define, a binding path nothing fills, a
handler subscribed at module scope -- and each of those would otherwise be found by the
person who pressed the button.

Most of what is here was written after watching a screen recording of the window. Three
separate bugs were visible in it and all three had one cause: **WPF only ever sees the string
a Python object prints to**, because pythonnet hands the binding engine a ``PyObject``
whatever the value was. Every binding to a string target worked; every other binding failed
in silence.
"""
from __future__ import annotations

import ast
import re
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


@pytest.fixture(scope="module")
def markup():
    return xaml.layout_path("storey_editor").read_text(encoding="utf-8")


def function(tree: ast.AST, name: str) -> str:
    """One function's code, comments dropped -- a test must not match its own explanation."""
    found = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.unparse(found)


def names(markup: str) -> set[str]:
    return set(re.findall(r'x:Name="([^"]+)"', markup))


# ---------------------------------------------------------------------------
# It drives the window the layout actually declares
# ---------------------------------------------------------------------------

def test_the_file_is_valid_python(tree):
    assert tree is not None


def test_every_control_it_asks_for_exists_in_the_layout(source, markup):
    """A name the layout does not define raises at the first click, not at load."""
    asked = {node.args[1].value
             for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "find" and len(node.args) == 2
             and isinstance(node.args[1], ast.Constant)}
    assert asked - names(markup) == set(), f"the window has no {sorted(asked - names(markup))}"
    assert asked, "nothing is looked up, so this test proves nothing"


def test_the_buttons_it_wires_are_the_buttons_the_layout_has(source, markup):
    wired = set(re.findall(r'wpf\.find\(self\.window, "(Btn\w+)"\)\.Click', source))
    assert wired <= names(markup)
    assert {"BtnAdd", "BtnAddBottom", "BtnSave", "BtnCancel"} <= wired


# ---------------------------------------------------------------------------
# The rows: real .NET values, because a Python one only ever prints
# ---------------------------------------------------------------------------

def test_a_bound_row_is_a_dotnet_object_and_not_a_python_one(tree, source):
    """The bug this is about: every Build tick rendered empty and every plan picker rendered
    blank, because IsChecked wants a bool? and SelectedItem has to match an item, and a
    PyObject converts to neither. Only the string columns worked, on ToString()."""
    body = function(tree, "grid_row")
    assert "ExpandoObject" in body, "the rows are Python objects again, so only strings bind"
    assert "IDictionary" in body, "an ExpandoObject's members are set through its dictionary"
    assert "__slots__" not in source, "the slotted row is what could not carry a bool"


def test_every_binding_path_the_layout_uses_is_a_field_the_row_sets(tree, markup):
    """A binding path with nothing behind it renders an empty cell and says nothing at all."""
    grid = markup.split("<DataGrid ")[1]
    paths = {m.split(",")[0].strip() for m in re.findall(r"\{Binding ([^}]+)\}", grid)}
    paths = {p for p in paths if p and not p.startswith(("RelativeSource", "IsSelected"))}
    filled = set(re.findall(r'fields\[[\'"](\w+)[\'"]\]', function(tree, "grid_row")))
    assert paths, "nothing is bound, so this test proves nothing"
    assert paths <= filled, f"nothing fills {sorted(paths - filled)}"


def test_the_row_never_offers_a_member_wpf_already_has_one_of(tree, markup):
    """A dynamic object is asked for its members by name. Calling one of them Name is a
    question with two answers, and the binding engine picks which one."""
    filled = set(re.findall(r'fields\[[\'"](\w+)[\'"]\]', function(tree, "grid_row")))
    assert "Name" not in filled, "the storey's name is bound as Storey for exactly this reason"
    assert "Storey" in filled
    assert "{Binding Storey" in markup


def test_the_grid_is_flushed_before_it_is_refilled(tree):
    """12.7.G - without this the grid reuses its row containers and shows stale cells."""
    body = function(tree, "refresh")
    assert body.index("ItemsSource = None") < body.index("ItemsSource = items")


def test_the_rows_bind_the_way_the_suite_proved_and_no_other(tree):
    """The ways that do not work -- an INPC class, a Python @property, a DataTrigger on a
    Python value -- are 12.7.G, J and Q, and none of them appear here."""
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in n.names}
    assert used.isdisjoint({"INotifyPropertyChanged", "PropertyChangedEventHandler",
                            "ObservableCollection"})
    assert "ArrayList" in used, "12.7.G asks for an ArrayList, not a Python list"


def test_no_datatrigger_is_used_at_all(markup):
    """12.7.Q, the one that looks correct and silently does nothing."""
    assert "<DataTrigger" not in markup


# ---------------------------------------------------------------------------
# Every edit comes from the control the person touched
# ---------------------------------------------------------------------------

def test_what_was_typed_is_read_off_the_editor_not_out_of_the_binding(tree):
    """One direction of marshalling instead of two, and the direction that is known to work."""
    body = function(tree, "_on_cell_edit_ending")
    assert "args.EditingElement" in body, "it trusts the write-back it cannot verify"
    assert "args.Column.Header" in body, "nothing says which column was edited"
    assert "DataGridEditAction.Commit" in body, "a cancelled edit would be applied"


def test_the_edit_table_names_columns_the_layout_actually_draws(markup):
    """The header is what the person read when they typed, so it is what the edit is keyed on
    -- and a header renamed in the layout must not quietly stop being editable."""
    from c2b.ui.storey_wpf import EDITS

    headers = set(re.findall(r'Header="([^"]+)"', markup))
    assert set(EDITS) <= headers, f"no column headed {sorted(set(EDITS) - headers)}"
    assert set(EDITS) == {"Storey", "Height mm", "Elevation mm", "Repeat"}


def test_the_tick_is_the_storeys_own_value_and_not_the_rows_selection(markup):
    """It was bound to DataGridRow.IsSelected once. That threw on a Single-selection grid, and
    it made ticking a storey also change which row the buttons acted on."""
    tick = markup.split('Header="Build"')[1].split("</DataGridTemplateColumn>")[0]
    assert "{Binding Build, Mode=OneWay}" in tick
    assert "IsSelected" not in tick
    assert 'Tag="BuildTick"' in tick, "the handler cannot tell this from a ComboBox's toggle"


def test_the_tick_listens_for_a_click_and_not_for_checked(tree, source):
    """Checked is raised by the binding as each row is realised, so the first draw was a storm
    of edits that each queued another redraw. Click is raised only by a person."""
    wired = function(tree, "_wire")
    assert "ButtonBase.ClickEvent" in wired
    assert "CheckedEvent" not in source and "UncheckedEvent" not in source
    assert "self._handlers" in wired, "a delegate only .NET holds is one Python may collect"


def test_a_tick_does_not_redraw_the_table(tree):
    """Rebuilding drops the selection the person is in the middle of making -- and while the
    tick was bound one way to a value WPF could not read, the redraw put the box back."""
    body = function(tree, "_on_build_clicked")
    assert "refresh" not in body, "a tick rebuilds the table, so it appears to undo itself"
    assert "self._show_status()" in body, "nothing says what the tick changed"
    assert "box.IsChecked" in body, "it guesses at the new state instead of reading it"


def test_a_plan_picked_in_a_cell_is_told_apart_from_the_grids_own_selection(tree, markup):
    """A ComboBox inside a cell raises Selector.SelectionChanged, which bubbles up and arrives
    as though the grid's own selection had changed."""
    body = function(tree, "_on_selection_changed")
    assert "PLAN_PICK" in body, "a plan pick is treated as a row selection"
    assert "args.OriginalSource" in body
    assert 'Tag="PlanPick"' in markup


def test_filling_the_table_does_not_count_as_typing(tree):
    """Setting a value in code raises the same events a person does."""
    for handler in ("_on_cell_edit_ending", "_on_build_clicked", "_on_selection_changed"):
        assert "self._filling" in function(tree, handler), f"{handler} acts on its own redraw"


def test_a_redraw_never_happens_inside_the_event_that_asked_for_it(tree):
    """It replaces the very row the grid is still closing an editor on."""
    for handler in ("_on_cell_edit_ending", "_on_selection_changed"):
        body = function(tree, handler)
        if "_redraw" in body:
            assert "self._after(" in body, f"{handler} redraws mid-event"
    assert "BeginInvoke" in function(tree, "_after")


# ---------------------------------------------------------------------------
# Selection means the rows the buttons act on -- all of them
# ---------------------------------------------------------------------------

def test_a_person_can_pick_more_than_one_storey(markup):
    """Ctrl-click and shift-click are what a Windows user reaches for on a table, and they do
    nothing whatsoever on a grid left in Single mode."""
    grid = markup.split('x:Name="StoreyGrid"')[1].split(">")[0]
    assert 'SelectionMode="Extended"' in grid


def test_the_row_commands_act_on_every_row_the_user_picked(tree):
    body = function(tree, "_on_selected")
    assert "_selected_ids()" in body, "it acts on one row out of the several that are selected"
    assert "Ctrl-click" in body, "a command with no row must say how to give it one"
    assert "reversed" in body, "moving a block up has an order, and this is not it"
    wired = function(tree, "_wire")
    for command in ("'move'", "'remove'"):
        assert command in wired, f"no button runs {command}"


def test_every_command_takes_what_is_typed_before_it_acts(tree):
    """Press a button with a half-typed height in a cell, or a new default height beside the
    table, and neither must be lost. The default height is a plain TextBox with no
    CellEditEnding of its own, so it needs taking by hand."""
    for name in ("_command", "_on_selected", "_on_save"):
        assert "self._commit()" in function(tree, name), f"{name} discards what is typed"
    commit = function(tree, "_commit")
    assert "CommitEdit()" in commit and "DefaultHeight" in commit


def test_an_edit_to_a_row_the_grid_has_not_realised_is_dropped(tree):
    """GetIndex returns -1 for one, and -1 into a Python list is the last storey."""
    body = function(tree, "_on_cell_edit_ending")
    assert "0 <= index < len(self._rows)" in body


def test_the_footer_never_claims_a_row_that_is_gone(tree):
    """Remove the selected storey and the selection cannot be restored. The label said it was
    still selected while the buttons said to click a storey first."""
    body = function(tree, "refresh")
    assert "self._show_selection()" in body
    assert body.rindex("_show_selection") > body.rindex("self._filling = False")


def test_a_stack_with_an_error_cannot_be_saved(tree):
    body = function(tree, "_on_save")
    assert "can_save()" in body and "DialogResult" in body
    assert body.index("can_save()") < body.index("self.saved = True")


# ---------------------------------------------------------------------------
# House rules
# ---------------------------------------------------------------------------

def test_selection_is_painted_in_the_brand_not_the_system_blue(markup):
    """12.7.H - the DataGrid's visual state manager wins over a RowStyle trigger unless these
    system keys are redefined at the grid's own scope."""
    assert "SystemColors.HighlightBrushKey" in markup
    assert "SystemColors.InactiveSelectionHighlightBrushKey" in markup


def test_the_grid_lets_a_user_drag_its_column_widths():
    theme = xaml.theme_xaml()
    grid = theme.split('x:Key="DataGridStyle"')[1].split("</Style>")[0]
    assert '<Setter Property="CanUserResizeColumns" Value="True"/>' in grid


def test_no_revit_or_wpf_import_happens_at_module_scope(tree):
    """Importing clr on a machine without .NET is an error, and this module is imported on
    every machine C2B is developed on."""
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            names_ = [a.name for a in node.names]
            assert not module.startswith(("System", "Autodesk", "clr")), f"{module} at module scope"
            assert not any(n.startswith(("System", "Autodesk", "clr")) for n in names_)


def test_nothing_subscribes_a_handler_at_module_scope(source, tree):
    """12.9.2 - the persistent engine keeps module globals, so a handler subscribed once per
    module load fires once per press it has ever seen."""
    for node in tree.body:
        assert not (isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add)), \
            "a += at module scope is a subscription that outlives the window"


def test_the_window_is_built_per_opening_not_held_on_the_module(tree):
    assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                if isinstance(t, ast.Name)}
    assert "WINDOW" not in assigned and "_WINDOW" not in assigned


def test_the_severity_is_written_beside_the_message_not_only_coloured(tree):
    """10.4 - state is never signalled by colour alone."""
    assert "{severity}" in function(tree, "_show_problems")


def test_no_message_box_anywhere(source):
    """11.5, 13.4 - validation is inline, never a blocking dialog."""
    assert "MessageBox" not in source and "TaskDialog" not in source
