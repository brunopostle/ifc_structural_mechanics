"""
Regression test: End-to-end building model analysis.

Runs building_01a through the full pipeline (extract → mesh → write → solve → parse)
and checks that results are physically reasonable. This catches catastrophic
regressions like the mesh disconnectivity bug (6.74e+11 m displacements).

Also includes a faster slab_01 test for use without the @slow marker.
"""

import os
import shutil
import logging

import numpy as np
import pytest

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

logger = logging.getLogger(__name__)

IFC_MODELS_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

CCX_AVAILABLE = shutil.which("ccx") is not None

SLAB_01 = os.path.join(IFC_MODELS_DIR, "slab_01.ifc")
BUILDING_01A = os.path.join(IFC_MODELS_DIR, "building_01a.ifc")


def _get_ifc_path(path: str) -> str:
    if not os.path.exists(path):
        pytest.skip(f"IFC file not found: {path}")
    return path


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestSlabAnalysis:
    """End-to-end test for slab_01 (simpler, faster than building)."""

    def test_slab_analysis_succeeds(self, tmp_path):
        """slab_01 analysis should succeed."""
        ifc_path = _get_ifc_path(SLAB_01)
        output_dir = str(tmp_path / "slab_01")

        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )

        assert result["status"] == "success", (
            f"Analysis failed: {result.get('errors', [])}"
        )

    def test_slab_displacement_reasonable(self, tmp_path):
        """slab_01 max displacement should be < 1m (physically reasonable)."""
        ifc_path = _get_ifc_path(SLAB_01)
        output_dir = str(tmp_path / "slab_01")

        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )

        assert result["status"] == "success"

        parsed = result.get("parsed_results", {})
        displacements = parsed.get("displacements", {})

        if displacements:
            # Extract displacement magnitudes
            max_disp = 0.0
            for node_id, disp_data in displacements.items():
                if isinstance(disp_data, dict):
                    vals = [disp_data.get('ux', 0), disp_data.get('uy', 0), disp_data.get('uz', 0)]
                elif isinstance(disp_data, (list, tuple)):
                    vals = list(disp_data[:3])
                else:
                    continue
                mag = np.sqrt(sum(v**2 for v in vals))
                max_disp = max(max_disp, mag)

            logger.info(f"slab_01 max displacement: {max_disp:.4f} m")
            assert max_disp < 1.0, (
                f"Max displacement {max_disp:.2f}m > 1.0m — not physically reasonable"
            )
            assert max_disp > 0, "Zero displacement — analysis may not have run"

    def test_slab_reactions_nonzero(self, tmp_path):
        """slab_01 should have non-zero reaction forces (gravity pushes down, supports push up)."""
        ifc_path = _get_ifc_path(SLAB_01)
        output_dir = str(tmp_path / "slab_01")

        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )

        assert result["status"] == "success"

        parsed = result.get("parsed_results", {})
        reactions = parsed.get("reactions", {})

        if reactions:
            # Check total reaction force has vertical component
            total_fz = 0.0
            for node_id, rxn in reactions.items():
                if isinstance(rxn, dict):
                    total_fz += rxn.get('fz', 0) or 0
                elif isinstance(rxn, (list, tuple)) and len(rxn) >= 3:
                    total_fz += rxn[2]

            logger.info(f"slab_01 total Fz reaction: {total_fz:.1f} N")
            # Gravity pulls down (negative Z), reactions push up (positive Z)
            assert abs(total_fz) > 0, "Zero vertical reaction force"


@pytest.mark.slow
@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestBuildingAnalysis:
    """End-to-end regression test for building_01a."""

    def test_building_analysis_succeeds(self, tmp_path):
        """building_01a analysis should succeed."""
        ifc_path = _get_ifc_path(BUILDING_01A)
        output_dir = str(tmp_path / "building_01a")

        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=output_dir,
            mesh_size=2.0,
            gravity=True,
        )

        assert result["status"] == "success", (
            f"Analysis failed: {result.get('errors', [])}"
        )

    def test_building_displacement_reasonable(self, tmp_path):
        """building_01a max displacement should be < 1.0m (not billions)."""
        ifc_path = _get_ifc_path(BUILDING_01A)
        output_dir = str(tmp_path / "building_01a")

        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=output_dir,
            mesh_size=2.0,
            gravity=True,
        )

        assert result["status"] == "success"

        parsed = result.get("parsed_results", {})
        displacements = parsed.get("displacements", {})

        if displacements:
            max_disp = 0.0
            for node_id, disp_data in displacements.items():
                if isinstance(disp_data, dict):
                    vals = [disp_data.get('ux', 0), disp_data.get('uy', 0), disp_data.get('uz', 0)]
                elif isinstance(disp_data, (list, tuple)):
                    vals = list(disp_data[:3])
                else:
                    continue
                mag = np.sqrt(sum(v**2 for v in vals))
                max_disp = max(max_disp, mag)

            logger.info(f"building_01a max displacement: {max_disp:.4f} m")
            # The critical regression: the bug produced 6.74e+11 m
            assert max_disp < 1.0, (
                f"Max displacement {max_disp:.2f}m > 1.0m — "
                f"possible mesh disconnectivity regression"
            )

    def test_building_reactions_plausible(self, tmp_path):
        """building_01a reactions should have reasonable magnitude."""
        ifc_path = _get_ifc_path(BUILDING_01A)
        output_dir = str(tmp_path / "building_01a")

        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=output_dir,
            mesh_size=2.0,
            gravity=True,
        )

        assert result["status"] == "success"

        parsed = result.get("parsed_results", {})
        reactions = parsed.get("reactions", {})

        if reactions:
            total_f = np.zeros(3)
            for node_id, rxn in reactions.items():
                if isinstance(rxn, dict):
                    total_f[0] += rxn.get('fx', 0) or 0
                    total_f[1] += rxn.get('fy', 0) or 0
                    total_f[2] += rxn.get('fz', 0) or 0
                elif isinstance(rxn, (list, tuple)) and len(rxn) >= 3:
                    for k in range(3):
                        total_f[k] += rxn[k]

            fmag = np.linalg.norm(total_f)
            logger.info(
                f"building_01a total reaction: [{total_f[0]:.0f}, {total_f[1]:.0f}, {total_f[2]:.0f}] N, "
                f"magnitude={fmag:.0f} N"
            )
            # Should have significant reaction (building self-weight)
            assert fmag > 100, (
                f"Total reaction force magnitude {fmag:.1f}N is suspiciously small"
            )
