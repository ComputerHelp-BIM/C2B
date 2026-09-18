"""C2B's windows.

One entry point per dialog. Each picks WPF when the machine can show it and falls back to
Tkinter when it cannot, so a caller never has to know which toolkit it got -- and C2B still
starts on a machine with no pythonnet, which is every machine it is developed on.
"""
from __future__ import annotations

from ..storeys import StoreySchedule
from .storey_view import StoreyPresenter


def storey_toolkit() -> str:
    """Which toolkit a storey dialog would open in: ``"wpf"`` or ``"tk"``."""
    from . import wpf

    return "wpf" if wpf.available() else "tk"


def edit_storeys(schedule: StoreySchedule, plan_floors: list[tuple[str, str]] | None = None,
                 parent=None, subtitle: str = "", owner_handle: int | None = None) -> bool:
    """Edit a storey schedule in place. Returns True when it was saved, False when cancelled.

    ``plan_floors`` is the floor plans the drawing has, as ``(floor_id, name)``, so a storey can
    say which one it is built from. ``parent`` is a Tk widget and is only needed by the
    fallback; ``owner_handle`` is Revit's main window when C2B is running inside it.
    """
    presenter = StoreyPresenter(schedule=schedule, plan_floors=list(plan_floors or []))
    from . import wpf

    if wpf.available():
        from .storey_wpf import edit_storeys_wpf

        return edit_storeys_wpf(presenter, subtitle, owner_handle)

    from .storey_tk import edit_storeys_tk

    if parent is None:
        raise RuntimeError(
            "The storey editor needs WPF or a Tk window to open in. "
            f"WPF is not available here: {wpf.why_not()}")
    return edit_storeys_tk(parent, presenter, subtitle)
