"""Member end releases built from translation ties and stiff arms."""

import io
import re

import numpy as np

from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_connection import PointConnection
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)

# Axes of a release on a secondary beam running along global Y
ALONG_Y = [[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]


def _beam(member_id, start, end):
    return CurveMember(
        id=member_id,
        geometry=[start, end],
        material=Material(
            id="steel",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        ),
        section=Section.create_rectangular_section(
            id=f"sec_{member_id}", name="sec", width=0.2, height=0.3
        ),
    )


def _grid_joint(released, axes=None, secondary_start=(0.0, 0.15, 0.15)):
    """A main beam along X with a secondary beam along Y framing into its middle.

    Node 3 is the joint on the main beam; node 4 is the secondary beam's end.
    """
    model = StructuralModel(id="model")
    model.add_member(_beam("main", (-3.0, 0.0, 0.0), (3.0, 0.0, 0.0)))
    model.add_member(_beam("secondary", secondary_start, (0.0, 4.85, 0.15)))
    joint = PointConnection("joint", [0.0, 0.0, 0.0])
    joint.connect_member("main")
    joint.connect_member("secondary")
    if released:
        joint.released_dofs_by_member = {"secondary": released}
        joint.release_axes_by_member = {"secondary": axes}
    model.connections.append(joint)

    writer = UnifiedCalculixWriter(domain_model=model)
    writer.nodes = {
        1: (-3.0, 0.0, 0.0),
        2: (3.0, 0.0, 0.0),
        3: (0.0, 0.0, 0.0),
        4: tuple(secondary_start),
        5: (0.0, 4.85, 0.15),
    }
    writer.elements = {
        1: {"type": "B31", "nodes": [1, 3]},
        2: {"type": "B31", "nodes": [3, 2]},
        3: {"type": "B31", "nodes": [4, 5]},
    }
    writer.short_id_map = {"main": "M1", "secondary": "M2"}
    writer.element_sets = {"MEMBER_M1": [1, 2], "MEMBER_M2": [3]}
    writer._merge_rigid_connection_nodes()
    writer._build_release_hinges()
    return writer, joint


def _written_equations(writer, joint):
    out = io.StringIO()
    writer._write_point_connection(
        out, joint, ["main", "secondary"], set(), joint.released_dofs_by_member
    )
    equations = []
    lines = out.getvalue().splitlines()
    for i, line in enumerate(lines):
        if line == "*EQUATION":
            values = lines[i + 2].split(",")
            equations.append(
                [
                    (int(values[j]), int(values[j + 1]), float(values[j + 2]))
                    for j in range(0, len(values), 3)
                ]
            )
    return equations


def _links(writer):
    return [(a, b) for _, a, b in writer._rigid_links]


class TestFullPin:
    def test_eccentric_end_is_pinned_where_the_member_ends(self):
        """A rigid link carries the joint out to the member end; the pin is there."""
        writer, joint = _grid_joint(released=[4, 5, 6])

        # Node 6 sits on the member end and is linked to the joint
        assert writer.nodes[6] == writer.nodes[4]
        assert _links(writer) == [(3, 6)]
        assert _written_equations(writer, joint) == [
            [(4, dof, 1.0), (6, dof, -1.0)] for dof in (1, 2, 3)
        ]

    def test_shared_node_is_split(self):
        """Beams meshed with a common node at the joint are rigid until split."""
        writer, joint = _grid_joint(released=[4, 5, 6], secondary_start=(0.0, 0.0, 0.0))
        # Rebuild with the secondary beam starting on the joint node itself
        writer.nodes = {k: v for k, v in writer.nodes.items() if k <= 5}
        writer.nodes[4] = (0.0, 0.0, 0.0)
        writer.elements[3]["nodes"] = [3, 5]
        writer._rigid_links = []
        writer._member_node_cache = {}
        writer._build_release_hinges()

        new_node = writer.elements[3]["nodes"][0]
        assert new_node not in (3, 4)
        assert writer.nodes[new_node] == (0.0, 0.0, 0.0)
        assert _links(writer) == []
        assert _written_equations(writer, joint) == [
            [(new_node, dof, 1.0), (3, dof, -1.0)] for dof in (1, 2, 3)
        ]

    def test_no_warning_about_partial_release(self):
        writer, joint = _grid_joint(released=[5], axes=ALONG_Y)
        _written_equations(writer, joint)
        assert not getattr(writer.domain_model, "analysis_warnings", [])


class TestSingleAxisHinge:
    """grid_of_beams: bending released, torsion and plan rotation held."""

    def test_arms_run_along_the_released_axis(self):
        writer, _ = _grid_joint(released=[5], axes=ALONG_Y)
        # Local y of the release is global -X: the hinge axis
        tip = np.array(writer.nodes[4]) + 0.25 * np.array([-1.0, 0.0, 0.0])
        assert np.allclose(writer.nodes[7], tip)
        assert np.allclose(writer.nodes[8], tip)
        # joint -> offset node, member end -> its tip, offset node -> its tip
        assert _links(writer) == [(3, 6), (4, 7), (6, 8)]

    def test_tips_are_tied_across_the_hinge_axis_only(self):
        """Tying Y and Z at the tips stops rotation about Z and Y, not about X."""
        writer, joint = _grid_joint(released=[5], axes=ALONG_Y)
        equations = _written_equations(writer, joint)

        assert equations[:3] == [[(4, dof, 1.0), (6, dof, -1.0)] for dof in (1, 2, 3)]
        assert equations[3:] == [
            [(7, 2, 1.0), (8, 2, -1.0)],
            [(7, 3, 1.0), (8, 3, -1.0)],
        ]


class TestTwoAxisRelease:
    """structure_01's column: both bending rotations free, torsion held."""

    def test_one_tie_holds_the_remaining_rotation(self):
        writer, joint = _grid_joint(released=[5, 6], axes=ALONG_Y)
        equations = _written_equations(writer, joint)

        # Arm along local y (global -X), tips tied along local z (global Z):
        # that stops rotation about local x, the member's own axis.
        assert np.allclose(writer.nodes[7], np.array(writer.nodes[4]) + [-0.25, 0, 0])
        assert equations[3:] == [[(7, 3, 1.0), (8, 3, -1.0)]]


class TestSkewRelease:
    def test_tip_ties_combine_global_components(self):
        """In skew axes the tie is one equation over several global DOFs."""
        c, s = np.cos(np.radians(30)), np.sin(np.radians(30))
        axes = [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]
        writer, joint = _grid_joint(released=[5, 6], axes=axes)
        (tie,) = _written_equations(writer, joint)[3:]
        # Tips tied along local z only: a single global component here
        assert tie == [(7, 3, 1.0), (8, 3, -1.0)]

        writer, joint = _grid_joint(released=[6], axes=axes)
        ties = _written_equations(writer, joint)[3:]
        # Arm along local z; tips tied along local x and local y
        assert len(ties) == 2
        assert [len(t) for t in ties] == [4, 4]
        dependent = {(t[0][0], t[0][1]) for t in ties}
        assert len(dependent) == 2  # two different dependent DOFs


def test_rigid_joint_is_untouched():
    writer, joint = _grid_joint(released=None)
    assert writer._release_hinges == {}
    assert _links(writer) == [(3, 4)]
    assert not re.search(r"EQUATION", str(_written_equations(writer, joint)))
