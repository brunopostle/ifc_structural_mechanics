"""Hinged edges between surface members, and rigid links at joints."""

import io
import re

from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.structural_connection import (
    PointConnection,
    RigidConnection,
)
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)

# Release axes of a relation whose x runs along an edge parallel to global Y
ALONG_Y = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]


def _material():
    return Material(
        id="steel",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )


def _surface(member_id, geometry):
    return SurfaceMember(
        id=member_id,
        geometry=geometry,
        material=_material(),
        thickness=Thickness(id=f"t_{member_id}", name="t", value=0.2),
    )


def _slab_on_wall(slab_release=None, release_axes=None, wall_release=None):
    """A slab (z = 3) and a wall (x = 2) sharing the edge x = 2, z = 3.

    Nodes 2 and 3 are on the shared edge; one triangle per member.
    """
    model = StructuralModel(id="model")
    model.add_member(_surface("slab", [(0, 0, 3), (2, 0, 3), (2, 1, 3), (0, 1, 3)]))
    model.add_member(_surface("wall", [(2, 0, 0), (2, 1, 0), (2, 1, 3), (2, 0, 3)]))
    edge = RigidConnection("edge", [2.0, 0.5, 3.0])
    edge.edge = [[2.0, 0.0, 3.0], [2.0, 1.0, 3.0]]
    edge.connect_member("slab")
    edge.connect_member("wall")
    if slab_release:
        edge.released_dofs_by_member["slab"] = slab_release
        edge.release_axes_by_member["slab"] = release_axes
    if wall_release:
        edge.released_dofs_by_member["wall"] = wall_release
        edge.release_axes_by_member["wall"] = release_axes
    model.connections.append(edge)

    writer = UnifiedCalculixWriter(domain_model=model)
    writer.nodes = {
        1: (0.0, 0.0, 3.0),
        2: (2.0, 0.0, 3.0),
        3: (2.0, 1.0, 3.0),
        4: (2.0, 0.0, 0.0),
    }
    writer.elements = {
        1: {"type": "S3", "nodes": [1, 2, 3]},
        2: {"type": "S3", "nodes": [4, 3, 2]},
    }
    writer.short_id_map = {"slab": "M1", "wall": "M2"}
    writer.element_sets = {"MEMBER_M1": [1], "MEMBER_M2": [2]}
    return writer


def _equations(text):
    """Return (dependent node, dof, independent node) for each equation."""
    return [
        (int(a), int(dof), int(b))
        for a, dof, b in re.findall(r"^(\d+),(\d),1\.0,(\d+),\d,-1\.0$", text, re.M)
    ]


