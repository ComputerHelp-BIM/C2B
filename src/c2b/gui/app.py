"""The C2B window.

Plain Tkinter, which ships with Python on Windows, so a drafter needs nothing installed
beyond C2B itself. The pipeline runs on a worker thread and reports through a queue, so the
window stays responsive on a 25 MB drawing.
"""
from __future__ import annotations

import json
import os
import platform
import queue
import subprocess
import sys
import threading
from dataclasses import asdict
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from .runner import JobResult, JobSettings, run_job, run_verify

SETTINGS_FILE = Path.home() / ".c2b" / "gui.json"
UNITS = ("read from drawing", "mm", "cm", "m", "in", "ft")
COLUMN_SIZE_FROM = ("tag or schedule (client's intent)", "drawn outline (measure the drawing)")
COLORS = {"step": "#1F4E78", "good": "#1E7B34", "warn": "#9A6700", "bad": "#B42318", "info": "#333333"}


def _open(path: Path) -> None:
    """Open a file or folder in whatever the operating system uses."""
    path = Path(path)
    try:
        if platform.system() == "Windows":
            os.startfile(path)                                    # noqa: S606
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
        self.vars = {k: tk.StringVar() for k in ("drawing", "seed", "profile", "levels", "out", "units", "col_size")}
        self.vars["units"].set(UNITS[0])
        self.vars["col_size"].set(COLUMN_SIZE_FROM[0])
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

        top = ttk.Frame(self, padding=(14, 12, 14, 6))
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        self._row(top, 0, "Client drawing", "drawing", self._pick_drawing, "DXF from the client (DWG works when a converter is installed)")
        self._row(top, 1, "Our template", "seed", lambda: self._pick_file("seed", [("Template DXF", "*.dxf")]), "the firm's CH template DXF, remembered for next time")
        self._row(top, 2, "Layer profile", "profile", lambda: self._pick_file("profile", [("Profile", "*.yaml *.yml")]), "optional: saved layer roles for this client")
        self._row(top, 3, "Level heights", "levels", lambda: self._pick_file("levels", [("Level workbook", "*.xlsx")]), "optional: the filled levels workbook")
        self._row(top, 4, "Save results in", "out", self._pick_out, "leave empty to write next to the drawing")

        units = ttk.Frame(top)
        units.grid(row=5, column=1, sticky="w", pady=(6, 0))
        ttk.Label(units, text="Units:").pack(side="left")
        ttk.Combobox(units, textvariable=self.vars["units"], values=UNITS, width=18, state="readonly").pack(side="left", padx=(6, 18))
        ttk.Label(units, text="Column size from:").pack(side="left")
        ttk.Combobox(units, textvariable=self.vars["col_size"], values=COLUMN_SIZE_FROM, width=26,
                     state="readonly").pack(side="left", padx=(6, 18))
        self.run_btn = ttk.Button(units, text="Run", style="Run.TButton", command=self.start)
        self.run_btn.pack(side="left")
        self.verify_btn = ttk.Button(units, text="Re-check an edited template DXF", command=self.start_verify)
        self.verify_btn.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=3)
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

        self.actions = ttk.Frame(self, padding=(14, 0, 14, 12))
        self.actions.pack(fill="x")
        self.status = ttk.Label(self, text="Pick a client drawing and press Run.", anchor="w", padding=(16, 6))
        self.status.pack(fill="x")

    def _row(self, parent, row: int, label: str, key: str, command, hint: str) -> None:
        ttk.Label(parent, text=label, style="Head.TLabel").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(parent, text="Browse…", command=command, width=11).grid(row=row, column=2, padx=(8, 0))
        ttk.Label(parent, text=hint, foreground="#666666").grid(row=row, column=3, sticky="w", padx=(10, 0))

    # -------------------------------------------------------------- pickers
    def _pick_drawing(self) -> None:
        path = filedialog.askopenfilename(title="Client drawing", filetypes=[("Drawings", "*.dxf *.dwg"), ("DXF", "*.dxf"), ("DWG", "*.dwg"), ("All files", "*.*")])
        if path:
            self.vars["drawing"].set(path)
            self.status.configure(text=f"Ready: {Path(path).name}")

    def _pick_file(self, key: str, types) -> None:
        path = filedialog.askopenfilename(title=key.title(), filetypes=list(types) + [("All files", "*.*")])
        if path:
            self.vars[key].set(path)

    def _pick_out(self) -> None:
        path = filedialog.askdirectory(title="Save results in")
        if path:
            self.vars["out"].set(path)

    # --------------------------------------------------------------- running
    def start(self) -> None:
        drawing = self.vars["drawing"].get().strip()
        if not drawing or not Path(drawing).exists():
            messagebox.showwarning("C2B", "Pick a client drawing first.")
            return
        if self.worker and self.worker.is_alive():
            return
        self._save_settings()
        self._reset()
        units = self.vars["units"].get()
        settings = JobSettings(
            drawing=Path(drawing),
            out_dir=Path(self.vars["out"].get()) if self.vars["out"].get().strip() else None,
            seed=self._path("seed"), spec=None, profile=self._path("profile"), levels=self._path("levels"),
            units=None if units == UNITS[0] else units,
            column_size_from="tag" if self.vars["col_size"].get() == COLUMN_SIZE_FROM[0] else "outline",
        )
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

    def _path(self, key: str) -> Path | None:
        value = self.vars[key].get().strip()
        return Path(value) if value and Path(value).exists() else None

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
        self.progress.configure(value=3)
        for severity, code, count, meaning in result.issues[:200]:
            self.issues.insert("", "end", values=(severity.title(), count, meaning or code), tags=(severity,))
        summary = "   ".join(f"{v} {k}" for k, v in result.counts.items() if v)
        if result.error:
            self.status.configure(text=f"Stopped: {result.error}", foreground=COLORS["bad"])
        elif result.issues:
            self.status.configure(text=f"{summary}   —   {len(result.issues)} kinds of thing to check below", foreground=COLORS["warn"])
        else:
            self.status.configure(text=f"{summary}   —   nothing to flag", foreground=COLORS["good"])
        for label, path in (("Open the template DXF", result.template_dxf), ("Review workbook", result.review_xlsx),
                            ("Schedules", result.schedules_xlsx), ("Overlay on the client drawing", result.review_dxf),
                            ("Level heights", result.levels_xlsx), ("Check report", result.verify_md),
                            ("Open the folder", result.out_dir)):
            if path and Path(path).exists():
                ttk.Button(self.actions, text=label, command=lambda p=path: _open(p)).pack(side="left", padx=(0, 8), pady=6)

    # -------------------------------------------------------------- settings
    def _load_settings(self) -> None:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for key in ("seed", "profile", "out", "units", "col_size"):
                if data.get(key):
                    self.vars[key].set(data[key])
        except Exception:
            pass

    def _save_settings(self) -> None:
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({k: self.vars[k].get() for k in ("seed", "profile", "out", "units", "col_size")}, indent=2), encoding="utf-8")
        except Exception:
            pass


def run_gui(drawing: str | Path | None = None) -> int:
    try:
        window = C2BWindow()
    except tk.TclError as ex:
        print(f"No display available for the C2B window ({ex}). Use the command line: c2b run <drawing>", file=sys.stderr)
        return 2
    if drawing:
        window.vars["drawing"].set(str(drawing))
        window.status.configure(text=f"Ready: {Path(drawing).name}")
    window.mainloop()
    return 0


def main() -> int:
    return run_gui(sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    raise SystemExit(main())
