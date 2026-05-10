"""Unit tests for the section_profiles registry."""

import pytest

from ifc_structural_mechanics.converters.section_profiles import (
    SECTION_REGISTRY,
    SectionProfile,
    get_native_section,
    is_supported,
    uses_user_element,
)

# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_entries_are_section_profiles(self):
        for key, val in SECTION_REGISTRY.items():
            assert isinstance(val, SectionProfile), f"{key} is not a SectionProfile"

    def test_native_types_have_keyword_and_formatter(self):
        for key, val in SECTION_REGISTRY.items():
            if not val.use_general:
                assert val.ccx_keyword is not None, f"{key}: missing ccx_keyword"
                assert callable(val.format_data_line), f"{key}: missing formatter"

    def test_general_types_have_no_keyword(self):
        for key, val in SECTION_REGISTRY.items():
            if val.use_general:
                assert val.ccx_keyword is None, f"{key}: should have no ccx_keyword"
                assert val.format_data_line is None, f"{key}: should have no formatter"

    def test_known_native_types_present(self):
        for t in ("rectangular", "circular", "pipe", "box"):
            assert t in SECTION_REGISTRY, f"Missing native type: {t}"
            assert not SECTION_REGISTRY[t].use_general

    def test_known_general_types_present(self):
        for t in ("i", "l", "t", "c"):
            assert t in SECTION_REGISTRY, f"Missing general type: {t}"
            assert SECTION_REGISTRY[t].use_general


# ---------------------------------------------------------------------------
# uses_user_element()
# ---------------------------------------------------------------------------


class TestUsesUserElement:
    def test_none_returns_false(self):
        assert uses_user_element(None) is False

    def test_rectangular_is_b31(self):
        assert uses_user_element("rectangular") is False

    def test_i_is_general(self):
        assert uses_user_element("i") is True

    def test_l_is_general(self):
        assert uses_user_element("l") is True

    def test_t_is_general(self):
        assert uses_user_element("t") is True

    def test_c_is_general(self):
        assert uses_user_element("c") is True

    def test_unknown_type_defaults_to_general(self):
        assert uses_user_element("totally_unknown_section") is True

    def test_case_insensitive(self):
        assert uses_user_element("RECTANGULAR") is False
        assert uses_user_element("I") is True


# ---------------------------------------------------------------------------
# get_native_section()
# ---------------------------------------------------------------------------


class TestGetNativeSection:
    def test_rect_returns_profile(self):
        p = get_native_section("rectangular")
        assert p is not None
        assert p.ccx_keyword == "RECT"

    def test_i_returns_none(self):
        assert get_native_section("i") is None

    def test_none_returns_none(self):
        assert get_native_section(None) is None

    def test_unknown_returns_none(self):
        assert get_native_section("spaghetti") is None


# ---------------------------------------------------------------------------
# Format data lines (B31 native types)
# ---------------------------------------------------------------------------


class TestFormatDataLines:
    def _fmt(self, section_type, dims):
        p = get_native_section(section_type)
        assert p is not None
        return p.format_data_line(dims)

    def test_rect_format(self):
        line = self._fmt("rectangular", {"width": 0.2, "height": 0.3})
        assert "2.000000e-01" in line
        assert "3.000000e-01" in line

    def test_circ_format(self):
        line = self._fmt("circular", {"radius": 0.05})
        assert "5.000000e-02" in line

    def test_pipe_format(self):
        line = self._fmt("pipe", {"outer_radius": 0.06, "inner_radius": 0.05})
        assert "6.000000e-02" in line
        assert "5.000000e-02" in line

    def test_box_format_has_four_thickness_values(self):
        line = self._fmt("box", {"height": 0.3, "width": 0.2, "wall_thickness": 0.01})
        parts = [p.strip() for p in line.split(",")]
        assert len(parts) == 6

    def test_hollow_circ_inner_radius_computed(self):
        p = get_native_section("hollow_circular")
        assert p is not None
        line = p.format_data_line({"outer_radius": 0.1, "thickness": 0.01})
        # inner = 0.1 - 0.01 = 0.09
        assert "9.000000e-02" in line


# ---------------------------------------------------------------------------
# is_supported()
# ---------------------------------------------------------------------------


class TestIsSupported:
    def test_rectangular_is_supported(self):
        assert is_supported("rectangular")

    def test_i_is_supported(self):
        assert is_supported("i")

    def test_unknown_is_not_supported(self):
        assert not is_supported("unknown_exotic_shape")

    def test_none_is_not_supported(self):
        assert not is_supported(None)
