"""The generated theme and the window layouts, checked on a machine with no WPF.

WPF cannot run here, so the failures it would only show at ``XamlReader.Load()`` are found by
reading the markup instead: a resource key nobody defines, a ``{StaticResource}`` on the root
Window element, XML that does not parse. Each of those is a window that does not open, and
each is caught here rather than by the person who pressed the button.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from c2b.ui import theme as t
from c2b.ui import xaml

LAYOUTS = ["storey_editor", "main_window", "elapsed"]

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def without_comments(markup: str) -> str:
    """The markup WPF actually acts on. A rule about the UI must not be met or broken by a
    comment *describing* the rule."""
    return _COMMENT.sub("", markup)


@pytest.fixture(scope="module")
def theme_markup():
    return xaml.theme_xaml()


# --------------------------------------------------------------- the theme

def test_the_theme_is_well_formed_xml(theme_markup):
    ET.fromstring(theme_markup)


def test_every_brand_colour_reaches_the_dictionary(theme_markup):
    for token in (t.VIVID_RED, t.CHARCOAL_BLACK, t.SILVER_STEEL, t.MID_GREY, t.LIGHT_BORDER):
        assert t.wpf_colour(token) in theme_markup


def test_the_theme_defines_no_key_twice(theme_markup):
    keys = xaml._KEY.findall(theme_markup)
    assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)


def test_the_theme_resolves_every_key_it_uses_itself(theme_markup):
    missing = xaml.referenced_keys(theme_markup) - xaml.declared_keys(theme_markup)
    assert missing == set(), f"the theme names resources nothing defines: {sorted(missing)}"


def test_the_theme_hardcodes_no_colour_outside_its_own_colour_block(theme_markup):
    """13.4 - inline hex outside the colour tier is rejected. The shadow's own black is the
    one exception the suite ships, and it is an opacity, not a palette colour."""
    body = theme_markup.split("</Color>")[-1]
    stray = [line.strip() for line in body.splitlines()
             if _HEX.search(line) and "SolidColorBrush" not in line and "DropShadowEffect" not in line]
    assert stray == []


@pytest.mark.parametrize("key", [
    "ButtonPrimary", "ButtonSecondary", "ButtonNeutral", "ButtonDanger", "ButtonGhost",
    "InputTextBox", "InputComboBox", "CardBorder", "TextH1", "TextBody", "TextMono",
])
def test_the_components_the_brand_names_all_exist(theme_markup, key):
    assert key in xaml.declared_keys(theme_markup)


def test_every_button_variant_states_its_disabled_look(theme_markup):
    """10.3 - a disabled control stays visible and inert, never collapsed."""
    assert theme_markup.count('<Trigger Property="IsEnabled" Value="False">') >= 5
    assert "Visibility" not in theme_markup.split("ButtonBaseStyle")[1].split("InputTextBox")[0]


def test_the_editable_combobox_carries_the_parts_wpf_looks_for(theme_markup):
    """12.7.C - without these named parts, editable mode silently does nothing."""
    assert 'x:Name="PART_EditableTextBox"' in theme_markup
    assert 'x:Name="PART_Popup"' in theme_markup


def test_the_combobox_item_style_is_implicit(theme_markup):
    """12.7.D - a keyed one leaves items white-on-white inside Revit's shell."""
    assert '<Style TargetType="ComboBoxItem">' in theme_markup


def test_the_textbox_does_not_take_its_vertical_margin_from_padding(theme_markup):
    """12.7.E - Margin={TemplateBinding Padding} on a 36px box clips the text it holds."""
    template = theme_markup.split('x:Key="InputTextBox"')[1].split("</Style>")[0]
    assert 'Margin="{TemplateBinding Padding}"' not in template
    assert 'x:Name="PART_ContentHost"' in template
    assert 'VerticalAlignment="Center"' in template


def test_the_textbox_draws_its_stroke_over_its_content(theme_markup):
    """12.7.O - fill, then content, then stroke, or the bottom edge renders thin."""
    template = theme_markup.split('x:Key="InputTextBox"')[1].split("</Style>")[0]
    assert template.index('x:Name="Bg"') < template.index("PART_ContentHost") < template.index('x:Name="Stroke"')
    assert 'IsHitTestVisible="False"' in template


def test_a_container_watches_focus_within_not_its_own(theme_markup):
    """12.7.F - IsFocused never fires on a ComboBox whose child TextBox has the keyboard."""
    combo = theme_markup.split('x:Key="InputComboBox"')[1].split("<Style TargetType=")[0]
    assert 'Property="IsKeyboardFocusWithin"' in combo
    assert 'Property="IsFocused"' not in combo


