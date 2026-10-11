"""Circular and hollow IFC profiles become sections with their own properties.

Real IFC entities are used, not mocks: ``IfcCircleHollowProfileDef`` and
``IfcRectangleHollowProfileDef`` are subtypes of the solid profiles, so
``is_a()`` on the solid type is true for them. Testing the solid type first
once turned every hollow section into a solid one.
"""

import math
from unittest.mock import MagicMock

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.members_extractor import (  # noqa: E402
    MembersExtractor,
)

# An entity is only valid while its file is alive
_FILES = []


def _profile(ifc_class, **attributes):
    model = ifcopenshell.file(schema="IFC4")
    _FILES.append(model)
    return model.create_entity(
        ifc_class, ProfileType="AREA", ProfileName="benchmark", **attributes
    )


def _from_members_extractor(profile, length_scale=1.0):
    extractor = MagicMock(spec=MembersExtractor)
    extractor.length_scale = length_scale
    return MembersExtractor._create_section(extractor, profile)


EXTRACTORS = pytest.mark.parametrize("extract", [_from_members_extractor])


@EXTRACTORS
class TestProfiles:
    def test_pipe(self, extract):
        section = extract(
            _profile("IfcCircleHollowProfileDef", Radius=0.15, WallThickness=0.01)
        )

        assert section.section_type == "hollow_circular"
        assert section.area == pytest.approx(math.pi * (0.15**2 - 0.14**2))
        assert section.moment_of_inertia_y == pytest.approx(
            math.pi / 4 * (0.15**4 - 0.14**4)
        )
        assert section.moment_of_inertia_z == pytest.approx(section.moment_of_inertia_y)

    def test_box(self, extract):
        section = extract(
            _profile(
                "IfcRectangleHollowProfileDef", XDim=0.2, YDim=0.4, WallThickness=0.01
            )
        )

        assert section.section_type == "hollow_rectangular"
        assert section.area == pytest.approx(0.2 * 0.4 - 0.18 * 0.38)
        # The depth (YDim) goes with the strong axis, as for a solid rectangle
        assert section.moment_of_inertia_y == pytest.approx(
            (0.2 * 0.4**3 - 0.18 * 0.38**3) / 12
        )
        assert section.moment_of_inertia_z == pytest.approx(
            (0.4 * 0.2**3 - 0.38 * 0.18**3) / 12
        )

    def test_solid_circle(self, extract):
        section = extract(_profile("IfcCircleProfileDef", Radius=0.15))

        assert section.section_type == "circular"
        assert section.area == pytest.approx(math.pi * 0.15**2)
        assert section.moment_of_inertia_y == pytest.approx(math.pi / 4 * 0.15**4)

    def test_solid_rectangle_is_still_a_rectangle(self, extract):
        section = extract(_profile("IfcRectangleProfileDef", XDim=0.2, YDim=0.4))

        assert section.section_type == "rectangular"
        assert section.area == pytest.approx(0.08)

    def test_millimetres(self, extract):
        section = extract(
            _profile("IfcCircleHollowProfileDef", Radius=150.0, WallThickness=10.0),
            length_scale=0.001,
        )

        assert section.dimensions["outer_radius"] == pytest.approx(0.15)
        assert section.dimensions["thickness"] == pytest.approx(0.01)


def test_thin_tube_shears_over_about_half_its_area():
    section = _from_members_extractor(
        _profile("IfcCircleHollowProfileDef", Radius=0.15, WallThickness=0.001)
    )

    assert section.shear_area_y / section.area == pytest.approx(0.53, abs=0.01)


def test_channel_is_read_from_the_u_shape_profile():
    """IFC calls a channel IfcUShapeProfileDef; there is no IfcChannelProfileDef."""
    section = _from_members_extractor(
        _profile(
            "IfcUShapeProfileDef",
            Depth=0.4,
            FlangeWidth=0.2,
            WebThickness=0.01,
            FlangeThickness=0.02,
        )
    )

    assert section.section_type == "c"
    assert section.area == pytest.approx(0.4 * 0.01 + 2 * 0.19 * 0.02)
    assert section.moment_of_inertia_y > section.moment_of_inertia_z > 0


def test_unsupported_profile_is_an_error_not_a_default_section():
    from ifc_structural_mechanics.utils.error_handling import ModelExtractionError

    profile = _profile(
        "IfcZShapeProfileDef",
        Depth=0.4,
        FlangeWidth=0.2,
        WebThickness=0.01,
        FlangeThickness=0.02,
    )

    with pytest.raises(ModelExtractionError, match="IfcZShapeProfileDef"):
        _from_members_extractor(profile)
