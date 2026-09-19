"""The storey editor as a WPF window, driven from Python.

The layout is ``storey_editor.xaml``; this fills its ``DataGrid`` and wires the buttons.
Everything it decides it asks :class:`~c2b.ui.storey_view.StoreyPresenter`, so this file is
only the part that cannot be tested without WPF -- and is kept small for exactly that reason.

**Binding, carefully.** The grid's text columns bind to a ``__slots__`` row object, which is
the pattern the suite already ships (§12.7.G). Two things it does *not* do:

* the Build tick reads its row's ``Build`` **as a string** and is written back from the
  ``Checked``/``Unchecked`` routed event, never through a two-way binding: §12.7.Q is explicit
  that a write back to a Python bool does not land, and the strings are what every other
  column in this grid already binds through;
* every value is read back through the presenter, which parses it and either applies it or
  reports it. A write-back that silently did not happen therefore leaves the value unchanged
  rather than corrupting the stack.
"""
from __future__ import annotations

from typing import Any

from . import wpf
from .storey_view import StoreyPresenter, format_mm

#: Names the layout file gives the controls this module drives.
_BUTTONS = ("BtnUp", "BtnDown", "BtnAdd", "BtnAddBottom", "BtnRemove", "BtnSave", "BtnCancel")

#: What the Build slot holds. WPF's default converter turns these into the ``bool?`` that
#: ``IsChecked`` wants; a Python bool in the same slot does not survive the trip.
TICKED = "True"
UNTICKED = "False"

#: Set on the Build tick in the layout so the grid-wide handler can tell it from the
#: ``ToggleButton`` inside a ComboBox's template, which raises the very same routed event.
BUILD_TICK = "BuildTick"

_BADGE_BRUSH = {"ERROR": ("BrushErrorBadgeBackground", "BrushErrorBadgeForeground"),
                "WARNING": ("BrushWarningBadgeBackground", "BrushWarningBadgeForeground"),
                "SUCCESS": ("BrushSuccessBadgeBackground", "BrushSuccessBadgeForeground"),
                "INFO": ("BrushInfoBadgeBackground", "BrushInfoBadgeForeground")}


class StoreyRow:
    """One row of the grid, as WPF binds to it.

    ``__slots__`` and no ``INotifyPropertyChanged``: §12.7.G is explicit that a Python
    ``@property`` on an INPC class binds to empty strings under Python.NET 3, and that a plain
    slotted object in an ``ArrayList`` is what works. Slot names are the binding paths in the
    XAML and are case-sensitive.
    """

    __slots__ = [
        "Build",
        "Elevation",
        "Flag",
        "Height",
        "Name",
        "Number",
        "Plan",
        "PlanChoices",
        "Repeat",
        "StoreyId",
    ]

    def __init__(self, row, choices) -> None:
        self.StoreyId = row.storey_id
        self.Number = str(row.number)
        self.Name = row.name
        self.Height = "" if row.is_base else row.height_text
        self.Elevation = row.elevation_text
        self.Plan = row.plan_label
        self.PlanChoices = choices
        self.Repeat = str(row.repeat)
        self.Flag = row.flag
        self.Build = TICKED if row.build else UNTICKED


