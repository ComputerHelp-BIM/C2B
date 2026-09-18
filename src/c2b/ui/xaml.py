"""The AnonGee theme as a WPF ResourceDictionary, generated from the tokens.

The brand guide describes two ways to get the theme into a window (§12.3): merge it by path,
or paste a verbatim copy into the window's own resources. Inside Revit's sandbox only the
second works, and the guide is candid that a pasted copy drifts from the dictionaries it was
pasted from -- it asks for "a build/sync check that fails when they drift" as future work.

C2B takes the third option: **the inline copy is generated from the tokens every time the
window is loaded**, so it is inline where it has to be, and it cannot drift, because there is
no second copy to drift from. :func:`theme_xaml` is that generator and
:func:`window_xaml` splices its output into a layout file, which keeps the markup in a
``.xaml`` file as §12.2 requires.

Two rules from §12.7 are load-bearing here and are checked by the tests:

* **A.** ``XamlReader`` resolves a ``<Window>``'s own attributes before its ``Resources`` block
  is parsed, so the root element carries literal values only -- never a ``{StaticResource}``.
* **Every key a layout asks for must exist**, or the parse throws at load. On a machine with no
  WPF that cannot be discovered by running it, so :func:`referenced_keys` and
  :func:`declared_keys` let a test find it instead.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import theme as t

#: The line in a layout file that the theme is spliced over.
THEME_MARKER = "<!-- ANONGEE-THEME -->"

_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')

#: Tier 1: every brand colour, by the name the dictionary knows it as.
_COLOURS: list[tuple[str, str]] = [
    ("ColorVividRed", t.VIVID_RED), ("ColorCharcoalBlack", t.CHARCOAL_BLACK),
    ("ColorSilverSteel", t.SILVER_STEEL), ("ColorPureWhite", t.PURE_WHITE),
    ("ColorOffWhite", t.OFF_WHITE), ("ColorMidGrey", t.MID_GREY),
    ("ColorLightBorder", t.LIGHT_BORDER), ("ColorSuccessGreen", t.SUCCESS_GREEN),
    ("ColorCautionAmber", t.CAUTION_AMBER), ("ColorErrorRed", t.ERROR_RED),
    ("ColorInfoBlue", t.INFO_BLUE), ("ColorVividRedHover", t.VIVID_RED_HOVER),
    ("ColorVividRedPressed", t.VIVID_RED_PRESSED), ("ColorVividRed10", t.VIVID_RED_10),
    ("ColorErrorRedHover", t.ERROR_RED_HOVER), ("ColorOffWhiteHover", t.OFF_WHITE_HOVER),
    ("ColorTableRowHover", t.TABLE_ROW_HOVER), ("ColorTableRowSelected", t.TABLE_ROW_SELECTED),
]

#: Tier 2: the semantic brushes a component is allowed to name. A component never reaches past
#: these to a primitive (§13.1), which is what lets the palette stay fixed while controls change.
_BRUSHES: list[tuple[str, str]] = [
    ("BrushVividRed", "ColorVividRed"), ("BrushCharcoalBlack", "ColorCharcoalBlack"),
    ("BrushSilverSteel", "ColorSilverSteel"), ("BrushPureWhite", "ColorPureWhite"),
    ("BrushOffWhite", "ColorOffWhite"), ("BrushMidGrey", "ColorMidGrey"),
    ("BrushLightBorder", "ColorLightBorder"), ("BrushSuccessGreen", "ColorSuccessGreen"),
    ("BrushCautionAmber", "ColorCautionAmber"), ("BrushErrorRed", "ColorErrorRed"),
    ("BrushInfoBlue", "ColorInfoBlue"), ("BrushVividRedHover", "ColorVividRedHover"),
    ("BrushVividRedPressed", "ColorVividRedPressed"), ("BrushVividRed10", "ColorVividRed10"),
    ("BrushErrorRedHover", "ColorErrorRedHover"), ("BrushOffWhiteHover", "ColorOffWhiteHover"),
    ("BrushTableRowHover", "ColorTableRowHover"), ("BrushTableRowSelected", "ColorTableRowSelected"),
    # Named for what they do, not what colour they are.
    ("BrushInputFocusBorder", "ColorVividRed"), ("BrushInputErrorBorder", "ColorErrorRed"),
    ("BrushDisabledBackground", "ColorLightBorder"), ("BrushDisabledForeground", "ColorSilverSteel"),
    ("BrushTableHeaderBackground", "ColorCharcoalBlack"),
]

#: The badge pairs of §9.5, as flat brushes so a status never has to be assembled by hand.
_BADGES: list[tuple[str, str]] = [
    ("BrushSuccessBadgeBackground", t.SUCCESS_BADGE_BG), ("BrushSuccessBadgeForeground", t.SUCCESS_BADGE_FG),
    ("BrushWarningBadgeBackground", t.WARNING_BADGE_BG), ("BrushWarningBadgeForeground", t.WARNING_BADGE_FG),
    ("BrushErrorBadgeBackground", t.ERROR_BADGE_BG), ("BrushErrorBadgeForeground", t.ERROR_BADGE_FG),
    ("BrushInfoBadgeBackground", t.INFO_BADGE_BG), ("BrushInfoBadgeForeground", t.INFO_BADGE_FG),
]


def _colours() -> str:
    lines = [f'  <Color x:Key="{key}">{t.wpf_colour(value)}</Color>' for key, value in _COLOURS]
    lines += [f'  <SolidColorBrush x:Key="{key}" Color="{{StaticResource {colour}}}"/>' for key, colour in _BRUSHES]
    lines += [f'  <SolidColorBrush x:Key="{key}" Color="{t.wpf_colour(value)}"/>' for key, value in _BADGES]
    return "\n".join(lines)


def _typography() -> str:
    """§4. Font families and sizes are tokens; a control never declares its own (§13.4)."""
    sizes = [("FontSizeH1", t.FONT_SIZE_H1), ("FontSizeH2", t.FONT_SIZE_H2), ("FontSizeH3", t.FONT_SIZE_H3),
             ("FontSizeH4", t.FONT_SIZE_H4), ("FontSizeBody", t.FONT_SIZE_BODY),
             ("FontSizeSmall", t.FONT_SIZE_SMALL), ("FontSizeCaption", t.FONT_SIZE_CAPTION),
             ("FontSizeCode", t.FONT_SIZE_CODE)]
    out = [f'  <FontFamily x:Key="FontSans">{t.FONT_SANS}</FontFamily>',
           f'  <FontFamily x:Key="FontMono">{t.FONT_MONO}</FontFamily>']
    out += [f'  <sys:Double x:Key="{key}">{value}</sys:Double>' for key, value in sizes]
    # Named TextBlock styles (§4.4). Referenced by key; font properties are never set inline.
    text_styles = [
        ("TextH1", "FontSizeH1", "Bold", "BrushCharcoalBlack"),
        ("TextH2", "FontSizeH2", "SemiBold", "BrushCharcoalBlack"),
        ("TextH2OnDark", "FontSizeH2", "SemiBold", "BrushPureWhite"),
        ("TextH3", "FontSizeH3", "SemiBold", "BrushCharcoalBlack"),
        ("TextH4", "FontSizeH4", "Medium", "BrushCharcoalBlack"),
        ("TextBody", "FontSizeBody", "Normal", "BrushMidGrey"),
        ("TextSmall", "FontSizeSmall", "Normal", "BrushMidGrey"),
        ("TextCaption", "FontSizeCaption", "Normal", "BrushMidGrey"),
    ]
    for key, size, weight, brush in text_styles:
        out.append(f'''  <Style x:Key="{key}" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource {size}}}"/>
    <Setter Property="FontWeight" Value="{weight}"/>
    <Setter Property="Foreground" Value="{{StaticResource {brush}}}"/>
    <Setter Property="TextWrapping" Value="{"Wrap" if key == "TextBody" else "NoWrap"}"/>
  </Style>''')
    # All technical output is monospace (§4.5): ids, paths, counts, elevations.
    out.append(f'''  <Style x:Key="TextMono" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCode}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
  </Style>
  <Style x:Key="TextError" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushErrorRed}}"/>
    <Setter Property="Margin" Value="0,{t.SPACE_XS},0,0"/>
    <Setter Property="TextWrapping" Value="Wrap"/>
  </Style>''')
    return "\n".join(out)


def _button(key: str, background: str, foreground: str, border: str | None,
            hover_bg: str, pressed_bg: str, thickness: float = 1.0) -> str:
    """One button variant of §9.1, as a template over the shared base.

    Every state in the matrix is here -- hover, pressed, disabled -- because a control that
    improvises a shade is how a palette stops being fixed. Disabled stays visible (§10.3).
    """
    return f'''  <Style x:Key="{key}" TargetType="Button" BasedOn="{{StaticResource ButtonBaseStyle}}">
    <Setter Property="Background" Value="{{StaticResource {background}}}"/>
    <Setter Property="Foreground" Value="{{StaticResource {foreground}}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource {border or background}}}"/>
    <Setter Property="BorderThickness" Value="{thickness if border else 0}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="Face" Background="{{TemplateBinding Background}}"
                  BorderBrush="{{TemplateBinding BorderBrush}}"
                  BorderThickness="{{TemplateBinding BorderThickness}}"
                  CornerRadius="{t.RADIUS_MD}" SnapsToDevicePixels="True">
            <ContentPresenter x:Name="Label" HorizontalAlignment="Center" VerticalAlignment="Center"
                              Margin="{{TemplateBinding Padding}}" RecognizesAccessKey="True"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Face" Property="Background" Value="{{StaticResource {hover_bg}}}"/>
            </Trigger>
            <Trigger Property="IsPressed" Value="True">
              <Setter TargetName="Face" Property="Background" Value="{{StaticResource {pressed_bg}}}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter TargetName="Face" Property="Background" Value="{{StaticResource BrushDisabledBackground}}"/>
              <Setter TargetName="Face" Property="BorderBrush" Value="{{StaticResource BrushDisabledBackground}}"/>
              <Setter Property="Foreground" Value="{{StaticResource BrushDisabledForeground}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>'''


def _controls() -> str:
    """§9. Buttons, inputs and the containers they sit in."""
    base = f'''  <Style x:Key="ButtonBaseStyle" TargetType="Button">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Height" Value="{t.HEIGHT_COMFORTABLE}"/>
    <Setter Property="Padding" Value="{t.SPACE_MD},0"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="SnapsToDevicePixels" Value="True"/>
  </Style>'''
    buttons = [
        _button("ButtonPrimary", "BrushVividRed", "BrushPureWhite", None, "BrushVividRedHover", "BrushVividRedPressed"),
        _button("ButtonSecondary", "BrushPureWhite", "BrushVividRed", "BrushVividRed", "BrushVividRed10", "BrushVividRed10", 1.5),
        _button("ButtonNeutral", "BrushOffWhite", "BrushCharcoalBlack", "BrushLightBorder", "BrushOffWhiteHover", "BrushLightBorder"),
        _button("ButtonDanger", "BrushErrorRed", "BrushPureWhite", None, "BrushErrorRedHover", "BrushVividRedPressed"),
        _button("ButtonGhost", "BrushPureWhite", "BrushMidGrey", None, "BrushOffWhiteHover", "BrushLightBorder"),
    ]
    # A small button for a row's own controls (§9.1 sizing). Compact height, Body Small.
    small = f'''  <Style x:Key="ButtonSmall" TargetType="Button" BasedOn="{{StaticResource ButtonNeutral}}">
    <Setter Property="Height" Value="{t.HEIGHT_COMPACT}"/>
    <Setter Property="MinWidth" Value="{t.HEIGHT_COMPACT}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeSmall}}"/>
    <Setter Property="Padding" Value="{t.SPACE_SM},0"/>
  </Style>'''
    # §12.7.E and .O: no vertical Margin from Padding (it clips the text), and the stroke is
    # drawn last over the content so all four edges of the rounded border stay even.
    textbox = f'''  <Style x:Key="InputTextBox" TargetType="TextBox">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Background" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="MinHeight" Value="{t.HEIGHT_COMPACT}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TextBox">
          <Grid SnapsToDevicePixels="True">
            <Border x:Name="Bg" Background="{{TemplateBinding Background}}" CornerRadius="{t.RADIUS_MD}"/>
            <ScrollViewer x:Name="PART_ContentHost" Margin="{t.SPACE_SM},0" VerticalAlignment="Center"/>
            <Border x:Name="Stroke" CornerRadius="{t.RADIUS_MD}" IsHitTestVisible="False"
                    BorderBrush="{{TemplateBinding BorderBrush}}"
                    BorderThickness="{{TemplateBinding BorderThickness}}"/>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsFocused" Value="True">
              <Setter TargetName="Stroke" Property="BorderBrush" Value="{{StaticResource BrushInputFocusBorder}}"/>
              <Setter TargetName="Stroke" Property="BorderThickness" Value="1.5"/>
            </Trigger>
            <Trigger Property="Validation.HasError" Value="True">
              <Setter TargetName="Stroke" Property="BorderBrush" Value="{{StaticResource BrushInputErrorBorder}}"/>
              <Setter TargetName="Stroke" Property="BorderThickness" Value="1.5"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter TargetName="Bg" Property="Background" Value="{{StaticResource BrushDisabledBackground}}"/>
              <Setter Property="Foreground" Value="{{StaticResource BrushDisabledForeground}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style x:Key="InputNumberBox" TargetType="TextBox" BasedOn="{{StaticResource InputTextBox}}">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="TextAlignment" Value="Right"/>
  </Style>'''
    # §12.7.C and .D: an editable ComboBox needs PART_EditableTextBox and PART_Popup, and the
    # item style must be implicit or Revit's shell lends it a white foreground on white.
    combo = f'''  <Style x:Key="InputComboBox" TargetType="ComboBox">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeSmall}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Background" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Height" Value="{t.HEIGHT_COMPACT}"/>
    <Setter Property="Padding" Value="{t.SPACE_SM},0"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBox">
          <Grid SnapsToDevicePixels="True">
            <Border x:Name="Bg" Background="{{TemplateBinding Background}}"
                    BorderBrush="{{TemplateBinding BorderBrush}}" BorderThickness="{{TemplateBinding BorderThickness}}"
                    CornerRadius="{t.RADIUS_MD}"/>
            <ToggleButton x:Name="Toggle" Background="Transparent" BorderThickness="0" Focusable="False"
                          IsChecked="{{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={{RelativeSource TemplatedParent}}}}"
                          ClickMode="Press">
              <ToggleButton.Template>
                <ControlTemplate TargetType="ToggleButton">
                  <Border Background="Transparent"/>
                </ControlTemplate>
              </ToggleButton.Template>
            </ToggleButton>
            <ContentPresenter x:Name="ContentSite" IsHitTestVisible="False" VerticalAlignment="Center"
                              Margin="{t.SPACE_SM},0,{t.SPACE_LG},0"
                              Content="{{TemplateBinding SelectionBoxItem}}"
                              ContentTemplate="{{TemplateBinding SelectionBoxItemTemplate}}"/>
            <TextBox x:Name="PART_EditableTextBox" Visibility="Hidden" Background="Transparent"
                     BorderThickness="0" VerticalAlignment="Center" Margin="{t.SPACE_SM},0,{t.SPACE_LG},0"/>
            <Path x:Name="Chevron" HorizontalAlignment="Right" VerticalAlignment="Center"
                  Margin="0,0,{t.SPACE_SM},0" Data="M0,0 L4,4 L8,0" Stroke="{{StaticResource BrushMidGrey}}"
                  StrokeThickness="1.5" IsHitTestVisible="False"/>
            <Popup x:Name="PART_Popup" Placement="Bottom" AllowsTransparency="True" Focusable="False"
                   PopupAnimation="Slide" IsOpen="{{TemplateBinding IsDropDownOpen}}">
              <Border Background="{{StaticResource BrushPureWhite}}" BorderBrush="{{StaticResource BrushLightBorder}}"
                      BorderThickness="1" CornerRadius="6" MaxWidth="520"
                      MinWidth="{{Binding ActualWidth, RelativeSource={{RelativeSource TemplatedParent}}}}">
                <ScrollViewer MaxHeight="200" HorizontalScrollBarVisibility="Hidden">
                  <ItemsPresenter/>
                </ScrollViewer>
              </Border>
            </Popup>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsEditable" Value="True">
              <Setter TargetName="PART_EditableTextBox" Property="Visibility" Value="Visible"/>
              <Setter TargetName="ContentSite" Property="Visibility" Value="Hidden"/>
            </Trigger>
            <Trigger Property="IsKeyboardFocusWithin" Value="True">
              <Setter TargetName="Bg" Property="BorderBrush" Value="{{StaticResource BrushInputFocusBorder}}"/>
              <Setter TargetName="Bg" Property="BorderThickness" Value="1.5"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter TargetName="Bg" Property="Background" Value="{{StaticResource BrushDisabledBackground}}"/>
              <Setter Property="Foreground" Value="{{StaticResource BrushDisabledForeground}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style TargetType="ComboBoxItem">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeSmall}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Padding" Value="{t.SPACE_SM},5"/>
    <Setter Property="MinHeight" Value="{t.HEIGHT_COMPACT}"/>
  </Style>'''
    # §5.3 -- a card on canvas is a stroke, not a shadow, so it stays crisp inside Revit.
    cards = f'''  <Style x:Key="CardBorder" TargetType="Border">
    <Setter Property="Background" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="CornerRadius" Value="{t.RADIUS_LG}"/>
    <Setter Property="Padding" Value="{t.SPACE_MD}"/>
  </Style>
  <Style x:Key="SectionDivider" TargetType="Border">
    <Setter Property="Background" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="Height" Value="1"/>
    <Setter Property="Margin" Value="0,{t.SPACE_MD}"/>
  </Style>
  <Style x:Key="BadgeBorder" TargetType="Border">
    <Setter Property="CornerRadius" Value="{t.RADIUS_SM}"/>
    <Setter Property="Padding" Value="{t.SPACE_SM},2"/>
    <Setter Property="VerticalAlignment" Value="Center"/>
  </Style>
  <Style x:Key="TextBadge" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
  </Style>'''
    # §12.7.P -- both orientations, or a horizontal bar renders as a broken strip.
    scrollbar = '''  <Style x:Key="ThumbStyle" TargetType="Thumb">
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Thumb">
          <Border x:Name="Fill" Background="{StaticResource BrushSilverSteel}" CornerRadius="4"/>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Fill" Property="Background" Value="{StaticResource BrushCharcoalBlack}"/>
            </Trigger>
            <Trigger Property="IsDragging" Value="True">
              <Setter TargetName="Fill" Property="Background" Value="{StaticResource BrushVividRed}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style TargetType="ScrollBar">
    <Setter Property="Background" Value="Transparent"/>
    <Style.Triggers>
      <Trigger Property="Orientation" Value="Vertical">
        <Setter Property="Width" Value="8"/>
        <Setter Property="Template">
          <Setter.Value>
            <ControlTemplate TargetType="ScrollBar">
              <Track x:Name="PART_Track" IsDirectionReversed="True">
                <Track.Thumb><Thumb Style="{StaticResource ThumbStyle}" Margin="2,0"/></Track.Thumb>
                <Track.IncreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageDownCommand" Opacity="0" Focusable="False"/>
                </Track.IncreaseRepeatButton>
                <Track.DecreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageUpCommand" Opacity="0" Focusable="False"/>
                </Track.DecreaseRepeatButton>
              </Track>
            </ControlTemplate>
          </Setter.Value>
        </Setter>
      </Trigger>
      <Trigger Property="Orientation" Value="Horizontal">
        <Setter Property="Height" Value="8"/>
        <Setter Property="Template">
          <Setter.Value>
            <ControlTemplate TargetType="ScrollBar">
              <Track x:Name="PART_Track">
                <Track.Thumb><Thumb Style="{StaticResource ThumbStyle}" Margin="0,2"/></Track.Thumb>
                <Track.IncreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageRightCommand" Opacity="0" Focusable="False"/>
                </Track.IncreaseRepeatButton>
                <Track.DecreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageLeftCommand" Opacity="0" Focusable="False"/>
                </Track.DecreaseRepeatButton>
              </Track>
            </ControlTemplate>
          </Setter.Value>
        </Setter>
      </Trigger>
    </Style.Triggers>
  </Style>'''
    return "\n".join([base, *buttons, small, textbox, combo, cards, scrollbar])


def theme_xaml() -> str:
    """The whole theme as one ResourceDictionary, in the order the dictionaries merge in.

    Colours and typography come first because everything after them names their keys (§13.2).
    """
    return (f'<ResourceDictionary {_NS} xmlns:sys="clr-namespace:System;assembly=mscorlib">\n'
            f"{_colours()}\n{_typography()}\n{_controls()}\n</ResourceDictionary>")


def layout_path(name: str) -> Path:
    """Where a layout file lives. Markup is a ``.xaml`` file, never a Python string (§12.2)."""
    return Path(__file__).resolve().parent / f"{name}.xaml"


def window_xaml(name: str) -> str:
    """A layout file with the generated theme spliced into its resources.

    The result is what :func:`c2b.ui.wpf.load_window` hands to ``XamlReader``.
    """
    markup = layout_path(name).read_text(encoding="utf-8")
    if THEME_MARKER not in markup:
        raise ValueError(f"{name}.xaml has no {THEME_MARKER} line for the theme to go in")
    return markup.replace(THEME_MARKER, theme_xaml())


# ---------------------------------------------------------------------------
# What a test needs to catch a missing key without WPF
# ---------------------------------------------------------------------------
_KEY = re.compile(r'x:Key="([^"]+)"')
_REFERENCE = re.compile(r"\{(?:Static|Dynamic)Resource\s+([^}]+?)\s*\}")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def without_comments(markup: str) -> str:
    """The markup as WPF acts on it.

    A layout file documents its own rules, and a comment explaining that the root element takes
    no ``{StaticResource}`` contains the words ``<Window`` and ``{StaticResource}``. Anything
    reading the markup to check a rule has to read past its own documentation first.
    """
    return _COMMENT.sub("", markup)


def declared_keys(markup: str) -> set[str]:
    """Every ``x:Key`` the markup defines."""
    return set(_KEY.findall(markup))


def referenced_keys(markup: str) -> set[str]:
    """Every resource key the markup asks for.

    A key that is asked for and never defined throws at parse time, which on a machine with no
    WPF is a crash the user finds rather than a test. Here it is a failing assertion.
    """
    return {m.strip() for m in _REFERENCE.findall(markup)}


def root_attribute_references(markup: str) -> set[str]:
    """Resource keys used on the root ``<Window ...>`` element's own attributes.

    §12.7.A: ``XamlReader`` resolves these *before* ``Window.Resources`` is parsed, so any one
    of them throws at load. The root element carries literal values only. This returns what
    should always be an empty set.
    """
    match = re.search(r"<Window\b([^>]*)>", without_comments(markup), re.S)
    return referenced_keys(match.group(1)) if match else set()
