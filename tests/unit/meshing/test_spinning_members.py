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


def _run_of_members(points, supports, released=None, branch=None):
    """Members joined end to end at *points*, with ``{index: flags}`` supports.

    Args:
        released: ``{(point index, member id): [dofs]}``, member-side releases.
        branch: The far end of one more member starting at the last point.
    """
    model = StructuralModel(id="model")
    nodes = {i + 1: tuple(point) for i, point in enumerate(points)}
    joints = []
    for i, point in enumerate(points):
        joint = PointConnection(f"joint{i}", list(point))
        if i in supports:
            joint.set_stiffness_properties(
                {key: RIGID if flag else 0.0 for key, flag in zip(KEYS, supports[i])}
            )
        model.connections.append(joint)
        joints.append(joint)

    spans = [(f"m{i}", i + 1, i + 2) for i in range(len(points) - 1)]
    if branch is not None:
        nodes[len(points) + 1] = tuple(branch)
        spans.append(("branch", len(points), len(points) + 1))
    for member_id, a, b in spans:
        model.add_member(_beam(member_id, nodes[a], nodes[b]))
        joints[a - 1].connect_member(member_id)
        if b <= len(points):
            joints[b - 1].connect_member(member_id)
    for (index, member_id), dofs in (released or {}).items():
        joints[index].released_dofs_by_member = {member_id: dofs}

    writer = UnifiedCalculixWriter(domain_model=model)
    writer.nodes = nodes
    writer.elements = {
        number: {"type": "B31", "nodes": [a, b]}
        for number, (_, a, b) in enumerate(spans, start=1)
    }
    writer.short_id_map = {
        member_id: f"M{number}" for number, (member_id, _, _) in enumerate(spans, 1)
    }
    writer.element_sets = {f"MEMBER_M{number}": [number] for number in writer.elements}
    writer._hold_spinning_members()
    return writer


LINE = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (4.0, 0.0, 0.0)]


def test_two_members_in_line_do_not_hold_each_other():
    """They turn together: once each counted as held by the other."""
    writer = _run_of_members(LINE, {0: BALL, 2: BALL})

    assert writer._torsion_hold_dofs() == [(1, 4)]
    (message,) = _messages(writer)
    assert "2 member(s) are free to spin about their own axis" in message
    assert "m0, m1" in message


def test_run_is_held_once_wherever_its_supports_are():
    """At a joint inside the run when it has no support at an end."""
    points = [(0.0, 0.0, 0.0)] + [(x, 0.0, 0.0) for x in (1.0, 3.0, 5.0, 6.0)]
    writer = _run_of_members(points, {1: BALL, 3: BALL})

    assert writer._torsion_hold_dofs() == [(2, 4)]
    assert "4 member(s)" in _messages(writer)[0]


def test_run_held_in_torsion_at_one_support_is_left_alone():
    for supports in ({0: PIN, 2: BALL}, {0: BALL, 2: PIN}, {0: BALL, 1: PIN, 2: BALL}):
        writer = _run_of_members(LINE, supports)

        assert writer._torsion_hold_dofs() == []
        assert _messages(writer) == []


def test_torsional_release_ends_a_run():
    """Held on one side of the release, the other side still spins."""
    writer = _run_of_members(LINE, {0: PIN, 2: BALL}, released={(1, "m1"): [4]})

    assert writer._torsion_hold_dofs() == [(3, 4)]
    assert "1 member(s)" in _messages(writer)[0]
    assert "m1" in _messages(writer)[0]


def test_bending_release_between_them_leaves_the_run_whole():
    writer = _run_of_members(LINE, {0: PIN, 2: BALL}, released={(1, "m1"): [5, 6]})

    assert writer._torsion_hold_dofs() == []


def test_member_across_the_run_holds_all_of_it():
    """Turning the run would bend the member that leaves it."""
    writer = _run_of_members(LINE, {0: BALL, 2: BALL}, branch=(4.0, 0.0, -3.0))

    assert writer._torsion_hold_dofs() == []
    assert _messages(writer) == []


def test_run_along_a_skew_axis_is_reported():
    points = [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 2.0, 0.0)]
    writer = _run_of_members(points, {0: BALL, 2: BALL})

    assert writer._torsion_hold_dofs() == []
    assert "2 member(s)" in _messages(writer)[0]
    assert "could not be held automatically" in _messages(writer)[0]


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
