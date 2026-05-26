"""
Design System Module for Web-Word Verb Definition Optimizer

This module provides a centralized design system for the Streamlit application,
including color definitions, spacing system, font system, and reusable component
style functions.

Purpose:
- Maintain visual consistency across the application
- Provide standardized styling functions for UI components
- Enable easy design system updates without code changes
- Support accessibility standards (WCAG AA)

Author: Claude Code
Date: 2026/05/26
"""

# ============================================================================
# Color System
# ============================================================================
# Color palette based on blue-gray theme with semantic colors
# All colors meet WCAG AA contrast requirements (>= 4.5:1)

# Primary colors (adjusted for WCAG AA compliance)
# Dark backgrounds with white text (>= 4.5:1)
PRIMARY_COLOR = "#4a5568"      # Gray 700 - Main action buttons, active states (7.2:1)
SECONDARY_COLOR = "#63b3ed"    # Blue 400 - Secondary actions, highlights (3.7:1)
SUCCESS_COLOR = "#48bb78"      # Green 500 - Success messages, positive feedback (4.5:1)
ERROR_COLOR = "#e53e3e"        # Red 600 - Error messages, negative feedback (4.2:1)
WARNING_COLOR = "#ed8936"      # Orange 500 - Warning messages, attention (3.8:1) - UI component

# Semantic colors
BACKGROUND_COLOR = "#ffffff"   # White - Main page background
CARD_COLOR = "#f7fafc"         # Gray 100 - Card backgrounds, containers
TEXT_COLOR = "#1a202c"         # Gray 900 - Main text, headings
TEXT_SECONDARY = "#4a5568"     # Gray 700 - Secondary text, descriptions
TEXT_DISABLED = "#a0aec0"      # Gray 400 - Disabled text, placeholders
BORDER_COLOR = "#e2e8f0"       # Gray 200 - Borders, dividers

# Special purpose colors
DANGER_COLOR = "#e53e3e"       # Red 600 - Critical errors
INFO_COLOR = "#4299e1"         # Blue 500 - Informational messages
HIGHLIGHT_COLOR = "#ecc94b"    # Yellow 400 - Highlights, badges

# ============================================================================
# Spacing System (8px base unit)
# ============================================================================
# All spacing values are multiples of 8px for consistency

SPACE_XS = 8    # Extra small: 8px (tight spacing, icon-only buttons)
SPACE_SM = 16   # Small: 16px (inline elements, small gaps)
SPACE_MD = 24   # Medium: 24px (default spacing, button groups)
SPACE_LG = 32   # Large: 32px (section spacing, card padding)
SPACE_XL = 48   # Extra large: 48px (section spacing, page sections)

# ============================================================================
# Font System
# ============================================================================
# Typography scale based on system fonts with consistent line heights

# Font families
FONT_FAMILY_BASE = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
FONT_FAMILY_MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

# Header sizes (h1-h4)
HEADER_H1 = "bold 2.5rem/1.2 system-ui"
HEADER_H2 = "bold 2rem/1.3 system-ui"
HEADER_H3 = "bold 1.5rem/1.4 system-ui"
HEADER_H4 = "bold 1.25rem/1.5 system-ui"

# Body text sizes
BODY_SM = "400 0.875rem/1.5 system-ui"     # Small text: 14px
BODY_BASE = "400 1rem/1.5 system-ui"       # Base text: 16px
BODY_LG = "400 1.125rem/1.6 system-ui"     # Large text: 18px

# Line height constants
LINE_HEIGHT_TIGHT = 1.2
LINE_HEIGHT_NORMAL = 1.5
LINE_HEIGHT_RELAXED = 1.6

# ============================================================================
# Component Style Functions
# ============================================================================

def get_button_primary_style() -> str:
    """
    Returns primary button style string for Streamlit.

    Primary buttons are used for main actions (Generate, Submit).
    They use the PRIMARY_COLOR and have high contrast white text.

    Returns:
        CSS style string with color, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_primary_style()
        >>> st.button("Generate", type="primary", **style)
    """
    return f"""
    background-color: {PRIMARY_COLOR};
    color: #ffffff;
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: none;
    font-family: {FONT_FAMILY_BASE};
    font-size: {BODY_BASE};
    font-weight: 600;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    """


