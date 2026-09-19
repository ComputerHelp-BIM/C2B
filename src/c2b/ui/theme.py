"""AnonGee BIM Tools design tokens, in one place.

Every surface C2B puts in front of a person -- the WPF windows, the Tkinter fallback, a styled
workbook -- takes its colours, type and spacing from here. The brand guide is explicit that the
**code is authoritative** and the prose describes it, so this module is that code: a value is
written once and every window reads it, which is the only way a palette stays fixed while the
product grows.

Reference: *AnonGee BIM Tools -- Brand & Design System v3.5*, sections 3 (colour), 4
(typography), 5 (spacing, radius, density) and 6 (motion).

C2B's windows are the **foreground task** a person is looking at, not a panel embedded in
Revit's chrome, so they wear the light palette (§3.8). The dark tokens are here because the
pyRevit side of C2B is a dockable pane's worth of work away and a second copy of a palette is
how two surfaces drift apart.
"""
from __future__ import annotations

import math
from typing import Final

# ---------------------------------------------------------------------------
# 3.1  Brand colours
# ---------------------------------------------------------------------------
VIVID_RED: Final = "#E02020"          # primary action and identity; never the wordmark's colour
CHARCOAL_BLACK: Final = "#141414"     # headers, dark surfaces, primary text
SILVER_STEEL: Final = "#C0C8D8"       # borders, dividers, icons on dark. Never text on white.

# 3.2  Surface and text neutrals
PURE_WHITE: Final = "#FFFFFF"
OFF_WHITE: Final = "#F4F4F6"
MID_GREY: Final = "#6B7280"           # body text on white (4.83:1)
LIGHT_BORDER: Final = "#E2E4EA"

# 3.3  Semantic state colours. System feedback only -- never decorative.
SUCCESS_GREEN: Final = "#16A34A"
CAUTION_AMBER: Final = "#D97706"
ERROR_RED: Final = "#DC2626"          # distinct from Vivid Red; never substituted for it
INFO_BLUE: Final = "#2563EB"

# 3.4  Interaction variants. Hover and pressed are never hand-mixed.
VIVID_RED_HOVER: Final = "#C41A1A"
VIVID_RED_PRESSED: Final = "#A81515"
VIVID_RED_10: Final = "#1AE02020"     # #AARRGGBB -- a 10% red tint for a secondary hover fill
ERROR_RED_HOVER: Final = "#B91C1C"
ERROR_RED_PRESSED: Final = "#991B1B"
OFF_WHITE_HOVER: Final = "#E8E8EC"

# 3.5  Surface-specific tints, for tables and selection
TABLE_ROW_HOVER: Final = "#FDECEA"
TABLE_ROW_SELECTED: Final = "#FEF2F2"
SUCCESS_BADGE_BG: Final = "#DCFCE7"
SUCCESS_BADGE_FG: Final = "#15803D"
WARNING_BADGE_BG: Final = "#FEF9C3"
WARNING_BADGE_FG: Final = "#92400E"
ERROR_BADGE_BG: Final = "#FEE2E2"
ERROR_BADGE_FG: Final = "#991B1B"
INFO_BADGE_BG: Final = "#DBEAFE"
INFO_BADGE_FG: Final = "#1D4ED8"

# 3.8  Dark surfaces, for anything embedded in Revit's own chrome
DARK_CANVAS: Final = "#383838"
DARK_SURFACE: Final = "#434347"
DARK_SURFACE_HOVER: Final = "#4E4E55"
DARK_SURFACE_PRESSED: Final = "#5A5A63"
DARK_BORDER: Final = "#4A4A4E"          # decorative only
DARK_BORDER_STRONG: Final = "#9EA1AB"   # the boundary of an interactive control (WCAG 1.4.11)
DARK_TEXT_PRIMARY: Final = "#F2F3F5"
DARK_TEXT_MUTED: Final = "#B4BBC8"
DARK_DISABLED: Final = "#8A8D96"
VIVID_RED_ON_DARK: Final = "#FF5F4C"    # accents and borders on dark; fills keep VIVID_RED

# ---------------------------------------------------------------------------
# 4  Typography. WPF device-independent units are authoritative.
# ---------------------------------------------------------------------------
#: The primary UI face. The token is named for the tier, not the family: it has been Inter,
#: then Source Serif 4, then JetBrains Mono-led, and is **Segoe UI** here at the owner's
#: instruction -- a monospace face reads as a terminal across a whole desktop window, which is
#: not what C2B is. The fallback chain is still mandatory: nothing may assume a font is
#: installed on a drafting machine.
FONT_SANS: Final = "Segoe UI, Inter, Calibri, Arial"
#: Numbers only -- an elevation column and a progress log are columns of figures, and figures
#: that do not line up are harder to read than figures in the wrong face. Consolas ships with
#: Windows, so this never falls through to something arbitrary.
FONT_MONO: Final = "Consolas, Courier New"
#: Tkinter takes one family, not a chain, so it gets the first of these that exists.
FONT_SANS_FALLBACKS: Final = ("Segoe UI", "Inter", "Calibri", "Arial", "TkDefaultFont")
FONT_MONO_FALLBACKS: Final = ("Consolas", "Courier New", "TkFixedFont")

