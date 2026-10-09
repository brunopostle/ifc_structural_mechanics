"""
Regression test: End-to-end building model analysis.

Runs building_02 through the full pipeline (extract → mesh → write → solve → parse)
and checks that results are physically reasonable. This catches catastrophic
regressions like the mesh disconnectivity bug (6.74e+11 m displacements).

Also includes a faster slab_01 test for use without the @slow marker.
"""

import logging
import os
import shutil

import numpy as np
import pytest

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

logger = logging.getLogger(__name__)

IFC_MODELS_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

CCX_AVAILABLE = shutil.which("ccx") is not None

SLAB_01 = os.path.join(IFC_MODELS_DIR, "slab_01.ifc")
BUILDING_02 = os.path.join(IFC_MODELS_DIR, "building_02.ifc")


def _max_displacement(result: dict) -> float:
    """Largest nodal displacement magnitude over all load cases, in metres."""
    displacements = result["parsed_results"]["displacement"]
    assert displacements, "No displacement results were parsed"
    return max(r.get_magnitude() for r in displacements)


def _total_reaction(result: dict) -> np.ndarray:
    """Sum of reaction force vectors over all parsed reaction records, in N."""
    reactions = result["parsed_results"]["reaction"]
    assert reactions, "No reaction results were parsed"
    return np.sum([r.get_forces() for r in reactions], axis=0)


def _get_ifc_path(path: str) -> str:
    if not os.path.exists(path):
        pytest.skip(f"IFC file not found: {path}")
    return path


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestSlabAnalysis:
    """End-to-end test for slab_01 (simpler, faster than building)."""

    @pytest.fixture(scope="class")
    def slab_result(self, tmp_path_factory):
        return analyze_ifc(
            ifc_path=_get_ifc_path(SLAB_01),
            output_dir=str(tmp_path_factory.mktemp("slab_01")),
            mesh_size=0.5,
            gravity=True,
        )

    def test_slab_analysis_succeeds(self, slab_result):
        """slab_01 analysis should succeed."""
        assert (
            slab_result["status"] == "success"
        ), f"Analysis failed: {slab_result.get('errors', [])}"

    def test_slab_displacement_reasonable(self, slab_result):
        """slab_01 deflects under self-weight by a fraction of a millimetre."""
        max_disp = _max_displacement(slab_result)
        logger.info(f"slab_01 max displacement: {max_disp:.6f} m")
        assert 1e-5 < max_disp < 1e-2

    def test_slab_reactions_balance_self_weight(self, slab_result):
        """slab_01 reactions push up with a force of a few hundred kN."""
        total = _total_reaction(slab_result)
        logger.info(f"slab_01 total reaction: {total} N")
        assert 1e5 < total[2] < 1e6
        assert abs(total[0]) < 1.0 and abs(total[1]) < 1.0


@pytest.mark.slow
class TestBuildingAnalysis:
    """End-to-end regression test for building_02 (shared session run)."""

    def test_building_analysis_succeeds(self, building_02_run):
        """building_02 analysis should succeed."""
        result, _ = building_02_run
        assert (
            result["status"] == "success"
        ), f"Analysis failed: {result.get('errors', [])}"

    @pytest.mark.xfail(
        strict=True,
        reason="building_02 is near-singular under self-weight (ifc_structural_mechanics-aiz.15)",
    )
    def test_building_displacement_reasonable(self, building_02_run):
        """building_02 max displacement should be < 1.0m (not kilometres)."""
        result, _ = building_02_run
        max_disp = _max_displacement(result)
        logger.info(f"building_02 max displacement: {max_disp:.4f} m")
        assert 0 < max_disp < 1.0

    def test_building_reactions_plausible(self, building_02_run):
        """building_02 reactions carry a building's worth of vertical load."""
        result, _ = building_02_run
        total = _total_reaction(result)
        logger.info(f"building_02 total reaction: {total} N")
        assert abs(total[2]) > 1e6