class TestHingedEdge:
    def test_rigid_edge_keeps_shared_nodes(self):
        writer = _slab_on_wall()
        writer._release_hinged_edges()
        assert writer.elements[1]["nodes"] == [1, 2, 3]
        assert len(writer.nodes) == 4

    def test_released_slab_gets_its_own_edge_nodes(self):
        writer = _slab_on_wall(slab_release=[4, 5, 6])
        writer._release_hinged_edges()

        assert writer.elements[1]["nodes"] == [1, 5, 6]
        assert writer.elements[2]["nodes"] == [4, 3, 2]  # the wall keeps the edge
        assert writer.nodes[5] == writer.nodes[2]
        assert writer.nodes[6] == writer.nodes[3]

    def test_copies_are_tied_to_the_edge_in_translation_only(self):
        writer = _slab_on_wall(slab_release=[4, 5, 6])
        writer._release_hinged_edges()
        out = io.StringIO()
        writer._write_edge_hinges(out, set())

        assert _equations(out.getvalue()) == [
            (5, 1, 2),
            (5, 2, 2),
            (5, 3, 2),
            (6, 1, 3),
            (6, 2, 3),
            (6, 3, 3),
        ]

    def test_release_about_the_edge_is_enough(self):
        """Local x of the relation runs along the edge, so drx is the hinge."""
        writer = _slab_on_wall(slab_release=[4], release_axes=ALONG_Y)
        writer._release_hinged_edges()
        assert writer.elements[1]["nodes"] == [1, 5, 6]

    def test_release_about_other_axes_leaves_the_edge_rigid(self):
        """slab_01 as authored: clamped about the edge, free about the others."""
        writer = _slab_on_wall(slab_release=[5, 6], release_axes=ALONG_Y)
        writer._release_hinged_edges()
        assert writer.elements[1]["nodes"] == [1, 2, 3]

    def test_one_member_keeps_the_edge_when_all_are_released(self):
        writer = _slab_on_wall(slab_release=[4, 5, 6], wall_release=[4, 5, 6])
        writer._release_hinged_edges()
        assert writer.elements[1]["nodes"] == [1, 2, 3]
        assert writer.elements[2]["nodes"] == [4, 5, 6]
        assert writer.nodes[5] == writer.nodes[3]
        assert writer.nodes[6] == writer.nodes[2]

    def test_supported_copy_gets_no_equation(self):
        """A DOF already fixed by a support must not also depend on an equation."""
        writer = _slab_on_wall(slab_release=[4, 5, 6])
        writer._release_hinged_edges()
        out = io.StringIO()
        writer._write_edge_hinges(out, {(5, 1), (5, 2), (5, 3)})
        assert {node for node, _, _ in _equations(out.getvalue())} == {6}


class TestRigidLinkedJoint:
    """A column stopping below a slab is joined to it by a rigid link alone."""

    def _column_under_slab(self):
        model = StructuralModel(id="model")
        model.add_member(_surface("slab", [(0, 0, 3), (2, 0, 3), (2, 1, 3)]))
        model.add_member(
            CurveMember(
                id="column",
                geometry=[(0.0, 0.0, 0.0), (0.0, 0.0, 2.85)],
                material=_material(),
                section=Section.create_rectangular_section(
                    id="sec", name="sec", width=0.2, height=0.2
                ),
            )
        )
        joint = PointConnection("joint", [0.0, 0.0, 3.0])
        joint.connect_member("slab")
        joint.connect_member("column")
        model.connections.append(joint)

        writer = UnifiedCalculixWriter(domain_model=model)
        writer.nodes = {
            1: (0.0, 0.0, 3.0),
            2: (2.0, 0.0, 3.0),
            3: (2.0, 1.0, 3.0),
            4: (0.0, 0.0, 0.0),
            5: (0.0, 0.0, 2.85),
        }
        writer.elements = {
            1: {"type": "S3", "nodes": [1, 2, 3]},
            2: {"type": "B31", "nodes": [4, 5]},
        }
        writer.short_id_map = {"slab": "M1", "column": "M2"}
        writer.element_sets = {"MEMBER_M1": [1], "MEMBER_M2": [2]}
        return writer, joint

    def test_link_is_created_between_column_top_and_slab(self):
        writer, _ = self._column_under_slab()
        writer._merge_rigid_connection_nodes()
        assert [(a, b) for _, a, b in writer._rigid_links] == [(1, 5)]

    def test_linked_nodes_are_not_also_tied_in_translation(self):
        """Tying both ends of the link together would stop the joint rotating."""
        writer, joint = self._column_under_slab()
        writer._merge_rigid_connection_nodes()
        out = io.StringIO()
        writer._write_point_connection(out, joint, ["slab", "column"], set())
        assert _equations(out.getvalue()) == []

    def test_released_member_is_still_tied(self):
        writer, joint = self._column_under_slab()
        joint.released_dofs_by_member = {"column": [4, 5, 6]}
        writer._merge_rigid_connection_nodes()
        assert writer._rigid_links == []
        out = io.StringIO()
        writer._write_point_connection(
            out, joint, ["slab", "column"], set(), joint.released_dofs_by_member
        )
        assert len(_equations(out.getvalue())) == 3
