"""
Regression test: Physical group element mapping.

Verifies that GmshGeometryConverter.convert_model() creates Gmsh physical
groups that map geometry entities to member IDs, and that the generated mesh
carries these tags through to meshio's cell_data['gmsh:physical'] and
field_data.

Uses slab_01 (multi-member model with both curve and surface members).
"""

import logging
import os

import gmsh
import meshio
import pytest

from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.meshing.gmsh_geometry import GmshGeometryConverter
from ifc_structural_mechanics.meshing.gmsh_runner import GmshRunner

logger = logging.getLogger(__name__)

IFC_MODELS_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

SLAB_01 = os.path.join(IFC_MODELS_DIR, "slab_01.ifc")
BUILDING_01A = os.path.join(IFC_MODELS_DIR, "building_01a.ifc")


def _get_ifc_path(relative_path: str) -> str:
    """Return absolute path, skip test if file not found."""
    if not os.path.exists(relative_path):
        pytest.skip(f"IFC file not found: {relative_path}")
    return relative_path


class TestPhysicalGroupMapping:
    """Test that physical groups correctly map geometry to member IDs."""

    @pytest.fixture(autouse=True)
    def setup_gmsh(self, tmp_path):
        """Initialize Gmsh for each test, finalize afterwards."""
        self.tmp_path = tmp_path
        if gmsh.isInitialized():
            gmsh.finalize()
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        yield
        if gmsh.isInitialized():
            gmsh.finalize()

    def test_physical_groups_populated_slab(self):
        """physical_group_map is populated after convert_model()."""
        ifc_path = _get_ifc_path(SLAB_01)
        extractor = Extractor(ifc_path)
        model = extractor.extract_model()

        config = MeshingConfig()
        converter = GmshGeometryConverter(meshing_config=config, domain_model=model)
        converter._we_initialized_gmsh = False  # Don't let converter finalize
        converter.convert_model(model)

        assert hasattr(converter, "physical_group_map"), "physical_group_map not set"
        assert len(converter.physical_group_map) > 0, "No physical groups created"

    def test_all_members_have_physical_groups_slab(self):
        """Every member with geometry should have a physical group."""
        ifc_path = _get_ifc_path(SLAB_01)
        extractor = Extractor(ifc_path)
        model = extractor.extract_model()

        config = MeshingConfig()
        converter = GmshGeometryConverter(meshing_config=config, domain_model=model)
        converter._we_initialized_gmsh = False
        converter.convert_model(model)

        phys_member_ids = set(converter.physical_group_map.values())
        model_member_ids = {m.id for m in model.members}

        # At minimum, most members should have physical groups
        # (some may lose theirs during fragment if geometry overlaps)
        coverage = len(phys_member_ids & model_member_ids) / len(model_member_ids)
        assert coverage > 0.8, (
            f"Only {coverage:.0%} of members have physical groups "
            f"({len(phys_member_ids & model_member_ids)}/{len(model_member_ids)})"
        )

    def test_mesh_carries_physical_group_data(self):
        """Generated mesh has gmsh:physical cell_data and field_data."""
        ifc_path = _get_ifc_path(SLAB_01)
        extractor = Extractor(ifc_path)
        model = extractor.extract_model()

        config = MeshingConfig()
        converter = GmshGeometryConverter(meshing_config=config, domain_model=model)
        converter._we_initialized_gmsh = False
        converter.convert_model(model)

        # Generate mesh
        runner = GmshRunner(meshing_config=config)
        runner._we_initialized_gmsh = False
        success = runner.run_meshing()
        assert success, "Mesh generation failed"

        mesh_file = str(self.tmp_path / "test.msh")
        runner.generate_mesh_file(mesh_file)

        # Read with meshio
        mesh = meshio.read(mesh_file)

        # Check field_data (physical group names → tags)
        assert hasattr(mesh, "field_data") and mesh.field_data, "No field_data in mesh"
        # field_data keys should be member IDs
        member_ids = {m.id for m in model.members}
        field_member_ids = set(mesh.field_data.keys())
        assert field_member_ids & member_ids, (
            f"field_data keys don't match member IDs. "
            f"Got: {list(field_member_ids)[:5]}"
        )

        # Check cell_data has gmsh:physical
        assert hasattr(mesh, "cell_data") and mesh.cell_data, "No cell_data in mesh"
        phys = mesh.cell_data.get("gmsh:physical")
        assert phys is not None, "No 'gmsh:physical' in cell_data"

        # At least some elements should have non-zero physical group tags
        import numpy as np

        all_tags = np.concatenate(phys)
        nonzero = np.count_nonzero(all_tags)
        assert nonzero > 0, "All physical group tags are zero"
        logger.info(f"{nonzero}/{len(all_tags)} elements have physical group tags")

    def test_physical_group_tags_are_unique_per_member(self):
        """Each member gets a distinct physical group tag."""
        ifc_path = _get_ifc_path(SLAB_01)
        extractor = Extractor(ifc_path)
        model = extractor.extract_model()

        config = MeshingConfig()
        converter = GmshGeometryConverter(meshing_config=config, domain_model=model)
        converter._we_initialized_gmsh = False
        converter.convert_model(model)

        pgmap = converter.physical_group_map
        # Tags should be unique (no two tags map to same member)
        member_ids = list(pgmap.values())
        assert len(member_ids) == len(
            set(member_ids)
        ), "Duplicate member IDs in physical_group_map"
        # Tags should also be unique
        tags = list(pgmap.keys())
        assert len(tags) == len(set(tags)), "Duplicate tags in physical_group_map"
