"""Line connections are found in the geometry by distance, not by rounded keys.

The coordinates are those of a building written by homemaker-addon, whose
files have single-precision values. A station rebuilt from a rounded distance
once landed a micrometre from the point already seeded at the connection's
middle, and a vertex that OpenCASCADE moved by 5e-8 once rounded to another
key than the beam's, and each stopped the analysis with E-MSH-004.
"""

import gmsh
import numpy as np
import pytest

from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_connection import RigidConnection
from ifc_structural_mechanics.domain.structural_member import (
    CurveMember,
    SurfaceMember,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.gmsh_geometry import GmshGeometryConverter
from ifc_structural_mechanics.utils.error_handling import MeshingError

MATERIAL = Material(
    id="m", name="Concrete", elastic_modulus=30e9, poisson_ratio=0.2, density=2800
)
SECTION = Section.create_rectangular_section(id="s", name="R", width=0.4, height=0.4)

START = [6.648303508758545, -3.4308414459228516, 0.0]
END = [4.860907554626465, -3.9343056678771973, 0.0]


@pytest.fixture(autouse=True)
def gmsh_session():
    if gmsh.isInitialized():
        gmsh.finalize()
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


def _beam_along_slab_edge() -> StructuralModel:
    """A slab and a beam along one edge, joined by a line connection."""
    model = StructuralModel(id="model", name="Line joint")
    model.add_member(
        CurveMember(
            id="beam", geometry=[END, START], material=MATERIAL, section=SECTION
        )
    )
    model.add_member(
        SurfaceMember(
            id="slab",
            geometry=[
                [6.648303508758545, -0.118, 0.0],
                START,
                END,
                [3.714, 0.139, 0.0],
            ],
            material=MATERIAL,
            thickness=0.2,
        )
    )
    joint = RigidConnection(
        id="joint", position=[(a + b) / 2 for a, b in zip(START, END)]
    )
    joint.edge = [START, END]
    joint.connected_members = ["beam", "slab"]
    model.add_connection(joint)
    return model


def _curve_lengths() -> list:
    lengths = []
    for _, tag in gmsh.model.getEntities(1):
        ends = gmsh.model.getBoundary([(1, tag)], oriented=False)
        a, b = (np.array(gmsh.model.getValue(0, abs(p), [])) for _, p in ends)
        lengths.append(float(np.linalg.norm(a - b)))
    return lengths


def _nodes_on_curve(tag: int) -> int:
    return len(gmsh.model.mesh.getNodes(1, tag, includeBoundary=True)[0])


class TestLineJointInItsGeometry:
    def test_no_sliver_at_the_seeded_middle(self):
        """The connection's middle and the station there are one point."""
        model = _beam_along_slab_edge()
        converter = GmshGeometryConverter(
            meshing_config=MeshingConfig(), domain_model=model
        )
        converter._we_initialized_gmsh = False
        converter.convert_model(model)
        assert min(_curve_lengths()) > 1e-3

    def test_a_vertex_moved_across_a_rounding_boundary_is_found(self):
        """Both sides get the same nodes though their ends round differently."""
        beam_end = [6.648303508758545, 6.782777786254883, 0.0]
        slab_end = [6.648303463362987, 6.782777773468102, 0.0]
        other_end = [5.10932195186615, 6.34928560256958, 0.0]
        converter = GmshGeometryConverter(meshing_config=MeshingConfig())
        assert converter._coord_key(*beam_end) != converter._coord_key(*slab_end)

        occ = gmsh.model.occ
        slab = occ.addLine(occ.addPoint(*other_end), occ.addPoint(*slab_end))
        beam = occ.addLine(occ.addPoint(*other_end), occ.addPoint(*beam_end))
        occ.synchronize()
        converter._member_curve_tags = {"beam": [beam]}
        converter._line_joint_pieces = [
            (
                "beam",
                np.zeros(3),
                [(np.array(other_end), np.array(beam_end))],
                0.5,
            )
        ]
        converter._conform_line_joints()
        gmsh.model.mesh.generate(1)
        assert _nodes_on_curve(slab) == _nodes_on_curve(beam) == 5

    def test_a_line_that_is_not_there_still_stops_the_analysis(self):
        """A vertex further off than rounding can explain is a real mismatch."""
        converter = GmshGeometryConverter(meshing_config=MeshingConfig())
        occ = gmsh.model.occ
        occ.addLine(occ.addPoint(0.0, 0.0, 0.0), occ.addPoint(1.0, 0.0, 0.0))
        beam = occ.addLine(occ.addPoint(0.0, 1.0, 0.0), occ.addPoint(1.0, 1.0, 0.0))
        occ.synchronize()
        converter._member_curve_tags = {"beam": [beam]}
        converter._line_joint_pieces = [
            (
                "beam",
                np.zeros(3),
                [(np.array([0.0, 0.0, 0.0]), np.array([1.001, 0.0, 0.0]))],
                0.5,
            )
        ]
        with pytest.raises(MeshingError) as error:
            converter._conform_line_joints()
        assert error.value.code == "E-MSH-004"
