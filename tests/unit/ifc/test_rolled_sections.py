"""Sections of rolled profiles are read with their fillets (94g.26).

A HEB 160 with no Pset_ProfileMechanical was once analysed with the area and
inertias of its three plates: 3.6% short of its area and 3.2% of its strong
inertia, as Bonsai's library gives it, in millimetres.
"""

import math

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.members_extractor import (  # noqa: E402
    MembersExtractor,
)
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

_FILES = []


def _profile(ifc_class, **attributes):
    model = ifcopenshell.file(schema="IFC4")
    _FILES.append(model)
    return model.create_entity(
        ifc_class, ProfileType="AREA", ProfileName="rolled", **attributes
    )


def _extractor(profile, scales=None):
    return MembersExtractor(profile.file, scales or {"LENGTHUNIT": 0.001})


def _stated(profile, **values):
    """Pset_ProfileMechanical: an area in the file's mm², inertias in m⁴.

    With no unit declared, an area is in the length unit squared and an
    inertia in m⁴ (94g.22, 94g.23).
    """
    measures = {
        "CrossSectionArea": "IfcAreaMeasure",
        "MomentOfInertiaY": "IfcMomentOfInertiaMeasure",
        "MomentOfInertiaZ": "IfcMomentOfInertiaMeasure",
        "MomentOfInertiaYZ": "IfcMomentOfInertiaMeasure",
    }
    profile.file.create_entity(
        "IfcProfileProperties",
        Name="Pset_ProfileMechanical",
        Properties=[
            profile.file.create_entity(
                "IfcPropertySingleValue",
                Name=name,
                NominalValue=profile.file.create_entity(measures[name], value),
            )
            for name, value in values.items()
        ],
        ProfileDefinition=profile,
    )


def _heb_160(**more):
    return _profile(
        "IfcIShapeProfileDef",
        OverallWidth=160.0,
        OverallDepth=160.0,
        WebThickness=8.0,
        FlangeThickness=13.0,
        FilletRadius=15.0,
        **more,
    )


def test_heb_160_in_millimetres_is_that_of_the_tables():
    section = _extractor(_heb_160())._create_section(_heb_160())
    assert section.area == pytest.approx(54.25e-4, rel=5e-3)
    assert section.moment_of_inertia_y == pytest.approx(2492e-8, rel=5e-3)
    assert section.moment_of_inertia_z == pytest.approx(889.2e-8, rel=5e-3)
    assert section.dimensions["fillet_radius"] == pytest.approx(0.015)


def test_ipe_300_in_millimetres_is_that_of_the_tables():
    profile = _profile(
        "IfcIShapeProfileDef",
        OverallWidth=150.0,
        OverallDepth=300.0,
        WebThickness=7.1,
        FlangeThickness=10.7,
        FilletRadius=15.0,
    )
    section = _extractor(profile)._create_section(profile)
    assert section.area == pytest.approx(53.81e-4, rel=5e-3)
    assert section.moment_of_inertia_y == pytest.approx(8356e-8, rel=5e-3)
    assert section.moment_of_inertia_z == pytest.approx(603.8e-8, rel=5e-3)


def test_the_stated_values_still_go_first():
    profile = _heb_160()
    _stated(profile, MomentOfInertiaY=2.5e-5)
    section = _extractor(profile)._create_section(profile)
    assert section.moment_of_inertia_y == 2.5e-5


@pytest.mark.parametrize(
    "ifc_class, attributes",
    [
        (
            "IfcTShapeProfileDef",
            dict(
                Depth=200.0, FlangeWidth=200.0, WebThickness=10.0, FlangeThickness=20.0
            ),
        ),
        ("IfcLShapeProfileDef", dict(Depth=100.0, Width=100.0, Thickness=10.0)),
        (
            "IfcUShapeProfileDef",
            dict(Depth=200.0, FlangeWidth=80.0, WebThickness=8.0, FlangeThickness=12.0),
        ),
        (
            "IfcAsymmetricIShapeProfileDef",
            dict(
                BottomFlangeWidth=300.0,
                OverallDepth=400.0,
                WebThickness=10.0,
                BottomFlangeThickness=20.0,
                TopFlangeWidth=100.0,
                TopFlangeThickness=20.0,
            ),
        ),
    ],
    ids=["T", "L", "U", "asymmetric I"],
)
class TestTheOtherShapes:
    def test_fillets_add_their_area(self, ifc_class, attributes):
        sharp = _profile(ifc_class, **attributes)
        radius = (
            "BottomFlangeFilletRadius"
            if ifc_class == "IfcAsymmetricIShapeProfileDef"
            else "FilletRadius"
        )
        rounded = _profile(ifc_class, **attributes, **{radius: 8.0})
        added = (
            _extractor(rounded)._create_section(rounded).area
            - _extractor(sharp)._create_section(sharp).area
        )
        assert added > 0.9 * (1 - math.pi / 4) * 0.008**2

    def test_their_stated_values_are_taken(self, ifc_class, attributes):
        """Only the I section's were once read."""
        profile = _profile(ifc_class, **attributes)
        found = _extractor(profile)._create_section(profile)
        _stated(profile, CrossSectionArea=found.area * 1.01e6)
        section = _extractor(profile)._create_section(profile)
        assert section.area == pytest.approx(found.area * 1.01)


