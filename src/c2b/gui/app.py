"""The C2B window.

Plain Tkinter, which ships with Python on Windows, so a drafter needs nothing installed
beyond C2B itself. The pipeline runs on a worker thread and reports through a queue, so the
window stays responsive on a 25 MB drawing.
"""
from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from ..ui import theme as t
from .runner import COLUMN_SIZE_DEFAULT, JobResult, run_job, run_verify
from .session import FIELDS, KEYS, UNITS, MainPresenter

#: The brand tokens, by the name the progress log knows each severity as (§3.3).
COLORS = {"step": t.CHARCOAL_BLACK, "good": t.SUCCESS_GREEN, "warn": t.CAUTION_AMBER,
          "bad": t.ERROR_RED, "info": t.MID_GREY}


def _open(path: Path) -> None:
    """Open a file or folder in whatever the operating system uses."""
    path = Path(path)
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as ex:
        messagebox.showerror("C2B", f"Could not open {path}\n\n{ex}")


class C2BWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"C2B  —  CAD to BIM  {__version__}")
        self.geometry("980x720")
        self.minsize(860, 620)
        self.queue: queue.Queue = queue.Queue()
        self.result: JobResult | None = None
        self.worker: threading.Thread | None = None
        self.presenter = MainPresenter()
        self.vars = {k: tk.StringVar() for k in KEYS}
        self.vars["units"].set(UNITS[0])
        self.vars["col_size"].set(COLUMN_SIZE_DEFAULT)
        self._build()
        self._load_settings()
        self.after(80, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Run.TButton", font=("Segoe UI", 11, "bold"), padding=8)
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Next.TLabel", font=("Segoe UI", 10, "bold"), foreground="#1A5FB4")

        top = ttk.Frame(self, padding=(14, 12, 14, 6))
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        # The five file rows come from the shared field list, so this window and the WPF one
        # ask for the same things in the same order and neither can gain a row alone.
        for n, f in enumerate(FIELDS):
            self._row(top, n, f)

        opts = ttk.Frame(top)
        opts.grid(row=len(FIELDS), column=1, columnspan=3, sticky="w", pady=(6, 0))
        for key, label, choices, hint in self.presenter.option_boxes():
            ttk.Label(opts, text=f"{label}:").pack(side="left")
            ttk.Combobox(opts, textvariable=self.vars[key], values=choices, width=16,
                         state="readonly").pack(side="left", padx=(6, 8))
            if hint:
                ttk.Label(opts, text=hint, foreground=COLORS["info"]).pack(side="left", padx=(0, 18))

        # A beam or a slab the drawing never sizes cannot go into Revit without one, and
        # dropping it loses the member. Typed once, remembered, and the run says how many used it.
        sizes = ttk.Frame(top)
        sizes.grid(row=len(FIELDS) + 1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(sizes, text="When the drawing gives no size —  beam depth:").pack(side="left")
        ttk.Entry(sizes, textvariable=self.vars["beam_depth"], width=8, justify="right").pack(side="left", padx=(6, 4))
        ttk.Label(sizes, text="mm     slab thickness:").pack(side="left")
        ttk.Entry(sizes, textvariable=self.vars["slab_thk"], width=8, justify="right").pack(side="left", padx=(6, 4))
        ttk.Label(sizes, text="mm     leave empty to leave those members out of the Revit model",
                  foreground="#6B6B6B").pack(side="left")

        # The buttons get their own strip on the window rather than a cell of the entry grid:
        # inside the grid a wider option box pushes them past the window edge and out of sight.
        run_row = ttk.Frame(self, padding=(14, 10, 14, 0))
        run_row.pack(fill="x")
        self.run_btn = ttk.Button(run_row, text="Run", style="Run.TButton", command=self.start)
        self.run_btn.pack(side="left")
        self.verify_btn = ttk.Button(run_row, text="Re-check an edited template DXF", command=self.start_verify)
        self.verify_btn.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=4)
        self.progress.pack(fill="x", padx=14, pady=(10, 4))

        body = ttk.Panedwindow(self, orient="vertical")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        log_frame = ttk.Labelframe(body, text="Progress", padding=6)
        self.log = tk.Text(log_frame, height=12, wrap="word", font=("Consolas", 9), background="#FBFBFB", relief="flat")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for name, color in COLORS.items():
            self.log.tag_configure(name, foreground=color)
        self.log.tag_configure("step", font=("Consolas", 9, "bold"), foreground=COLORS["step"])
        body.add(log_frame, weight=3)

        issues_frame = ttk.Labelframe(body, text="Things to check", padding=6)
        cols = ("severity", "count", "what")
        self.issues = ttk.Treeview(issues_frame, columns=cols, show="headings", height=7)
        for col, text, width in (("severity", "", 70), ("count", "How many", 80), ("what", "What it means", 700)):
            self.issues.heading(col, text=text)
            self.issues.column(col, width=width, anchor="w" if col == "what" else "center")
        iscroll = ttk.Scrollbar(issues_frame, command=self.issues.yview)
        self.issues.configure(yscrollcommand=iscroll.set)
        self.issues.tag_configure("ERROR", background="#FDECEA")
        self.issues.tag_configure("WARNING", background="#FFF6E5")
        self.issues.pack(side="left", fill="both", expand=True)
        iscroll.pack(side="right", fill="y")
        body.add(issues_frame, weight=2)

        # The next step gets a strip of its own. A drafter reading a log of forty lines cannot
        # tell which one is addressed to them, so the single thing to do next is said here.
        self.next_frame = ttk.Frame(self, padding=(14, 6, 14, 0))
        self.next_frame.pack(fill="x")
        self.next_label = ttk.Label(self.next_frame, text="", style="Next.TLabel", anchor="w", wraplength=980)
        self.next_label.pack(side="left", fill="x", expand=True)
        self.storeys_btn = ttk.Button(self.next_frame, text="Storeys…", command=self._edit_storeys)

        self.actions = ttk.Frame(self, padding=(14, 0, 14, 12))
        self.actions.pack(fill="x")
        self.status = ttk.Label(self, text="Pick a client drawing and press Run.", anchor="w", padding=(16, 6))
        self.status.pack(fill="x")

    def _row(self, parent, row: int, f) -> None:
        ttk.Label(parent, text=f.label, style="Head.TLabel").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        ttk.Entry(parent, textvariable=self.vars[f.key]).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(parent, text="Browse…", width=11,
                   command=lambda f=f: self._pick(f)).grid(row=row, column=2, padx=(8, 0))
        ttk.Label(parent, text=f.hint, foreground=COLORS["info"]).grid(row=row, column=3, sticky="w", padx=(10, 0))

    # -------------------------------------------------------------- pickers
    def _pick(self, f) -> None:
        """One picker for every field. Tk wants space-separated patterns, not semicolons."""
        if f.kind == "folder":
            path = filedialog.askdirectory(title=f.label)
        else:
            types = [(name, pattern.replace(";", " ")) for name, pattern in f.filters]
            path = filedialog.askopenfilename(title=f.label, filetypes=[*types, ("All files", "*.*")])
        if path:
            self.vars[f.key].set(path)
            if f.key == "drawing":
                self.status.configure(text=f"Ready: {Path(path).name}")

    # --------------------------------------------------------------- running
    def start(self) -> None:
        self._sync_to_presenter()
        problem = self.presenter.problem()
        if problem:
            messagebox.showwarning("C2B", problem)
            return
        if self.worker and self.worker.is_alive():
            return
        self._save_settings()
        self._reset()
        settings = self.presenter.job_settings()
        self.status.configure(text="Working…  a large drawing can take a minute.")
        self.worker = threading.Thread(target=self._work, args=(run_job, (settings,)), daemon=True)
        self.worker.start()

    def start_verify(self) -> None:
        path = filedialog.askopenfilename(title="Edited template DXF", filetypes=[("Template DXF", "*.dxf"), ("All files", "*.*")])
        if not path:
            return
        if self.worker and self.worker.is_alive():
            return
        self._reset()
        self.status.configure(text="Checking the edited drawing…")
        self.worker = threading.Thread(target=self._work, args=(run_verify, (Path(path), None)), daemon=True)
        self.worker.start()

    def _work(self, fn, args) -> None:
        result = fn(*args, self._report)
        self.queue.put(("done", result))

    def _report(self, level: str, message: str) -> None:
        self.queue.put(("log", (level, message)))

    def _reset(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.issues.delete(*self.issues.get_children())
        for child in self.actions.winfo_children():
            child.destroy()
        self.progress.configure(value=0)
        self.run_btn.state(["disabled"])
        self.verify_btn.state(["disabled"])

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    level, message = payload
                    self.log.configure(state="normal")
                    self.log.insert("end", message + "\n", level)
                    self.log.see("end")
                    self.log.configure(state="disabled")
                    if level == "step":
                        self.progress.step(1)
                else:
                    self._finish(payload)
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _finish(self, result: JobResult) -> None:
        self.result = result
        self.run_btn.state(["!disabled"])
        self.verify_btn.state(["!disabled"])
        self.progress.configure(value=4)
        for severity, code, count, meaning in result.issues[:200]:
            self.issues.insert("", "end", values=(severity.title(), count, meaning or code), tags=(severity,))
        self.presenter.result = result
        severity, _word, line = self.presenter.summary()
        self.status.configure(text=line, foreground={"ERROR": COLORS["bad"], "WARNING": COLORS["warn"],
                                                     "SUCCESS": COLORS["good"]}.get(severity, COLORS["info"]))
        self.next_label.configure(text=f"Next:  {result.next_step}" if result.next_step else "")
        # The storey editor is always offered once a drawing has been read. It is not a remedy
        # for a missing elevation any more -- it is where the building's levels are decided, and
        # a drafter reaches for it on a run that went perfectly as often as on one that did not.
        self.storeys_btn.pack_forget()
        if self.presenter.can_edit_storeys():
            self.storeys_btn.pack(side="right", padx=(10, 0))

        for label, path in self.presenter.actions():
            ttk.Button(self.actions, text=label, command=lambda p=path: _open(p)).pack(side="left", padx=(0, 8), pady=6)

    # ---------------------------------------------------------------- storeys
    def _edit_storeys(self) -> None:
        """Add, remove, move, repeat and size the building's storeys, then run again.

        The elevations are the one thing a plan cannot tell us, and a drawing's floor plans are
        not the same list as a building's storeys: eight typical floors are drawn once. This is
        where that gap is closed, and ``levels.xlsx`` is written from what is decided here.
        """
        from ..storeys import StoreySchedule
        from ..ui import edit_storeys

        path = self.result.storeys_json if self.result else None
        if not path or not Path(path).exists():
            messagebox.showinfo("C2B", "Run a drawing first: the storeys are seeded from it.")
            return
        try:
            schedule = StoreySchedule.load(path)
        except Exception as ex:
            messagebox.showerror("C2B", f"Could not read {Path(path).name}:\n{ex}")
            return

        plans = self.result.plan_floors if self.result else []
        subtitle = (f"{len(schedule)} storeys from {len(plans)} floor "
                    f"{'plan' if len(plans) == 1 else 'plans'} in {Path(self.vars['drawing'].get()).name}. "
                    "Repeat a storey to build a typical floor more than once.")
        try:
            saved = edit_storeys(schedule, plan_floors=plans, parent=self, subtitle=subtitle)
        except Exception as ex:
            messagebox.showerror("C2B", f"The storey editor could not open:\n{ex}")
            return
        if not saved:
            return
        try:
            schedule.save(path)
        except Exception as ex:
            messagebox.showerror("C2B", f"Could not save the storeys:\n{ex}")
            return
        # The levels the drawing was run with have changed, so a workbook chosen on a previous
        # run would now contradict them. The storeys are the source of truth from here.
        self.vars["levels"].set("")
        self.start()

    # -------------------------------------------------------------- settings
    def _sync_to_presenter(self) -> None:
        for key in self.vars:
            self.presenter.values[key] = self.vars[key].get()

    def _load_settings(self) -> None:
        self.presenter.load()
        for key, value in self.presenter.values.items():
            if key in self.vars and value:
                self.vars[key].set(value)

    def _save_settings(self) -> None:
        self._sync_to_presenter()
        self.presenter.save()


def run_gui(drawing: str | Path | None = None) -> int:
    window = C2BWindow()
    if drawing:
        window.vars["drawing"].set(str(drawing))
    window.mainloop()
    return 0