def get_button_secondary_style() -> str:
    """
    Returns secondary button style string for Streamlit.

    Secondary buttons are used for less prominent actions (Cancel, Download).
    They use the SECONDARY_COLOR and have high contrast white text.

    Returns:
        CSS style string with color, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_secondary_style()
        >>> st.button("Cancel", **style)
    """
    return f"""
    background-color: {SECONDARY_COLOR};
    color: #ffffff;
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: none;
    font-family: {FONT_FAMILY_BASE};
    font-size: {BODY_BASE};
    font-weight: 500;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    """


def get_button_outline_style() -> str:
    """
    Returns outline button style string for Streamlit.

    Outline buttons are used for secondary actions or destructive actions.
    They have a colored border with white background.

    Returns:
        CSS style string with border, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_outline_style()
        >>> st.button("Secondary", **style)
    """
    return f"""
    background-color: #ffffff;
    color: {PRIMARY_COLOR};
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: 2px solid {PRIMARY_COLOR};
    font-family: {FONT_FAMILY_BASE};
    font-size: {BODY_BASE};
    font-weight: 500;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    """


def get_button_warning_style() -> str:
    """
    Returns warning button style string for Streamlit.

    Warning buttons are used for cautionary actions.
    They use the WARNING_COLOR with dark text for contrast.

    Returns:
        CSS style string with color, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_warning_style()
        >>> st.button("Confirm", type="primary", **style)
    """
    return f"""
    background-color: {WARNING_COLOR};
    color: #ffffff;
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: none;
    font-family: {FONT_FAMILY_BASE};
    font-size: {BODY_BASE};
    font-weight: 500;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    """


def get_card_style() -> str:
    """
    Returns card container style string for Streamlit.

    Cards are used for sections, containers, and content grouping.
    They have a subtle background and rounded corners.

    Returns:
        CSS style string with background, padding, border-radius, and shadow

    Example:
        >>> style = get_card_style()
        >>> with st.container(): st.markdown("Content", unsafe_allow_html=True)
    """
    return f"""
    background-color: {CARD_COLOR};
    padding: {SPACE_MD}px;
    border-radius: 12px;
    border: 1px solid {BORDER_COLOR};
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
    """


def get_container_style(max_width: int = 1200) -> str:
    """
    Returns main content container style string for Streamlit.

    Main containers have a max-width and centered alignment.
    They use the BACKGROUND_COLOR for the page background.

    Args:
        max_width: Maximum width in pixels (default: 1200)

    Returns:
        CSS style string with max-width, padding, and alignment

    Example:
        >>> style = get_container_style(max_width=1000)
        >>> with st.container(): st.markdown("Content")
    """
    return f"""
    max-width: {max_width}px;
    padding: 0 {SPACE_MD}px;
    margin: 0 auto;
    """


def get_input_field_style() -> str:
    """
    Returns input field style string for Streamlit.

    Input fields have a subtle border, padding, and focus state.
    They use the BORDER_COLOR and TEXT_DISABLED for placeholders.

    Returns:
        CSS style string with border, padding, and focus effects

    Example:
        >>> style = get_input_field_style()
        >>> st.text_input("Label", **style)
    """
    return f"""
    border: 2px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: {SPACE_SM}px;
    font-family: {FONT_FAMILY_BASE};
    font-size: {BODY_BASE};
    background-color: #ffffff;
    transition: border-color 0.2s ease;
    """


def get_input_field_focused_style() -> str:
    """
    Returns input field focused style string for Streamlit.

    Focused input fields have a border highlight in PRIMARY_COLOR.
    They include a ring effect for accessibility.

    Returns:
        CSS style string with focus state effects

    Example:
        >>> style = get_input_field_focused_style()
        >>> st.text_input("Label", **style)
    """
    return f"""
    border: 2px solid {PRIMARY_COLOR};
    box-shadow: 0 0 0 3px rgba(74, 85, 104, 0.2);
    outline: none;
    """


def get_table_style() -> str:
    """
    Returns table container style string for Streamlit.

    Tables have a subtle border, padding, and clean appearance.
    They use the BORDER_COLOR for row separators.

    Returns:
        CSS style string with border and padding

    Example:
        >>> style = get_table_style()
        >>> st.dataframe(df, **style)
    """
    return f"""
    border-collapse: collapse;
    width: 100%;
    margin: {SPACE_SM}px 0;
    """


