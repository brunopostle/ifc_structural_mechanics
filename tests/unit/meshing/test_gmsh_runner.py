"""
Unit tests for the Gmsh runner module.

The runner meshes the model that is in the Gmsh Python API and writes it to a
file. It once had a second mode that ran the Gmsh executable on a ``.geo``
file, which could not see that model, and wrote an empty file in place of a
mesh when it ran under pytest.
"""

import os

import pytest

gmsh = pytest.importorskip("gmsh")

from ifc_structural_mechanics.config.meshing_config import MeshingConfig  # noqa: E402
from ifc_structural_mechanics.meshing.gmsh_runner import GmshRunner  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import MeshingError  # noqa: E402


@pytest.fixture
def line_model():
    """A 2 m line in a fresh Gmsh model."""
    if gmsh.isInitialized():
        gmsh.finalize()
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("line")
    start = gmsh.model.occ.addPoint(0.0, 0.0, 0.0)
    end = gmsh.model.occ.addPoint(2.0, 0.0, 0.0)
    line = gmsh.model.occ.addLine(start, end)
    gmsh.model.occ.synchronize()
    gmsh.model.addPhysicalGroup(1, [line], 1)
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


def _config(size=0.5, order=2):
    config = MeshingConfig()
    config.set_default_mesh_size(size)
    config.set_element_order(order)
    return config


class TestGmshRunner:
    def test_meshes_the_model_in_the_api(self, line_model):
        runner = GmshRunner(meshing_config=_config(order=1))
        assert runner.run_meshing() is True
        node_tags, _, _ = gmsh.model.mesh.getNodes()
        assert len(node_tags) >= 3

    def test_element_order_comes_from_the_configuration(self, line_model):
        GmshRunner(meshing_config=_config(order=2)).run_meshing()
        element_types, _, _ = gmsh.model.mesh.getElements(1)
        # Gmsh type 8 is the three-node line
        assert list(element_types) == [8]

    def test_mesh_file_is_written(self, line_model, tmp_path):
        runner = GmshRunner(meshing_config=_config())
        runner.run_meshing()
        path = str(tmp_path / "sub" / "mesh.msh")
        assert runner.generate_mesh_file(path) == path
        assert os.path.getsize(path) > 0

    def test_unknown_algorithm_is_an_error(self, line_model):
        """It used to be replaced by Delaunay without a word."""
        runner = GmshRunner(meshing_config=_config())
        with pytest.raises(MeshingError, match="Unknown meshing algorithm"):
            runner.run_meshing(algorithm="Nonsense")

    def test_file_that_cannot_be_written_is_an_error(self, line_model, tmp_path):
        runner = GmshRunner(meshing_config=_config())
        runner.run_meshing()
        with pytest.raises(MeshingError):
            runner.generate_mesh_file(str(tmp_path / "mesh.not_a_format"))

    def test_does_not_finalize_a_gmsh_it_did_not_start(self, line_model):
        runner = GmshRunner(meshing_config=_config())
        assert runner._we_initialized_gmsh is False
        del runner
        assert gmsh.isInitialized()
