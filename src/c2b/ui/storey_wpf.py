"""The storey editor as a WPF window, driven from Python.

The layout is ``storey_editor.xaml``; this fills its ``DataGrid`` and wires the buttons.
Everything it decides it asks :class:`~c2b.ui.storey_view.StoreyPresenter`, so this file is
only the part that cannot be tested without WPF -- and is kept small for exactly that reason.

**WPF only ever sees the string a Python object prints to.** That is the whole of §12.7.G/Q
and it is worth stating plainly, because two releases were spent on the symptoms rather than
the cause. pythonnet hands the binding engine a ``PyObject`` wrapper, whatever the Python
value is. A binding whose target is a string therefore works, because WPF falls back to
``ToString()``; every other target fails **silently**:

* ``CheckBox.IsChecked`` wants ``bool?``, cannot convert a ``PyObject``, and stays unticked --
  so every Build tick rendered empty, and clicking one appeared to untick itself the moment
  the table was redrawn;
* ``ComboBox.SelectedItem`` compares the bound value against the items and never matches one,
  so every "Built from" cell rendered blank.

So the rows handed to the grid are **ExpandoObjects**, not Python objects: every field is a
real .NET value that WPF can convert, compare and display. And nothing is read back through a
binding at all. Every edit is taken from the control the person actually touched -- the
``TextBox`` in ``CellEditEnding``, the ``CheckBox`` in its ``Click``, the ``ComboBox`` in its
``SelectionChanged`` -- which is one direction of marshalling instead of two, and the
direction that is known to work.

**A tick has to change what it is bound to, or it does not stay ticked.** ``ToggleButton``
flips ``IsChecked`` with ``SetCurrentValue``, which deliberately leaves the binding in place,
so the control shows the new state and the *source* still holds the old one. The next thing
that re-evaluates the binding -- a row container recycled as the problems panel opens and the
table resizes, a scroll, a redraw -- reads the source and puts the tick back. Telling the
presenter is not enough: the row object has to be written too.

**The tick is not the selection.** Selection is which rows the buttons act on, and the grid is
in ``Extended`` mode, so ctrl-click and shift-click pick several. Ticking one row of a
selection ticks all of it, which is what makes unticking six storeys six rows of work rather
than six rounds of clicking. Build is still the storey's own value and clicking a row never
changes it.

**A redraw costs the selection anchor.** Replacing ``ItemsSource`` destroys every container,
and with them the row shift-click measures its range from. So a redraw happens only when
something actually changed -- an edit that retypes the same text does nothing at all.
"""
from __future__ import annotations

from typing import Any

from . import wpf
from .storey_view import StoreyPresenter, format_mm

#: Names the layout file gives the controls this module drives.
_BUTTONS = ("BtnUp", "BtnDown", "BtnAdd", "BtnAddBottom", "BtnRemove", "BtnSave", "BtnCancel")

#: Set on the Build tick in the layout so the grid-wide handler can tell it from the
#: ``ToggleButton`` inside a ComboBox's template, which raises the very same routed events.
BUILD_TICK = "BuildTick"
#: And on the "Built from" picker, whose SelectionChanged bubbles up to the grid's own.
PLAN_PICK = "PlanPick"

#: Column header -> the row field it shows, and the presenter call that takes what was typed
#: into it. The header is what the person read when they typed, which makes this table the
#: documentation as well. The field is there so an edit that changed nothing can be told from
#: one that did, and only the second kind redraws.
EDITS = {"Storey": ("Storey", "set_name"),
         "Height mm": ("Height", "set_height"),
         "Elevation mm": ("Elevation", "set_elevation"),
         "Repeat": ("Repeat", "set_repeat")}

_BADGE_BRUSH = {"ERROR": ("BrushErrorBadgeBackground", "BrushErrorBadgeForeground"),
                "WARNING": ("BrushWarningBadgeBackground", "BrushWarningBadgeForeground"),
                "SUCCESS": ("BrushSuccessBadgeBackground", "BrushSuccessBadgeForeground"),
                "INFO": ("BrushInfoBadgeBackground", "BrushInfoBadgeForeground")}


