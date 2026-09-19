"""What the C2B window does, with nothing in it that knows about a toolkit.

The window is WPF and the fallback is Tkinter. Which fields there are, what each one is for,
how a typed value becomes a :class:`~c2b.gui.runner.JobSettings`, what is remembered between
runs and what the footer says when a run ends -- all of that is the same in both, so it lives
here and is tested without a display.

The field list is **data, not layout**. Both windows build their rows from :data:`FIELDS`, so a
row cannot exist in one and be missing from the other, and adding one is a line here rather
than the same edit made twice in two languages.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .runner import COLUMN_SIZE_DEFAULT, COLUMN_SIZE_FROM, JobResult, JobSettings, column_size_label, column_size_value

#: Where the window remembers what was typed last time.
SETTINGS_FILE = Path.home() / ".c2b" / "gui.json"

UNITS = ("read from drawing", "mm", "cm", "m", "in", "ft")


@dataclass(frozen=True)
class Field_:
    """One file or folder the window asks for."""

    key: str
    label: str
    hint: str
    kind: str                       # "open" | "folder"
    filters: tuple[tuple[str, str], ...] = ()      # (description, pattern)
    remembered: bool = True         # kept for the next run; the drawing itself is not


#: The five rows at the top of the window, in order. The first is the only required one.
FIELDS: tuple[Field_, ...] = (
    Field_("drawing", "Client drawing", "DXF from the client (DWG works when a converter is installed)",
           "open", (("Drawings", "*.dxf;*.dwg"), ("DXF", "*.dxf"), ("DWG", "*.dwg")), remembered=False),
    Field_("seed", "Our template", "leave empty to use the firm's CH template from the C2B folder",
           "open", (("Template DXF", "*.dxf"),)),
    Field_("profile", "Layer profile", "optional: saved layer roles for this client",
           "open", (("Profile", "*.yaml;*.yml"),)),
    Field_("levels", "Level heights", "optional: a level workbook to use instead of the storeys",
           "open", (("Level workbook", "*.xlsx"),)),
    Field_("out", "Save results in", "leave empty to write next to the drawing", "folder"),
)

#: Everything the window holds, including the option boxes.
KEYS = (*(f.key for f in FIELDS), "units", "col_size", "beam_depth", "slab_thk")

#: A progress line's severity -> the token its text is drawn in. "step" is also bold.
LOG_SEVERITY = {"step": "CHARCOAL_BLACK", "good": "SUCCESS_GREEN", "warn": "CAUTION_AMBER",
                "bad": "ERROR_RED", "info": "MID_GREY"}

#: The buttons offered when a run finishes, and which result each one opens.
RESULT_ACTIONS: tuple[tuple[str, str], ...] = (
    ("Open the template DXF", "template_dxf"),
    ("Review workbook", "review_xlsx"),
    ("Schedules", "schedules_xlsx"),
    ("Overlay on the client drawing", "review_dxf"),
    ("What Revit will build", "revit_xlsx"),
    ("Check report", "verify_md"),
    ("Open the folder", "out_dir"),
)


@dataclass
class MainPresenter:
    """The C2B window's state: what is typed in it, and what a run made of it."""

    values: dict[str, str] = field(default_factory=lambda: {k: "" for k in KEYS})
    result: JobResult | None = None

    def __post_init__(self) -> None:
        for key in KEYS:
            self.values.setdefault(key, "")
        self.values["units"] = self.values["units"] or UNITS[0]
        self.values["col_size"] = self.values["col_size"] or COLUMN_SIZE_DEFAULT

    # ------------------------------------------------------------ what to run
    def problem(self) -> str:
        """Why the run cannot start, or an empty string. Checked before anything is disabled."""
        drawing = self.values["drawing"].strip()
        if not drawing:
            return "Pick a client drawing first."
        if not Path(drawing).exists():
            return f"There is no file at {drawing}"
        return ""

    def job_settings(self) -> JobSettings:
        """The run, as the pipeline takes it. Call only when :meth:`problem` is empty."""
        units = self.values["units"]
        return JobSettings(
            drawing=Path(self.values["drawing"].strip()),
            out_dir=self.path("out"), seed=self.path("seed"), spec=None,
            profile=self.path("profile"), levels=self.path("levels"),
            default_beam_depth_mm=self.number("beam_depth"),
            default_slab_thickness_mm=self.number("slab_thk"),
            units=None if units == UNITS[0] else units,
            column_size_from=column_size_value(self.values["col_size"]))

    def path(self, key: str) -> Path | None:
        """A path typed in the window, or None when it is empty or does not exist.

        A path that has been deleted since it was remembered is silently dropped rather than
        failing the run: the last job's output folder is exactly the kind of thing that goes.
        """
        value = self.values.get(key, "").strip()
        return Path(value) if value and Path(value).exists() else None

    def number(self, key: str) -> float | None:
        """A millimetre value typed in the window, or None when it is empty or not a number."""
        text = self.values.get(key, "").strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    # -------------------------------------------------------- what a run said
    def summary(self) -> tuple[str, str, str]:
        """(severity, badge word, footer line) for the run that finished."""
        result = self.result
        if result is None:
            return "INFO", "READY", "Pick a client drawing and press Run."
        if result.error:
            return "ERROR", "ERROR", f"Stopped: {result.error}"
        counts = "   ".join(f"{v} {k}" for k, v in result.counts.items() if v)
        if result.issues:
            kinds = len(result.issues)
            return "WARNING", "CHECK", f"{counts}   -   {kinds} kind{'s' if kinds != 1 else ''} of thing to check below"
        return "SUCCESS", "DONE", f"{counts}   -   nothing to flag"

    def actions(self) -> list[tuple[str, Path]]:
        """The result buttons worth offering: the ones whose file is actually there."""
        if self.result is None:
            return []
        out: list[tuple[str, Path]] = []
        for label, attribute in RESULT_ACTIONS:
            value = getattr(self.result, attribute, None)
            if value and Path(value).exists():
                out.append((label, Path(value)))
        return out

    def can_edit_storeys(self) -> bool:
        """The storey editor is offered on any run that read a drawing, not only a failed one."""
        return bool(self.result and self.result.storeys_json and Path(self.result.storeys_json).exists())

    def next_step(self) -> str:
        return self.result.next_step if self.result else ""

    def issue_rows(self) -> list[tuple[str, int, str]]:
        """(severity, how many, what it means) for the things-to-check table."""
        return [(sev.title(), n, meaning or code)
                for sev, code, n, meaning in (self.result.issues if self.result else [])][:200]

    # ------------------------------------------------------------- remembering
    def load(self, path: Path = SETTINGS_FILE) -> None:
        """Take what was typed last time. A settings file that will not read is not fatal."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        for f in FIELDS:
            if f.remembered and data.get(f.key):
                self.values[f.key] = str(data[f.key])
        for key in ("beam_depth", "slab_thk"):
            if data.get(key):
                self.values[key] = str(data[key])
        if data.get("units") in UNITS:
            self.values["units"] = data["units"]
        # A label that is no longer offered falls back to the default rather than silently
        # meaning the other option.
        saved = column_size_label(data.get("col_size"))
        self.values["col_size"] = saved or COLUMN_SIZE_DEFAULT

    def save(self, path: Path = SETTINGS_FILE) -> None:
        """Remember for next time. Never raises: a read-only home must not stop a run."""
        remembered = {f.key: self.values.get(f.key, "") for f in FIELDS if f.remembered}
        remembered.update({k: self.values.get(k, "") for k in ("units", "col_size", "beam_depth", "slab_thk")})
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(remembered, indent=2), encoding="utf-8")
        except Exception:
            pass

    #: The option boxes, as (key, label, choices, hint), so both windows build them the same.
    def option_boxes(self) -> list[tuple[str, str, list[str], str]]:
        return [("units", "Units", list(UNITS), ""),
                ("col_size", "Column size from", list(COLUMN_SIZE_FROM),
                 "what the client stated, or the drawing measured")]
