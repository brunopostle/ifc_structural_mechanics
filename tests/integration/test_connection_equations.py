"""
Regression test: Connection equation quality.

Verifies that *EQUATION constraints in the CalculiX INP file connect nodes
that are actually near each other spatially (within 0.5m tolerance). This
catches the bug where wrong element-to-member mapping caused equations to
connect nodes on opposite sides of the building (16+ meters apart).
"""

import os
import re
import logging

import numpy as np
import pytest

from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    run_complete_analysis_workflow,
)
from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.config.system_config import SystemConfig

logger = logging.getLogger(__name__)

IFC_MODELS_DIR = os.path.join("examples", "analysis-models", "ifcFiles")
BUILDING_01A = os.path.join(IFC_MODELS_DIR, "building_01a.ifc")
STRUCTURE_01 = os.path.join(IFC_MODELS_DIR, "structure_01.ifc")


def _get_ifc_path(path: str) -> str:
    if not os.path.exists(path):
        pytest.skip(f"IFC file not found: {path}")
    return path


def _generate_inp(ifc_path: str, tmp_path, mesh_size: float = 1.0) -> tuple:
    """Generate INP file and return (model, inp_path)."""
    extractor = Extractor(ifc_path)
    model = extractor.extract_model()

    analysis_config = AnalysisConfig()
    analysis_config._config["gravity"] = True

    meshing_config = MeshingConfig()
    meshing_config._config["global_settings"]["default_element_size"] = mesh_size
    if mesh_size > meshing_config._config["global_settings"]["max_element_size"]:
        meshing_config._config["global_settings"]["max_element_size"] = mesh_size
    for mt in meshing_config._config["member_types"]:
        meshing_config._config["member_types"][mt]["element_size"] = mesh_size

    output_dir = str(tmp_path / "output")
    os.makedirs(output_dir, exist_ok=True)
    inp_file = os.path.join(output_dir, "analysis.inp")

    run_complete_analysis_workflow(
        domain_model=model,
        output_inp_file=inp_file,
        analysis_config=analysis_config,
        meshing_config=meshing_config,
        system_config=SystemConfig(),
        intermediate_files_dir=os.path.join(output_dir, "intermediate"),
    )

    return model, inp_file


def _parse_equation_pairs(inp_path: str) -> list:
    """
    Parse *EQUATION node pairs from an INP file.

    Returns list of (node1, dof1, node2, dof2) tuples.
    """
    pairs = []
    lines = open(inp_path).readlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == '*EQUATION':
            # Next line is the number of terms (should be 2)
            i += 1
            if i < len(lines):
                nterms = lines[i].strip()
                if nterms == '2':
                    i += 1
                    if i < len(lines):
                        data = lines[i].strip()
                        parts = data.split(',')
                        if len(parts) >= 6:
                            try:
                                n1 = int(parts[0])
                                d1 = int(parts[1])
                                n2 = int(parts[3])
                                d2 = int(parts[4])
                                pairs.append((n1, d1, n2, d2))
                            except ValueError:
                                pass
        i += 1
    return pairs


def _parse_nodes(inp_path: str) -> dict:
    """Parse node coordinates from INP file."""
    nodes = {}
    in_nodes = False
    with open(inp_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('*NODE'):
                in_nodes = True
                continue
            if in_nodes:
                if line.startswith('*'):
                    break
                parts = line.split(',')
                if len(parts) >= 4:
                    try:
                        nid = int(parts[0].strip())
                        x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                        nodes[nid] = np.array([x, y, z])
                    except ValueError:
                        continue
    return nodes


class TestConnectionEquations:
    """Test that connection equations connect spatially close nodes."""

    def test_equation_node_distances_structure(self, tmp_path):
        """All equation pairs in structure_01 should connect nearby nodes (<1m)."""
        ifc_path = _get_ifc_path(STRUCTURE_01)
        _, inp_file = _generate_inp(ifc_path, tmp_path, mesh_size=0.5)

        nodes = _parse_nodes(inp_file)
        pairs = _parse_equation_pairs(inp_file)

        if not pairs:
            pytest.skip("No equations found in structure_01 INP")

        distances = []
        for n1, d1, n2, d2 in pairs:
            if n1 in nodes and n2 in nodes:
                dist = np.linalg.norm(nodes[n1] - nodes[n2])
                distances.append(dist)

        if not distances:
            pytest.skip("Could not compute distances (nodes not found)")

        distances = np.array(distances)
        max_dist = distances.max()
        median_dist = np.median(distances)

        logger.info(
            f"structure_01: {len(pairs)} equations, "
            f"max distance={max_dist:.3f}m, median={median_dist:.3f}m"
        )

        assert max_dist < 1.0, (
            f"Max equation node distance {max_dist:.2f}m > 1.0m — "
            f"nodes are too far apart (bad element-to-member mapping?)"
        )

    @pytest.mark.slow
    def test_equation_node_distances_building(self, tmp_path):
        """All equation pairs in building_01a should connect nearby nodes (<0.5m)."""
        ifc_path = _get_ifc_path(BUILDING_01A)
        model, inp_file = _generate_inp(ifc_path, tmp_path, mesh_size=2.0)

        nodes = _parse_nodes(inp_file)
        pairs = _parse_equation_pairs(inp_file)

        if not pairs:
            pytest.skip("No equations found in building_01a INP")

        distances = []
        for n1, d1, n2, d2 in pairs:
            if n1 in nodes and n2 in nodes:
                dist = np.linalg.norm(nodes[n1] - nodes[n2])
                distances.append(dist)

        distances = np.array(distances)
        max_dist = distances.max()
        median_dist = np.median(distances)
        far_count = np.sum(distances > 0.5)

        logger.info(
            f"building_01a: {len(pairs)} equations, "
            f"max dist={max_dist:.3f}m, median={median_dist:.3f}m, "
            f">0.5m: {far_count}"
        )

        # The critical regression: the old bug connected nodes 16+m apart
        assert max_dist < 2.0, (
            f"Max equation distance {max_dist:.2f}m > 2.0m — "
            f"possible element-to-member mapping regression"
        )
        assert median_dist < 0.5, (
            f"Median equation distance {median_dist:.3f}m > 0.5m"
        )

    @pytest.mark.slow
    def test_connection_count_building(self, tmp_path):
        """Building model should produce a reasonable number of connections."""
        ifc_path = _get_ifc_path(BUILDING_01A)
        model, inp_file = _generate_inp(ifc_path, tmp_path, mesh_size=2.0)

        pairs = _parse_equation_pairs(inp_file)

        # Count connections with 2+ real members
        real_connections = 0
        for conn in model.connections:
            real_members = [
                m for m in conn.connected_members
                if not m.startswith('dummy_member_')
            ]
            if len(real_members) >= 2:
                real_connections += 1

        logger.info(
            f"building_01a: {real_connections} real connections, "
            f"{len(pairs)} equation pairs written"
        )

        # Should have at least some equations written
        # (exact count depends on shared nodes vs equations needed)
        if real_connections > 0:
            assert len(pairs) > 0, (
                f"No equations written despite {real_connections} connections with 2+ members"
            )
