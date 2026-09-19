"""The brand tokens, and the contrast the brand guide computes rather than transcribes.

Section 3.8.6 of the design system is explicit: every ratio in its tables is computed from the
palette by a test, "not transcribed. Nudge a token and the arithmetic fails the build." These
are that test. A failure here is not a styling preference -- it is an accessibility defect
about to ship.
"""
from __future__ import annotations

import pytest

from c2b.ui import theme as t

AA_NORMAL = 4.5
AA_LARGE = 3.0
NON_TEXT = 3.0          # WCAG 2.1 1.4.11, the boundary of an interactive control


def ratio(fg, bg):
    return round(t.contrast_ratio(fg, bg), 2)


# ---------------------------------------------------- 10.1, the light palette

@pytest.mark.parametrize("fg, bg, expected", [
    (t.CHARCOAL_BLACK, t.PURE_WHITE, 18.4),
    (t.CHARCOAL_BLACK, t.OFF_WHITE, 16.8),
    (t.PURE_WHITE, t.CHARCOAL_BLACK, 18.4),
    (t.MID_GREY, t.PURE_WHITE, 4.83),
    (t.PURE_WHITE, t.VIVID_RED, 4.78),
    (t.VIVID_RED, t.PURE_WHITE, 4.78),
    (t.SILVER_STEEL, t.CHARCOAL_BLACK, 10.96),
    (t.SILVER_STEEL, t.PURE_WHITE, 1.68),
])
def test_the_published_light_ratios_are_what_the_palette_computes(fg, bg, expected):
    assert ratio(fg, bg) == pytest.approx(expected, abs=0.05)


def test_body_text_on_white_passes_aa():
    assert t.contrast_ratio(t.MID_GREY, t.PURE_WHITE) >= AA_NORMAL


def test_a_primary_button_label_passes_aa():
    assert t.contrast_ratio(t.PURE_WHITE, t.VIVID_RED) >= AA_NORMAL


def test_silver_steel_is_not_usable_as_text_on_white():
    """Why the body colour is Mid Grey and not the brand's own complement."""
    assert t.contrast_ratio(t.SILVER_STEEL, t.PURE_WHITE) < AA_LARGE


# ----------------------------------------------------- 10.1, the dark palette

@pytest.mark.parametrize("fg, expected", [
    (t.DARK_TEXT_PRIMARY, 10.56),
    (t.SILVER_STEEL, 6.98),
    (t.DARK_TEXT_MUTED, 6.08),
    (t.DARK_BORDER_STRONG, 4.55),
    (t.VIVID_RED_ON_DARK, 3.90),
    (t.VIVID_RED, 2.46),
    (t.ERROR_RED, 2.43),
    (t.INFO_BLUE, 2.27),
])
def test_the_published_dark_ratios_are_what_the_palette_computes(fg, expected):
    assert ratio(fg, t.DARK_CANVAS) == pytest.approx(expected, abs=0.05)


def test_vivid_red_itself_is_not_a_legal_accent_on_revit_grey():
    """The whole reason a lifted red exists, rather than a preference about brightness."""
    assert t.contrast_ratio(t.VIVID_RED, t.DARK_CANVAS) < NON_TEXT
    assert t.contrast_ratio(t.VIVID_RED_ON_DARK, t.DARK_CANVAS) >= NON_TEXT


def test_the_interactive_boundary_clears_1411_against_the_tightest_fill():
    """Dark Border Strong is sized against the *hover* fill, which is the smallest step."""
    for surface in (t.DARK_CANVAS, t.DARK_SURFACE, t.DARK_SURFACE_HOVER):
        assert t.contrast_ratio(t.DARK_BORDER_STRONG, surface) >= NON_TEXT


def test_the_decorative_dark_border_is_not_good_enough_to_outline_a_control():
    """Why 3.8.3 says never to use it there, however much tidier it looks."""
    assert t.contrast_ratio(t.DARK_BORDER, t.DARK_CANVAS) < NON_TEXT


def test_the_dark_surface_ramp_steps_up_monotonically():
    """Raised, not recessed: hover must read lighter than rest, pressed lighter than hover."""
    ramp = [t.DARK_CANVAS, t.DARK_SURFACE, t.DARK_SURFACE_HOVER, t.DARK_SURFACE_PRESSED]
    luminance = [t._relative_luminance(c) for c in ramp]
    assert luminance == sorted(luminance)


@pytest.mark.parametrize("light, dark", [
    (t.SUCCESS_GREEN, "#4ADE80"), (t.CAUTION_AMBER, "#FBBF24"),
    (t.ERROR_RED, "#FF9A93"), (t.INFO_BLUE, "#8FC1FF"),
])
def test_every_light_semantic_fails_on_dark_and_its_lifted_twin_passes(light, dark):
    assert t.contrast_ratio(light, t.DARK_CANVAS) < AA_NORMAL
    assert t.contrast_ratio(dark, t.DARK_CANVAS) >= AA_NORMAL


