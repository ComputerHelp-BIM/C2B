"""Every C2B window is the same window.

Two kinds of check live here, and both of them exist because of a bug that shipped.

**Layout.** ``DockPanel.Dock`` defaults to ``Left`` and says nothing about it. The storey
editor's instruction panel had no Dock for a release: it became a left column, a wrapping
TextBlock measured to its unwrapped width because a left column is offered infinite width,
and the DataGrid that was supposed to fill the rest got nothing. The window opened with no
table on it. Nothing in the markup looked wrong, because nothing in the markup was there.

**Chrome.** Colour, type and spacing come from one token module, so those cannot drift. What
*can* drift is shape and wording -- the finished window had no header band at all and read as
a different product from the window that opened it.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

LAYOUTS = Path(__file__).resolve().parents[1] / "src" / "c2b" / "ui"
WPF = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
X = "{http://schemas.microsoft.com/winfx/2006/xaml}"

#: How the firm is written on a window. One spelling, one middle dot, the tool in full (§2.3).
IDENTITY = "AnonGee &#183; CAD to BIM"


def layouts() -> list[Path]:
    found = sorted(LAYOUTS.glob("*.xaml"))
    assert len(found) >= 3, "the layouts moved; this module is checking nothing"
    return found


@pytest.fixture(params=layouts(), ids=lambda p: p.stem)
def layout(request) -> Path:
    return request.param


def local(tag: str) -> str:
    return tag.split("}")[-1]


def children(panel: ET.Element) -> list[ET.Element]:
    """The real children -- a tag with a dot in it is a property element, not a child."""
    return [c for c in panel if "." not in local(c.tag)]


def content(layout: Path) -> str:
    """What is inside the window: past the file's comment, past the root's own attributes.

    The root carries the Title, which names the firm because a taskbar entry has to, and the
    comment at the top names it because it is a heading. Neither of those is chrome.
    """
    after_comment = layout.read_text(encoding="utf-8").split("-->", 1)[1]
    return after_comment.split("<Window", 1)[1].split(">", 1)[1]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def test_every_dockpanel_child_but_the_last_declares_its_dock(layout):
    """Dock defaults to Left in silence, and a left column is measured with infinite width."""
    undocked = []
    for panel in ET.parse(layout).getroot().iter(f"{WPF}DockPanel"):
        kids = children(panel)
        fills = panel.get("LastChildFill", "True").lower() == "true"
        for n, child in enumerate(kids):
            docked = any(key.endswith("Dock") for key in child.attrib)
            if not docked and not (fills and n == len(kids) - 1):
                undocked.append(f"<{local(child.tag)} {child.get(f'{X}Name', '')}>")
    assert undocked == [], f"{layout.name}: {', '.join(undocked)} would dock Left"


def test_a_dockpanel_that_fills_puts_the_thing_that_should_grow_last(layout):
    """LastChildFill hands the rest of the window to the last child. On a window with a table
    on it, that had better be the table."""
    for panel in ET.parse(layout).getroot().iter(f"{WPF}DockPanel"):
        if panel.get("LastChildFill", "True").lower() != "true":
            continue
        last = children(panel)[-1]
        assert not any(key.endswith("Dock") for key in last.attrib), (
            f"{layout.name}: the filling child also declares a Dock, so nothing fills")


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------

def test_every_window_wears_the_header_band(layout):
    text = layout.read_text(encoding="utf-8")
    header = [el for el in ET.parse(layout).getroot().iter(f"{WPF}Border")
              if el.get("Background") == "{StaticResource BrushCharcoalBlack}"]
    assert len(header) == 1, f"{layout.name} has {len(header)} Charcoal headers, not 1"
    assert header[0].get("CornerRadius") == "5,5,0,0", "the header's top corners are not rounded"
    assert header[0].get("Padding") == "16,12"
    assert "TextH2OnDark" in text, "the title is not in the heading style the suite uses"


def test_every_window_wears_the_accent_rule(layout):
    rules = [el for el in ET.parse(layout).getroot().iter(f"{WPF}Rectangle")
             if el.get("Fill") == "{StaticResource BrushVividRed}"]
    assert len(rules) == 1, f"{layout.name} has {len(rules)} accent rules, not 1"
    assert 'Height="3"' in layout.read_text(encoding="utf-8"), "the accent rule is not 3px"


def test_every_window_wears_the_footer(layout):
    footers = [el for el in ET.parse(layout).getroot().iter(f"{WPF}Border")
               if el.get("Background") == "{StaticResource BrushOffWhite}"
               and el.get("BorderThickness") == "0,1,0,0"]
    assert footers, f"{layout.name} has no Off White footer with a rule above it"


def test_the_firm_is_written_the_same_way_on_every_window(layout):
    """Once per window, in the header's right-hand slot, over the version badge. It sat in the
    status bar on one window and the header on another, which is two answers to one question."""
    body = content(layout)
    assert body.count(IDENTITY) == 1, f"{layout.name} names the firm {body.count(IDENTITY)} times"
    assert 'x:Name="VersionBadge"' in body, "no version on the window, so no version in a report"
    assert body.index("VersionBadge") > body.index(IDENTITY), "the version belongs under it"


def test_every_window_is_titled_the_way_the_naming_rule_writes_it(layout):
    """§2.3 -- the brand, a middle dot with a space each side, then the tool written in full."""
    title = re.search(r'\n\s+Title="([^"]+)"', layout.read_text(encoding="utf-8"))
    assert title, f"{layout.name} has no Title"
    assert title.group(1).startswith("AnonGee &#183; "), f"{title.group(1)!r} is not the pattern"
    assert " - " not in title.group(1), "a hyphen where the middle dot belongs"


def test_no_layout_sets_its_own_type(layout):
    """§13.4 -- a size or a face on a control is a token that has escaped the token module.
    The root element is the one exception: XamlReader resolves it before Resources (§12.7.A)."""
    body = content(layout)
    assert "FontSize=" not in body
    assert "FontFamily=" not in body
