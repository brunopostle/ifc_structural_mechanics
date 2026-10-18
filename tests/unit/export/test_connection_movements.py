"""How point connections move, from the members' deflected shapes (94g.13.3)."""

import pytest

from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_connection import PointConnection
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter


def _shape(uz, ry):
    """A shape of a 2 m member along X: its end moves by uz and turns by ry."""
    return {
        "distance_m": [0.0, 2.0],
        "ux_m": [0.0, 0.0],
        "uy_m": [0.0, 0.0],
        "uz_m": [0.0, uz],
        "rx_rad": [0.0, 0.0],
        "ry_rad": [0.0, ry],
        "rz_rad": [0.0, 0.0],
    }


def _connections(position=(2.0, 0.0, 0.0)):
    model = StructuralModel(id="model")
    model.add_member(
        CurveMember(
            id="beam",
            geometry=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
            material=Material(
                id="m",
                name="m",
                density=7850.0,
                elastic_modulus=210e9,
                poisson_ratio=0.3,
            ),
            section=Section.create_rectangular_section("s", "s", width=0.1, height=0.1),
        )
    )
    tip = PointConnection("tip", list(position))
    tip.connect_member("beam")
    model.connections.append(tip)
    data = {
        "members": [
            {"deflected_shapes": {"A": _shape(-0.01, 0.002), "B": _shape(0.004, 0.0)}}
        ],
        "load_combinations": [
            {"name": "C", "factors": {"A": 2.0, "B": -1.0}},
            {"name": "Only B", "factors": {"B": 1.5, "Not solved": 1.0}},
        ],
    }
    return ResultsExporter(model, {})._connections(data)


def test_a_combination_is_its_cases_times_their_factors():
    """The movement is linear in the load, so it is not solved again."""
    (tip,) = _connections()
    assert tip["by_load_case"]["A"]["translation_m"] == pytest.approx([0, 0, -0.01])
    combined = tip["by_load_combination"]
    assert combined["C"]["translation_m"] == pytest.approx([0.0, 0.0, -0.024])
    assert combined["C"]["rotation_rad"] == pytest.approx([0.0, 0.004, 0.0])
    # A case that was not solved adds nothing
    assert combined["Only B"]["translation_m"] == pytest.approx([0.0, 0.0, 0.006])


def test_an_eccentric_joint_moves_with_the_member_end_as_a_rigid_body():
    """0.5 m above the end, which turns by ry: x moves by 0.5 ry."""
    (tip,) = _connections(position=(2.0, 0.0, 0.5))
    assert tip["by_load_case"]["A"]["translation_m"] == pytest.approx(
        [0.5 * 0.002, 0.0, -0.01]
    )
