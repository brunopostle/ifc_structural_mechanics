"""Second-order meshes: node ordering, U1 splitting and beam element sets."""

import io

import meshio
import numpy as np

from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _material():
    return Material(
        id="steel",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )


def _beam(section_type="rectangular"):
    if section_type == "rectangular":
        section = Section.create_rectangular_section(
            id="rect", name="Rect", width=0.1, height=0.2
        )
    else:
        section = Section(
            id="i_sec",
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
    return CurveMember(
        id="beam",
        geometry=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        material=_material(),
        section=section,
    )


def _writer(*members):
    model = StructuralModel(id="model")
    for member in members:
        model.add_member(member)
    return UnifiedCalculixWriter(domain_model=model)


def _two_quadratic_lines():
    """Two three-node line elements along x, in Gmsh node order (ends, middle)."""
    points = np.array([[0.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0], [0.5, 0, 0], [1.5, 0, 0]])
    return meshio.Mesh(points, [("line3", np.array([[0, 1, 3], [1, 2, 4]]))])


class TestQuadraticBeamNodeOrder:
    def test_middle_node_is_written_second(self):
        """Gmsh gives (start, end, middle); CalculiX wants (start, middle, end)."""
        writer = _writer(_beam())
        writer._process_mesh(_two_quadratic_lines())

        assert writer.elements[1]["nodes"] == [1, 4, 2]
        assert writer.elements[2]["nodes"] == [2, 5, 3]
        assert writer.elements[1]["type"] == "B32R"

    def test_node_ids_are_plain_ints(self):
        writer = _writer(_beam())
        writer._process_mesh(_two_quadratic_lines())
        assert all(type(n) is int for n in writer.elements[1]["nodes"])

    def test_quadratic_triangle_keeps_gmsh_order(self):
        """Gmsh and CalculiX agree on six-node triangles."""
        slab = SurfaceMember(
            id="slab",
            geometry=[(0.0, 0, 0), (1.0, 0, 0), (0.0, 1, 0)],
            material=_material(),
            thickness=Thickness(id="t", name="t", value=0.2),
        )
        points = np.array(
            [[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0.5, 0, 0], [0.5, 0.5, 0], [0, 0.5, 0]]
        )
        writer = _writer(slab)
        writer._process_mesh(
            meshio.Mesh(points, [("triangle6", np.array([[0, 1, 2, 3, 4, 5]]))])
        )
        assert writer.elements[1] == {
            "type": "S6",
            "nodes": [1, 2, 3, 4, 5, 6],
            "block_name": "triangle6",
        }


class TestQuadraticUserElements:
    """U1 has two nodes, so each three-node element becomes two."""

    def _retyped_writer(self):
        member = _beam(section_type="i")
        writer = _writer(member)
        writer.analysis_config.set_open_sections("user_element")
        writer._process_mesh(_two_quadratic_lines())
        writer.element_sets = {"MEMBER_M1": [1, 2]}
        writer.short_id_map = {"beam": "M1"}
        writer._identify_and_retype_u1_members()
        return writer, member

    def test_each_element_is_split_at_its_middle_node(self):
        writer, _ = self._retyped_writer()

        assert writer.element_sets["MEMBER_M1"] == [1, 3, 2, 4]
        assert [writer.elements[e]["nodes"] for e in (1, 3, 2, 4)] == [
            [1, 4],
            [4, 2],
            [2, 5],
            [5, 3],
        ]
        assert all(writer.elements[e]["type"] == "U1" for e in (1, 2, 3, 4))

    def test_new_elements_are_traceable_to_the_member(self):
        writer, member = self._retyped_writer()
        assert writer.domain_model.analysis_element_to_member[3] == "beam"
        assert {3, 4}.issubset(member.analysis_element_ids)

    def test_linear_elements_are_left_alone(self):
        member = _beam(section_type="i")
        writer = _writer(member)
        writer.analysis_config.set_open_sections("user_element")
        points = np.array([[0.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0]])
        writer._process_mesh(
            meshio.Mesh(points, [("line", np.array([[0, 1], [1, 2]]))])
        )
        writer.element_sets = {"MEMBER_M1": [1, 2]}
        writer.short_id_map = {"beam": "M1"}
        writer._identify_and_retype_u1_members()
        assert writer.element_sets["MEMBER_M1"] == [1, 2]
        assert len(writer.elements) == 2


def test_native_beam_set_includes_quadratic_beams():
    """BEAM_B31 (the set section forces are requested on) covers B32R too."""
    writer = _writer(_beam())
    writer._process_mesh(_two_quadratic_lines())
    writer.element_sets = {"MEMBER_M1": [1, 2]}
    out = io.StringIO()
    writer._write_element_sets(out)
    text = out.getvalue()
    assert "*ELSET, ELSET=BEAM_B31\n1, 2\n" in text
