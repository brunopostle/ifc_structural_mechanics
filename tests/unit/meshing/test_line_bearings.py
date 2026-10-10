"""Curve members lying in a surface member are tied to it along their length."""

import io

import numpy as np
import pytest

from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _material():
    return Material(
        id="concrete",
        name="Concrete",
        density=2500.0,
        elastic_modulus=30e9,
        poisson_ratio=0.2,
    )


def _beam(member_id, start, end):
    return CurveMember(
        id=member_id,
        geometry=[start, end],
        material=_material(),
        section=Section.create_rectangular_section(
            id=f"sec_{member_id}", name="sec", width=0.2, height=0.6
        ),
    )


def _slab_with_beam(beam_nodes, beam_elements, quadratic=False):
    """A 4 m x 2 m slab at z = 0 of two triangles, and one curve member.

    Slab corners are nodes 1-4; with ``quadratic`` the mid-side nodes are 5-9.
    ``beam_nodes`` maps node ID to position and ``beam_elements`` lists the
    node IDs of each beam element.
    """
    model = StructuralModel(id="model")
    model.add_member(
        SurfaceMember(
            id="slab",
            geometry=[(0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0)],
            material=_material(),
            thickness=Thickness(id="t", name="t", value=0.2),
        )
    )
    points = [beam_nodes[n] for n in beam_nodes]
    model.add_member(_beam("beam", points[0], points[-1]))

    writer = UnifiedCalculixWriter(domain_model=model)
    writer.nodes = {
        1: (0.0, 0.0, 0.0),
        2: (4.0, 0.0, 0.0),
        3: (4.0, 2.0, 0.0),
        4: (0.0, 2.0, 0.0),
    }
    if quadratic:
        writer.nodes.update(
            {
                5: (2.0, 0.0, 0.0),
                6: (4.0, 1.0, 0.0),
                7: (2.0, 1.0, 0.0),
                8: (2.0, 2.0, 0.0),
                9: (0.0, 1.0, 0.0),
            }
        )
        writer.elements = {
            1: {"type": "S6", "nodes": [1, 2, 3, 5, 6, 7]},
            2: {"type": "S6", "nodes": [1, 3, 4, 7, 8, 9]},
        }
    else:
        writer.elements = {
            1: {"type": "S3", "nodes": [1, 2, 3]},
            2: {"type": "S3", "nodes": [1, 3, 4]},
        }
    writer.nodes.update(beam_nodes)
    beam_type = "B32R" if len(beam_elements[0]) == 3 else "B31"
    first = 10
    for offset, nodes in enumerate(beam_elements):
        writer.elements[first + offset] = {"type": beam_type, "nodes": list(nodes)}
    writer.short_id_map = {"slab": "M1", "beam": "M2"}
    writer.element_sets = {
        "MEMBER_M1": [1, 2],
        "MEMBER_M2": [first + i for i in range(len(beam_elements))],
    }
    writer._rigid_links = []
    return writer


def _edge_beam(**kwargs):
    """A beam along the slab edge y = 0 whose nodes fall between the slab's."""
    return _slab_with_beam(
        {20: (0.0, 0.0, 0.0), 21: (1.0, 0.0, 0.0), 22: (3.0, 0.0, 0.0)},
        [(20, 21), (21, 22)],
        **kwargs,
    )


def _interpolated(writer, terms):
    return sum(weight * np.array(writer.nodes[node]) for node, weight in terms)


class TestBeamOnSlabEdge:
    def test_nodes_between_the_slab_nodes_are_tied(self):
        writer = _edge_beam()
        writer._build_line_bearings()

        assert [node for node, _ in writer._line_bearings] == [20, 21, 22]

    def test_weights_reproduce_the_node_position(self):
        writer = _edge_beam()
        writer._build_line_bearings()

        for node, terms in writer._line_bearings:
            assert sum(weight for _, weight in terms) == pytest.approx(1.0)
            assert _interpolated(writer, terms) == pytest.approx(
                np.array(writer.nodes[node]), abs=1e-9
            )

    def test_only_the_edge_nodes_carry_a_node_on_the_edge(self):
        writer = _edge_beam()
        writer._build_line_bearings()

        terms = dict(writer._line_bearings)[21]
        assert sorted(node for node, _ in terms) == [1, 2]
        assert dict(terms)[1] == pytest.approx(0.75)

    def test_quadratic_shell_weights(self):
        writer = _edge_beam(quadratic=True)
        writer._build_line_bearings()

        terms = dict(dict(writer._line_bearings)[21])
        # x = 1 on the edge 1-5-2 (x = 0, 2, 4): xi = 0.25
        assert terms[1] == pytest.approx(0.75 * 0.5)
        assert terms[5] == pytest.approx(4 * 0.75 * 0.25)
        assert terms[2] == pytest.approx(0.25 * -0.5)

    def test_user_is_told(self):
        writer = _edge_beam()
        writer._build_line_bearings()

        messages = [w["message"] for w in writer.domain_model.analysis_warnings]
        assert len(messages) == 1
        assert "1 curve member(s) lie in a surface member" in messages[0]


