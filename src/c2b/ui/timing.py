"""How long a run took, and where the time went.

Three figures, and the difference between them is the point:

* **the build** -- the time C2B spent working. This is the tool's own time and the only one it
  is fair to be judged on, so it is the big number.
* **the dialogs** -- the time somebody spent reading a window and deciding. That is the
  person's time, and counting it in a headline about the tool's speed is dishonest in the
  tool's favour when it is short and against it when it is long.
* **from the click** -- the two added up. What a wall clock saw.

Nothing here knows about a toolkit, so the WPF window, the Tkinter fallback and the pyRevit
side all report the same numbers in the same words.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


def human(seconds: float) -> str:
    """A duration as a person says it out loud.

    Under a minute is seconds with one decimal, because the difference between 8 and 12 seconds
    is something a drafter feels. Over a minute nobody cares about the decimal, and over an
    hour nobody cares about the seconds.
    """
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


@dataclass
class Phase:
    """One named stretch of a run."""

    name: str
    seconds: float
    waiting: bool = False        # the person's time, not the tool's


@dataclass
class Stopwatch:
    """Times a run, phase by phase.

    ``waiting`` phases are the ones a window was open and nothing was being computed. They are
    counted and reported, but they are kept out of the build figure.
    """

    started: float = field(default_factory=time.perf_counter)
    phases: list[Phase] = field(default_factory=list)
    _open: tuple[str, float, bool] | None = None

    def start(self, name: str, waiting: bool = False) -> None:
        """Begin a phase, closing whichever one was running."""
        self.stop()
        self._open = (name, time.perf_counter(), waiting)

    def stop(self) -> None:
        """Close the running phase, if there is one. Safe to call twice."""
        if self._open is None:
            return
        name, began, waiting = self._open
        self._open = None
        self.phases.append(Phase(name, time.perf_counter() - began, waiting))

    def mark(self, name: str, seconds: float, waiting: bool = False) -> None:
        """Record a phase that was timed somewhere else."""
        self.phases.append(Phase(name, max(0.0, float(seconds)), waiting))

    # ------------------------------------------------------------- the figures
    def build_seconds(self) -> float:
        """What the tool spent working."""
        return sum(p.seconds for p in self.phases if not p.waiting)

    def waiting_seconds(self) -> float:
        """What a person spent in front of a window."""
        return sum(p.seconds for p in self.phases if p.waiting)

    def total_seconds(self) -> float:
        """From the click. The wall clock, not the sum of the parts: a phase nobody named is
        still time that passed."""
        return max(time.perf_counter() - self.started,
                   self.build_seconds() + self.waiting_seconds())

    def report(self, headline: str = "Model prepared", caption: str = "preparing the model") -> dict:
        """Everything the finished window shows, already worded."""
        longest = max((p for p in self.phases if not p.waiting),
                      key=lambda p: p.seconds, default=None)
        return {
            "headline": headline,
            "caption": caption,
            "elapsed": human(self.build_seconds()),
            "waiting": human(self.waiting_seconds()),
            "total": human(self.total_seconds()),
            "breakdown": self.breakdown(),
            "slowest": longest.name if longest else "",
        }

    def breakdown(self, most: int = 6) -> str:
        """The phases worth naming, slowest first, as one line.

        A phase under a twentieth of the run is noise on a page about where the time went, so
        it is left out rather than making the line longer than the figure above it.
        """
        build = self.build_seconds()
        floor = build * 0.05
        worth = [p for p in self.phases if not p.waiting and p.seconds >= floor]
        worth.sort(key=lambda p: -p.seconds)
        return "   ".join(f"{p.name} {human(p.seconds)}" for p in worth[:most])
