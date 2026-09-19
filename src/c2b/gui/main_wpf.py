"""The C2B window in WPF, driven from Python.

The layout is ``c2b/ui/main_window.xaml``; this fills it and wires it. What it decides it asks
:class:`~c2b.gui.session.MainPresenter`, which the Tkinter fallback also drives, so the two
windows cannot come to behave differently.

**The pipeline runs on a worker thread**, because a 25 MB drawing takes a minute and a window
that stops repainting looks broken. WPF owns its controls from one thread only, so every
progress line comes back through ``Dispatcher.BeginInvoke`` -- touching a control from the
worker is not a race that shows up sometimes, it is an immediate exception.

**And this class is itself built on a thread WPF will have**, which is what
:func:`c2b.ui.wpf.run_sta` is for. Construct it anywhere else and the ``Window`` constructor
throws before a single control exists.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

from .. import __version__
from ..ui import theme as t
from ..ui import wpf
from .runner import JobResult, run_job, run_verify
from .session import FIELDS, LOG_SEVERITY, MainPresenter

_BADGE_BRUSH = {"ERROR": ("BrushErrorBadgeBackground", "BrushErrorBadgeForeground"),
                "WARNING": ("BrushWarningBadgeBackground", "BrushWarningBadgeForeground"),
                "SUCCESS": ("BrushSuccessBadgeBackground", "BrushSuccessBadgeForeground"),
                "INFO": ("BrushInfoBadgeBackground", "BrushInfoBadgeForeground")}

#: A progress severity -> the brush its line is drawn in. The names are the theme's, and the
#: mapping is the session's, so the two windows colour the same line the same way.
_LOG_BRUSH = {"CHARCOAL_BLACK": "BrushCharcoalBlack", "SUCCESS_GREEN": "BrushSuccessGreen",
              "CAUTION_AMBER": "BrushCautionAmber", "ERROR_RED": "BrushErrorRed",
              "MID_GREY": "BrushMidGrey"}


class C2BWindow:
    """One opening of the C2B window."""

    def __init__(self) -> None:
        self.presenter = MainPresenter()
        self.presenter.load()
        self.worker: threading.Thread | None = None
        self.window = wpf.load_window("main_window")
        self.inputs: dict[str, Any] = {}
        wpf.find(self.window, "VersionBadge").Text = f"v{__version__}"
        self._build_fields()
        self._build_options()
        self._wire()
        self._show_status()

    # ---------------------------------------------------------------- layout
    def _build_fields(self) -> None:
        """The file rows, from the session's field list rather than from markup.

        One list describes them, so a row cannot exist here and be missing from the Tkinter
        window, and adding one is a line of data rather than the same edit made twice.
        """
        from System.Windows import GridLength, GridUnitType, Thickness, VerticalAlignment
        from System.Windows.Controls import Button, Grid, RowDefinition, TextBlock, TextBox

        host = wpf.find(self.window, "FieldsHost")
        for n, f in enumerate(FIELDS):
            row = RowDefinition()
            row.Height = GridLength(1, GridUnitType.Auto)
            host.RowDefinitions.Add(row)

            label = TextBlock()
            label.Text = f.label
            label.Style = self._style("TextH4")
            label.VerticalAlignment = VerticalAlignment.Center
            label.Margin = Thickness(0, 3, t.SPACE_SM, 3)
            self._place(Grid, host, label, n, 0)

            box = TextBox()
            box.Text = self.presenter.values.get(f.key, "")
            box.Style = self._style("InputRowBox")
            box.Margin = Thickness(0, 3, t.SPACE_SM, 3)
            self._place(Grid, host, box, n, 1)
            self.inputs[f.key] = box

            browse = Button()
            browse.Content = "Browse…"
            browse.Style = self._style("ButtonSmall")
            browse.MinWidth = 86
            browse.Margin = Thickness(0, 3, t.SPACE_SM, 3)
            browse.Click += self._picker(f)
            self._place(Grid, host, browse, n, 2)

            hint = TextBlock()
            hint.Text = f.hint
            hint.Style = self._style("TextCaption")
            hint.VerticalAlignment = VerticalAlignment.Center
            self._place(Grid, host, hint, n, 3)

        for key, control in (("beam_depth", "BeamDepth"), ("slab_thk", "SlabThickness")):
            box = wpf.find(self.window, control)
            box.Text = self.presenter.values.get(key, "")
            self.inputs[key] = box

    def _build_options(self) -> None:
        from System.Windows import Thickness, VerticalAlignment
        from System.Windows.Controls import ComboBox, TextBlock

        host = wpf.find(self.window, "OptionsHost")
        for key, label, choices, hint in self.presenter.option_boxes():
            caption = TextBlock()
            caption.Text = label
            caption.Style = self._style("TextCaption")
            caption.VerticalAlignment = VerticalAlignment.Center
            caption.Margin = Thickness(0, 0, t.SPACE_SM, 0)
            host.Children.Add(caption)

            box = ComboBox()
            box.Style = self._style("InputComboBox")
            box.Width = 180
            box.Margin = Thickness(0, 0, t.SPACE_MD, 0)
            for choice in choices:
                box.Items.Add(choice)
            current = self.presenter.values.get(key, "")
            box.SelectedIndex = choices.index(current) if current in choices else 0
            host.Children.Add(box)
            self.inputs[key] = box

            if hint:
                note = TextBlock()
                note.Text = hint
                note.Style = self._style("TextCaption")
                note.VerticalAlignment = VerticalAlignment.Center
                note.Margin = Thickness(0, 0, t.SPACE_LG, 0)
                host.Children.Add(note)

    def _wire(self) -> None:
        wpf.find(self.window, "BtnRun").Click += self._on_run
        wpf.find(self.window, "BtnVerify").Click += self._on_verify
        wpf.find(self.window, "BtnStoreys").Click += self._on_storeys

    # --------------------------------------------------------------- pickers
    def _picker(self, f):
        def handler(sender, args):
            picked = _ask_for_folder(f.label) if f.kind == "folder" else _ask_for_file(f.label, f.filters)
            if picked:
                self.inputs[f.key].Text = picked
        return handler

    def _read_back(self) -> None:
        """Take what is in the window into the presenter, before anything is done with it."""
        for key, control in self.inputs.items():
            if hasattr(control, "SelectedItem"):
                self.presenter.values[key] = str(control.SelectedItem or "")
            else:
                self.presenter.values[key] = control.Text

    # --------------------------------------------------------------- running
    def _on_run(self, sender, args) -> None:
        self._read_back()
        problem = self.presenter.problem()
        if problem:
            self._say("ERROR", "CHECK", problem)
            return
        if self.worker and self.worker.is_alive():
            return
        self.presenter.save()
        settings = self.presenter.job_settings()
        self._start(run_job, (settings,), "Working…  a large drawing can take a minute.")

    def _on_verify(self, sender, args) -> None:
        picked = _ask_for_file("Edited template DXF", (("Template DXF", "*.dxf"),))
        if not picked or (self.worker and self.worker.is_alive()):
            return
        self._start(run_verify, (Path(picked), None), "Checking the edited drawing…")

    def _start(self, fn, fn_args, message: str) -> None:
        self._reset()
        self._say("INFO", "WORKING", message)
        # The triggering button shows the running verb and goes inert while it runs (§11.2).
        run = wpf.find(self.window, "BtnRun")
        run.IsEnabled = False
        run.Content = "Running…"
        wpf.find(self.window, "BtnVerify").IsEnabled = False
        self.worker = threading.Thread(target=self._work, args=(fn, fn_args), daemon=True)
        self.worker.start()

    def _work(self, fn, fn_args) -> None:
        """The pipeline, on the worker thread. Nothing here touches a control."""
        try:
            result = fn(*fn_args, self._report)
        except Exception as ex:                  # run_job never raises; run_verify is newer
            result = JobResult(error=f"{type(ex).__name__}: {ex}")
            self._report("bad", traceback.format_exc(limit=3))
        self._on_ui(lambda: self._finish(result))

    def _report(self, level: str, message: str) -> None:
        """Called from the worker for every progress line."""
        self._on_ui(lambda: self._log(level, message))

    def _on_ui(self, work) -> None:
        """Run something on the thread that owns the controls.

        ``System.Action`` wraps the callable as a real .NET delegate, which is what
        ``BeginInvoke`` takes -- a plain Python callable is not one, and neither is a Python
        class carrying ``__namespace__`` (that only means anything on a class deriving from a
        CLR type). The shipping tools do exactly this.

        ``DispatcherPriority.Background`` rather than ``Send``: a run reports a few hundred
        lines, and a blocking hop per line makes the pipeline wait for the window to paint.
        """
        from System import Action
        from System.Windows.Threading import DispatcherPriority

        self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(work))

    # ----------------------------------------------------------- the reporting
    def _log(self, level: str, message: str) -> None:
        from System.Windows.Controls import TextBlock

        line = TextBlock()
        line.Text = message
        line.Style = self._style("TextMono")
        line.Foreground = self._style(_LOG_BRUSH.get(LOG_SEVERITY.get(level, "MID_GREY"), "BrushMidGrey"))
        if level == "step":
            from System.Windows import FontWeights

            line.FontWeight = FontWeights.SemiBold
            progress = wpf.find(self.window, "Progress")
            progress.Value = min(progress.Value + 1, progress.Maximum)
        wpf.find(self.window, "LogHost").Children.Add(line)
        wpf.find(self.window, "LogScroller").ScrollToEnd()

    def _reset(self) -> None:
        from System.Windows import Visibility

        wpf.find(self.window, "LogHost").Children.Clear()
        wpf.find(self.window, "IssuesHost").Children.Clear()
        wpf.find(self.window, "ActionsHost").Children.Clear()
        wpf.find(self.window, "Progress").Value = 0
        wpf.find(self.window, "NextLabel").Text = ""
        wpf.find(self.window, "BtnStoreys").Visibility = Visibility.Collapsed

    def _finish(self, result: JobResult) -> None:
        from System.Windows import Thickness, Visibility
        from System.Windows.Controls import Button

        self.presenter.result = result
        run = wpf.find(self.window, "BtnRun")
        run.IsEnabled = True
        run.Content = "_Run"
        wpf.find(self.window, "BtnVerify").IsEnabled = True
        wpf.find(self.window, "Progress").Value = 4

        self._show_issues()
        self._show_status()

        next_step = self.presenter.next_step()
        label = wpf.find(self.window, "NextLabel")
        label.Text = f"Next:  {next_step}" if next_step else ""
        label.Foreground = self._style("BrushVividRed" if next_step else "BrushMidGrey")
        # The storey editor is offered on any run that read a drawing. It is where the levels
        # are decided, not a remedy for a run that went wrong.
        wpf.find(self.window, "BtnStoreys").Visibility = (
            Visibility.Visible if self.presenter.can_edit_storeys() else Visibility.Collapsed)

        # What it cost, once the results are on screen behind it.
        if result.timing:
            from ..ui import show_elapsed

            show_elapsed(result.timing, owner_handle=_handle(self.window))

        host = wpf.find(self.window, "ActionsHost")
        for text, path in self.presenter.actions():
            button = Button()
            button.Content = text
            button.Style = self._style("ButtonSmall")
            button.Margin = Thickness(0, 0, t.SPACE_SM, t.SPACE_XS)
            button.Click += self._opener(path)
            host.Children.Add(button)

    def _opener(self, path: Path):
        def handler(sender, args):
            _open(path)
        return handler

    def _show_issues(self) -> None:
        from System.Windows import GridLength, GridUnitType, HorizontalAlignment, Thickness
        from System.Windows.Controls import ColumnDefinition, Grid, TextBlock

        host = wpf.find(self.window, "IssuesHost")
        host.Children.Clear()
        for n, (severity, count, meaning) in enumerate(self.presenter.issue_rows()):
            grid = Grid()
            # The same three widths as the header row in main_window.xaml, less the 16 the
            # header's own margins take: a heading that does not sit over its column is worse
            # than no heading.
            for width in (112.0, 98.0, None):
                column = ColumnDefinition()
                column.Width = (GridLength(1, GridUnitType.Star) if width is None
                                else GridLength(width, GridUnitType.Pixel))
                grid.ColumnDefinitions.Add(column)
            # Zebra shading, Off White, never a red tint (§9.8, §16.1).
            grid.Background = self._style("BrushOffWhite" if n % 2 else "BrushPureWhite")

            word = TextBlock()
            word.Text = severity
            word.Style = self._style("TextCaption")
            word.Margin = Thickness(t.SPACE_SM, 4, 0, 4)
            word.Foreground = self._style("BrushErrorRed" if severity.upper() == "ERROR"
                                          else "BrushCautionAmber")
            self._place(Grid, grid, word, None, 0)

            number = TextBlock()
            number.Text = str(count)
            number.Style = self._style("TextMono")
            number.HorizontalAlignment = HorizontalAlignment.Center
            number.Margin = Thickness(0, 4, 0, 4)
            self._place(Grid, grid, number, None, 1)

            what = TextBlock()
            what.Text = meaning
            what.Style = self._style("TextCaption")
            what.Margin = Thickness(t.SPACE_SM, 4, t.SPACE_SM, 4)
            self._place(Grid, grid, what, None, 2)

            host.Children.Add(grid)

    def _show_status(self) -> None:
        severity, word, line = self.presenter.summary()
        self._say(severity, word, line)

    def _say(self, severity: str, word: str, line: str) -> None:
        background, foreground = _BADGE_BRUSH.get(severity, _BADGE_BRUSH["INFO"])
        wpf.find(self.window, "StatusBadgeBorder").Background = self._style(background)
        badge = wpf.find(self.window, "StatusBadge")
        badge.Foreground = self._style(foreground)
        badge.Text = word
        wpf.find(self.window, "StatusLine").Text = line

    # --------------------------------------------------------------- storeys
    def _on_storeys(self, sender, args) -> None:
        """Add, remove, move, repeat and size the building's storeys, then run again."""
        from ..storeys import StoreySchedule
        from ..ui import edit_storeys

        result = self.presenter.result
        path = result.storeys_json if result else None
        if not path or not Path(path).exists():
            self._say("WARNING", "CHECK", "Run a drawing first: the storeys are seeded from it.")
            return
        try:
            schedule = StoreySchedule.load(path)
        except Exception as ex:
            self._say("ERROR", "ERROR", f"Could not read {Path(path).name}: {ex}")
            return

        plans = result.plan_floors
        drawing = Path(self.presenter.values.get("drawing", "") or "the drawing").name
        subtitle = (f"{len(schedule)} storeys from {len(plans)} floor "
                    f"{'plan' if len(plans) == 1 else 'plans'} in {drawing}. "
                    "Repeat a storey to build a typical floor more than once.")
        try:
            saved = edit_storeys(schedule, plan_floors=plans, subtitle=subtitle,
                                 owner_handle=_handle(self.window))
        except Exception as ex:
            self._say("ERROR", "ERROR", f"The storey editor could not open: {ex}")
            return
        if not saved:
            return
        schedule.save(path)
        # The levels the drawing was run with have changed, so a workbook chosen on an earlier
        # run would now contradict them. The storeys are the source of truth from here.
        self.inputs["levels"].Text = ""
        self._on_run(sender, args)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _place(Grid, grid, control, row: int | None, column: int) -> None:
        if row is not None:
            Grid.SetRow(control, row)
        Grid.SetColumn(control, column)
        grid.Children.Add(control)

    def _style(self, key: str):
        return self.window.FindResource(key)

    def show(self) -> None:
        """Run the window until it is closed.

        ``ShowDialog`` and not ``Application().Run``. A ``Application`` is a process-wide
        singleton -- a second one throws, and inside Revit there is already one -- while
        ``ShowDialog`` pumps its own nested message loop and needs no application object at
        all. It is also what every tool in the suite uses, which is the stronger argument:
        the first build called ``Application().Run`` and the window never appeared.
        """
        self.window.ShowDialog()


