"""Points that fragment() adds take the mesh size of the members they lie on.

Support points inside a span, connection points on a slab and crossings are
passed to fragment() as tools, so they are no member's own points. They once
all took the smallest member size in the model: with beams at 0.25 m and slabs
at 1.0 m, a support under the middle of a slab refined the slab around it to
0.25 m without saying so (kbq).
"""

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
from tests.helpers import fixed_support

MATERIAL = Material(
    id="m", name="Concrete", elastic_modulus=30e9, poisson_ratio=0.2, density=2500
)
SECTION = Section.create_rectangular_section(id="s", name="R", width=0.3, height=0.3)

SLAB_MIDDLE = [2.0, 2.0, 0.0]
BEAM_MIDDLE = [2.0, 10.0, 0.0]


@pytest.fixture(autouse=True)
def gmsh_session():
    if gmsh.isInitialized():
        gmsh.finalize()
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


def _slab_and_beam() -> StructuralModel:
    """A slab and a beam apart from it, each with a support in its middle."""
    model = StructuralModel(id="model", name="Seeded point sizes")
    model.add_member(
        SurfaceMember(
            id="slab",
            geometry=[
                [0.0, 0.0, 0.0],
                [4.0, 0.0, 0.0],
                [4.0, 4.0, 0.0],
                [0.0, 4.0, 0.0],
            ],
            material=MATERIAL,
            thickness=0.2,
        )
    )
    model.add_member(
        CurveMember(
            id="beam",
            geometry=[[0.0, 10.0, 0.0], [4.0, 10.0, 0.0]],
            material=MATERIAL,
            section=SECTION,
        )
    )
    model.add_connection(fixed_support(SLAB_MIDDLE, "slab", "slab_support"))
    model.add_connection(fixed_support(BEAM_MIDDLE, "beam", "beam_support"))
    return model


def _size_at(position) -> float:
    """The mesh size Gmsh has for its point at ``position``."""
    for dim_tag in gmsh.model.getEntities(0):
        xyz = np.array(gmsh.model.getValue(0, dim_tag[1], []))
        if np.linalg.norm(xyz - np.array(position)) < 1e-6:
            return gmsh.model.mesh.getSizes([dim_tag])[0]
    raise AssertionError(f"No Gmsh point at {position}")


@pytest.mark.parametrize("beam_size, slab_size", [(0.25, 1.0), (1.0, 0.25)])
def test_a_seeded_point_takes_the_size_of_its_member(beam_size, slab_size):
    config = MeshingConfig()
    config.set_element_size("curve_members", beam_size)
    config.set_element_size("surface_members", slab_size)
    GmshGeometryConverter(meshing_config=config).convert_model(_slab_and_beam())

    assert _size_at(SLAB_MIDDLE) == pytest.approx(slab_size)
    assert _size_at(BEAM_MIDDLE) == pytest.approx(beam_size)