#: These are the sizes the **shipping** ``Typography.xaml`` uses, taken from the reference
#: ``ui.xaml`` of AnonGee . One Filter Parameter, not the ones the brand document's table
#: prints. The document is explicit about which wins: "Where a number here and a number in
#: code disagree, the code wins and this document is wrong." Its own §4.2 already carries one
#: such reconciliation note. Following the table instead gave a window a third larger than
#: every other tool in the suite.
FONT_SIZE_H1: Final = 21.0
FONT_SIZE_H2: Final = 16.5
FONT_SIZE_H3: Final = 11.0          # document says 12
FONT_SIZE_H4: Final = 9.5           # document says 10.5
FONT_SIZE_BODY: Final = 9.5         # document says 10.5
FONT_SIZE_SMALL: Final = 8.5        # document says 9
FONT_SIZE_CAPTION: Final = 8.5      # document says 9
FONT_SIZE_CODE: Final = 8.5         # document says 9

LINE_HEIGHT_H1: Final = 26.0
LINE_HEIGHT_BODY: Final = 17.0
LINE_HEIGHT_CODE: Final = 14.0

#: A WPF device-independent unit is 1/96 inch, which is one CSS pixel. Tkinter reads a
#: *negative* font size as pixels, so a size crosses over exactly rather than through a
#: rounding that would make the scale drift between the two toolkits.
def _half_up(value: float) -> int:
    """Round half away from zero.

    Python rounds halves to even, which on a type scale of 10.5 and 16.5 would send one down
    and the other up. A size is rounded the way a designer reads it.
    """
    return math.floor(value + 0.5) if value >= 0 else -math.floor(-value + 0.5)


def pixels(wpf_units: float) -> int:
    """A WPF type size as the negative pixel size Tkinter wants."""
    return -max(8, _half_up(wpf_units))


def points(wpf_units: float) -> int:
    """A WPF type size in whole points, for anything that cannot take pixels (Excel, PDF)."""
    return max(6, _half_up(wpf_units * 72.0 / 96.0))


# ---------------------------------------------------------------------------
# 5  Spacing, radius, elevation, density
# ---------------------------------------------------------------------------
SPACE_XS: Final = 4
SPACE_SM: Final = 8
SPACE_MD: Final = 16
SPACE_LG: Final = 24
SPACE_XL: Final = 32
SPACE_2XL: Final = 48
SPACE_3XL: Final = 64

RADIUS_SM: Final = 3        # badges, chips, checkboxes
RADIUS_MD: Final = 5        # buttons, inputs, combo boxes, list items
RADIUS_LG: Final = 8        # cards, panels, group boxes
RADIUS_XL: Final = 10       # dialogs and modal windows

#: 5.4 -- density is control height and padding, never a smaller type scale. As with the type
#: scale, these are the shipping numbers: a button is 28 and an input is 26 in every tool in
#: the suite, which is tighter than the document's 28/36 table and is what a Revit user's eye
#: is already calibrated to.
HEIGHT_INPUT: Final = 26         # text boxes, combo boxes
HEIGHT_COMPACT: Final = 26       # list items, checkboxes, a parameter grid
HEIGHT_BUTTON: Final = 28        # every button unless it is the one primary action
HEIGHT_LARGE: Final = 34         # the primary action of a dialog
BUTTON_PADDING_H: Final = 12     # horizontal padding inside a button
INPUT_PADDING_H: Final = 7       # horizontal inset of a text box's content

DIALOG_WIDTH: Final = 480        # 5.5 -- a dialog is a fixed width and centres on its owner

# ---------------------------------------------------------------------------
# 6  Motion. Functional, never expressive.
# ---------------------------------------------------------------------------
MOTION_INSTANT_MS: Final = 0
MOTION_FAST_MS: Final = 120
MOTION_STANDARD_MS: Final = 200
MOTION_SLOW_MS: Final = 300

# ---------------------------------------------------------------------------
# 2  Naming
# ---------------------------------------------------------------------------
BRAND: Final = "AnonGee BIM Tools"
#: 2.3 -- a middle dot with one space each side is the separator, and the tool name is written
#: in full. A window's title bar carries this; the version badge carries the version.
SEPARATOR: Final = "·"


def display_name(tool: str) -> str:
    """The full display name of a tool, e.g. ``AnonGee . Storey Editor``."""
    return f"AnonGee {SEPARATOR} {tool}"


#: Severities, as the badge colours §9.5 gives them. A status is never colour alone (§10.4),
#: so each carries the word that goes beside it.
BADGE: Final = {
    "ERROR":   (ERROR_BADGE_BG, ERROR_BADGE_FG, "ERROR"),
    "WARNING": (WARNING_BADGE_BG, WARNING_BADGE_FG, "WARNING"),
    "INFO":    (INFO_BADGE_BG, INFO_BADGE_FG, "INFO"),
    "SUCCESS": (SUCCESS_BADGE_BG, SUCCESS_BADGE_FG, "READY"),
}


def wpf_colour(hex_rgb: str) -> str:
    """A ``#RRGGBB`` token as the ``#AARRGGBB`` WPF wants, leaving an existing alpha alone."""
    value = hex_rgb.strip()
    if not value.startswith("#"):
        raise ValueError(f"{hex_rgb!r} is not a colour token")
    digits = value[1:]
    if len(digits) == 8:
        return value.upper()
    if len(digits) == 6:
        return f"#FF{digits.upper()}"
    raise ValueError(f"{hex_rgb!r} is not #RRGGBB or #AARRGGBB")


def _relative_luminance(hex_rgb: str) -> float:
    digits = wpf_colour(hex_rgb)[3:]
    channels = []
    for i in (0, 2, 4):
        c = int(digits[i:i + 2], 16) / 255.0
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.1 contrast between two opaque tokens.

    The brand guide computes every ratio in its tables from the palette rather than
    transcribing them, so that nudging a token fails the build instead of quietly shipping an
    accessibility defect. This is the function that lets the tests do the same.
    """
    a, b = _relative_luminance(foreground), _relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)