def _handle(window) -> int | None:
    from System.Windows.Interop import WindowInteropHelper

    try:
        return int(WindowInteropHelper(window).Handle)
    except Exception:
        return None


def _ask_for_file(title: str, filters) -> str:
    from Microsoft.Win32 import OpenFileDialog

    dialog = OpenFileDialog()
    dialog.Title = title
    dialog.Filter = "|".join(f"{name}|{pattern}" for name, pattern in (*filters, ("All files", "*.*")))
    return dialog.FileName if dialog.ShowDialog() else ""


def _ask_for_folder(title: str) -> str:
    """A folder, through whichever picker this .NET has.

    ``OpenFolderDialog`` arrived in .NET 8. Older runtimes get ``OpenFileDialog`` pointed at a
    folder, and the chosen file's folder is what comes back -- clumsier, but it is a picker
    rather than an error, and the machines this runs on are not all new.
    """
    try:
        from Microsoft.Win32 import OpenFolderDialog

        dialog = OpenFolderDialog()
        dialog.Title = title
        return dialog.FolderName if dialog.ShowDialog() else ""
    except ImportError:
        from Microsoft.Win32 import OpenFileDialog

        dialog = OpenFileDialog()
        dialog.Title = f"{title} - pick any file in the folder"
        dialog.CheckFileExists = False
        dialog.FileName = "this folder"
        return str(Path(dialog.FileName).parent) if dialog.ShowDialog() else ""


def _open(path: Path) -> None:
    """Open a file or folder in whatever the operating system uses."""
    import os

    try:
        os.startfile(str(path))
    except Exception:
        import subprocess

        subprocess.run(["explorer", str(path)], check=False)


def main() -> None:
    wpf.run_sta(lambda: C2BWindow().show())
