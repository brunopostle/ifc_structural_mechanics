"""Unit tests for the section_profiles registry."""

import pytest

from ifc_structural_mechanics.converters.section_profiles import (
    SECTION_REGISTRY,
    SectionProfile,
    expanded_rectangle_torsion_stiffness,
    get_native_section,
    rectangle_shear_moduli,
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

    def test_only_the_solid_rectangle_is_native(self):
        """CalculiX's CIRC, PIPE and BOX are not used; see the module docstring."""
        native = [k for k, v in SECTION_REGISTRY.items() if not v.use_general]
        assert native == ["rectangular"]

    def test_round_and_hollow_sections_are_general(self):
        for t in ("circular", "hollow_circular", "hollow_rectangular"):
            assert SECTION_REGISTRY[t].use_general

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


class TestRectangleShearModuli:
    """Timoshenko's shear along the depth, and the other modulus for torsion."""

    @pytest.mark.parametrize(
        "a, b, torsion_constant, across_width",
        [
            (0.3, 0.3, 0.1406 * 0.3**4, 0.8541),
            (0.4, 0.2, 0.229 * 0.4 * 0.2**3, 0.9781),
            (0.2, 0.4, 0.229 * 0.4 * 0.2**3, 0.8653),
        ],
        ids=["square", "deep", "flat"],
    )
    def test_torsion_is_matched_and_the_depth_shears_with_five_sixths(
        self, a, b, torsion_constant, across_width
    ):
        shear = 80e9
        modulus_12, modulus_13 = rectangle_shear_moduli(a, b, shear, torsion_constant)

        assert modulus_12 == pytest.approx(5 / 6 * shear)
        assert modulus_13 / shear == pytest.approx(across_width, abs=2e-3)
        assert expanded_rectangle_torsion_stiffness(
            a, b, modulus_12, modulus_13
        ) == pytest.approx(shear * torsion_constant)

    def test_deep_section_keeps_the_width_modulus_at_the_materials(self):
        """At 5:1 torsion would need more than G across the width: G13 is
        held at G and G12 raised, 8.6 % above 5/6 G."""
        shear = 80e9
        torsion_constant = 0.291 * 1.0 * 0.2**3
        modulus_12, modulus_13 = rectangle_shear_moduli(
            1.0, 0.2, shear, torsion_constant
        )

        assert modulus_13 == shear
        assert modulus_12 / (5 / 6 * shear) == pytest.approx(1.086, abs=2e-3)
        assert expanded_rectangle_torsion_stiffness(
            1.0, 0.2, modulus_12, modulus_13
        ) == pytest.approx(shear * torsion_constant)

    @pytest.mark.parametrize("torsion_constant", [0.0, -1.0, 0.3 * 0.3**3 / 3, 1.0])
    def test_impossible_torsion_constant_is_refused(self, torsion_constant):
        with pytest.raises(ValueError, match="torsion constant"):
            rectangle_shear_moduli(0.3, 0.3, 80e9, torsion_constant)

    def test_sizes_must_be_positive(self):
        with pytest.raises(ValueError, match="positive"):
            rectangle_shear_moduli(0.0, 0.3, 80e9, 1e-4)