def fields(item: Any) -> Any:
    """An ExpandoObject's members, as the dictionary it keeps them in."""
    from System import Object, String
    from System.Collections.Generic import IDictionary

    return IDictionary[String, Object](item)


def field(item: Any, key: str) -> Any:
    return fields(item)[key]


def set_field(item: Any, key: str, value: Any) -> None:
    """Write a row's own value, which is the half of a tick that WPF does not do for you."""
    fields(item)[key] = value


def grid_row(row, choices: Any) -> Any:
    """One row of the table, as an object WPF can actually read.

    An ``ExpandoObject`` holds real .NET values -- a ``System.Boolean`` for the tick, a
    ``System.String`` for every text cell -- where a Python object of any shape reaches the
    binding engine as a ``PyObject`` that only converts to a string. The keys are the binding
    paths in the XAML and are case-sensitive.

    ``Storey`` and not ``Name``: a dynamic object is asked for its members by name, and giving
    one of them the name of a property half of WPF already has is a question with two answers.
    """
    from System.Dynamic import ExpandoObject

    item = ExpandoObject()
    values = fields(item)
    values["Number"] = str(row.number)
    values["Storey"] = row.name
    values["Height"] = "" if row.is_base else row.height_text
    values["Elevation"] = row.elevation_text
    values["Plan"] = row.plan_label
    values["PlanChoices"] = choices
    values["Repeat"] = str(row.repeat)
    values["Flag"] = row.flag
    values["Build"] = bool(row.build)
    return item


