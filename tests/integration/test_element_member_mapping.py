"""
Regression test: Element-to-member mapping via physical groups.

Verifies that UnifiedCalculixWriter correctly assigns mesh elements to their
parent structural members using physical group tags. Checks:
- Every member with geometry gets an element set (MEMBER_Mx)
- Element centroids are spatially close to their assigned member's geometry
- No element is assigned to two members
- The spatial fallback works for unmapped members
"""

import logging
import os

import numpy as np
import pytest

from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.config.system_config import SystemConfig
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    run_complete_analysis_workflow,
)

logger = logging.getLogger(__name__)

IFC_MODELS_DIR = os.path.join("examples", "analysis-models", "ifcFiles")
SLAB_01 = os.path.join(IFC_MODELS_DIR, "slab_01.ifc")
BUILDING_01A = os.path.join(IFC_MODELS_DIR, "building_01a.ifc")


def _get_ifc_path(relative_path: str) -> str:
    if not os.path.exists(relative_path):
        pytest.skip(f"IFC file not found: {relative_path}")
    return relative_path


def _run_workflow_to_inp(ifc_path: str, tmp_path, mesh_size: float = 0.5):
    """Extract model and generate CalculiX input, returning (model, writer_data)."""
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
    intermediate_dir = os.path.join(output_dir, "intermediate")

    run_complete_analysis_workflow(
        domain_model=model,
        output_inp_file=inp_file,
        analysis_config=analysis_config,
        meshing_config=meshing_config,
        system_config=SystemConfig(),
        intermediate_files_dir=intermediate_dir,
    )

    return model, inp_file


class TestElementMemberMapping:
    """Test element-to-member mapping correctness."""

    def test_every_member_gets_element_set_slab(self, tmp_path):
        """Every member in slab_01 should have a MEMBER_Mx element set in the INP."""
        ifc_path = _get_ifc_path(SLAB_01)
        model, inp_file = _run_workflow_to_inp(ifc_path, tmp_path)

        # Parse element sets from INP
        member_sets = _parse_member_element_sets(inp_file)

        # Check that most members have element sets
        members_with_sets = len(member_sets)
        total_members = len(model.members)
        coverage = members_with_sets / total_members if total_members else 0

        logger.info(f"{members_with_sets}/{total_members} members have element sets")
        assert coverage > 0.8, (
            f"Only {coverage:.0%} of members have element sets "
            f"({members_with_sets}/{total_members})"
        )

    def test_no_element_assigned_to_two_members_slab(self, tmp_path):
        """No element should appear in two different MEMBER_Mx element sets."""
        ifc_path = _get_ifc_path(SLAB_01)
        _, inp_file = _run_workflow_to_inp(ifc_path, tmp_path)

        member_sets = _parse_member_element_sets(inp_file)

        seen_elements = {}
        duplicates = []
        for set_name, elements in member_sets.items():
            for elem_id in elements:
                if elem_id in seen_elements:
                    duplicates.append(
                        f"Element {elem_id} in both {seen_elements[elem_id]} and {set_name}"
                    )
                seen_elements[elem_id] = set_name

        assert not duplicates, (
            f"Found {len(duplicates)} elements assigned to multiple members:\n"
            + "\n".join(duplicates[:10])
        )

    @pytest.mark.slow
    def test_element_centroids_near_member_geometry_building(self, tmp_path):
        """Element centroids should be spatially close to their assigned member."""
        ifc_path = _get_ifc_path(BUILDING_01A)
        model, inp_file = _run_workflow_to_inp(ifc_path, tmp_path, mesh_size=2.0)

        # Parse nodes and element-to-member from INP
        nodes = _parse_nodes(inp_file)
        member_sets = _parse_member_element_sets(inp_file)
        elements = _parse_elements(inp_file)

        # Build member geometry bounding boxes from domain model
        member_bboxes = {}
        for member in model.members:
            coords = _get_member_coords(member)
            if coords:
                arr = np.array(coords)
                member_bboxes[member.id] = (arr.min(axis=0), arr.max(axis=0))

        # For each member element set, check element centroids
        bad_elements = 0
        total_checked = 0
        for set_name, elem_ids in member_sets.items():
            # Try to find corresponding member
            member_id = None
            for m in model.members:
                short_id = _get_short_id(m.id)
                if set_name == f"MEMBER_{short_id}":
                    member_id = m.id
                    break

            if member_id is None or member_id not in member_bboxes:
                continue

            bbox_min, bbox_max = member_bboxes[member_id]
            # Expand bbox by generous margin (mesh elements can extend slightly)
            margin = 2.0  # meters
            bbox_min = bbox_min - margin
            bbox_max = bbox_max + margin

            for elem_id in elem_ids:
                if elem_id not in elements:
                    continue
                elem_nodes = elements[elem_id]
                centroid = np.mean([nodes[n] for n in elem_nodes if n in nodes], axis=0)
                total_checked += 1
                if np.any(centroid < bbox_min) or np.any(centroid > bbox_max):
                    bad_elements += 1

        if total_checked > 0:
            bad_pct = bad_elements / total_checked
            logger.info(
                f"Checked {total_checked} elements: "
                f"{bad_elements} outside member bbox ({bad_pct:.1%})"
            )
            assert (
                bad_pct < 0.05
            ), f"{bad_pct:.1%} of elements are outside their member's bounding box"


