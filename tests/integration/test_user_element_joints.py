"""A U1 member joined to native elements is refused (aiz.14).

CalculiX passes no moment between a U1 element and an expanded beam or shell
at a shared node, so such a joint is a pin whatever the file says; stock
CalculiX stops in gen3delem on the model anyway.
"""

import ifcopenshell.guid
import pytest

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_connection import PointConnection
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)
from ifc_structural_mechanics.utils.error_handling import AnalysisError
from tests.helpers import PLANE_FIXED, PLANE_PIN, plane_model


def _propped_cantilever_half_of_i(path):
    """A frame of two bars in line, rigidly joined, the second an I section."""
    plane_model(
        path,
        nodes={"a": (0.0, 0.0), "b": (1.0, 0.0), "c": (2.0, 0.0)},
        members=[("a", "b"), ("b", "c")],
        supports={"a": PLANE_FIXED, "c": PLANE_PIN},
        loads={"b": (0.0, -1000.0)},
        hinged=False,
    )
    model = ifcopenshell.open(str(path))
    (association,) = model.by_type("IfcRelAssociatesMaterial")
    second = next(m for m in association.RelatedObjects if m.Name == "bc")
    association.RelatedObjects = [m for m in association.RelatedObjects if m != second]
    profile = model.create_entity(
        "IfcIShapeProfileDef",
        ProfileType="AREA",
        ProfileName="I",
        OverallWidth=0.1,
        OverallDepth=0.2,
        WebThickness=0.01,
        FlangeThickness=0.015,
    )
    profile_set = model.create_entity(
        "IfcMaterialProfileSet",
        MaterialProfiles=[
            model.create_entity(
                "IfcMaterialProfile",
                Material=model.by_type("IfcMaterial")[0],
                Profile=profile,
            )
        ],
    )
    model.create_entity(
        "IfcRelAssociatesMaterial",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[second],
        RelatingMaterial=profile_set,
    )
    model.write(str(path))
    return str(path)


def test_a_user_element_member_joined_to_a_native_one_is_refused(tmp_path):
    path = _propped_cantilever_half_of_i(tmp_path / "frame.ifc")
    result = analyze_ifc(
        ifc_path=path,
        output_dir=str(tmp_path / "out"),
        mesh_size=0.25,
        open_sections="user_element",
    )
    assert result["status"] == "failed"
    message = " ".join(str(e) for e in result["errors"])
    assert "user elements (U1" in message
    assert "native beam or shell" in message


def test_the_same_frame_runs_on_native_elements(tmp_path):
    path = _propped_cantilever_half_of_i(tmp_path / "frame.ifc")
    result = analyze_ifc(
        ifc_path=path, output_dir=str(tmp_path / "out"), mesh_size=0.25
    )
    assert result["status"] == "success", result.get("errors")


def _material():
    return Material(
        id="steel",
        name="Steel",
        density=7850.0,
        elastic_modulus=2.1e11,
        poisson_ratio=0.3,
    )


def _i_section():
    return Section(
        id="i",
        name="I",
        section_type="i",
        area=5.0e-3,
        dimensions={
            "width": 0.2,
            "height": 0.4,
            "web_thickness": 0.01,
            "flange_thickness": 0.015,
        },
    )


def _writer(second_section, released=None, share_node=True):
    """Two members in line meeting at x = 1, the first of U1 elements."""
    model = StructuralModel(id="model")
    first = CurveMember(
        id="u1",
        geometry=[(0.0, 0, 0), (1.0, 0, 0)],
        material=_material(),
        section=_i_section(),
    )
    second = CurveMember(
        id="other",
        geometry=[(1.0, 0, 0), (2.0, 0, 0)],
        material=_material(),
        section=second_section,
    )
    model.add_member(first)
    model.add_member(second)
    joint = PointConnection("joint", [1.0, 0.0, 0.0])
    joint.connect_member("u1")
    joint.connect_member("other")
    if released:
        joint.released_dofs_by_member = released
    model.add_connection(joint)
    writer = UnifiedCalculixWriter(domain_model=model)
    writer.analysis_config.set_open_sections("user_element")
    writer.nodes = {1: (0.0, 0, 0), 2: (1.0, 0, 0), 3: (1.0, 0, 0), 4: (2.0, 0, 0)}
    writer.elements = {
        1: {"type": "B31", "nodes": [1, 2]},
        2: {"type": "B31", "nodes": [2 if share_node else 3, 4]},
    }
    writer.short_id_map = {"u1": "M1", "other": "M2"}
    writer.element_sets = {"MEMBER_M1": [1], "MEMBER_M2": [2]}
    writer._identify_and_retype_u1_members()
    return writer


RECTANGLE = Section.create_rectangular_section(id="r", name="R", width=0.1, height=0.2)


class TestCheck:
    def test_a_shared_node_is_refused(self):
        with pytest.raises(AnalysisError, match="u1 with other"):
            _writer(RECTANGLE)._check_user_elements_join_their_own_kind()

    def test_a_connection_is_refused(self):
        writer = _writer(RECTANGLE, share_node=False)
        with pytest.raises(AnalysisError, match="1 joint"):
            writer._check_user_elements_join_their_own_kind()

    def test_a_pin_in_the_file_is_a_pin(self):
        for released in ({"u1": [4, 5, 6]}, {"other": [4, 5, 6]}):
            writer = _writer(RECTANGLE, released=released)
            writer._check_user_elements_join_their_own_kind()

    def test_a_partial_release_is_refused(self):
        writer = _writer(RECTANGLE, released={"u1": [5]})
        with pytest.raises(AnalysisError):
            writer._check_user_elements_join_their_own_kind()

    def test_user_elements_join_each_other(self):
        _writer(_i_section())._check_user_elements_join_their_own_kind()