class StoreyEditorWindow:
    """One run of the storey editor.

    A fresh instance per opening, never one held at module scope: the persistent engine keeps
    module globals between presses, and a handler subscribed once per press fires once per
    press it has ever seen (§12.9.2).
    """

    def __init__(self, presenter: StoreyPresenter, subtitle: str = "") -> None:
        from .. import __version__

        self.presenter = presenter
        self.saved = False
        self.window = wpf.load_window("storey_editor")
        self.grid = wpf.find(self.window, "StoreyGrid")
        #: ``(storey_id, item)`` in the order the grid shows them, so a row container's index
        #: is all that is needed to say which storey an edit belongs to.
        self._rows: list[tuple[str, Any]] = []
        self._filling = False              # so a programmatic rebuild is not a user's edit
        self._handlers: list[Any] = []     # a delegate only .NET holds is one Python may collect
        wpf.find(self.window, "VersionBadge").Text = f"v{__version__}"
        if subtitle:
            wpf.find(self.window, "HeaderSubtitle").Text = subtitle
        wpf.find(self.window, "DefaultHeight").Text = f"{presenter.schedule.default_height_mm:.0f}"
        self._wire()
        self.refresh()

    # ----------------------------------------------------------------- wiring
    def _wire(self) -> None:
        from System.Windows import RoutedEventHandler
        from System.Windows.Controls.Primitives import ButtonBase

        for name in _BUTTONS:
            wpf.find(self.window, name)          # fail here, with the name, not at the click
        wpf.find(self.window, "BtnUp").Click += lambda s, e: self._on_selected("move", +1)
        wpf.find(self.window, "BtnDown").Click += lambda s, e: self._on_selected("move", -1)
        wpf.find(self.window, "BtnAdd").Click += self._on_add
        wpf.find(self.window, "BtnAddBottom").Click += self._on_add_bottom
        wpf.find(self.window, "BtnRemove").Click += lambda s, e: self._on_selected("remove")
        wpf.find(self.window, "BtnSave").Click += self._on_save
        wpf.find(self.window, "BtnCancel").Click += self._on_cancel

        # Click and not Checked: Checked is raised by the binding as every row is realised,
        # which made the first draw a storm of edits that each queued another redraw. Click is
        # raised only by a person, and ToggleButton has already flipped IsChecked by then.
        ticked = RoutedEventHandler(self._on_build_clicked)
        self._handlers.append(ticked)
        self.grid.AddHandler(ButtonBase.ClickEvent, ticked)

        # A ComboBox in a cell raises Selector.SelectionChanged, which bubbles to the grid's
        # own. One handler, told apart by what raised it.
        self.grid.SelectionChanged += self._on_selection_changed
        self.grid.CellEditEnding += self._on_cell_edit_ending

    # ------------------------------------------------------- what is selected
    def _row_id(self, item: Any) -> str | None:
        """The storey a bound row belongs to, found by where it sits rather than by reading it."""
        index = self.grid.Items.IndexOf(item)
        return self._rows[index][0] if 0 <= index < len(self._rows) else None

    def _container_index(self, element: Any) -> int | None:
        """Which row of the table holds this control, or None if it is not in one."""
        from System.Windows.Controls import ItemsControl

        container = ItemsControl.ContainerFromElement(self.grid, element)
        if container is None:
            return None
        index = container.GetIndex()
        return index if 0 <= index < len(self._rows) else None

    def _container_id(self, element: Any) -> str | None:
        """The storey whose row container holds this control."""
        index = self._container_index(element)
        return None if index is None else self._rows[index][0]

    def _selected_ids(self) -> list[str]:
        """Every selected storey, in the order the stack has them, lowest first."""
        picked = {self._row_id(item) for item in self.grid.SelectedItems}
        return [s.id for s in self.presenter.schedule.storeys if s.id in picked]

    def _selected_id(self) -> str | None:
        ids = self._selected_ids()
        return ids[0] if ids else None

    # ------------------------------------------------------------- commands
    def _commit(self) -> None:
        """Everything typed and not yet taken, before a command acts on the schedule.

        Two things are outstanding at the moment a button is pressed: the cell the person was
        still editing, and the default height, which is an ordinary TextBox outside the grid
        and so has no CellEditEnding of its own to carry it.
        """
        self.grid.CommitEdit()
        self.presenter.set_default_height(wpf.find(self.window, "DefaultHeight").Text)

    def _command(self, run, *args) -> None:
        """Commit whatever is typed, run the command, redraw. In that order, always."""
        self._commit()
        problem = run(*args)
        self.refresh()
        if problem:
            self._say(problem)

    def _on_selected(self, name: str, *extra) -> None:
        """A command about the rows the user picked, applied to all of them.

        Moving a block has an order: going up, the topmost storey has to move first or it has
        nowhere to go. Going down, the bottom one does.
        """
        ids = self._selected_ids()
        if not ids:
            self._say("Click a storey in the table first. Ctrl-click or shift-click for several.")
            return
        if extra and extra[0] > 0:
            ids = list(reversed(ids))
        run = getattr(self.presenter, name)
        self._commit()
        problems = [p for p in (run(storey_id, *extra) for storey_id in ids) if p]
        self.refresh()
        if problems:
            self._say(problems[0])

    def _on_add(self, sender, args) -> None:
        self._command(self.presenter.add_above, self._selected_id())

    def _on_add_bottom(self, sender, args) -> None:
        self._command(self.presenter.add_below, None)

    def _on_save(self, sender, args) -> None:
        self._commit()
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

    # --------------------------------------------------------- edits in a cell
    def _on_cell_edit_ending(self, sender, args) -> None:
        """What was typed, taken from the TextBox rather than from the bound row.

        The bindings are one way. A cell's editor holds the text the moment it is committed,
        which is the same text a two-way binding would have tried to carry back into a Python
        object -- and this way there is no marshalling step that can quietly do nothing.
        """
        from System.Windows.Controls import DataGridEditAction

        if self._filling or args.EditAction != DataGridEditAction.Commit:
            return
        typed = getattr(args.EditingElement, "Text", None)
        edit = EDITS.get(str(args.Column.Header))
        index = args.Row.GetIndex()
        if typed is None or edit is None or not 0 <= index < len(self._rows):
            return                          # -1 for a row the grid has not realised, and -1
        storey_id, item = self._rows[index]  # into a Python list is the last storey, silently
        shown, call = edit
        # An editor closes whenever focus leaves a cell, whether or not anything was typed in
        # it. Redrawing on those replaced the table between a click and the shift-click meant
        # to extend from it, and took the anchor with it.
        if typed.strip() == str(field(item, shown)).strip():
            return
        problem = getattr(self.presenter, call)(storey_id, typed)
        # After the edit has finished, never during it: a redraw here replaces the very row
        # the grid is still closing an editor on.
        self._after(lambda: self._redraw(problem))

    def _on_build_clicked(self, sender, args) -> None:
        """A storey ticked or unticked. The one edit that is not about the table's shape.

        Ticking a row that is part of a selection ticks the whole selection. Six storeys to
        leave out is then six rows to pick and one click, rather than six clicks that each
        have to land on a 21-pixel box.
        """
        box = args.OriginalSource
        if self._filling or getattr(box, "Tag", None) != BUILD_TICK:
            return
        index = self._container_index(box)
        if index is None:
            return
        ticked = bool(box.IsChecked)
        clicked = self._rows[index][0]
        chosen = set(self._selected_ids())
        targets = chosen if len(chosen) > 1 and clicked in chosen else {clicked}
        for storey_id, item in self._rows:
            if storey_id in targets:
                # The row object, not only the presenter. ToggleButton flipped IsChecked with
                # SetCurrentValue, which leaves the binding alive, so the source still says
                # what it said before and the next re-evaluation puts the tick back.
                set_field(item, "Build", ticked)
                self.presenter.set_build(storey_id, ticked)
        self._show_problems()
        self._show_status()
        if len(targets) > 1:
            # One box was clicked and several changed. A redraw is the only way to be certain
            # the rest of them show it; for a single row it would only cost the anchor that
            # shift-click measures from.
            self._after(lambda: self._redraw(""))

    def _on_selection_changed(self, sender, args) -> None:
        """Two events arrive here: the grid's own, and a plan picker's bubbling up through it."""
        source = args.OriginalSource
        if getattr(source, "Tag", None) == PLAN_PICK:
            index = self._container_index(source)
            picked = source.SelectedItem
            if index is None or picked is None or self._filling:
                return
            storey_id, item = self._rows[index]
            if str(picked) == str(field(item, "Plan")):
                return                      # the picker settling on what it already showed
            self.presenter.set_plan_label(storey_id, str(picked))
            self._after(lambda: self._redraw(""))
            return
        if source is not None and not self._filling:
            self._show_selection()

    def _redraw(self, problem: str) -> None:
        self.refresh()
        if problem:
            self._say(problem)

    def _after(self, work) -> None:
        """Run something once the event that asked for it has finished."""
        from System import Action
        from System.Windows.Threading import DispatcherPriority

        self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(work))

    # ------------------------------------------------------------- the table
    def refresh(self) -> None:
        """Rebuild the grid from the schedule, keeping every row that was selected."""
        from System.Collections import ArrayList

        self._filling = True
        try:
            keep = set(self._selected_ids())
            choices = ArrayList()
            for label, _fid in self.presenter.plan_choices():
                choices.Add(label)

            rows = self.presenter.rows()
            self._rows = [(row.storey_id, grid_row(row, choices)) for row in rows]

            items = ArrayList()
            for _storey_id, item in self._rows:
                items.Add(item)
            # §12.7.G: clearing first makes the grid destroy its row containers rather than
            # reuse them, so every cell is read fresh from the new objects.
            self.grid.ItemsSource = None
            self.grid.ItemsSource = items

            self.grid.SelectedItems.Clear()
            for storey_id, item in self._rows:
                if storey_id in keep:
                    self.grid.SelectedItems.Add(item)

            self._show_problems()
            self._show_status()
        finally:
            self._filling = False
        # Outside the guard: what it says has to match what is now selected, and a redraw that
        # dropped a removed row must not leave the footer claiming it is still there.
        self._show_selection()

    # ------------------------------------------------------------ the footer
    def _show_selection(self) -> None:
        ids = self._selected_ids()
        names = {s.id: s.name for s in self.presenter.schedule.storeys}
        if not ids:
            text = ""
        elif len(ids) == 1:
            text = f"{names.get(ids[0], '')} selected"
        else:
            text = f"{len(ids)} storeys selected"
        wpf.find(self.window, "SelectionText").Text = text

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


def edit_storeys_wpf(presenter: StoreyPresenter, subtitle: str = "",
                     owner_handle: int | None = None) -> bool:
    """Open the storey editor and report whether it was saved."""
    return StoreyEditorWindow(presenter, subtitle).show(owner_handle)


__all__ = ["BUILD_TICK", "EDITS", "PLAN_PICK", "StoreyEditorWindow", "edit_storeys_wpf",
           "field", "fields", "format_mm", "grid_row", "set_field"]