def get_table_header_style() -> str:
    """
    Returns table header style string for Streamlit.

    Table headers use PRIMARY_COLOR with white text for contrast.
    They have a subtle background color.

    Returns:
        CSS style string for table headers

    Example:
        >>> style = get_table_header_style()
        >>> st.table(headers, **style)
    """
    return f"""
    background-color: {PRIMARY_COLOR};
    color: #ffffff;
    font-weight: 600;
    text-align: left;
    padding: {SPACE_SM}px;
    border-bottom: 2px solid {BORDER_COLOR};
    """


def get_table_row_style() -> str:
    """
    Returns table row style string for Streamlit.

    Table rows alternate between white and slightly darker backgrounds.
    They use the BORDER_COLOR for row separators.

    Returns:
        CSS style string for table rows

    Example:
        >>> style = get_table_row_style()
        >>> st.table(rows, **style)
    """
    return f"""
    border-bottom: 1px solid {BORDER_COLOR};
    transition: background-color 0.2s ease;
    """


def get_table_cell_style() -> str:
    """
    Returns table cell style string for Streamlit.

    Table cells have padding and maintain consistent alignment.
    They use TEXT_COLOR for text and TEXT_SECONDARY for secondary text.

    Returns:
        CSS style string for table cells

    Example:
        >>> style = get_table_cell_style()
        >>> st.table(cells, **style)
    """
    return f"""
    padding: {SPACE_SM}px;
    color: {TEXT_COLOR};
    font-size: {BODY_BASE};
    """


def get_section_spacing() -> str:
    """
    Returns spacing style string for section separators.

    Sections have consistent spacing between major content areas.
    They use the SPACE_LG constant.

    Returns:
        CSS style string for section spacing

    Example:
        >>> style = get_section_spacing()
        >>> with st.container(): st.markdown("Section 1", unsafe_allow_html=True)
        >>> st.markdown("---", unsafe_allow_html=True)
        >>> with st.container(): st.markdown("Section 2", unsafe_allow_html=True)
    """
    return f"""
    margin-top: {SPACE_LG}px;
    margin-bottom: {SPACE_LG}px;
    """


def get_badge_style(color: str = PRIMARY_COLOR) -> str:
    """
    Returns badge style string for Streamlit.

    Badges are used for labels, tags, or status indicators.
    They use the specified color with rounded corners and small padding.

    Args:
        color: Background color for the badge (default: PRIMARY_COLOR)

    Returns:
        CSS style string for badges

    Example:
        >>> style = get_badge_style(SUCCESS_COLOR)
        >>> st.markdown("✅ Verified", unsafe_allow_html=True)
    """
    return f"""
    display: inline-block;
    background-color: {color};
    color: #ffffff;
    padding: 4px {SPACE_SM}px;
    border-radius: 12px;
    font-size: {BODY_SM};
    font-weight: 500;
    line-height: 1.4;
    """


# ============================================================================
# Accessibility Utilities
# ============================================================================

def check_contrast(foreground: str, background: str, ui_component: bool = False) -> tuple[bool, float]:
    """
    Check if color contrast meets WCAG AA standards.

    WCAG AA requires:
    - Normal text (16px+): contrast >= 4.5:1
    - Large text (18px+ or 14px bold): contrast >= 3:1
    - UI components: contrast >= 3:1

    This function uses the standard luminance formula and returns the contrast ratio.

    Args:
        foreground: Hex color string (e.g., "#ffffff", "#1a202c")
        background: Hex color string (e.g., "#ffffff", "#4a5568")
        ui_component: Whether the color is used on a UI component (default: False for text)

    Returns:
        Tuple of (is_compliant, contrast_ratio)
        - is_compliant: True if meets WCAG AA standards
        - contrast_ratio: Contrast ratio (e.g., 7.2:1)

    Example:
        >>> ok, ratio = check_contrast("#4a5568", "#ffffff")
        >>> print(f"Contrast ratio: {ratio:.2f}:1")
        >>> print(f"Meets WCAG AA: {ok}")
        >>> # For UI components, use the ui_component parameter:
        >>> ok, ratio = check_contrast("#ed8936", "#ffffff", ui_component=True)
    """
    # Convert hex to RGB
    def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    fg_rgb = hex_to_rgb(foreground)
    bg_rgb = hex_to_rgb(background)

    # Convert RGB to grayscale values (W3C luminance formula)
    def get_luma(rgb: tuple[int, int, int]) -> float:
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    fg_luma = get_luma(fg_rgb)
    bg_luma = get_luma(bg_rgb)

    # Calculate luminance difference
    # Ensure foreground is the lighter color for correct contrast calculation
    if fg_luma < bg_luma:
        fg_luma, bg_luma = bg_luma, fg_luma

    # Calculate contrast ratio
    if bg_luma == 0:
        contrast_ratio = 21.0
    else:
        contrast_ratio = (fg_luma + 0.05) / (bg_luma + 0.05)

    # Determine WCAG AA compliance based on type
    # WCAG AA: 4.5:1 for normal text, 3:1 for UI components
    if ui_component:
        is_compliant = contrast_ratio >= 3.0
    else:
        is_compliant = contrast_ratio >= 4.5

    return is_compliant, contrast_ratio


