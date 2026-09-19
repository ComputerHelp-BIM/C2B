"""The storey editor as a WPF window, driven from Python.

The layout is ``storey_editor.xaml``; this builds the rows into it and wires the buttons.
Everything it decides it asks :class:`~c2b.ui.storey_view.StoreyPresenter`, so this file is
only the part that cannot be tested without WPF -- and is kept small for exactly that reason.

**No data binding.** A building has a dozen storeys, so the rows are made as real controls and
read back through ``.Text``. That is not a shortcut: §12.7.G, H, J, K and Q of the brand guide
are all ways a ``DataGrid`` bound to Python objects fails under pythonnet, from blank cells to
a checkbox that will not tick. None of them can happen to a ``TextBox`` whose text Python put
there and reads back itself.

**Each row acts on itself.** Repeat, Move and Remove are buttons in the row they affect, so
there is never a question of which storey a command is about.
"""
from __future__ import annotations

from typing import Any

from . import theme as t
from . import wpf
from .storey_view import StoreyPresenter

#: Names the layout file gives the controls this module drives.
_BUTTONS = ("BtnAdd", "BtnAddBottom", "BtnSave", "BtnCancel")

_BADGE_BRUSH = {"ERROR": ("BrushErrorBadgeBackground", "BrushErrorBadgeForeground"),
                "WARNING": ("BrushWarningBadgeBackground", "BrushWarningBadgeForeground"),
                "SUCCESS": ("BrushSuccessBadgeBackground", "BrushSuccessBadgeForeground"),
                "INFO": ("BrushInfoBadgeBackground", "BrushInfoBadgeForeground")}

#: The columns of a row, matching ``HeaderRow`` in the layout file. Kept here as one list so a
#: column cannot be widened in the header and left narrow in the rows. A test reads both.
_COLUMNS = (30.0, None, 82.0, 92.0, 168.0, 86.0, 188.0)
_ROW_MIN_WIDTH = 150.0
#: Compact density (§5.4): a data row is 26px of content, as the suite's DataGrid ships.
_ROW_HEIGHT = 26.0