class TestBeamInsideSlab:
    def test_node_inside_a_triangle_uses_all_three_corners(self):
        writer = _slab_with_beam({20: (1.0, 0.5, 0.0), 21: (3.0, 0.5, 0.0)}, [(20, 21)])
        writer._build_line_bearings()

        terms = dict(writer._line_bearings)[21]
        assert sorted(node for node, _ in terms) == [1, 2, 3]
        assert _interpolated(writer, terms) == pytest.approx(
            np.array([3.0, 0.5, 0.0]), abs=1e-9
        )


class TestMembersLeftAlone:
    def test_column_through_the_slab_is_not_tied(self):
        writer = _slab_with_beam(
            {20: (1.0, 0.5, -3.0), 21: (1.0, 0.5, 0.0), 22: (1.0, 0.5, 3.0)},
            [(20, 21), (21, 22)],
        )
        writer._build_line_bearings()

        assert writer._line_bearings == []
        assert not getattr(writer.domain_model, "analysis_warnings", [])

    def test_beam_above_the_slab_is_not_tied(self):
        writer = _slab_with_beam({20: (1.0, 0.5, 0.3), 21: (3.0, 0.5, 0.3)}, [(20, 21)])
        writer._build_line_bearings()

        assert writer._line_bearings == []

    def test_node_shared_with_the_slab_needs_no_tie(self):
        writer = _slab_with_beam({1: (0.0, 0.0, 0.0), 21: (1.0, 0.0, 0.0)}, [(1, 21)])
        writer._build_line_bearings()

        assert [node for node, _ in writer._line_bearings] == [21]

    def test_node_on_a_rigid_link_is_not_tied(self):
        writer = _edge_beam()
        writer._rigid_links = [(99, 20, 1)]
        writer._build_line_bearings()

        assert [node for node, _ in writer._line_bearings] == [21, 22]

    def test_part_of_a_beam_outside_the_slab_is_not_tied(self):
        writer = _slab_with_beam(
            {20: (1.0, 0.0, 0.0), 21: (3.0, 0.0, 0.0), 22: (6.0, 0.0, 0.0)},
            [(20, 21), (21, 22)],
        )
        writer._build_line_bearings()

        assert [node for node, _ in writer._line_bearings] == [20, 21]


def _written(writer, constrained=None, supports=None):
    out = io.StringIO()
    supports = set() if supports is None else supports
    constrained = set(supports) if constrained is None else constrained
    writer._write_line_bearings(out, constrained, supports)
    return out.getvalue().splitlines()


class TestWriting:
    def test_three_translations_per_node(self):
        writer = _edge_beam()
        writer._build_line_bearings()

        lines = _written(writer)
        assert lines.count("*EQUATION") == 9
        assert "21,1,1,1,1,-0.75,2,1,-0.25" in lines
        assert "21,3,1,1,3,-0.75,2,3,-0.25" in lines

    def test_at_most_four_terms_per_line(self):
        writer = _slab_with_beam(
            {20: (1.0, 0.5, 0.0), 21: (3.0, 0.5, 0.0)}, [(20, 21)], quadratic=True
        )
        writer._build_line_bearings()

        lines = _written(writer)
        data = [line for line in lines if line[0].isdigit() and "," in line]
        assert data
        assert max(len(line.split(",")) for line in data) <= 12
        counts = [
            int(lines[i + 1]) for i, line in enumerate(lines) if line == "*EQUATION"
        ]
        assert max(counts) > 4

    def test_restrained_dofs_are_skipped(self):
        writer = _edge_beam()
        writer._build_line_bearings()

        lines = _written(writer, constrained={(20, 1), (20, 2), (20, 3), (21, 3)})
        assert lines.count("*EQUATION") == 5
        assert not any(line.startswith("20,") for line in lines)
        assert not any(line.startswith("21,3,") for line in lines)

    def test_tie_leaning_on_a_restrained_shell_node_is_left_out(self):
        """Its force would be reported at the tied node, not at the support."""
        writer = _edge_beam()
        writer._build_line_bearings()

        lines = _written(writer, supports={(2, 3)})
        # Node 20 sits on slab node 1 alone; 21 and 22 lean on node 2 as well
        assert lines.count("*EQUATION") == 7
        assert not any(line.startswith(("21,3,", "22,3,")) for line in lines)
        assert any(line.startswith("21,1,") for line in lines)

    def test_node_of_an_earlier_equation_is_skipped(self):
        writer = _edge_beam()
        writer._build_line_bearings()
        writer._note_equation_nodes((21, 2))

        lines = _written(writer)
        assert lines.count("*EQUATION") == 6
        assert not any(line.startswith("21,") for line in lines)

    def test_nothing_written_without_bearings(self):
        writer = _slab_with_beam({20: (1.0, 0.5, 0.3), 21: (3.0, 0.5, 0.3)}, [(20, 21)])
        writer._build_line_bearings()

        assert _written(writer) == []