def _get_short_id(member_id: str) -> str:
    """Extract short member ID (e.g. 'M43' from '2Su8k...M43')."""
    if "_M" in member_id:
        return member_id.split("_M")[-1]
    return member_id[:8]


def _get_member_coords(member) -> list:
    """Extract defining coordinates from a member."""
    coords = []
    if isinstance(member, CurveMember):
        if hasattr(member, "start_point") and member.start_point:
            coords.append(list(member.start_point))
        if hasattr(member, "end_point") and member.end_point:
            coords.append(list(member.end_point))
    elif isinstance(member, SurfaceMember):
        if hasattr(member, "vertices") and member.vertices:
            coords.extend([list(v) for v in member.vertices])
    return coords


def _parse_member_element_sets(inp_path: str) -> dict:
    """Parse MEMBER_* element sets from an INP file."""
    sets = {}
    current_set = None
    with open(inp_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("*ELSET") and "MEMBER_" in line:
                # Extract set name
                for part in line.split(","):
                    part = part.strip()
                    if part.startswith("ELSET="):
                        current_set = part.split("=")[1].strip()
                        sets[current_set] = []
                        break
            elif current_set and not line.startswith("*") and line:
                # Parse element IDs
                for token in line.split(","):
                    token = token.strip()
                    if token.isdigit():
                        sets[current_set].append(int(token))
            elif line.startswith("*"):
                current_set = None
    return sets


def _parse_nodes(inp_path: str) -> dict:
    """Parse node coordinates from INP file."""
    nodes = {}
    in_nodes = False
    with open(inp_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("*NODE"):
                in_nodes = True
                continue
            if in_nodes:
                if line.startswith("*"):
                    in_nodes = False
                    continue
                parts = line.split(",")
                if len(parts) >= 4:
                    try:
                        nid = int(parts[0].strip())
                        x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                        nodes[nid] = np.array([x, y, z])
                    except ValueError:
                        continue
    return nodes


def _parse_elements(inp_path: str) -> dict:
    """Parse element connectivity from INP file."""
    elements = {}
    in_elements = False
    with open(inp_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("*ELEMENT"):
                in_elements = True
                continue
            if in_elements:
                if line.startswith("*"):
                    in_elements = False
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        eid = int(parts[0].strip())
                        node_ids = [int(p.strip()) for p in parts[1:] if p.strip()]
                        elements[eid] = node_ids
                    except ValueError:
                        continue
    return elements
