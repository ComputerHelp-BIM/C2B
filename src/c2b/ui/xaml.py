"""The AnonGee theme as a WPF ResourceDictionary, generated from the tokens.

The brand guide describes two ways to get the theme into a window (§12.3): merge it by path,
or paste a verbatim copy into the window's own resources. Inside Revit's sandbox only the
second works, and the guide is candid that a pasted copy drifts from the dictionaries it was
pasted from -- it asks for "a build/sync check that fails when they drift" as future work.

C2B takes the third option: **the inline copy is generated from the tokens every time the
window is loaded**, so it is inline where it has to be, and it cannot drift, because there is
no second copy to drift from. :func:`theme_xaml` is that generator and :func:`window_xaml`
splices its output into a layout file, which keeps the markup in a ``.xaml`` file as §12.2
requires.

**Every control here is a port of the shipping dictionary** in AnonGee . One Filter Parameter's
``ui.xaml``: the same structures, the same sizes, the same triggers. That is deliberate. A
control written from the prose looks approximately right and is wrong in the details that
matter -- the first version of this file gave each button variant its own template and set its
fill through ``{TemplateBinding Background}`` over a Setter, which is correct WPF and came up
on a real machine as a bare outline with an invisible label. The shipping dictionary is the
specification; the document describes it.

Two rules from §12.7 are load-bearing and are checked by the tests:

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
    ("ColorErrorRedHover", t.ERROR_RED_HOVER), ("ColorErrorRedPressed", t.ERROR_RED_PRESSED),
    ("ColorOffWhiteHover", t.OFF_WHITE_HOVER), ("ColorTableRowHover", t.TABLE_ROW_HOVER),
    ("ColorTableRowSelected", t.TABLE_ROW_SELECTED),
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
    ("BrushErrorRedHover", "ColorErrorRedHover"), ("BrushErrorRedPressed", "ColorErrorRedPressed"),
    ("BrushOffWhiteHover", "ColorOffWhiteHover"),
    ("BrushTableRowHover", "ColorTableRowHover"), ("BrushTableRowSelected", "ColorTableRowSelected"),
    # Named for what they do, not what colour they are.
    ("BrushSecondaryHover", "ColorVividRed10"), ("BrushGhostHover", "ColorOffWhiteHover"),
    ("BrushInputBackground", "ColorPureWhite"), ("BrushInputBorder", "ColorLightBorder"),
    ("BrushInputFocusBorder", "ColorVividRed"), ("BrushInputErrorBorder", "ColorErrorRed"),
    ("BrushDisabledBackground", "ColorLightBorder"), ("BrushDisabledForeground", "ColorSilverSteel"),
    ("BrushPrimaryForeground", "ColorPureWhite"),
    ("BrushSecondaryBackground", "ColorPureWhite"), ("BrushSecondaryBorder", "ColorVividRed"),
    ("BrushSecondaryForeground", "ColorVividRed"), ("BrushGhostForeground", "ColorMidGrey"),
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
    # §5.3 -- a shadow only at elevation 2 and 3; a card on canvas is a stroke.
    lines.append('  <DropShadowEffect x:Key="ElevationLevel2" Color="#000000" Opacity="0.14" '
                 'BlurRadius="12" ShadowDepth="4" Direction="270"/>')
    return "\n".join(lines)


def _typography() -> str:
    """§4. Font families and sizes are tokens; a control never declares its own (§13.4)."""
    sizes = [("FontSizeH1", t.FONT_SIZE_H1), ("FontSizeH2", t.FONT_SIZE_H2), ("FontSizeH3", t.FONT_SIZE_H3),
             ("FontSizeH4", t.FONT_SIZE_H4), ("FontSizeBody", t.FONT_SIZE_BODY),
             ("FontSizeSmall", t.FONT_SIZE_SMALL), ("FontSizeCaption", t.FONT_SIZE_CAPTION),
             ("FontSizeCode", t.FONT_SIZE_CODE), ("FontSizeHelp", t.FONT_SIZE_HELP),
             ("FontSizeFigure", t.FONT_SIZE_FIGURE)]
    out = [f'  <FontFamily x:Key="FontSans">{t.FONT_SANS}</FontFamily>',
           f'  <FontFamily x:Key="FontMono">{t.FONT_MONO}</FontFamily>']
    out += [f'  <sys:Double x:Key="{key}">{value}</sys:Double>' for key, value in sizes]

    # Named TextBlock styles (§4.4). Referenced by key; font properties are never set inline.
    text_styles = [
        ("TextH1", "FontSizeH1", "Bold", "BrushCharcoalBlack", False),
        ("TextH2", "FontSizeH2", "SemiBold", "BrushCharcoalBlack", False),
        ("TextH2OnDark", "FontSizeH2", "SemiBold", "BrushPureWhite", False),
        ("TextH3", "FontSizeH3", "SemiBold", "BrushCharcoalBlack", False),
        ("TextH3OnDark", "FontSizeH3", "SemiBold", "BrushSilverSteel", False),
        ("TextH4", "FontSizeH4", "SemiBold", "BrushCharcoalBlack", False),
        ("TextBody", "FontSizeBody", "Normal", "BrushMidGrey", True),
        ("TextSmall", "FontSizeSmall", "Normal", "BrushMidGrey", False),
        ("TextCaption", "FontSizeCaption", "Normal", "BrushMidGrey", False),
        ("StatusText", "FontSizeCaption", "Normal", "BrushMidGrey", True),
        ("TextStatus", "FontSizeCaption", "Normal", "BrushMidGrey", True),
        # A form's own label: Body weight SemiBold, centred against its input.
        ("FieldLabel", "FontSizeBody", "SemiBold", "BrushCharcoalBlack", False),
        ("TextLabel", "FontSizeBody", "SemiBold", "BrushCharcoalBlack", False),
    ]
    for key, size, weight, brush, wraps in text_styles:
        wrapping = "Wrap" if wraps else "NoWrap"
        out.append(f'''  <Style x:Key="{key}" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource {size}}}"/>
    <Setter Property="FontWeight" Value="{weight}"/>
    <Setter Property="Foreground" Value="{{StaticResource {brush}}}"/>
    <Setter Property="TextWrapping" Value="{wrapping}"/>
    <Setter Property="VerticalAlignment" Value="Center"/>
  </Style>''')

    # Help prose sits a tier above body, as it does in the suite: a paragraph explaining what
    # a table means is the one thing on a dense window that a person actually reads. The size
    # is a token like every other; it was a literal here once, which is exactly how a scale
    # ends up with one member that does not follow it.
    out.append('''  <Style x:Key="HelpText" TargetType="TextBlock" BasedOn="{StaticResource TextBody}">
    <Setter Property="FontSize" Value="{StaticResource FontSizeHelp}"/>
    <Setter Property="VerticalAlignment" Value="Top"/>
  </Style>
  <Style x:Key="PageTitle" TargetType="TextBlock" BasedOn="{StaticResource TextH2}">
    <Setter Property="Margin" Value="0,0,0,4"/>
  </Style>''')

    # A section heading above a group of fields.
    out.append('''  <Style x:Key="SectionLabel" TargetType="Label">
    <Setter Property="FontFamily" Value="{StaticResource FontSans}"/>
    <Setter Property="FontSize" Value="{StaticResource FontSizeH3}"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Foreground" Value="{StaticResource BrushCharcoalBlack}"/>
    <Setter Property="Padding" Value="0"/>
    <Setter Property="Margin" Value="0,0,0,6"/>
  </Style>''')

    # All technical output is monospace (§4.5): ids, paths, counts, elevations.
    out.append(f'''  <Style x:Key="TextMono" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCode}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="VerticalAlignment" Value="Center"/>
  </Style>
  <Style x:Key="TextError" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushErrorRed}}"/>
    <Setter Property="Margin" Value="0,{t.SPACE_XS},0,0"/>
    <Setter Property="TextWrapping" Value="Wrap"/>
  </Style>
  <!-- One figure, once per window: the number a "finished" dialog exists to show. Bigger than
       the Display level of §4.2 on purpose - there is nothing else on the surface to balance
       it against, and it is read from across a desk. -->
  <Style x:Key="TextFigure" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeFigure}}"/>
    <Setter Property="FontWeight" Value="Bold"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushVividRed}}"/>
  </Style>
  <Style x:Key="TextFigureSmall" TargetType="TextBlock" BasedOn="{{StaticResource TextCaption}}">
    <Setter Property="FontWeight" Value="Bold"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushVividRed}}"/>
  </Style>
  <Style x:Key="TextBadge" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
  </Style>''')
    return "\n".join(out)


def _button(key: str, background: str, foreground: str, border: str | None, thickness: float,
            hover: str | None, pressed: str | None) -> str:
    """One button variant of §9.1.

    The shipping dictionary's shape: the **template lives once** on ``ButtonBaseStyle`` and a
    variant is nothing but colours and a ``Style.Triggers`` block. That is what is in front of
    users in every other tool in the suite, so it is what goes here.
    """
    lines = [f'  <Style x:Key="{key}" TargetType="Button" BasedOn="{{StaticResource ButtonBaseStyle}}">',
             f'    <Setter Property="Background" Value="{{StaticResource {background}}}"/>',
             f'    <Setter Property="Foreground" Value="{{StaticResource {foreground}}}"/>']
    if border:
        lines.append(f'    <Setter Property="BorderBrush" Value="{{StaticResource {border}}}"/>')
    lines.append(f'    <Setter Property="BorderThickness" Value="{thickness}"/>')
    lines.append("    <Style.Triggers>")
    if hover:
        lines.append(f'''      <Trigger Property="IsMouseOver" Value="True">
        <Setter Property="Background" Value="{{StaticResource {hover}}}"/>
      </Trigger>''')
    if pressed:
        lines.append(f'''      <Trigger Property="IsPressed" Value="True">
        <Setter Property="Background" Value="{{StaticResource {pressed}}}"/>
      </Trigger>''')
    # Disabled stays visible and inert, never collapsed (§10.3).
    lines.append('''      <Trigger Property="IsEnabled" Value="False">
        <Setter Property="Background" Value="{StaticResource BrushDisabledBackground}"/>
        <Setter Property="BorderBrush" Value="{StaticResource BrushDisabledBackground}"/>
        <Setter Property="Foreground" Value="{StaticResource BrushDisabledForeground}"/>
      </Trigger>
    </Style.Triggers>
  </Style>''')
    return "\n".join(lines)


def _buttons() -> str:
    base = f'''  <Style x:Key="ButtonBaseStyle" TargetType="Button">
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Padding" Value="{t.BUTTON_PADDING_H},0"/>
    <Setter Property="Height" Value="{t.HEIGHT_BUTTON}"/>
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Background" Value="Transparent"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="BorderBrush" Value="Transparent"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="SnapsToDevicePixels" Value="True"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="Root"
                  Background="{{TemplateBinding Background}}"
                  BorderBrush="{{TemplateBinding BorderBrush}}"
                  BorderThickness="{{TemplateBinding BorderThickness}}"
                  CornerRadius="{t.RADIUS_MD}"
                  Padding="{{TemplateBinding Padding}}">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              RecognizesAccessKey="True"/>
          </Border>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>'''
    variants = [
        _button("ButtonPrimary", "BrushVividRed", "BrushPrimaryForeground", None, 0,
                "BrushVividRedHover", "BrushVividRedPressed"),
        _button("ButtonSecondary", "BrushSecondaryBackground", "BrushSecondaryForeground",
                "BrushSecondaryBorder", 1.5, "BrushSecondaryHover", "BrushSecondaryHover"),
        _button("ButtonNeutral", "BrushOffWhite", "BrushCharcoalBlack", "BrushLightBorder", 1,
                "BrushOffWhiteHover", "BrushLightBorder"),
        _button("ButtonDanger", "BrushErrorRed", "BrushPrimaryForeground", None, 0,
                "BrushErrorRedHover", "BrushErrorRedPressed"),
        _button("ButtonGhost", "BrushPureWhite", "BrushGhostForeground", None, 0,
                "BrushGhostHover", "BrushLightBorder"),
    ]
    # A table row acts on itself, so its own controls live in it. Smaller than a dialog's
    # action bar because a row is compact density (§5.4).
    rows = [
        f'''  <Style x:Key="ButtonSmall" TargetType="Button" BasedOn="{{StaticResource ButtonNeutral}}">
    <Setter Property="Height" Value="24"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="Padding" Value="{t.SPACE_SM},0"/>
  </Style>''',
        '''  <Style x:Key="ButtonRowAction" TargetType="Button" BasedOn="{StaticResource ButtonGhost}">
    <Setter Property="Height" Value="24"/>
    <Setter Property="Width" Value="24"/>
    <Setter Property="Padding" Value="0"/>
    <Setter Property="FontSize" Value="{StaticResource FontSizeCaption}"/>
    <Setter Property="BorderBrush" Value="{StaticResource BrushLightBorder}"/>
    <Setter Property="BorderThickness" Value="1"/>
  </Style>''',
        # The row's own destructive action. Outlined rather than filled: a wall of red down a
        # table makes every row look like a warning, and §9.1 keeps one filled emphasis per view.
        '''  <Style x:Key="ButtonRowDanger" TargetType="Button" BasedOn="{StaticResource ButtonRowAction}">
    <Setter Property="Foreground" Value="{StaticResource BrushErrorRed}"/>
    <Setter Property="BorderBrush" Value="{StaticResource BrushErrorRed}"/>
    <Style.Triggers>
      <Trigger Property="IsMouseOver" Value="True">
        <Setter Property="Background" Value="{StaticResource BrushErrorBadgeBackground}"/>
      </Trigger>
    </Style.Triggers>
  </Style>''',
    ]
    return "\n".join([base, *variants, *rows])


def _inputs() -> str:
    """§9.2, §9.3, §9.4. The stroke is drawn over the content so all four edges stay even (§12.7.O)."""
    textbox = f'''  <Style x:Key="InputTextBox" TargetType="TextBox">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Background" Value="{{StaticResource BrushInputBackground}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushInputBorder}}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Height" Value="{t.HEIGHT_INPUT}"/>
    <Setter Property="VerticalContentAlignment" Value="Center"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TextBox">
          <Grid SnapsToDevicePixels="True">
            <Border x:Name="Bg" Background="{{TemplateBinding Background}}" CornerRadius="{t.RADIUS_MD}"/>
            <ScrollViewer x:Name="PART_ContentHost" Margin="{t.INPUT_PADDING_H},0" VerticalAlignment="Center"/>
            <Border x:Name="Stroke" CornerRadius="{t.RADIUS_MD}"
                    BorderBrush="{{TemplateBinding BorderBrush}}"
                    BorderThickness="{{TemplateBinding BorderThickness}}"
                    IsHitTestVisible="False"/>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsKeyboardFocusWithin" Value="True">
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
  </Style>
  <Style x:Key="InputRowBox" TargetType="TextBox" BasedOn="{{StaticResource InputTextBox}}">
    <Setter Property="Height" Value="24"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
  </Style>
  <Style x:Key="InputRowNumberBox" TargetType="TextBox" BasedOn="{{StaticResource InputRowBox}}">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="TextAlignment" Value="Right"/>
  </Style>'''

    # §12.7.C, .D and .P: the named parts editable mode needs, an implicit item style, and a
    # popup that grows to its content instead of clipping it.
    combo = f'''  <Style x:Key="InputComboBox" TargetType="ComboBox">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Background" Value="{{StaticResource BrushInputBackground}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushInputBorder}}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Height" Value="{t.HEIGHT_INPUT}"/>
    <Setter Property="VerticalContentAlignment" Value="Center"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBox">
          <Grid SnapsToDevicePixels="True">
            <Border x:Name="Bg" Background="{{TemplateBinding Background}}" CornerRadius="{t.RADIUS_MD}"/>
            <ToggleButton x:Name="OpenToggle" Focusable="False" ClickMode="Press"
                          IsChecked="{{Binding IsDropDownOpen, Mode=TwoWay,
                                      RelativeSource={{RelativeSource TemplatedParent}}}}">
              <ToggleButton.Template>
                <ControlTemplate TargetType="ToggleButton">
                  <Grid Background="Transparent">
                    <Grid.ColumnDefinitions>
                      <ColumnDefinition Width="*"/>
                      <ColumnDefinition Width="22"/>
                    </Grid.ColumnDefinitions>
                    <Path Grid.Column="1" Data="M0,0 L4,4 L8,0"
                          Fill="{{StaticResource BrushMidGrey}}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
                  </Grid>
                </ControlTemplate>
              </ToggleButton.Template>
            </ToggleButton>
            <ContentPresenter x:Name="ContentSite" Margin="{t.SPACE_SM},0,24,0"
                              IsHitTestVisible="False" VerticalAlignment="Center"
                              Content="{{TemplateBinding SelectionBoxItem}}"
                              ContentTemplate="{{TemplateBinding SelectionBoxItemTemplate}}"/>
            <TextBox x:Name="PART_EditableTextBox" Margin="6,0,24,0"
                     VerticalAlignment="Center" Visibility="Hidden"
                     Background="Transparent" BorderThickness="0"
                     Foreground="{{StaticResource BrushCharcoalBlack}}"
                     IsReadOnly="{{TemplateBinding IsReadOnly}}"/>
            <Border x:Name="Stroke" CornerRadius="{t.RADIUS_MD}"
                    BorderBrush="{{TemplateBinding BorderBrush}}"
                    BorderThickness="{{TemplateBinding BorderThickness}}"
                    IsHitTestVisible="False"/>
            <Popup x:Name="PART_Popup" Placement="Bottom"
                   IsOpen="{{TemplateBinding IsDropDownOpen}}"
                   AllowsTransparency="True" Focusable="False" PopupAnimation="Slide">
              <Border MinWidth="{{TemplateBinding ActualWidth}}" MaxWidth="520"
                      BorderBrush="{{StaticResource BrushLightBorder}}"
                      BorderThickness="1" CornerRadius="6"
                      Background="{{StaticResource BrushPureWhite}}"
                      Effect="{{StaticResource ElevationLevel2}}">
                <ScrollViewer MaxHeight="220" Margin="4" HorizontalScrollBarVisibility="Hidden">
                  <ItemsPresenter/>
                </ScrollViewer>
              </Border>
            </Popup>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsEditable" Value="True">
              <Setter TargetName="PART_EditableTextBox" Property="Visibility" Value="Visible"/>
              <Setter TargetName="ContentSite" Property="Visibility" Value="Collapsed"/>
            </Trigger>
            <Trigger Property="IsKeyboardFocusWithin" Value="True">
              <Setter TargetName="Stroke" Property="BorderBrush" Value="{{StaticResource BrushInputFocusBorder}}"/>
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
  <Style x:Key="InputRowComboBox" TargetType="ComboBox" BasedOn="{{StaticResource InputComboBox}}">
    <Setter Property="Height" Value="24"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
  </Style>
  <Style TargetType="ComboBoxItem">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Background" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="Padding" Value="10,5"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBoxItem">
          <Border x:Name="Bd" Background="{{TemplateBinding Background}}"
                  Padding="{{TemplateBinding Padding}}">
            <ContentPresenter/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{{StaticResource BrushTableRowHover}}"/>
            </Trigger>
            <Trigger Property="IsSelected" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{{StaticResource BrushTableRowSelected}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>'''

    # §9.4. Implicit, because a window should not have to style every tick box it puts down.
    selection = f'''  <Style TargetType="CheckBox">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="MinHeight" Value="22"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="CheckBox">
          <Grid Background="Transparent">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Border x:Name="CheckBoxBorder" Grid.Column="0" Width="16" Height="16"
                    CornerRadius="{t.RADIUS_SM}" BorderThickness="1"
                    BorderBrush="{{StaticResource BrushLightBorder}}"
                    Background="{{StaticResource BrushPureWhite}}" VerticalAlignment="Center">
              <Viewbox x:Name="CheckMark" Margin="3" Visibility="Collapsed">
                <Path Data="M0,3.5 L3.5,7 L9,0" Stroke="{{StaticResource BrushPureWhite}}"
                      StrokeThickness="1.8" StrokeLineJoin="Round"
                      StrokeStartLineCap="Round" StrokeEndLineCap="Round" Fill="Transparent"/>
              </Viewbox>
            </Border>
            <ContentPresenter Grid.Column="1" Margin="7,0,0,0" VerticalAlignment="Center"
                              RecognizesAccessKey="True"/>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsChecked" Value="True">
              <Setter TargetName="CheckMark" Property="Visibility" Value="Visible"/>
              <Setter TargetName="CheckBoxBorder" Property="Background" Value="{{StaticResource BrushVividRed}}"/>
              <Setter TargetName="CheckBoxBorder" Property="BorderBrush" Value="{{StaticResource BrushVividRed}}"/>
            </Trigger>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="CheckBoxBorder" Property="BorderBrush" Value="{{StaticResource BrushVividRed}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style TargetType="RadioButton">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="RadioButton">
          <Grid Background="Transparent">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Grid Grid.Column="0" Width="16" Height="16" VerticalAlignment="Center">
              <Ellipse x:Name="Ring" Stroke="{{StaticResource BrushLightBorder}}"
                       StrokeThickness="1.4" Fill="{{StaticResource BrushPureWhite}}"/>
              <Ellipse x:Name="Dot" Width="8" Height="8"
                       Fill="{{StaticResource BrushVividRed}}" Visibility="Collapsed"/>
            </Grid>
            <ContentPresenter Grid.Column="1" Margin="7,0,0,0" VerticalAlignment="Center"
                              RecognizesAccessKey="True"/>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsChecked" Value="True">
              <Setter TargetName="Dot" Property="Visibility" Value="Visible"/>
              <Setter TargetName="Ring" Property="Stroke" Value="{{StaticResource BrushVividRed}}"/>
            </Trigger>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Ring" Property="Stroke" Value="{{StaticResource BrushVividRed}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style x:Key="InputListBox" TargetType="ListBox">
    <Setter Property="Background" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Padding" Value="4"/>
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeBody}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="ScrollViewer.VerticalScrollBarVisibility" Value="Auto"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ListBox">
          <Grid SnapsToDevicePixels="True">
            <Border x:Name="Bg" Background="{{TemplateBinding Background}}" CornerRadius="{t.RADIUS_MD}"/>
            <ScrollViewer Focusable="False" Margin="{{TemplateBinding BorderThickness}}"
                          Padding="{{TemplateBinding Padding}}">
              <ItemsPresenter/>
            </ScrollViewer>
            <Border x:Name="Stroke" CornerRadius="{t.RADIUS_MD}"
                    BorderBrush="{{TemplateBinding BorderBrush}}"
                    BorderThickness="{{TemplateBinding BorderThickness}}"
                    IsHitTestVisible="False"/>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style TargetType="ListBoxItem">
    <Setter Property="Padding" Value="6,2"/>
    <Setter Property="Margin" Value="1,0"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ListBoxItem">
          <Border x:Name="Bd" Background="Transparent" CornerRadius="4"
                  Padding="{{TemplateBinding Padding}}">
            <ContentPresenter/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{{StaticResource BrushTableRowHover}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>'''
    return "\n".join([textbox, combo, selection])


_THUMB = '''<Thumb>
                  <Thumb.Template>
                    <ControlTemplate TargetType="Thumb">
                      <Border x:Name="ThumbBd" CornerRadius="3" Margin="%s"
                              Background="{StaticResource BrushSilverSteel}"/>
                      <ControlTemplate.Triggers>
                        <Trigger Property="IsMouseOver" Value="True">
                          <Setter TargetName="ThumbBd" Property="Background" Value="{StaticResource BrushCharcoalBlack}"/>
                        </Trigger>
                        <Trigger Property="IsDragging" Value="True">
                          <Setter TargetName="ThumbBd" Property="Background" Value="{StaticResource BrushVividRed}"/>
                        </Trigger>
                      </ControlTemplate.Triggers>
                    </ControlTemplate>
                  </Thumb.Template>
                </Thumb>'''


def _surfaces() -> str:
    """Cards, dividers, badges, the progress bar and the scrollbar."""
    cards = f'''  <Style x:Key="CardBorder" TargetType="Border">
    <Setter Property="Background" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="CornerRadius" Value="{t.RADIUS_LG}"/>
    <Setter Property="Padding" Value="16,12"/>
  </Style>
  <Style x:Key="DividerRule" TargetType="Rectangle">
    <Setter Property="Height" Value="1"/>
    <Setter Property="Fill" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="Margin" Value="0,12,0,12"/>
  </Style>
  <Style x:Key="SectionDivider" TargetType="Border">
    <Setter Property="Background" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="Height" Value="1"/>
    <Setter Property="Margin" Value="0,{t.SPACE_MD}"/>
  </Style>
  <Style x:Key="BadgeBorder" TargetType="Border">
    <Setter Property="CornerRadius" Value="4"/>
    <Setter Property="Padding" Value="10,3"/>
    <Setter Property="VerticalAlignment" Value="Center"/>
  </Style>
  <Style x:Key="ProgressBarStyle" TargetType="ProgressBar">
    <Setter Property="Height" Value="4"/>
    <Setter Property="BorderThickness" Value="0"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ProgressBar">
          <Grid SnapsToDevicePixels="True">
            <Border Background="{{StaticResource BrushLightBorder}}" CornerRadius="{t.RADIUS_SM}"/>
            <Border x:Name="PART_Track" Background="Transparent"/>
            <Border x:Name="PART_Indicator" HorizontalAlignment="Left"
                    Background="{{StaticResource BrushVividRed}}" CornerRadius="{t.RADIUS_SM}"/>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>'''

    # §12.7.P -- both orientations, or a horizontal bar renders as a broken strip.
    scrollbar = f'''  <Style TargetType="ScrollBar">
    <Setter Property="Background" Value="Transparent"/>
    <Style.Triggers>
      <Trigger Property="Orientation" Value="Vertical">
        <Setter Property="Width" Value="8"/>
        <Setter Property="MinWidth" Value="8"/>
        <Setter Property="Template">
          <Setter.Value>
            <ControlTemplate TargetType="ScrollBar">
              <Grid Background="Transparent">
                <Border Background="{{StaticResource BrushOffWhite}}" CornerRadius="4" Margin="2,0"/>
                <Track x:Name="PART_Track" IsDirectionReversed="True">
                  <Track.DecreaseRepeatButton>
                    <RepeatButton Command="ScrollBar.PageUpCommand" Focusable="False"
                                  Opacity="0" Background="Transparent" BorderThickness="0"/>
                  </Track.DecreaseRepeatButton>
                  <Track.IncreaseRepeatButton>
                    <RepeatButton Command="ScrollBar.PageDownCommand" Focusable="False"
                                  Opacity="0" Background="Transparent" BorderThickness="0"/>
                  </Track.IncreaseRepeatButton>
                  <Track.Thumb>{_THUMB % "2,0"}</Track.Thumb>
                </Track>
              </Grid>
            </ControlTemplate>
          </Setter.Value>
        </Setter>
      </Trigger>
      <Trigger Property="Orientation" Value="Horizontal">
        <Setter Property="Height" Value="8"/>
        <Setter Property="MinHeight" Value="8"/>
        <Setter Property="Template">
          <Setter.Value>
            <ControlTemplate TargetType="ScrollBar">
              <Grid Background="Transparent">
                <Border Background="{{StaticResource BrushOffWhite}}" CornerRadius="4" Margin="0,2"/>
                <Track x:Name="PART_Track">
                  <Track.DecreaseRepeatButton>
                    <RepeatButton Command="ScrollBar.PageLeftCommand" Focusable="False"
                                  Opacity="0" Background="Transparent" BorderThickness="0"/>
                  </Track.DecreaseRepeatButton>
                  <Track.IncreaseRepeatButton>
                    <RepeatButton Command="ScrollBar.PageRightCommand" Focusable="False"
                                  Opacity="0" Background="Transparent" BorderThickness="0"/>
                  </Track.IncreaseRepeatButton>
                  <Track.Thumb>{_THUMB % "0,2"}</Track.Thumb>
                </Track>
              </Grid>
            </ControlTemplate>
          </Setter.Value>
        </Setter>
      </Trigger>
    </Style.Triggers>
  </Style>'''
    return "\n".join([cards, scrollbar])


def _datagrid() -> str:
    """§9.8, ported from the suite's own preview grid.

    The checkbox column is the one part that cannot be done the obvious way. §12.7.Q: a
    ``DataTrigger`` on a Python ``bool`` never fires and a two-way write back to a ``__slots__``
    bool does not land, so the tick is bound to the **row's own** ``IsSelected`` -- a real .NET
    bool -- and ``SelectedItems`` is the source of truth that Python reads.
    """
    return f'''  <Style x:Key="GridCheckBox" TargetType="CheckBox">
    <Setter Property="Cursor" Value="Hand"/>
    <!-- The control fills its cell and the drawn box sits in the middle of it, so the target
         is the whole cell rather than {t.CHECKBOX_SIZE} pixels of it. A tick that has to be
         hit exactly is a tick somebody reports as not working. -->
    <Setter Property="HorizontalAlignment" Value="Stretch"/>
    <Setter Property="VerticalAlignment" Value="Stretch"/>
    <Setter Property="HorizontalContentAlignment" Value="Center"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="CheckBox">
         <Border Background="Transparent">
          <Border x:Name="Box" Width="{t.CHECKBOX_SIZE}" Height="{t.CHECKBOX_SIZE}" CornerRadius="{t.RADIUS_SM}"
                  HorizontalAlignment="Center" VerticalAlignment="Center"
                  BorderBrush="{{StaticResource BrushLightBorder}}" BorderThickness="1"
                  Background="{{StaticResource BrushPureWhite}}">
            <Viewbox x:Name="CheckMark" Margin="3" Visibility="Collapsed">
              <Path Data="M0,3.5 L3.5,7 L9,0" Stroke="{{StaticResource BrushPureWhite}}"
                    StrokeThickness="1.8" StrokeLineJoin="Round"
                    StrokeStartLineCap="Round" StrokeEndLineCap="Round" Fill="Transparent"/>
            </Viewbox>
          </Border>
         </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsChecked" Value="True">
              <Setter TargetName="CheckMark" Property="Visibility" Value="Visible"/>
              <Setter TargetName="Box" Property="Background" Value="{{StaticResource BrushVividRed}}"/>
              <Setter TargetName="Box" Property="BorderBrush" Value="{{StaticResource BrushVividRed}}"/>
            </Trigger>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Box" Property="BorderBrush" Value="{{StaticResource BrushVividRed}}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style x:Key="GridColumnHeader" TargetType="DataGridColumnHeader">
    <Setter Property="Background" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Padding" Value="8,6"/>
    <Setter Property="BorderBrush" Value="{{StaticResource BrushMidGrey}}"/>
    <Setter Property="BorderThickness" Value="0,0,1,0"/>
    <Setter Property="HorizontalContentAlignment" Value="Left"/>
  </Style>
  <Style x:Key="GridCell" TargetType="DataGridCell">
    <Setter Property="BorderThickness" Value="0"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Style.Triggers>
      <Trigger Property="IsSelected" Value="True">
        <Setter Property="Background" Value="Transparent"/>
        <Setter Property="BorderBrush" Value="Transparent"/>
        <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
      </Trigger>
    </Style.Triggers>
  </Style>
  <Style x:Key="GridRow" TargetType="DataGridRow">
    <Style.Triggers>
      <Trigger Property="IsMouseOver" Value="True">
        <Setter Property="Background" Value="{{StaticResource BrushTableRowHover}}"/>
      </Trigger>
      <Trigger Property="IsSelected" Value="True">
        <Setter Property="Background" Value="{{StaticResource BrushTableRowSelected}}"/>
      </Trigger>
    </Style.Triggers>
  </Style>
  <!-- A cell's own text, in the grid's compact size. -->
  <Style x:Key="GridText" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
    <Setter Property="Padding" Value="8,0"/>
    <Setter Property="VerticalAlignment" Value="Center"/>
  </Style>
  <Style x:Key="GridNumber" TargetType="TextBlock" BasedOn="{{StaticResource GridText}}">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="TextAlignment" Value="Right"/>
  </Style>
  <Style x:Key="GridMuted" TargetType="TextBlock" BasedOn="{{StaticResource GridText}}">
    <Setter Property="Foreground" Value="{{StaticResource BrushMidGrey}}"/>
    <Style.Triggers>
      <!-- Mid Grey is 4.8:1 on white and only 3.8:1 on a selected row, so the muted columns
           stop being muted and go back to body colour there. 12.7.Q permits this DataTrigger
           and only this one: DataGridRow.IsSelected is a real .NET bool on a real .NET
           object, not a value read off a row. -->
      <DataTrigger Value="True"
                   Binding="{{Binding IsSelected, RelativeSource={{RelativeSource AncestorType=DataGridRow}}}}">
        <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
      </DataTrigger>
    </Style.Triggers>
  </Style>
  <!-- A number the table works out rather than one a person types. Muted where it is
       derived, body colour on the one row that can be edited - and body colour on a selected
       row too, which it inherits from GridMuted along with the reason. -->
  <Style x:Key="GridDerivedNumber" TargetType="TextBlock" BasedOn="{{StaticResource GridMuted}}">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="TextAlignment" Value="Right"/>
    <Style.Triggers>
      <DataTrigger Binding="{{Binding Derived}}" Value="False">
        <Setter Property="Foreground" Value="{{StaticResource BrushCharcoalBlack}}"/>
      </DataTrigger>
    </Style.Triggers>
  </Style>
  <!-- The editor a cell puts up on F2 or a double click. -->
  <Style x:Key="GridEditBox" TargetType="TextBox" BasedOn="{{StaticResource InputTextBox}}">
    <Setter Property="Height" Value="{t.HEIGHT_INPUT - 5}"/>
    <Setter Property="Margin" Value="4,0"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
  </Style>
  <Style x:Key="GridEditNumberBox" TargetType="TextBox" BasedOn="{{StaticResource GridEditBox}}">
    <Setter Property="FontFamily" Value="{{StaticResource FontMono}}"/>
    <Setter Property="TextAlignment" Value="Right"/>
  </Style>
  <Style x:Key="GridComboBox" TargetType="ComboBox" BasedOn="{{StaticResource InputComboBox}}">
    <Setter Property="Height" Value="{t.HEIGHT_INPUT - 5}"/>
    <Setter Property="Margin" Value="4,0"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
  </Style>
  <Style x:Key="DataGridStyle" TargetType="DataGrid">
    <Setter Property="AutoGenerateColumns" Value="False"/>
    <Setter Property="CanUserAddRows" Value="False"/>
    <Setter Property="CanUserDeleteRows" Value="False"/>
    <Setter Property="CanUserReorderColumns" Value="False"/>
    <Setter Property="CanUserSortColumns" Value="False"/>
    <!-- The owner asked for column width adjusters, and this is them. -->
    <Setter Property="CanUserResizeColumns" Value="True"/>
    <Setter Property="CanUserResizeRows" Value="False"/>
    <Setter Property="HeadersVisibility" Value="Column"/>
    <Setter Property="GridLinesVisibility" Value="Horizontal"/>
    <Setter Property="HorizontalGridLinesBrush" Value="{{StaticResource BrushLightBorder}}"/>
    <Setter Property="Background" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="RowBackground" Value="{{StaticResource BrushPureWhite}}"/>
    <Setter Property="AlternatingRowBackground" Value="{{StaticResource BrushOffWhite}}"/>
    <Setter Property="BorderThickness" Value="0"/>
    <Setter Property="RowHeight" Value="{t.HEIGHT_INPUT}"/>
    <Setter Property="SelectionMode" Value="Single"/>
    <Setter Property="SelectionUnit" Value="FullRow"/>
    <Setter Property="FontFamily" Value="{{StaticResource FontSans}}"/>
    <Setter Property="FontSize" Value="{{StaticResource FontSizeCaption}}"/>
    <Setter Property="ColumnHeaderStyle" Value="{{StaticResource GridColumnHeader}}"/>
    <Setter Property="CellStyle" Value="{{StaticResource GridCell}}"/>
    <Setter Property="RowStyle" Value="{{StaticResource GridRow}}"/>
  </Style>'''


def theme_xaml() -> str:
    """The whole theme as one ResourceDictionary, in the order the dictionaries merge in.

    Colours and typography come first because everything after them names their keys (§13.2),
    and ``StaticResource`` resolves only backwards through a dictionary.
    """
    return (f'<ResourceDictionary {_NS} xmlns:sys="clr-namespace:System;assembly=mscorlib">\n'
            f"{_colours()}\n{_typography()}\n{_buttons()}\n{_inputs()}\n{_surfaces()}\n{_datagrid()}\n"
            f"</ResourceDictionary>")


def layout_path(name: str) -> Path:
    """Where a layout file lives. Markup is a ``.xaml`` file, never a Python string (§12.2)."""
    return Path(__file__).resolve().parent / f"{name}.xaml"


def window_xaml(name: str) -> str:
    """A layout file with the generated theme spliced into its resources."""
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
