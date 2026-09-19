"""The finished window in Tkinter, for a machine that cannot show a WPF one."""
from __future__ import annotations

import contextlib
import tkinter as tk
from tkinter import ttk

from . import theme as t
from .elapsed_wpf import CLOSE_AFTER_SECONDS
from .storey_tk import _family


class ElapsedTk(tk.Toplevel):
    """What the run cost, in the plain window."""

    def __init__(self, parent: tk.Misc, report: dict, close_after: int | None = None) -> None:
        super().__init__(parent)
        self._left = CLOSE_AFTER_SECONDS if close_after is None else max(0, int(close_after))
        self.title("CAD to BIM - finished")
        self.configure(background=t.PURE_WHITE)
        self.resizable(False, False)
        self.transient(parent)

        sans = _family(t.FONT_SANS_FALLBACKS)
        body = ttk.Frame(self, padding=(24, 20, 24, 18))
        body.pack(fill="both", expand=True)
        tk.Label(body, text=report.get("headline", ""), background=t.PURE_WHITE,
                 foreground=t.CHARCOAL_BLACK, font=(sans, abs(t.pixels(t.FONT_SIZE_H3)), "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(body, text=report.get("elapsed", "-"), background=t.PURE_WHITE,
                 foreground=t.VIVID_RED, font=(sans, 30, "bold"), anchor="w").pack(fill="x")
        tk.Label(body, text=report.get("caption", ""), background=t.PURE_WHITE,
                 foreground=t.MID_GREY, font=(sans, abs(t.pixels(t.FONT_SIZE_CAPTION))),
                 anchor="w").pack(fill="x")
        tk.Label(body, background=t.PURE_WHITE, foreground=t.MID_GREY, anchor="w",
                 font=(sans, abs(t.pixels(t.FONT_SIZE_CAPTION))),
                 text=f"in the dialogs {report.get('waiting', '-')}   ·   "
                      f"from the click {report.get('total', '-')}").pack(fill="x", pady=(8, 0))
        tk.Label(body, text=report.get("breakdown", ""), background=t.PURE_WHITE,
                 foreground=t.MID_GREY, font=(sans, abs(t.pixels(t.FONT_SIZE_CAPTION))),
                 anchor="w", wraplength=400, justify="left").pack(fill="x", pady=(6, 0))

        tk.Frame(self, height=1, background=t.LIGHT_BORDER).pack(fill="x")
        footer = tk.Frame(self, background=t.OFF_WHITE)
        footer.pack(fill="x")
        self.countdown = tk.Label(footer, text="", background=t.OFF_WHITE, foreground=t.MID_GREY,
                                  font=(sans, abs(t.pixels(t.FONT_SIZE_CAPTION))))
        self.countdown.pack(side="left", padx=16, pady=8)
        tk.Button(footer, text="Close", command=self._close, font=(sans, abs(t.pixels(t.FONT_SIZE_BODY))),
                  background=t.VIVID_RED, foreground=t.PURE_WHITE, activebackground=t.VIVID_RED_HOVER,
                  activeforeground=t.PURE_WHITE, relief="flat", borderwidth=0, padx=20, pady=4,
                  cursor="hand2", highlightthickness=0).pack(side="right", padx=16, pady=8)
        self.bind("<Escape>", lambda e: self._close())
        self._centre_on(parent)
        self._tick()

    def _centre_on(self, parent) -> None:
        """Middle of whatever opened it, or of the screen.

        Tk puts a new Toplevel at the top left of the screen, which for a small dialog that
        appears on its own is somewhere nobody is looking.
        """
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        try:
            if parent is not None and parent.winfo_viewable():
                x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
                y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
            else:
                raise RuntimeError
        except Exception:
            x = (self.winfo_screenwidth() - width) // 2
            y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _tick(self) -> None:
        if self._left <= 0:
            self._close()
            return
        self.countdown.configure(text=f"closing in {self._left}s")
        self._left -= 1
        self._job = self.after(1000, self._tick)

    def _close(self) -> None:
        with contextlib.suppress(Exception):     # already fired, or never scheduled
            self.after_cancel(self._job)
        self.destroy()


def show_elapsed_tk(parent, report: dict, close_after: int | None = None) -> None:
    window = ElapsedTk(parent, report, close_after)
    parent.wait_window(window)
