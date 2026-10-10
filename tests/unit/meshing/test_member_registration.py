"""The writer records each member's final elements and mesh nodes in the model."""

from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _writer():
    """A beam of two elements ending on the corner of a one-triangle slab."""
    material = Material(
        id="mat", name="Steel", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
    )
    model = StructuralModel(id="model")
    model.add_member(
        CurveMember(
            id="beam",
            geometry=[(0, 0, 0), (2, 0, 0)],
            material=material,
            section=Section.create_rectangular_section("s", "s", width=0.2, height=0.3),
        )
    )
    model.add_member(
        SurfaceMember(
            id="slab",
            geometry=[(2, 0, 0), (4, 0, 0), (4, 2, 0)],
            material=material,
            thickness=Thickness(id="t", name="t", value=0.2),
        )
    )
    # As the mesh mapper leaves it before elements are split or reassigned
    model.register_analysis_elements("beam", [1, 99])

    writer = UnifiedCalculixWriter(domain_model=model)
    writer.nodes = {
        1: (0.0, 0.0, 0.0),
        2: (1.0, 0.0, 0.0),
        3: (2.0, 0.0, 0.0),
        4: (4.0, 0.0, 0.0),
        5: (4.0, 2.0, 0.0),
    }
    writer.elements = {
        1: {"type": "B31", "nodes": [1, 2]},
        2: {"type": "B31", "nodes": [2, 3]},
        3: {"type": "S3", "nodes": [3, 4, 5]},
    }
    writer.short_id_map = {"beam": "M1", "slab": "M2"}
    writer.element_sets = {"MEMBER_M1": [1, 2], "MEMBER_M2": [3]}
    return writer


def test_members_get_their_final_elements():
    writer = _writer()
    writer._register_node_memberships()

    model = writer.domain_model
    assert model.get_member("beam").analysis_element_ids == [1, 2]
    assert model.get_member("slab").analysis_element_ids == [3]
    assert 99 not in model.analysis_element_to_member
    assert model.trace_error_to_ifc(2) == model.trace_error_to_ifc(1)


def test_shared_node_is_recorded_for_both_members():
    writer = _writer()
    writer._register_node_memberships()

    model = writer.domain_model
    assert model.member_nodes["beam"] == {1, 2, 3}
    assert model.member_nodes["slab"] == {3, 4, 5}


def test_no_guessed_node_numbers_are_registered():
    """Expanded nodes are numbered by the solver, not by a multiple of ours."""
    writer = _writer()
    writer._register_node_memberships()

    assert set(writer.domain_model.node_to_member) == {1, 2, 3, 4, 5}