def test_the_scrollbar_is_templated_for_both_orientations(theme_markup):
    """12.7.P - a vertical-only style renders a horizontal bar as a broken strip."""
    bar = theme_markup.split('<Style TargetType="ScrollBar">')[1]
    assert 'Property="Orientation" Value="Vertical"' in bar
    assert 'Property="Orientation" Value="Horizontal"' in bar
    assert "PageLeftCommand" in bar and "PageUpCommand" in bar


# -------------------------------------------------------------- the layouts

@pytest.mark.parametrize("name", LAYOUTS)
def test_a_layout_file_is_well_formed_xml(name):
    ET.fromstring(xaml.layout_path(name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", LAYOUTS)
def test_a_spliced_window_is_well_formed_xml(name):
    ET.fromstring(xaml.window_xaml(name))


@pytest.mark.parametrize("name", LAYOUTS)
def test_a_window_resolves_every_resource_key_it_names(name):
    """The parse throws on the first key nobody defined, and the window never opens."""
    markup = xaml.window_xaml(name)
    missing = xaml.referenced_keys(markup) - xaml.declared_keys(markup)
    assert missing == set(), f"{name}.xaml names resources nothing defines: {sorted(missing)}"


@pytest.mark.parametrize("name", LAYOUTS)
def test_the_root_window_element_carries_no_resource_reference(name):
    """12.7.A - a Window's own attributes resolve before its Resources block is parsed."""
    markup = xaml.layout_path(name).read_text(encoding="utf-8")
    assert xaml.root_attribute_references(markup) == set()


@pytest.mark.parametrize("name", LAYOUTS)
def test_the_theme_lands_inside_the_window_resources(name):
    markup = xaml.window_xaml(name)
    assert markup.index("<Window.Resources>") < markup.index("ButtonPrimary") < markup.index("</Window.Resources>")


@pytest.mark.parametrize("name", LAYOUTS)
def test_a_window_declares_no_marker_after_splicing(name):
    assert xaml.THEME_MARKER not in xaml.window_xaml(name)


def test_a_layout_with_no_marker_is_refused(tmp_path, monkeypatch):
    bad = tmp_path / "broken.xaml"
    bad.write_text("<Window><Window.Resources/></Window>", encoding="utf-8")
    monkeypatch.setattr(xaml, "layout_path", lambda name: bad)
    with pytest.raises(ValueError, match="ANONGEE-THEME"):
        xaml.window_xaml("broken")


# ---------------------------------------- what the storey editor must offer

def test_the_storey_editor_offers_what_is_not_about_one_storey():
    """The toolbar holds only what has no particular storey: add, the default height, save.

    Move, repeat and remove are about one storey, so they live in that storey's row and are
    built in Python -- test_storey_wpf.py checks they are all there.
    """
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    for control in ("BtnAdd", "BtnAddBottom", "BtnUp", "BtnDown", "BtnRemove", "DefaultHeight",
                    "StoreyGrid", "BtnSave", "BtnCancel", "StatusBadge", "StatusLine",
                    "ProblemsHost", "SelectionText"):
        assert f'x:Name="{control}"' in markup, f"the window has no {control}"


def test_the_storey_table_has_every_column_the_brief_asked_for():
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    for header in ("Build", "No.", "Storey", "Height mm", "Elevation mm", "Built from",
                   "Repeat", "Note"):
        assert f'Header="{header}"' in markup, f"the table has no {header} column"


def test_every_window_opens_big_enough_to_use():
    """5.5: a tool window has an explicit width and a height it can be resized from; a dialog
    is a fixed width that grows to its content. A table that scrolls needs a height of its own
    -- a thirteen-storey tower would otherwise open taller than the screen."""
    for name in LAYOUTS:
        markup = without_comments(xaml.layout_path(name).read_text(encoding="utf-8"))
        assert 'Width="' in markup
        fixed = 'ResizeMode="NoResize"' in markup
        assert fixed or 'MinWidth="' in markup, f"{name} can be dragged to nothing"
        assert 'MinHeight="' in markup or 'SizeToContent="Height"' in markup


def test_the_table_uses_compact_density_not_the_dialog_size():
    """5.4 - a table row is smaller than the dialog's own inputs and buttons."""
    theme = xaml.theme_xaml()
    for key in ("InputRowBox", "InputRowNumberBox", "InputRowComboBox",
                "ButtonSmall", "ButtonRowAction", "ButtonRowDanger"):
        assert key in xaml.declared_keys(theme), f"no compact {key}"
    row = theme.split('x:Key="InputRowBox"')[1].split("</Style>")[0]
    assert 'Value="24"' in row and "FontSizeCaption" in row


def test_the_button_template_lives_once_and_variants_are_only_colours():
    """The shipping dictionary's shape, and the one in front of users in every other tool in
    the suite: one template on ButtonBaseStyle, and a variant is colours plus Style.Triggers."""
    theme = xaml.theme_xaml()
    assert theme.count("<ControlTemplate TargetType=\"Button\">") == 1
    base = theme.split('x:Key="ButtonBaseStyle"')[1].split("\n  <Style")[0]
    assert 'x:Name="Root"' in base and "TemplateBinding Background" in base
    assert 'Padding="{TemplateBinding Padding}"' in base

    for key in ("ButtonPrimary", "ButtonDanger", "ButtonSecondary", "ButtonGhost", "ButtonNeutral"):
        variant = theme.split(f'x:Key="{key}"')[1].split("\n  <Style")[0]
        assert "BasedOn=\"{StaticResource ButtonBaseStyle}\"" in theme.split(f'x:Key="{key}"')[1][:80]
        assert "<ControlTemplate" not in variant, f"{key} redefines the shared template"
        assert "<Style.Triggers>" in variant, f"{key} states no hover or disabled state"


def test_every_button_variant_states_a_disabled_look(theme_markup):
    """10.3 - a disabled control stays visible and inert, never collapsed."""
    assert theme_markup.count('<Trigger Property="IsEnabled" Value="False">') >= 5


def test_the_suite_shapes_are_all_here():
    """The window furniture One Filter Parameter uses, so a C2B window can be built the same."""
    keys = xaml.declared_keys(xaml.theme_xaml())
    for key in ("CardBorder", "DividerRule", "BadgeBorder", "TextBadge", "SectionLabel",
                "FieldLabel", "StatusText", "ElevationLevel2", "InputListBox", "TextH3OnDark"):
        assert key in keys, f"the theme has no {key}"


def test_the_implicit_selection_controls_are_styled():
    """9.4 - a window should not have to style every tick box and radio it puts down."""
    theme = xaml.theme_xaml()
    for target in ("CheckBox", "RadioButton", "ComboBoxItem", "ListBoxItem", "ScrollBar"):
        assert f'<Style TargetType="{target}">' in theme, f"{target} has no implicit style"


def test_the_storey_editor_has_exactly_one_primary_button():
    """9.1 - one Primary per view, and it is the thing the dialog is for."""
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    assert markup.count("{StaticResource ButtonPrimary}") == 1


def test_enter_saves_and_escape_cancels():
    """10.2 - a dialog sets IsDefault on confirm and IsCancel on cancel."""
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    assert 'x:Name="BtnSave"' in markup and 'IsDefault="True"' in markup
    assert 'x:Name="BtnCancel"' in markup and 'IsCancel="True"' in markup


def test_the_window_centres_on_whatever_opened_it():
    """12.4 - or the dialog appears behind Revit."""
    markup = xaml.layout_path("storey_editor").read_text(encoding="utf-8")
    assert 'WindowStartupLocation="CenterOwner"' in markup


def test_problems_are_reported_in_the_window_not_in_a_message_box():
    markup = without_comments(xaml.layout_path("storey_editor").read_text(encoding="utf-8"))
    assert 'x:Name="ProblemsHost"' in markup and "MessageBox" not in markup


def test_no_button_in_a_layout_is_left_with_default_chrome():
    """13.4 - every Button carries a named style."""
    for name in LAYOUTS:
        root = ET.fromstring(xaml.layout_path(name).read_text(encoding="utf-8"))
        ns = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        for button in root.iter(f"{ns}Button"):
            assert button.get("Style"), f"{button.get('{http://schemas.microsoft.com/winfx/2006/xaml}Name')} has no style"


def test_no_layout_declares_a_font_or_a_colour_of_its_own():
    """13.4 - no inline hex and no inline font below the root element, which 12.7.A forces."""
    for name in LAYOUTS:
        body = without_comments(xaml.layout_path(name).read_text(encoding="utf-8")).split("</Window.Resources>")[1]
        assert "FontFamily=" not in body and "FontSize=" not in body
        # 12.7.H forces four literal system-colour overrides at a DataGrid's own scope; there
        # is no resource-key form of them.
        stray = [h for h in _HEX.findall(body) if h.upper() not in ("#FEF2F2", "#141414")]
        assert stray == [], stray