class TestAnglesOnTheirPrincipalAxes:
    """An angle is analysed about its principal axes (94g.37)."""

    def test_an_equal_angle_is_turned_45_degrees(self):
        profile = _profile(
            "IfcLShapeProfileDef", Depth=100.0, Width=100.0, Thickness=10.0
        )
        section = _extractor(profile)._create_section(profile)
        assert section.principal_angle == pytest.approx(math.pi / 4)
        # L 100 x 100 x 10, sharp: 286.6 and 73.4 cm4 about u and v
        assert section.moment_of_inertia_y == pytest.approx(286.6e-8, rel=1e-3)
        assert section.moment_of_inertia_z == pytest.approx(73.4e-8, rel=2e-3)
        assert section.product_of_inertia < 0
        # Equal legs: the shear areas are as they were, 2/3 of a leg
        assert section.shear_area_y == pytest.approx(2 / 3 * 0.1 * 0.01)
        assert section.shear_area_z == pytest.approx(2 / 3 * 0.1 * 0.01)
        # The heel from the axis across the diagonal through it, the toes
        # from the diagonal; the centroid is from the middle of the box
        cx, cy = section.centroid_offset
        heel = math.hypot(cx + 0.05, cy + 0.05)
        assert section.fibre_distances[1] == pytest.approx(heel, rel=1e-6)
        assert section.fibre_distances[0] == pytest.approx(0.1 / math.sqrt(2))

    def test_the_stated_product_of_inertia_is_taken(self):
        profile = _profile(
            "IfcLShapeProfileDef", Depth=100.0, Width=100.0, Thickness=10.0
        )
        found = _extractor(profile)._create_section(profile)
        _stated(profile, MomentOfInertiaYZ=found.product_of_inertia * 1.01)
        section = _extractor(profile)._create_section(profile)
        assert section.product_of_inertia == pytest.approx(
            found.product_of_inertia * 1.01
        )
        assert section.moment_of_inertia_y > found.moment_of_inertia_y

    def test_a_symmetric_shape_takes_no_stated_product(self):
        """Bonsai's HEB 160 gives a MomentOfInertiaYZ of 3.14e-7 m4, its
        torsion constant; its outline's is 6e-22, rounding. It was compared
        and the user warned (W-SEC-005), on a donated Gerber beam."""
        profile = _heb_160()
        extractor = _extractor(profile)
        _stated(profile, MomentOfInertiaYZ=3.14e-7)
        section = extractor._create_section(profile)
        assert section.principal_angle == 0.0
        assert not [w for w in extractor.warnings if w["code"] == "W-SEC-005"]

    def test_symmetric_shapes_are_not_turned(self):
        for profile in (
            _heb_160(),
            _profile(
                "IfcUShapeProfileDef",
                Depth=200.0,
                FlangeWidth=80.0,
                WebThickness=8.0,
                FlangeThickness=12.0,
            ),
        ):
            section = _extractor(profile)._create_section(profile)
            assert section.principal_angle == 0.0


def test_an_asymmetric_i_is_about_its_own_centroid():
    """Its flanges were once averaged: two 0.2 m flanges about mid-depth."""
    profile = _profile(
        "IfcAsymmetricIShapeProfileDef",
        BottomFlangeWidth=300.0,
        OverallDepth=400.0,
        WebThickness=10.0,
        BottomFlangeThickness=20.0,
        TopFlangeWidth=100.0,
        TopFlangeThickness=20.0,
    )
    section = _extractor(profile)._create_section(profile)
    plates = [(0.006, -0.19), (0.002, 0.19), (0.0036, 0.0)]
    area = sum(a for a, _ in plates)
    centre = sum(a * z for a, z in plates) / area
    own = 0.3 * 0.02**3 / 12 + 0.1 * 0.02**3 / 12 + 0.01 * 0.36**3 / 12
    expected = own + sum(a * (z - centre) ** 2 for a, z in plates)
    assert section.moment_of_inertia_y == pytest.approx(expected)


class TestSlopedFlanges:
    def _ipn(self):
        return _profile(
            "IfcIShapeProfileDef",
            OverallWidth=90.0,
            OverallDepth=200.0,
            WebThickness=7.5,
            FlangeThickness=11.3,
            FilletRadius=7.5,
            FlangeEdgeRadius=4.5,
            FlangeSlope=math.atan(0.14),
        )

    def test_are_read_and_said_to_be_so(self):
        profile = self._ipn()
        extractor = _extractor(profile)
        flat = _profile(
            "IfcIShapeProfileDef",
            OverallWidth=90.0,
            OverallDepth=200.0,
            WebThickness=7.5,
            FlangeThickness=11.3,
            FilletRadius=7.5,
            FlangeEdgeRadius=4.5,
        )
        assert extractor._create_section(profile).area > (
            _extractor(flat)._create_section(flat).area
        )
        (found,) = [w for w in extractor.warnings if w["code"] == "W-SEC-004"]
        assert "IfcOpenShell draws them" in found["message"]
        assert "'rolled'" in found["message"]

    def test_say_nothing_when_the_pset_gives_the_values(self):
        profile = self._ipn()
        _stated(
            profile,
            CrossSectionArea=3340.0,
            MomentOfInertiaY=2140e-8,
            MomentOfInertiaZ=117e-8,
        )
        extractor = _extractor(profile)
        extractor._create_section(profile)
        assert extractor.warnings == []


class TestErrors:
    def test_a_fillet_that_does_not_fit(self):
        profile = _heb_160()
        profile.FilletRadius = 200.0
        with pytest.raises(ModelExtractionError, match="does not fit") as error:
            _extractor(profile)._create_section(profile)
        assert error.value.code == "E-SEC-004"

    def test_a_missing_dimension_is_not_made_up(self):
        """An L with no thickness was once 0.01 m thick."""
        profile = _profile("IfcLShapeProfileDef", Depth=100.0, Width=100.0)
        with pytest.raises(ModelExtractionError, match="Thickness") as error:
            _extractor(profile)._create_section(profile)
        assert error.value.code == "E-SEC-004"