class StoreyEditorWindow:
    """One run of the storey editor.

    A fresh instance per opening, never one held at module scope: the persistent engine keeps
    module globals between presses, and a handler subscribed once per press fires once per
    press it has ever seen (§12.9.2). Building the object in the entry point is the fix, and
    it is a correctness rule rather than a tidiness one.
    """

    def __init__(self, presenter: StoreyPresenter, subtitle: str = "") -> None:
        self.presenter = presenter
        self.saved = False
        self.window = wpf.load_window("storey_editor")
        self._rows_host = wpf.find(self.window, "RowsHost")
        self._fields: dict[str, dict[str, Any]] = {}       # storey id -> its own controls
        self._filling = False                              # so a programmatic edit is not an edit
        if subtitle:
            wpf.find(self.window, "HeaderSubtitle").Text = subtitle
        wpf.find(self.window, "DefaultHeight").Text = f"{presenter.schedule.default_height_mm:.0f}"
        self._wire()
        self.refresh()

    # ----------------------------------------------------------------- wiring
    def _wire(self) -> None:
        for name in _BUTTONS:
            wpf.find(self.window, name)          # fail here, with the name, not at the click
        wpf.find(self.window, "BtnAdd").Click += self._on_add_top
        wpf.find(self.window, "BtnAddBottom").Click += self._on_add_bottom
        wpf.find(self.window, "BtnSave").Click += self._on_save
        wpf.find(self.window, "BtnCancel").Click += self._on_cancel

    def _command(self, run, *args) -> None:
        """Take what is typed, run the command, redraw. In that order, always."""
        self._read_back()
        problem = run(*args)
        self.refresh()
        if problem:
            self._say(problem)

    def _on_add_top(self, sender, args) -> None:
        self._command(self.presenter.add_above)

    def _on_add_bottom(self, sender, args) -> None:
        self._command(self.presenter.add_below)

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
        """Take every field's text into the schedule, in the order the stack depends on.

        Names first, then the heights bottom-up, then the elevations that were retyped. Height
        and elevation describe the same thing, so the order matters: an elevation typed on one
        storey is an instruction about where it sits, and it is applied after the heights it
        would otherwise be recomputed from.
        """
        if self._filling:
            return
        self.presenter.set_default_height(wpf.find(self.window, "DefaultHeight").Text)
        for storey_id, controls in list(self._fields.items()):
            self.presenter.set_name(storey_id, controls["name"].Text)
            plan = controls["plan"]
            if plan.SelectedIndex >= 0:
                self.presenter.set_plan(storey_id, self.presenter.plan_choices()[plan.SelectedIndex][1])
        for storey_id, controls in self._ordered_fields():
            text = controls["height"].Text
            if text.strip() and text != controls["height_was"]:
                self.presenter.set_height(storey_id, text)
        for storey_id, controls in self._ordered_fields():
            text = controls["elevation"].Text
            if text.strip() and text != controls["elevation_was"]:
                self.presenter.set_elevation(storey_id, text)

    def _ordered_fields(self):
        """The fields, lowest storey first -- the direction the heights add up in."""
        for storey in self.presenter.schedule.storeys:
            if storey.id in self._fields:
                yield storey.id, self._fields[storey.id]

    def refresh(self) -> None:
        """Rebuild the table from the schedule. Every row is new, so no handler accumulates."""
        from System.Windows import Thickness, VerticalAlignment
        from System.Windows.Controls import ComboBox, Grid, TextBlock, TextBox

        self._filling = True
        try:
            self._rows_host.Children.Clear()
            self._fields.clear()
            choices = self.presenter.plan_choices()
            for n, row in enumerate(self.presenter.rows()):
                grid = self._row_grid()
                grid.MinHeight = _ROW_HEIGHT
                grid.Margin = Thickness(0, 0, 0, 1)
                # Zebra shading in Off White, never a red tint (§9.8, §16.1), the way the
                # suite's DataGrid alternates its rows.
                grid.Background = self._style("BrushOffWhite" if n % 2 else "BrushPureWhite")

                number = TextBlock()
                number.Text = str(row.number)
                number.Style = self._style("TextMono")
                number.Foreground = self._style("BrushMidGrey")
                number.VerticalAlignment = VerticalAlignment.Center
                number.Margin = Thickness(t.SPACE_SM, 0, 0, 0)
                self._place(Grid, grid, number, 0)

                name = TextBox()
                name.Text = row.name
                name.Style = self._style("InputRowBox")
                name.Margin = Thickness(t.SPACE_SM, 2, t.SPACE_SM, 2)
                self._place(Grid, grid, name, 1)

                height = TextBox()
                height.Text = row.height_text
                height.Style = self._style("InputRowNumberBox")
                height.IsEnabled = not row.is_base
                height.Margin = Thickness(0, 2, t.SPACE_SM, 2)
                height.ToolTip = ("The lowest storey rises from nothing. Set its elevation instead."
                                  if row.is_base else "Rise from the storey below. Everything above moves with it.")
                self._place(Grid, grid, height, 2)

                elevation = TextBox()
                elevation.Text = row.elevation_text
                elevation.Style = self._style("InputRowNumberBox")
                elevation.Margin = Thickness(0, 2, t.SPACE_SM, 2)
                elevation.ToolTip = "Top of the structural slab. The storeys above keep their distance."
                self._place(Grid, grid, elevation, 3)

                plan = ComboBox()
                plan.Style = self._style("InputRowComboBox")
                for label, _ in choices:
                    plan.Items.Add(label)
                plan.SelectedIndex = next((i for i, (label, _) in enumerate(choices)
                                           if label == row.plan_label), 0)
                plan.Margin = Thickness(t.SPACE_SM, 2, t.SPACE_SM, 2)
                plan.ToolTip = "Which drawn floor plan is built on this storey."
                self._place(Grid, grid, plan, 4)

                flag = TextBlock()
                flag.Text = row.flag
                flag.Style = self._style("TextCaption")
                flag.Margin = Thickness(t.SPACE_SM, 0, t.SPACE_SM, 0)
                flag.VerticalAlignment = VerticalAlignment.Center
                if row.severity:
                    flag.Foreground = self._style("BrushErrorRed" if row.severity == "ERROR"
                                                  else "BrushCautionAmber")
                if row.tooltip:
                    flag.ToolTip = row.tooltip
                self._place(Grid, grid, flag, 5)

                self._place(Grid, grid, self._row_actions(row), 6)

                self._rows_host.Children.Add(grid)
                self._fields[row.storey_id] = {"name": name, "height": height, "elevation": elevation,
                                               "plan": plan, "height_was": row.height_text,
                                               "elevation_was": row.elevation_text}
            self._show_problems()
            self._show_status()
        finally:
            self._filling = False

    def _row_actions(self, row):
        """The buttons that act on this row, in the row: move, repeat, remove."""
        from System.Windows import Thickness, VerticalAlignment
        from System.Windows.Controls import Orientation, StackPanel, TextBox

        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        panel.VerticalAlignment = VerticalAlignment.Center
        panel.Margin = Thickness(t.SPACE_XS, 0, 0, 0)

        up = self._row_button("↑", "Move this storey up", "ButtonRowAction",
                              lambda s, e, sid=row.storey_id: self._command(self.presenter.move, sid, +1))
        up.IsEnabled = not row.is_top
        down = self._row_button("↓", "Move this storey down", "ButtonRowAction",
                                lambda s, e, sid=row.storey_id: self._command(self.presenter.move, sid, -1))
        down.IsEnabled = not row.is_base
        panel.Children.Add(up)
        panel.Children.Add(down)

        times = TextBox()
        times.Text = "1"
        times.Style = self._style("InputRowNumberBox")
        times.Width = 34
        times.Margin = Thickness(t.SPACE_SM, 0, 2, 0)
        times.ToolTip = "How many more storeys like this one"
        panel.Children.Add(times)

        repeat = self._row_button("Repeat", "Build this storey's plan this many more times "
                                            "- a typical floor, drawn once", "ButtonSmall",
                                  lambda s, e, sid=row.storey_id, box=times:
                                      self._command(self.presenter.repeat, sid, box.Text))
        panel.Children.Add(repeat)

        panel.Children.Add(self._row_button(
            "✕", "Remove this storey", "ButtonRowDanger",
            lambda s, e, sid=row.storey_id: self._command(self.presenter.remove, sid),
            left=t.SPACE_SM))
        return panel

    def _row_button(self, text: str, tip: str, style: str, on_click, left: int = 0):
        from System.Windows import Thickness
        from System.Windows.Controls import Button

        button = Button()
        button.Content = text
        button.Style = self._style(style)
        button.ToolTip = tip
        button.Margin = Thickness(left, 0, 2, 0)
        button.Click += on_click
        return button

    def _row_grid(self):
        from System.Windows import GridLength, GridUnitType
        from System.Windows.Controls import ColumnDefinition, Grid

        grid = Grid()
        for width in _COLUMNS:
            column = ColumnDefinition()
            column.Width = (GridLength(1, GridUnitType.Star) if width is None
                            else GridLength(width, GridUnitType.Pixel))
            if width is None:
                column.MinWidth = _ROW_MIN_WIDTH
            grid.ColumnDefinitions.Add(column)
        return grid

    @staticmethod
    def _place(Grid, grid, control, column: int) -> None:
        Grid.SetColumn(control, column)
        grid.Children.Add(control)

    def _style(self, key: str):
        return self.window.FindResource(key)

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

    # -------------------------------------------------------------- showing
    def show(self, owner_handle: int | None = None) -> bool:
        wpf.show_dialog(self.window, owner_handle)
        return self.saved


def edit_storeys_wpf(presenter: StoreyPresenter, subtitle: str = "",
                     owner_handle: int | None = None) -> bool:
    """Open the storey editor and report whether it was saved."""
    return StoreyEditorWindow(presenter, subtitle).show(owner_handle)
