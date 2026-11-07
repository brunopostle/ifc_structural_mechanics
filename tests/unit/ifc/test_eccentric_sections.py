"""Where a section's centroid lies from its member's reference curve (94g.35).

IFC puts the origin of a profile on the reference curve of a structural curve
member, its x along the member's local y and its y along local z. A
parameterised profile has the middle of its bounding box there, so a T, an
asymmetric I, an angle or a channel has its centroid off the curve, and the
profile's ``Position`` moves it. Both were once left out: every member was
analysed as if its centroid were on the curve.
"""

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.members_extractor import (  # noqa: E402
    MembersExtractor,
)
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

_FILES = []


def _profile(ifc_class, position=None, **attributes):
    """A profile in millimetres; ``position`` is ``((x, y), (dx, dy))``."""
    model = ifcopenshell.file(schema="IFC4")
    _FILES.append(model)
    placement = None
    if position is not None:
        location, direction = position
        placement = model.create_entity(
            "IfcAxis2Placement2D",
            model.create_entity("IfcCartesianPoint", [float(v) for v in location]),
            (
                model.create_entity("IfcDirection", [float(v) for v in direction])
                if direction is not None
                else None
            ),
        )
    return model.create_entity(
        ifc_class,
        ProfileType="AREA",
        ProfileName="eccentric",
        Position=placement,
        **attributes,
    )


def _section(profile):
    return MembersExtractor(profile.file, {"LENGTHUNIT": 0.001})._create_section(
        profile
    )


def _tee(position=None):
    return _profile(
        "IfcTShapeProfileDef",
        position,
        Depth=400.0,
        FlangeWidth=200.0,
        WebThickness=10.0,
        FlangeThickness=20.0,
    )


# The T's flange is on top: 200 x 20 at 190 mm above the middle of its depth,
# and a web of 10 x 380 at 10 mm below it
_TEE_CENTROID = (4000.0 * 190.0 - 3800.0 * 10.0) / 7800.0 / 1000.0


def test_a_tee_has_its_centroid_towards_its_flange():
    section = _section(_tee())
    assert section.centroid_offset[0] == pytest.approx(0.0, abs=1e-12)
    assert section.centroid_offset[1] == pytest.approx(_TEE_CENTROID)


def test_its_farthest_fibres_are_from_its_centroid():
    """The tip of the web, 0.2 m below the middle; the flange's edges across."""
    section = _section(_tee())
    assert section.get_extreme_fibre_distances() == pytest.approx(
        (0.2 + _TEE_CENTROID, 0.1)
    )


def test_an_asymmetric_i_has_its_centroid_towards_its_wider_flange():
    profile = _profile(
        "IfcAsymmetricIShapeProfileDef",
        BottomFlangeWidth=300.0,
        OverallDepth=400.0,
        WebThickness=10.0,
        BottomFlangeThickness=20.0,
        TopFlangeWidth=100.0,
        TopFlangeThickness=20.0,
    )
    plates = [(6000.0, -190.0), (2000.0, 190.0), (3600.0, 0.0)]
    centre = sum(a * z for a, z in plates) / sum(a for a, _ in plates)
    section = _section(profile)
    assert centre < 0.0
    assert section.centroid_offset[1] == pytest.approx(centre / 1000.0)
    # The narrow flange's top, farther from the centroid than the middle
    assert section.get_extreme_fibre_distances()[0] == pytest.approx(
        0.2 - centre / 1000.0
    )


def test_an_angle_has_its_centroid_off_both_ways():
    profile = _profile("IfcLShapeProfileDef", Depth=400.0, Width=200.0, Thickness=20.0)
    # The upright leg on the left, the other along the bottom
    plates = [(8000.0, (-90.0, 0.0)), (3600.0, (10.0, -190.0))]
    area = sum(a for a, _ in plates)
    expected = [sum(a * c[i] for a, c in plates) / area / 1000.0 for i in (0, 1)]
    assert _section(profile).centroid_offset == pytest.approx(expected)


def test_a_symmetric_profile_is_centric():
    profile = _profile("IfcRectangleProfileDef", XDim=200.0, YDim=400.0)
    assert _section(profile).centroid_offset == (0.0, 0.0)


class TestPosition:
    def test_moves_a_rectangle_off_the_curve(self):
        """A downstand beam drawn with its top on the curve."""
        profile = _profile(
            "IfcRectangleProfileDef", ((0.0, -200.0), None), XDim=200.0, YDim=400.0
        )
        assert _section(profile).centroid_offset == pytest.approx((0.0, -0.2))

    def test_puts_a_tee_on_its_centroid(self):
        profile = _tee(((0.0, -_TEE_CENTROID * 1000.0), (1.0, 0.0)))
        assert _section(profile).centroid_offset == pytest.approx((0.0, 0.0), abs=1e-12)

    def test_turns_a_tee_upside_down(self):
        section = _section(_tee(((25.0, 0.0), (-1.0, 0.0))))
        assert section.centroid_offset == pytest.approx((0.025, -_TEE_CENTROID))
        assert section.get_extreme_fibre_distances() == pytest.approx(
            (0.2 + _TEE_CENTROID, 0.1)
        )

    def test_that_turns_it_otherwise_is_refused(self):
        """Its inertias would turn with it, and they once did not."""
        with pytest.raises(ModelExtractionError, match="turned 90 degrees") as error:
            _section(_tee(((0.0, 0.0), (0.0, 1.0))))
        assert error.value.code == "E-SEC-007"