class StoreyEditorWindow:
    """One run of the storey editor.

    A fresh instance per opening, never one held at module scope: the persistent engine keeps
    module globals between presses, and a handler subscribed once per press fires once per
    press it has ever seen (§12.9.2).
    """

    def __init__(self, presenter: StoreyPresenter, subtitle: str = "") -> None:
        self.presenter = presenter
        self.saved = False
        self._toggled: Any = None
        self.window = wpf.load_window("storey_editor")
        self.grid = wpf.find(self.window, "StoreyGrid")
        self._rows: list[Any] = []
        self._filling = False              # so a programmatic rebuild is not a user's edit
        if subtitle:
            wpf.find(self.window, "HeaderSubtitle").Text = subtitle
        wpf.find(self.window, "DefaultHeight").Text = f"{presenter.schedule.default_height_mm:.0f}"
        self._wire()
        self.refresh()

    # ----------------------------------------------------------------- wiring
    def _wire(self) -> None:
        for name in _BUTTONS:
            wpf.find(self.window, name)          # fail here, with the name, not at the click
        wpf.find(self.window, "BtnUp").Click += lambda s, e: self._on_selected(self.presenter.move, +1)
        wpf.find(self.window, "BtnDown").Click += lambda s, e: self._on_selected(self.presenter.move, -1)
        wpf.find(self.window, "BtnAdd").Click += self._on_add
        wpf.find(self.window, "BtnAddBottom").Click += self._on_add_bottom
        wpf.find(self.window, "BtnRemove").Click += lambda s, e: self._on_selected(self.presenter.remove)
        wpf.find(self.window, "BtnSave").Click += self._on_save
        wpf.find(self.window, "BtnCancel").Click += self._on_cancel
        self.grid.SelectionChanged += self._on_selection_changed
        # Checked and Unchecked bubble, so one pair of handlers on the grid serves every row
        # -- including rows the grid has not realised yet. The delegate is kept because a
        # handler that is only referenced by .NET is a handler Python may collect.
        from System.Windows import RoutedEventHandler
        from System.Windows.Controls.Primitives import ToggleButton

        self._toggled = RoutedEventHandler(self._on_build_toggled)
        self.grid.AddHandler(ToggleButton.CheckedEvent, self._toggled)
        self.grid.AddHandler(ToggleButton.UncheckedEvent, self._toggled)

    def _on_build_toggled(self, sender, args) -> None:
        """A storey ticked or unticked: the one edit that does not go through a binding."""
        box = args.OriginalSource
        if self._filling or getattr(box, "Tag", None) != BUILD_TICK:
            return
        row = box.DataContext
        if getattr(row, "StoreyId", None) is None:
            # The row came back as something other than the Python object it was bound from.
            # The cell takes the selection on mouse-down, before this event, so the selected
            # row is the row whose tick was clicked.
            row = self.grid.SelectedItem
        if getattr(row, "StoreyId", None) is None:
            return
        row.Build = TICKED if box.IsChecked else UNTICKED
        # Through _read_back like every other command, and for the same reason: a refresh is
        # about to redraw the table, and a height typed into the row above and not yet taken
        # would be redrawn as whatever it was before. The tick itself is one of the values
        # _read_back carries across, now that it lives on the row.
        self._read_back()
        # Unticking a storey changes what the footer says and which rows are flagged, and both
        # of those live on objects the grid is bound to. Rebuilding from inside the tick's own
        # event would destroy the control still raising it, so it goes after.
        self._after(self.refresh)

    def _after(self, work) -> None:
        """Run something once the event that asked for it has finished."""
        from System import Action
        from System.Windows.Threading import DispatcherPriority

        self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(work))

    def _selected_id(self) -> str | None:
        item = self.grid.SelectedItem
        return getattr(item, "StoreyId", None) if item is not None else None

    def _command(self, run, *args) -> None:
        """Take what is typed, run the command, redraw. In that order, always."""
        self._read_back()
        problem = run(*args)
        self.refresh()
        if problem:
            self._say(problem)

    def _on_selected(self, run, *extra) -> None:
        """A command about the row the user picked. Nothing selected is worth saying, not
        worth guessing at."""
        storey_id = self._selected_id()
        if storey_id is None:
            self._say("Click a storey in the table first.")
            return
        self._command(run, storey_id, *extra)

    def _on_add(self, sender, args) -> None:
        self._command(self.presenter.add_above, self._selected_id())

    def _on_add_bottom(self, sender, args) -> None:
        self._command(self.presenter.add_below, None)

    def _on_selection_changed(self, sender, args) -> None:
        if self._filling:
            return
        item = self.grid.SelectedItem
        wpf.find(self.window, "SelectionText").Text = (
            f"{item.Name} selected" if item is not None else "")

    def _on_save(self, sender, args) -> None:
        self._read_back()
        self.refresh()
        if not self.presenter.can_save():
            self._say("Fix what is listed below before saving: Revit would refuse this stack.")
            return
        self.saved = True
        self.window.DialogResult = True
        self.window.Close()

    def _on_cancel(self, sender, args) -> None:
        self.window.DialogResult = False
        self.window.Close()

    # ------------------------------------------------------------- the table
    def _read_back(self) -> None:
        """Take every bound row into the schedule, in the order the stack depends on.

        The grid commits a cell on leaving it, so the bound object already carries what was
        typed. Names, plans, repeats and builds first; then the heights bottom-up; then the
        elevations that were retyped. Height and elevation describe the same thing, so the
        order matters: an elevation is an instruction about where a storey sits and is applied
        after the heights it would otherwise be recomputed from.
        """
        if self._filling:
            return
        self.grid.CommitEdit()
        self.presenter.set_default_height(wpf.find(self.window, "DefaultHeight").Text)
        for row in self._rows:
            self.presenter.set_name(row.StoreyId, row.Name)
            self.presenter.set_plan_label(row.StoreyId, row.Plan)
            self.presenter.set_repeat(row.StoreyId, row.Repeat)
            self.presenter.set_build(row.StoreyId, row.Build == TICKED)
        for row in self._ordered_rows():
            if row.Height.strip() and row.Height != row_was(row, "height"):
                self.presenter.set_height(row.StoreyId, row.Height)
        for row in self._ordered_rows():
            if row.Elevation.strip() and row.Elevation != row_was(row, "elevation"):
                self.presenter.set_elevation(row.StoreyId, row.Elevation)

    def _ordered_rows(self):
        """The rows, lowest storey first -- the direction the heights add up in."""
        by_id = {row.StoreyId: row for row in self._rows}
        for storey in self.presenter.schedule.storeys:
            if storey.id in by_id:
                yield by_id[storey.id]

    def refresh(self) -> None:
        """Rebuild the grid from the schedule, keeping the row that was selected."""
        from System.Collections import ArrayList

        self._filling = True
        try:
            keep = self._selected_id()
            choices = ArrayList()
            for label, _fid in self.presenter.plan_choices():
                choices.Add(label)

            self._rows = [StoreyRow(row, choices) for row in self.presenter.rows()]
            for row in self._rows:
                _remember(row)

            items = ArrayList()
            for row in self._rows:
                items.Add(row)
            # §12.7.G: clearing first makes the grid destroy its row containers rather than
            # reuse them, so every cell is read fresh from the new objects.
            self.grid.ItemsSource = None
            self.grid.ItemsSource = items

            # Selection means one thing here: the row the buttons act on. The grid is in
            # Single mode, where touching SelectedItems at all throws.
            if keep is not None:
                for row in self._rows:
                    if row.StoreyId == keep:
                        self.grid.SelectedItem = row
                        break

            self._show_problems()
            self._show_status()
        finally:
            self._filling = False

    # ------------------------------------------------------------ the footer
    def _show_problems(self) -> None:
        from System.Windows import Thickness, Visibility
        from System.Windows.Controls import TextBlock

        host = wpf.find(self.window, "ProblemsHost")
        panel = wpf.find(self.window, "ProblemsPanel")
        host.Children.Clear()
        lines = self.presenter.problem_lines()
        for severity, message in lines:
            line = TextBlock()
            # Never colour alone (§10.4): the severity is spelt out beside the message.
            line.Text = f"{severity}  {message}"
            line.Style = self._style("TextError" if severity == "ERROR" else "TextCaption")
            line.Margin = Thickness(0, 0, 0, 1)
            host.Children.Add(line)
        panel.Visibility = Visibility.Visible if lines else Visibility.Collapsed

    def _show_status(self) -> None:
        severity, word, line = self.presenter.status()
        background, foreground = _BADGE_BRUSH.get(severity, _BADGE_BRUSH["INFO"])
        wpf.find(self.window, "StatusBadgeBorder").Background = self._style(background)
        badge = wpf.find(self.window, "StatusBadge")
        badge.Foreground = self._style(foreground)
        badge.Text = word
        wpf.find(self.window, "StatusLine").Text = line
        wpf.find(self.window, "BtnSave").IsEnabled = self.presenter.can_save()

    def _say(self, message: str) -> None:
        wpf.find(self.window, "StatusLine").Text = message

    def _style(self, key: str):
        return self.window.FindResource(key)

    # -------------------------------------------------------------- showing
    def show(self, owner_handle: int | None = None) -> bool:
        wpf.show_dialog(self.window, owner_handle)
        return self.saved


#: What a row held when the table was drawn, so an edit can be told from a redraw. Kept beside
#: the row rather than in it: a slot the XAML does not bind is a slot that invites a binding.
_WAS: dict[int, tuple[str, str]] = {}


def _remember(row: StoreyRow) -> None:
    _WAS[id(row)] = (row.Height, row.Elevation)


def row_was(row: StoreyRow, which: str) -> str:
    """The value this row was drawn with, or an empty string when it is new."""
    height, elevation = _WAS.get(id(row), ("", ""))
    return height if which == "height" else elevation


def edit_storeys_wpf(presenter: StoreyPresenter, subtitle: str = "",
                     owner_handle: int | None = None) -> bool:
    """Open the storey editor and report whether it was saved."""
    _WAS.clear()
    return StoreyEditorWindow(presenter, subtitle).show(owner_handle)


__all__ = ["BUILD_TICK", "TICKED", "UNTICKED", "StoreyEditorWindow", "StoreyRow",
           "edit_storeys_wpf", "format_mm"]
