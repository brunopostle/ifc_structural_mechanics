"""Eccentric member ends given only in IfcRelConnectsWithEccentricity (d36).

``structure_01`` draws its columns 0.15 m short of the joints at their tops
and says so in an ``IfcConnectionPointEccentricity`` as well; RFEM's export of
it draws them up to the joints and gives the offset only in the relation.
Either way the column must end 0.15 m below the joint, or it is longer and
stiffer than the file says.
"""

import os

import numpy as np
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

STRUCTURE = os.path.join("examples", "analysis-models", "ifcFiles", "structure_01.ifc")
RFEM = os.path.join("examples", "rfem", "structure_01_rfem.ifc")
RFEM_SLAB = "0MBetTBij3CBOT8x93dlIS"

# An entity is only valid while its file is alive
_FILES = []


def _open(path):
    model = ifcopenshell.open(path)
    _FILES.append(model)
    return model


def _codes(model):
    return [w["code"] for w in model.analysis_warnings]


def _column_tops(model):
    """The height of the top of each column of structure_01, by name."""
    extracted = Extractor(model).extract_model()
    tops = {}
    for relation in model.by_type("IfcRelConnectsWithEccentricity"):
        member = relation.RelatingStructuralMember
        geometry = np.array(extracted.get_member(member.GlobalId).geometry)
        tops[member.Name] = round(float(geometry[:, 2].max()), 9)
    return tops, extracted


def _drawn_to_the_joint(model):
    """structure_01 with its columns drawn up to the joints at their tops."""
    for relation in model.by_type("IfcRelConnectsWithEccentricity"):
        edge = relation.RelatingStructuralMember.Representation.Representations[
            0
        ].Items[0]
        top = edge.EdgeEnd.VertexGeometry
        top.Coordinates = (*[float(v) for v in top.Coordinates[:2]], 3.0)
    return model


class TestDrawnEccentricity:
    def test_a_drawn_gap_is_the_eccentricity(self):
        tops, extracted = _column_tops(_open(STRUCTURE))
        assert tops == {"Column_01": 2.85, "Column_02": 2.85}
        assert not {"W-JNT-011", "W-JNT-012"} & set(_codes(extracted))


class TestStatedEccentricity:
    def test_point_on_the_member_the_ifc_way_cuts_it_back(self):
        """(2.85, 0, 0) from the start of the column's edge is its top."""
        tops, extracted = _column_tops(_drawn_to_the_joint(_open(STRUCTURE)))
        assert tops == {"Column_01": 2.85, "Column_02": 2.85}
        assert not {"W-JNT-011", "W-JNT-012"} & set(_codes(extracted))

    def test_eccentricities_from_the_connection_cut_it_back(self):
        model = _drawn_to_the_joint(_open(STRUCTURE))
        for constraint in model.by_type("IfcConnectionPointEccentricity"):
            # Off the member: only the eccentricities can be read
            constraint.PointOnRelatingElement.Coordinates = (10.0, 0.0, 0.0)
            # From the joint to the member's point, in the member's axes
            constraint.EccentricityInX = -0.15
        tops, extracted = _column_tops(model)
        assert tops == {"Column_01": 2.85, "Column_02": 2.85}
        assert "W-JNT-011" not in _codes(extracted)

    def test_eccentricities_are_not_turned_round(self):
        """+0.15 puts the point above the joint, off the member: an error,
        not the other way round, nor no eccentricity at all."""
        model = _drawn_to_the_joint(_open(STRUCTURE))
        for constraint in model.by_type("IfcConnectionPointEccentricity"):
            constraint.PointOnRelatingElement.Coordinates = (0.0, 0.0, 0.0)
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert error.value.code == "E-JNT-006"

    def test_offset_across_the_member_is_an_error(self):
        model = _drawn_to_the_joint(_open(STRUCTURE))
        relation = model.by_type("IfcRelConnectsWithEccentricity")[0]
        constraint = relation.ConnectionConstraint
        constraint.PointOnRelatingElement.Coordinates = (2.85, 0.3, 0.0)
        constraint.EccentricityInX = None
        constraint.EccentricityInY = None
        constraint.EccentricityInZ = None
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert error.value.code == "E-JNT-006"
        member = relation.RelatingStructuralMember.GlobalId
        assert member in error.value.ifc_guids
        assert relation.RelatedStructuralConnection.GlobalId in error.value.ifc_guids
        assert relation.GlobalId in error.value.ifc_guids
        assert member in str(error.value)


class TestRfem:
    def test_point_measured_from_the_connection_is_read_with_a_warning(self):
        tops, extracted = _column_tops(_open(RFEM))
        assert tops == {"Member 1": 2.85, "Member 2": 2.85}
        assert "W-JNT-011" in _codes(extracted)

    def test_the_slab_the_joint_lies_in_is_joined_to_it(self):
        model = _open(RFEM)
        extracted = Extractor(model).extract_model()
        for relation in model.by_type("IfcRelConnectsWithEccentricity"):
            joint = extracted.get_connection(
                relation.RelatedStructuralConnection.GlobalId
            )
            assert RFEM_SLAB in joint.connected_members
        (found,) = [w for w in extracted.analysis_warnings if w["code"] == "W-JNT-012"]
        assert RFEM_SLAB in found["ifc_guids"]

    def test_the_slab_is_not_joined_where_the_column_reaches_the_joint(self):
        model = _open(RFEM)
        for relation in model.by_type("IfcRelConnectsWithEccentricity"):
            model.remove(relation.ConnectionConstraint)
            relation.ConnectionConstraint = model.create_entity(
                "IfcConnectionPointGeometry",
                PointOnRelatingElement=model.create_entity(
                    "IfcCartesianPoint", (0.0, 0.0, 0.0)
                ),
                PointOnRelatedElement=model.create_entity(
                    "IfcCartesianPoint", (0.0, 0.0, 0.0)
                ),
            )
        # (0, 0, 0) from the start is the foot: on the member, but the other
        # end; from the joint it is the joint itself, so no eccentricity
        tops, extracted = _column_tops(model)
        assert tops == {"Member 1": 3.0, "Member 2": 3.0}
        assert not {"W-JNT-011", "W-JNT-012"} & set(_codes(extracted))
