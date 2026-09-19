"""The storey editor in Tkinter, for a machine that cannot show a WPF window.

WPF is the storey editor. This is the same editor when pythonnet is not installed or the tool
is being run somewhere that is not Windows -- which includes every machine C2B is developed
and tested on, so it is not a token fallback: it is the window that gets used the most.

It drives the same :class:`~c2b.ui.storey_view.StoreyPresenter`, so what it does is what the
WPF window does, and it wears the brand tokens, so it looks like the same tool. What it cannot
have is the control templates: Tk draws its own widgets, and fighting that produces something
that looks wrong in a different way. Colour, type and spacing carry the brand here.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import theme as t
from .storey_view import StoreyPresenter


def _family(candidates) -> str:
    """The first of the brand's fallback chain this machine actually has.

    Tk takes one family, not a chain, and silently substitutes something arbitrary for a name
    it does not know -- so the chain is walked here instead (§4.1: the fallback is mandatory).
    """
    try:
        installed = {name.lower() for name in tkfont.families()}
    except tk.TclError:                                   # pragma: no cover - no display
        return candidates[-1]
    for name in candidates:
        if name.lower() in installed:
            return name
    return candidates[-1]


class StoreyEditorTk(tk.Toplevel):
    """The storey editor as a modal Tk window."""

    def __init__(self, parent: tk.Misc, presenter: StoreyPresenter, subtitle: str = "") -> None:
        super().__init__(parent)
        self.presenter = presenter
        self.saved = False
        self._fields: dict[str, dict] = {}
        self._filling = False
        self.title(t.display_name("Storey Editor"))
        self.configure(background=t.PURE_WHITE)
        self.minsize(820, 520)
        self.transient(parent)

        sans, mono = _family(t.FONT_SANS_FALLBACKS), _family(t.FONT_MONO_FALLBACKS)
        self._f_body = (sans, abs(t.pixels(t.FONT_SIZE_BODY)))
        self._f_h2 = (sans, abs(t.pixels(t.FONT_SIZE_H2)), "bold")
        self._f_h3 = (sans, abs(t.pixels(t.FONT_SIZE_H3)), "bold")
        self._f_small = (sans, abs(t.pixels(t.FONT_SIZE_SMALL)))
        self._f_caption = (sans, abs(t.pixels(t.FONT_SIZE_CAPTION)))
        self._f_mono = (mono, abs(t.pixels(t.FONT_SIZE_CODE)))
        self._styles()
        self._build(subtitle)
        self.refresh()
        self._centre_on(parent)
        self.grab_set()

    def _centre_on(self, parent) -> None:
        """Middle of whatever opened it. Tk puts a new Toplevel at the screen's top left."""
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

    # ---------------------------------------------------------------- layout
    def _styles(self) -> None:
        style = ttk.Style(self)
        style.configure("C2B.TFrame", background=t.PURE_WHITE)
        style.configure("C2BBar.TFrame", background=t.OFF_WHITE)
        style.configure("C2BHead.TFrame", background=t.CHARCOAL_BLACK)
        style.configure("C2B.TLabel", background=t.PURE_WHITE, foreground=t.MID_GREY, font=self._f_caption)
        style.configure("C2BBody.TLabel", background=t.PURE_WHITE, foreground=t.CHARCOAL_BLACK, font=self._f_body)
        style.configure("C2BMono.TLabel", background=t.PURE_WHITE, foreground=t.CHARCOAL_BLACK, font=self._f_mono)
        style.configure("C2BError.TLabel", background=t.PURE_WHITE, foreground=t.ERROR_RED, font=self._f_caption)
        style.configure("C2BBar.TLabel", background=t.OFF_WHITE, foreground=t.MID_GREY, font=self._f_caption)
        style.configure("C2BTitle.TLabel", background=t.CHARCOAL_BLACK, foreground=t.PURE_WHITE, font=self._f_h2)
        style.configure("C2BSub.TLabel", background=t.CHARCOAL_BLACK, foreground=t.SILVER_STEEL, font=self._f_caption)
        style.configure("C2BCol.TLabel", background=t.CHARCOAL_BLACK, foreground=t.PURE_WHITE, font=self._f_h3)
        style.configure("C2B.TButton", font=self._f_body, padding=(t.SPACE_MD, 6))

    def _filled_button(self, parent, text, fill, hover, command, width=None):
        """A coloured button that is actually coloured.

        ttk's Windows themes draw a TButton from a theme element and ignore ``background`` and
        ``foreground`` entirely, so a styled Primary or Danger button comes out as a bare box
        with no label -- which is exactly what the red rectangles in the screenshots were. A
        plain ``tk.Button`` takes its colours, so the two that must be coloured use one.
        """
        button = tk.Button(parent, text=text, command=command, font=self._f_body,
                           background=fill, foreground=t.PURE_WHITE,
                           activebackground=hover, activeforeground=t.PURE_WHITE,
                           disabledforeground=t.SILVER_STEEL,
                           relief="flat", borderwidth=0, padx=t.SPACE_MD, pady=5,
                           cursor="hand2", highlightthickness=0)
        if width:
            button.configure(width=width)
        return button

    def _build(self, subtitle: str) -> None:
        header = ttk.Frame(self, style="C2BHead.TFrame", padding=(t.SPACE_MD, 13))
        header.pack(fill="x")
        ttk.Label(header, text=t.display_name("Storey Editor"), style="C2BTitle.TLabel").pack(anchor="w")
        ttk.Label(header, style="C2BSub.TLabel", wraplength=780,
                  text=subtitle or "The storeys of the building, and how far apart they are."
                  ).pack(anchor="w", pady=(2, 0))
        tk.Frame(self, height=3, background=t.VIVID_RED).pack(fill="x")

        bar = ttk.Frame(self, style="C2B.TFrame", padding=(t.SPACE_MD, 12, t.SPACE_MD, t.SPACE_SM))
        bar.pack(fill="x")
        buttons = ttk.Frame(bar, style="C2B.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Add on top", style="C2B.TButton",
                   command=lambda: self._command(self.presenter.add_above)).pack(side="left")
        ttk.Button(buttons, text="Add at the bottom", style="C2B.TButton",
                   command=lambda: self._command(self.presenter.add_below)).pack(side="left", padx=(t.SPACE_SM, 0))
        ttk.Label(buttons, text="mm tall", style="C2B.TLabel").pack(side="right")
        self.default_height = tk.StringVar(value=f"{self.presenter.schedule.default_height_mm:.0f}")
        ttk.Entry(buttons, textvariable=self.default_height, width=7, justify="right",
                  font=self._f_mono).pack(side="right", padx=(0, 6))
        ttk.Label(buttons, text="New storeys are", style="C2B.TLabel").pack(side="right", padx=(0, 6))

        ttk.Label(bar, style="C2B.TLabel", wraplength=900,
                  text="Every storey rises from the one below it. Type a height or an elevation and the "
                       "other follows. Repeat a storey to build one drawn plan more than once."
                  ).pack(fill="x", pady=(8, 0))

        columns = tk.Frame(self, background=t.CHARCOAL_BLACK)
        columns.pack(fill="x", padx=t.SPACE_MD)
        for text, width, anchor in (("Build", 5, "w"), ("#", 3, "w"), ("Storey", 20, "w"),
                                    ("Height", 9, "e"), ("Elevation", 11, "e"),
                                    ("Built from", 18, "w"), ("Rpt", 4, "e"),
                                    ("Note", 9, "w"), ("This storey", 24, "w")):
            tk.Label(columns, text=text, width=width, anchor=anchor, background=t.CHARCOAL_BLACK,
                     foreground=t.PURE_WHITE, font=self._f_h3, padx=4, pady=4).pack(side="left")

        body = ttk.Frame(self, style="C2B.TFrame")
        body.pack(fill="both", expand=True, padx=t.SPACE_MD, pady=(4, 0))
        self.canvas = tk.Canvas(body, background=t.PURE_WHITE, highlightthickness=0)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.rows_host = ttk.Frame(self.canvas, style="C2B.TFrame")
        self.rows_host.bind("<Configure>",
                            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.rows_host, anchor="nw")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.problems = ttk.Frame(self, style="C2B.TFrame", padding=(t.SPACE_MD, t.SPACE_SM))
        self.problems.pack(fill="x")

        footer = ttk.Frame(self, style="C2BBar.TFrame", padding=(t.SPACE_MD, 12))
        footer.pack(fill="x")
        self.badge = tk.Label(footer, text="READY", font=self._f_mono, padx=t.SPACE_SM, pady=2)
        self.badge.pack(side="left")
        self.status = ttk.Label(footer, text="", style="C2BBar.TLabel")
        self.status.pack(side="left", padx=(t.SPACE_SM, 0))
        self.save_btn = self._filled_button(footer, "Save the storeys", t.VIVID_RED,
                                            t.VIVID_RED_HOVER, self._save)
        self.save_btn.pack(side="right")
        ttk.Button(footer, text="Cancel", style="C2B.TButton", command=self._cancel).pack(side="right", padx=(0, t.SPACE_SM))
        self.bind("<Escape>", lambda e: self._cancel())

    # -------------------------------------------------------------- the table
    def refresh(self) -> None:
        self._filling = True
        try:
            for child in self.rows_host.winfo_children():
                child.destroy()
            self._fields.clear()
            choices = self.presenter.plan_choices()
            labels = [label for label, _ in choices]
            for row in self.presenter.rows():
                line = ttk.Frame(self.rows_host, style="C2B.TFrame")
                line.pack(fill="x", pady=1)
                build = tk.BooleanVar(value=row.build)
                tk.Checkbutton(line, variable=build, width=3, background=t.PURE_WHITE,
                               activebackground=t.PURE_WHITE,
                               selectcolor=t.PURE_WHITE).pack(side="left")
                tk.Label(line, text=str(row.number), width=3, anchor="w", background=t.PURE_WHITE,
                         foreground=t.MID_GREY, font=self._f_mono, padx=4).pack(side="left")

                name = tk.StringVar(value=row.name)
                ttk.Entry(line, textvariable=name, width=20, font=self._f_small).pack(side="left", padx=2)
                height = tk.StringVar(value=row.height_text)
                entry = ttk.Entry(line, textvariable=height, width=9, justify="right", font=self._f_mono)
                entry.pack(side="left", padx=2)
                if row.is_base:
                    entry.state(["disabled"])
                elevation = tk.StringVar(value=row.elevation_text)
                ttk.Entry(line, textvariable=elevation, width=11, justify="right",
                          font=self._f_mono).pack(side="left", padx=2)
                plan = tk.StringVar(value=row.plan_label)
                ttk.Combobox(line, textvariable=plan, values=labels, width=18, state="readonly",
                             font=self._f_small).pack(side="left", padx=2)
                repeat = tk.StringVar(value=str(row.repeat))
                ttk.Entry(line, textvariable=repeat, width=4, justify="right",
                          font=self._f_mono).pack(side="left", padx=2)
                tk.Label(line, anchor="w", width=9, background=t.PURE_WHITE, padx=4, font=self._f_caption,
                         foreground=(t.ERROR_RED if row.severity == "ERROR" else
                                     t.CAUTION_AMBER if row.severity == "WARNING" else t.MID_GREY),
                         text=row.flag).pack(side="left")

                # This row's own buttons: no selection to keep track of, and no doubt about
                # which storey a command is about.
                sid = row.storey_id
                actions = ttk.Frame(line, style="C2B.TFrame")
                actions.pack(side="left", padx=(4, 0))
                up = ttk.Button(actions, text="\u2191", width=2, style="C2B.TButton",
                                command=lambda s=sid: self._command(self.presenter.move, s, +1))
                up.pack(side="left")
                down = ttk.Button(actions, text="\u2193", width=2, style="C2B.TButton",
                                  command=lambda s=sid: self._command(self.presenter.move, s, -1))
                down.pack(side="left", padx=(2, 0))
                if row.is_top:
                    up.state(["disabled"])
                if row.is_base:
                    down.state(["disabled"])
                times = tk.StringVar(value="1")
                ttk.Entry(actions, textvariable=times, width=3, justify="right",
                          font=self._f_mono).pack(side="left", padx=(t.SPACE_SM, 2))
                ttk.Button(actions, text="Repeat", style="C2B.TButton",
                           command=lambda s=sid, box=times: self._command(self.presenter.repeat, s, box.get())
                           ).pack(side="left")
                self._filled_button(actions, "\u2715", t.ERROR_RED, t.ERROR_RED_HOVER,
                                    lambda s=sid: self._command(self.presenter.remove, s), width=2
                                    ).pack(side="left", padx=(t.SPACE_SM, 0))

                self._fields[row.storey_id] = {"name": name, "height": height, "elevation": elevation,
                                               "plan": plan, "repeat": repeat, "build": build,
                                               "height_was": row.height_text,
                                               "elevation_was": row.elevation_text}
            self._show_problems()
            self._show_status()
        finally:
            self._filling = False

    def _read_back(self) -> None:
        """Every field into the schedule: names, then heights bottom-up, then retyped elevations."""
        if self._filling:
            return
        choices = dict(self.presenter.plan_choices())
        for storey_id, f in list(self._fields.items()):
            self.presenter.set_name(storey_id, f["name"].get())
            self.presenter.set_plan(storey_id, choices.get(f["plan"].get()))
            self.presenter.set_repeat(storey_id, f["repeat"].get())
            self.presenter.set_build(storey_id, bool(f["build"].get()))
        for storey_id, f in self._ordered_fields():
            text = f["height"].get()
            if text.strip() and text != f["height_was"]:
                self.presenter.set_height(storey_id, text)
        for storey_id, f in self._ordered_fields():
            text = f["elevation"].get()
            if text.strip() and text != f["elevation_was"]:
                self.presenter.set_elevation(storey_id, text)
        self.presenter.set_default_height(self.default_height.get())

    def _ordered_fields(self):
        for storey in self.presenter.schedule.storeys:
            if storey.id in self._fields:
                yield storey.id, self._fields[storey.id]

    # ------------------------------------------------------------- commands
    def _command(self, run, *args) -> None:
        self._read_back()
        problem = run(*args)
        self.refresh()
        if problem:
            self.status.configure(text=problem)

    def _save(self) -> None:
        self._read_back()
        self.refresh()
        if not self.presenter.can_save():
            self.status.configure(text="Fix what is listed above before saving: Revit would refuse this stack.")
            return
        self.saved = True
        self.destroy()

    def _cancel(self) -> None:
        self.saved = False
        self.destroy()

    # --------------------------------------------------------------- footer
    def _show_problems(self) -> None:
        for child in self.problems.winfo_children():
            child.destroy()
        for severity, message in self.presenter.problem_lines()[:12]:
            ttk.Label(self.problems, text=f"{severity}  {message}", wraplength=820,
                      style="C2BError.TLabel" if severity == "ERROR" else "C2B.TLabel").pack(anchor="w")

    def _show_status(self) -> None:
        severity, word, line = self.presenter.status()
        background, foreground, _ = t.BADGE.get(severity, t.BADGE["INFO"])
        self.badge.configure(text=word, background=background, foreground=foreground)
        self.status.configure(text=line)
        self.save_btn.configure(state="normal" if self.presenter.can_save() else "disabled",
                                background=t.VIVID_RED if self.presenter.can_save() else t.LIGHT_BORDER)


def edit_storeys_tk(parent, presenter: StoreyPresenter, subtitle: str = "") -> bool:
    """Open the storey editor and report whether it was saved."""
    window = StoreyEditorTk(parent, presenter, subtitle)
    parent.wait_window(window)
    return window.saved