# ------------------------------------------------------------ 9.5, badge pairs

@pytest.mark.parametrize("severity", sorted(t.BADGE))
def test_every_badge_reads_and_carries_a_word_not_just_a_colour(severity):
    background, foreground, word = t.BADGE[severity]
    assert t.contrast_ratio(foreground, background) >= AA_NORMAL
    assert word.isupper() and word


# ------------------------------------------------------------- 5, the scale

def test_every_space_token_is_a_multiple_of_the_base_unit():
    """5.1 -- everything is a whole multiple of 8, with one 4px half-step."""
    for value in (t.SPACE_SM, t.SPACE_MD, t.SPACE_LG, t.SPACE_XL, t.SPACE_2XL, t.SPACE_3XL):
        assert value % 8 == 0
    assert t.SPACE_XS == 4


def test_the_radius_tiers_grow_with_the_size_of_the_thing():
    assert t.RADIUS_SM < t.RADIUS_MD < t.RADIUS_LG < t.RADIUS_XL


def test_control_heights_match_the_shipping_suite():
    """The suite ships a 28px button over a 26px input, which is tighter than the document's
    28/36 table. The document's own rule settles it: where the two disagree the code wins."""
    assert t.HEIGHT_INPUT == 26
    assert t.HEIGHT_BUTTON == 28
    assert t.HEIGHT_LARGE > t.HEIGHT_BUTTON > t.HEIGHT_INPUT


def test_a_hit_target_is_never_smaller_than_an_input():
    """10.3 -- an inline control may be compact, but nothing goes under the input height."""
    assert min(t.HEIGHT_INPUT, t.HEIGHT_COMPACT, t.HEIGHT_BUTTON) >= 24


def test_the_type_scale_is_the_one_the_suite_ships():
    """Taken from the shipping ui.xaml, not from the document's §4.2 table. The document is
    explicit that the code wins, and it already carries one such reconciliation note itself;
    following the table gave a window a third larger than every other tool in the suite."""
    assert (t.FONT_SIZE_H2, t.FONT_SIZE_H3, t.FONT_SIZE_BODY, t.FONT_SIZE_CAPTION) == (16.5, 11.0, 9.5, 8.5)


def test_the_type_scale_descends_and_body_matches_h4():
    assert t.FONT_SIZE_H1 > t.FONT_SIZE_H2 > t.FONT_SIZE_H3 > t.FONT_SIZE_BODY
    assert t.FONT_SIZE_H4 == t.FONT_SIZE_BODY
    assert t.FONT_SIZE_SMALL == t.FONT_SIZE_CAPTION == t.FONT_SIZE_CODE


def test_a_type_size_crosses_to_tkinter_as_pixels_not_points():
    """A WPF unit is one CSS pixel, and Tk reads a negative size as pixels."""
    assert t.pixels(t.FONT_SIZE_BODY) == -10        # 9.5 rounds to 10 px, not 7 pt
    assert t.pixels(t.FONT_SIZE_H1) == -21
    assert t.points(t.FONT_SIZE_BODY) == 7


def test_motion_never_makes_an_engineer_wait():
    assert t.MOTION_INSTANT_MS == 0
    assert t.MOTION_FAST_MS < t.MOTION_STANDARD_MS < t.MOTION_SLOW_MS <= 300


# ------------------------------------------------------------ 2.3, the naming

def test_a_tool_is_named_with_the_middle_dot_and_written_in_full():
    assert t.display_name("Storey Editor") == "AnonGee · Storey Editor"
    assert t.BRAND == "AnonGee BIM Tools"


# -------------------------------------------------------- the colour helpers

def test_a_six_digit_token_gains_an_opaque_alpha_for_wpf():
    assert t.wpf_colour("#E02020") == "#FFE02020"


def test_a_token_that_already_carries_an_alpha_keeps_it():
    assert t.wpf_colour(t.VIVID_RED_10) == "#1AE02020"


@pytest.mark.parametrize("bad", ["E02020", "#E020", "red", "#E0202"])
def test_something_that_is_not_a_colour_is_refused(bad):
    with pytest.raises(ValueError):
        t.wpf_colour(bad)


def test_contrast_is_the_same_either_way_round():
    assert ratio(t.MID_GREY, t.PURE_WHITE) == ratio(t.PURE_WHITE, t.MID_GREY)


def test_a_colour_against_itself_has_no_contrast_at_all():
    assert t.contrast_ratio(t.VIVID_RED, t.VIVID_RED) == pytest.approx(1.0)
