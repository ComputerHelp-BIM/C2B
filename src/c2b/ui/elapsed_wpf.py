"""The finished window: what the run cost, after it is over.

One figure, big: the time C2B spent working. The parts are underneath in caption size, because
the time a person spent reading a dialog is theirs and putting it in a headline about the
tool's speed flatters the tool when it is short and libels it when it is long.

It closes itself. A window that reports a number and then waits to be dismissed is a window
somebody has to dismiss, and the count is visible so nobody is surprised by it.
"""
from __future__ import annotations

from . import wpf

#: How long the window waits before closing itself. Long enough to read three figures.
CLOSE_AFTER_SECONDS = 12


class ElapsedWindow:
    """One showing of the finished window."""

    def __init__(self, report: dict, close_after: int = CLOSE_AFTER_SECONDS) -> None:
        from .. import __version__

        self.window = wpf.load_window("elapsed")
        wpf.find(self.window, "VersionBadge").Text = f"v{__version__}"
        self._left = max(0, int(close_after))
        self._timer = None
        for control, key in (("HeadlineText", "headline"), ("ElapsedCaption", "caption"),
                             ("ElapsedText", "elapsed"), ("WaitingText", "waiting"),
                             ("TotalText", "total"), ("BreakdownText", "breakdown")):
            wpf.find(self.window, control).Text = str(report.get(key, ""))
        wpf.find(self.window, "BtnClose").Click += self._on_close
        self.window.Loaded += self._on_loaded

    def _on_loaded(self, sender, args) -> None:
        """Start the countdown once the window is up.

        A ``DispatcherTimer`` made anywhere but on the thread that owns the window belongs to
        the wrong dispatcher and never ticks (§12.8.7.4), so it is built here rather than in
        the constructor.
        """
        from System import TimeSpan
        from System.Windows.Threading import DispatcherTimer

        if self._left <= 0:
            return
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromSeconds(1.0)
        self._timer.Tick += self._on_tick
        self._show_countdown()
        self._timer.Start()

    def _on_tick(self, sender, args) -> None:
        self._left -= 1
        if self._left <= 0:
            self._stop()
            self.window.Close()
            return
        self._show_countdown()

    def _show_countdown(self) -> None:
        wpf.find(self.window, "CountdownText").Text = f"closing in {self._left}s"

    def _on_close(self, sender, args) -> None:
        self._stop()
        self.window.Close()

    def _stop(self) -> None:
        """Stop the timer before the window goes.

        A DispatcherTimer holds a reference to its handler, and a handler on a closed window
        is a callback into something that is no longer there (§12.9.2).
        """
        if self._timer is not None:
            self._timer.Stop()
            self._timer.Tick -= self._on_tick
            self._timer = None

    def show(self, owner_handle: int | None = None) -> None:
        wpf.show_dialog(self.window, owner_handle)


def show_elapsed_wpf(report: dict, owner_handle: int | None = None,
                     close_after: int = CLOSE_AFTER_SECONDS) -> None:
    """Show what the run cost."""
    ElapsedWindow(report, close_after).show(owner_handle)
