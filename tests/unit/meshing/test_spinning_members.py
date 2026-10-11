"""Members nothing stops turning about their own axis are held and reported."""

import io

from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_connection import PointConnection
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)

RIGID = 1e20
KEYS = ("dx", "dy", "dz", "drx", "dry", "drz")


def _beam(member_id, start, end):
    return CurveMember(
        id=member_id,
        geometry=[start, end],
        material=Material(
            id="m", name="m", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
        ),
        section=Section.create_rectangular_section("s", "s", width=0.2, height=0.3),
    )


def _support(connection_id, position, fixed, member_id):
    connection = PointConnection(connection_id, list(position))
    connection.connect_member(member_id)
    connection.set_stiffness_properties(
        {key: RIGID if flag else 0.0 for key, flag in zip(KEYS, fixed)}
    )
    return connection


def _writer(start_fixed, end_fixed, end_point=(4.0, 0.0, 0.0), second_member=False):
    model = StructuralModel(id="model")
    model.add_member(_beam("beam", (0.0, 0.0, 0.0), end_point))
    model.connections.append(_support("left", (0.0, 0.0, 0.0), start_fixed, "beam"))
    right = _support("right", end_point, end_fixed, "beam")
    model.connections.append(right)
    writer = UnifiedCalculixWriter(domain_model=model)
    writer.nodes = {1: (0.0, 0.0, 0.0), 2: tuple(end_point)}
    writer.elements = {1: {"type": "B31", "nodes": [1, 2]}}
    writer.short_id_map = {"beam": "M1"}
    writer.element_sets = {"MEMBER_M1": [1]}
    if second_member:
        model.add_member(_beam("column", end_point, (end_point[0], 0.0, -3.0)))
        right.connect_member("column")
        writer.nodes[3] = (end_point[0], 0.0, -3.0)
        writer.elements[2] = {"type": "B31", "nodes": [2, 3]}
        writer.short_id_map["column"] = "M2"
        writer.element_sets["MEMBER_M2"] = [2]
    writer._hold_spinning_members()
    return writer


BALL = (1, 1, 1, 0, 0, 0)
PIN = (1, 1, 1, 1, 0, 0)  # rotation about global X held: torsion of a beam along X
FIXED = (1, 1, 1, 1, 1, 1)


def _messages(writer):
    return [w["message"] for w in getattr(writer.domain_model, "analysis_warnings", [])]


def test_beam_on_two_ball_supports_is_held_at_the_first():
    writer = _writer(BALL, BALL)

    assert writer._torsion_hold_dofs() == [(1, 4)]
    assert len(_messages(writer)) == 1
    assert "1 member(s) are free to spin about their own axis" in _messages(writer)[0]
    assert "beam" in _messages(writer)[0]


def test_hold_counts_as_a_boundary_condition():
    writer = _writer(BALL, BALL)

    assert (1, 4) in writer._collect_boundary_condition_dofs()


def test_support_that_holds_torsion_is_enough():
    for start, end in ((PIN, BALL), (BALL, PIN), (FIXED, BALL)):
        writer = _writer(start, end)

        assert writer._torsion_hold_dofs() == []
        assert _messages(writer) == []


def test_rotation_held_about_another_axis_does_not_count():
    """drz held on a beam along X is bending, not torsion."""
    writer = _writer((1, 1, 1, 0, 0, 1), BALL)

    assert writer._torsion_hold_dofs() == [(1, 4)]


def test_axis_of_the_member_decides_which_rotation():
    writer = _writer(BALL, BALL, end_point=(0.0, 0.0, 3.0))

    assert writer._torsion_hold_dofs() == [(1, 6)]


def test_member_joined_to_another_is_taken_as_held():
    """The joint passes torsion on to the column, which has its own support."""
    writer = _writer(BALL, BALL, second_member=True)

    assert writer._torsion_hold_dofs() == []


def test_skew_member_is_reported_but_not_held():
    writer = _writer(BALL, BALL, end_point=(3.0, 3.0, 0.0))

    assert writer._torsion_hold_dofs() == []
    assert "could not be held automatically" in _messages(writer)[0]


def test_hold_is_written_as_a_boundary_condition(tmp_path):
    writer = _writer(BALL, BALL)
    path = tmp_path / "out.inp"
    writer._write_calculix_input_file(str(path))
    text = path.read_text()

    assert "** Members held against spinning about their own axis" in text
    block = text.split("** Members held against spinning about their own axis")[1]
    assert block.splitlines()[1:3] == ["*BOUNDARY", "1, 4, 4"]
    assert io.StringIO(text).readline().startswith("**")