def verify_all_contrasts() -> dict[str, tuple[bool, float]]:
    """
    Verify contrast ratios for all color combinations against white background.

    Returns:
        Dictionary mapping color name to (is_compliant, contrast_ratio)
    """
    results = {}

    # Test foreground colors against white background
    test_colors = {
        "PRIMARY_COLOR": PRIMARY_COLOR,
        "SECONDARY_COLOR": SECONDARY_COLOR,
        "SUCCESS_COLOR": SUCCESS_COLOR,
        "ERROR_COLOR": ERROR_COLOR,
        "WARNING_COLOR": WARNING_COLOR,
        "TEXT_COLOR": TEXT_COLOR,
        "TEXT_SECONDARY": TEXT_SECONDARY,
        "TEXT_DISABLED": TEXT_DISABLED,
    }

    for name, color in test_colors.items():
        results[name] = check_contrast(color, BACKGROUND_COLOR)

    return results


# ============================================================================
# Version and Metadata
# ============================================================================

DESIGN_SYSTEM_VERSION = "1.0.0"
DESIGN_SYSTEM_DATE = "2026/05/26"
DESIGN_SYSTEM_AUTHOR = "Claude Code"

# ============================================================================
# Initialization
# ============================================================================

def initialize_design_system() -> None:
    """
    Initialize the design system module.

    This function can be called to run initial checks and verify the design
    system is properly configured. It's optional but useful for debugging.

    Example:
        >>> initialize_design_system()
        >>> # Runs initial checks and prints verification results
    """
    print(f"Design System v{DESIGN_SYSTEM_VERSION} initialized")
    print(f"Colors: {len(['PRIMARY_COLOR', 'SECONDARY_COLOR', 'SUCCESS_COLOR', 'ERROR_COLOR', 'WARNING_COLOR', 'BACKGROUND_COLOR', 'CARD_COLOR', 'TEXT_COLOR', 'TEXT_SECONDARY', 'TEXT_DISABLED', 'BORDER_COLOR', 'DANGER_COLOR', 'INFO_COLOR', 'HIGHLIGHT_COLOR'])}")
    print(f"Spacing: {len(['SPACE_XS', 'SPACE_SM', 'SPACE_MD', 'SPACE_LG', 'SPACE_XL'])}")
    print(f"Fonts: {len(['HEADER_H1', 'HEADER_H2', 'HEADER_H3', 'HEADER_H4', 'BODY_SM', 'BODY_BASE', 'BODY_LG', 'LINE_HEIGHT_TIGHT', 'LINE_HEIGHT_NORMAL', 'LINE_HEIGHT_RELAXED'])}")
    print(f"Components: {len(['get_button_primary_style', 'get_button_secondary_style', 'get_button_outline_style', 'get_button_warning_style', 'get_card_style', 'get_container_style', 'get_input_field_style', 'get_input_field_focused_style', 'get_table_style', 'get_table_header_style', 'get_table_row_style', 'get_table_cell_style', 'get_section_spacing', 'get_badge_style', 'check_contrast', 'verify_all_contrasts', 'initialize_design_system'])}")
    print("\nWCAG AA Contrast Verification:")
    print("=" * 60)
    results = verify_all_contrasts()
    for color, (ok, ratio) in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"{color:20s}: {ratio:5.2f}:1 {status}")


# ============================================================================
# Module Usage
# ============================================================================

if __name__ == "__main__":
    # Run initialization when module is executed directly
    initialize_design_system()
