"""Tests for PIPE and BOX section extraction from hollow IFC profile types."""

import math
from unittest.mock import MagicMock

import pytest

from ifc_structural_mechanics.domain.property import Section


def _make_hollow_circle_profile(radius, wall_thickness, name="HSS 60.3x3.2"):
    """Create a mock IfcCircleHollowProfileDef."""
    p = MagicMock()
    p.is_a.side_effect = lambda t: t == "IfcCircleHollowProfileDef"
    p.Radius = radius
    p.WallThickness = wall_thickness
    p.ProfileName = name
    p.id.return_value = "profile-pipe-1"
    return p


def _make_hollow_rect_profile(x_dim, y_dim, wall_thickness, name="RHS 100x50x5"):
    """Create a mock IfcRectangleHollowProfileDef."""
    p = MagicMock()
    p.is_a.side_effect = lambda t: t == "IfcRectangleHollowProfileDef"
    p.XDim = x_dim
    p.YDim = y_dim
    p.WallThickness = wall_thickness
    p.ProfileName = name
    p.id.return_value = "profile-box-1"
    return p


class TestHollowSectionExtractionFromMembersExtractor:
    """Verify _create_section() in MembersExtractor handles hollow profiles."""

    def _make_extractor(self, length_scale=1.0):
        from ifc_structural_mechanics.ifc.members_extractor import MembersExtractor
        extractor = MagicMock(spec=MembersExtractor)
        extractor.length_scale = length_scale
        extractor._create_section = MembersExtractor._create_section.__get__(extractor)
        return extractor

    def test_pipe_section_type(self):
        profile = _make_hollow_circle_profile(radius=0.03, wall_thickness=0.003)
        extractor = self._make_extractor()
        section = extractor._create_section(profile)
        assert section is not None
        assert section.section_type == "pipe"

    def test_pipe_outer_radius(self):
        profile = _make_hollow_circle_profile(radius=0.03, wall_thickness=0.003)
        extractor = self._make_extractor()
        section = extractor._create_section(profile)
        assert abs(section.dimensions["outer_radius"] - 0.03) < 1e-9

    def test_pipe_inner_radius(self):
        profile = _make_hollow_circle_profile(radius=0.03, wall_thickness=0.003)
        extractor = self._make_extractor()
        section = extractor._create_section(profile)
        assert abs(section.dimensions["inner_radius"] - 0.027) < 1e-9

    def test_pipe_area(self):
        outer_r, wall_t = 0.03, 0.003
        inner_r = outer_r - wall_t
        expected_area = math.pi * (outer_r**2 - inner_r**2)
        profile = _make_hollow_circle_profile(radius=outer_r, wall_thickness=wall_t)
        extractor = self._make_extractor()
        section = extractor._create_section(profile)
        assert abs(section.area - expected_area) < 1e-9

    def test_box_section_type(self):
        profile = _make_hollow_rect_profile(x_dim=0.1, y_dim=0.2, wall_thickness=0.005)
        extractor = self._make_extractor()
        section = extractor._create_section(profile)
        assert section is not None
        assert section.section_type == "box"

    def test_box_dimensions(self):
        profile = _make_hollow_rect_profile(x_dim=0.1, y_dim=0.2, wall_thickness=0.005)
        extractor = self._make_extractor()
        section = extractor._create_section(profile)
        assert abs(section.dimensions["width"] - 0.1) < 1e-9
        assert abs(section.dimensions["height"] - 0.2) < 1e-9
        assert abs(section.dimensions["wall_thickness"] - 0.005) < 1e-9

    def test_box_area(self):
        w, h, t = 0.1, 0.2, 0.005
        expected_area = w * h - (w - 2 * t) * (h - 2 * t)
        profile = _make_hollow_rect_profile(x_dim=w, y_dim=h, wall_thickness=t)
        extractor = self._make_extractor()
        section = extractor._create_section(profile)
        assert abs(section.area - expected_area) < 1e-9

    def test_pipe_with_mm_units(self):
        """length_scale=0.001 (mm IFC): dimensions are converted to metres."""
        profile = _make_hollow_circle_profile(radius=30.0, wall_thickness=3.0)  # mm
        extractor = self._make_extractor(length_scale=0.001)
        section = extractor._create_section(profile)
        assert abs(section.dimensions["outer_radius"] - 0.03) < 1e-9
        assert abs(section.dimensions["inner_radius"] - 0.027) < 1e-9


class TestHollowSectionExtractionFromPropertiesExtractor:
    """Verify section extraction in PropertiesExtractor handles hollow profiles."""

    def _extractor_section_from_profile(self, profile, length_scale=1.0):
        from ifc_structural_mechanics.ifc.properties_extractor import PropertiesExtractor
        extractor = MagicMock(spec=PropertiesExtractor)
        extractor.length_scale = length_scale
        extractor.logger = MagicMock()
        extractor._safe_get_attribute = lambda obj, attr, default=None: getattr(obj, attr, default)
        extractor._create_default_section = lambda: None
        extractor._find_related_profile = MagicMock(return_value=profile)
        extractor._create_i_section = MagicMock(return_value=None)
        extractor.extract_section = PropertiesExtractor.extract_section.__get__(extractor)

        entity = MagicMock()
        return extractor.extract_section(entity)

    def test_pipe_type_from_properties_extractor(self):
        profile = _make_hollow_circle_profile(radius=0.03, wall_thickness=0.003)
        section = self._extractor_section_from_profile(profile)
        assert section is not None
        assert section.section_type == "pipe"
        assert abs(section.dimensions["outer_radius"] - 0.03) < 1e-9
        assert abs(section.dimensions["inner_radius"] - 0.027) < 1e-9

    def test_box_type_from_properties_extractor(self):
        profile = _make_hollow_rect_profile(x_dim=0.1, y_dim=0.2, wall_thickness=0.005)
        section = self._extractor_section_from_profile(profile)
        assert section is not None
        assert section.section_type == "box"
        assert abs(section.dimensions["width"] - 0.1) < 1e-9
