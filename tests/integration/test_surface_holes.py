"""The openings of a surface member are holes in its mesh (2uq)."""

import gmsh
import numpy as np
import pytest

from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import (
    CurveMember,
    SurfaceMember,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.gmsh_geometry import GmshGeometryConverter

MATERIAL = Material(
    id="m", name="Concrete", elastic_modulus=30e9, poisson_ratio=0.2, density=2800
)
SECTION = Section.create_rectangular_section(id="s", name="R", width=0.2, height=0.2)
HOLE = [[2.0, 1.0, 0.0], [3.0, 1.0, 0.0], [3.0, 2.0, 0.0], [2.0, 2.0, 0.0]]


@pytest.fixture(autouse=True)
def gmsh_session():
    if gmsh.isInitialized():
        gmsh.finalize()
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


def _slab_with_a_hole(*columns) -> StructuralModel:
    model = StructuralModel(id="model", name="Opening")
    slab = SurfaceMember(
        id="slab",
        geometry=[[0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [5.0, 3.0, 0.0], [0.0, 3.0, 0.0]],
        material=MATERIAL,
        thickness=0.2,
    )
    slab.holes = [HOLE]
    model.add_member(slab)
    for index, (x, y) in enumerate(columns):
        model.add_member(
            CurveMember(
                id=f"column{index}",
                geometry=[[x, y, -1.0], [x, y, 1.0]],
                material=MATERIAL,
                section=SECTION,
            )
        )
    return model


def _mesh(model) -> None:
    converter = GmshGeometryConverter(
        meshing_config=MeshingConfig(), domain_model=model
    )
    converter._we_initialized_gmsh = False
    converter.convert_model(model)
    gmsh.model.mesh.generate(2)


def _triangle_centres() -> np.ndarray:
    types, _, nodes = gmsh.model.mesh.getElements(2)
    corners = []
    for kind, connectivity in zip(types, nodes):
        count = gmsh.model.mesh.getElementProperties(kind)[3]
        corners.append(np.asarray(connectivity).reshape(-1, count)[:, :3])
    coordinates = {}
    tags, values, _ = gmsh.model.mesh.getNodes()
    for tag, point in zip(tags, values.reshape(-1, 3)):
        coordinates[int(tag)] = point
    return np.array(
        [
            np.mean([coordinates[int(n)] for n in triangle], axis=0)
            for triangle in np.vstack(corners)
        ]
    )


class TestHoleInTheMesh:
    def test_no_element_in_the_hole(self):
        _mesh(_slab_with_a_hole())
        centres = _triangle_centres()
        in_hole = (
            (centres[:, 0] > 2.0)
            & (centres[:, 0] < 3.0)
            & (centres[:, 1] > 1.0)
            & (centres[:, 1] < 2.0)
        )
        assert len(centres) > 0
        assert not in_hole.any()

    def test_column_through_the_hole_is_not_pinned_to_the_slab(self):
        """Only the column beside the hole gets a node in the slab."""
        _mesh(_slab_with_a_hole((2.5, 1.5), (1.0, 1.5)))
        points = np.array(
            [gmsh.model.getValue(0, tag, []) for _, tag in gmsh.model.getEntities(0)]
        )
        at_z_0 = points[np.abs(points[:, 2]) < 1e-9]
        assert np.linalg.norm(at_z_0 - [1.0, 1.5, 0.0], axis=1).min() < 1e-6
        assert np.linalg.norm(at_z_0 - [2.5, 1.5, 0.0], axis=1).min() > 0.1

    def test_column_on_the_edge_of_the_hole_is_on_the_slab(self):
        _mesh(_slab_with_a_hole((2.5, 1.0)))
        points = np.array(
            [gmsh.model.getValue(0, tag, []) for _, tag in gmsh.model.getEntities(0)]
        )
        assert np.linalg.norm(points - [2.5, 1.0, 0.0], axis=1).min() < 1e-6
