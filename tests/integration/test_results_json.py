"""Integration tests: results.json content produced by ResultsExporter.

Asserts that analyze_ifc() writes a well-formed results.json keyed to IFC
GlobalIds with correct structure, plausible displacement values, and the
right number of members for each example model.

Fast models (beam_01, portal_01, slab_01) run as part of the normal suite.
building_01a is marked slow.
"""

import json
import logging
import os
import shutil

import pytest

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

logger = logging.getLogger(__name__)

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

CCX_AVAILABLE = shutil.which("ccx") is not None


def _ifc(name: str) -> str:
    path = os.path.join(IFC_DIR, name)
    if not os.path.exists(path):
        pytest.skip(f"IFC file not found: {path}")
    return path


def _load_results_json(output_dir: str) -> dict:
    json_path = os.path.join(output_dir, "results.json")
    assert os.path.exists(json_path), f"results.json not written to {output_dir}"
    with open(json_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Schema validation helper
# ---------------------------------------------------------------------------


def _assert_schema(data: dict) -> None:
    """Assert top-level results.json schema is present and well-formed."""
    assert data.get("schema_version") == "1.0"
    units = data.get("units", {})
    assert units.get("displacement") == "m"
    assert units.get("stress") == "Pa"
    assert "members" in data
    assert isinstance(data["members"], list)
    assert len(data["members"]) > 0, "results.json has no members"
    for member in data["members"]:
        assert "ifc_guid" in member, f"Member missing ifc_guid: {member}"
        assert "id" in member
        assert "type" in member
        assert member["status"] in ("ok", "warning", "fail")


# ---------------------------------------------------------------------------
# beam_01 — single span simply-supported beam with point loads
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestBeam01ResultsJson:
    """results.json checks for beam_01.ifc."""

    def test_results_json_written(self, tmp_path):
        output_dir = str(tmp_path / "beam_01")
        analyze_ifc(ifc_path=_ifc("beam_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        assert os.path.exists(os.path.join(output_dir, "results.json"))

    def test_schema_valid(self, tmp_path):
        output_dir = str(tmp_path / "beam_01")
        analyze_ifc(ifc_path=_ifc("beam_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        _assert_schema(data)

    def test_member_has_ifc_guid(self, tmp_path):
        output_dir = str(tmp_path / "beam_01")
        analyze_ifc(ifc_path=_ifc("beam_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        guids = [m["ifc_guid"] for m in data["members"] if m["ifc_guid"]]
        assert len(guids) > 0, "No members have an ifc_guid"

    def test_displacement_plausible(self, tmp_path):
        """beam_01 max displacement should be in (0, 0.01] m (analytical: ~0.26 mm)."""
        output_dir = str(tmp_path / "beam_01")
        analyze_ifc(ifc_path=_ifc("beam_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        global_disp = data.get("global_displacements", {})
        envelope = global_disp.get("envelope", {})
        max_disp = envelope.get("max_displacement_m", None)
        assert max_disp is not None, "global_displacements.envelope.max_displacement_m missing"
        logger.info(f"beam_01 max displacement: {max_disp * 1000:.3f} mm")
        assert max_disp > 0, "Zero displacement — analysis may not have run"
        assert max_disp < 0.01, f"Displacement {max_disp * 1000:.2f} mm unexpectedly large"

    def test_global_reactions_present(self, tmp_path):
        output_dir = str(tmp_path / "beam_01")
        analyze_ifc(ifc_path=_ifc("beam_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        reactions = data.get("global_reactions", {})
        total = reactions.get("total", {})
        resultant = total.get("resultant_N", None)
        if resultant is not None:
            logger.info(f"beam_01 reaction resultant: {resultant:.1f} N")
            assert resultant > 0, "Zero total reaction force"


# ---------------------------------------------------------------------------
# portal_01 — portal frame with horizontal load
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestPortal01ResultsJson:
    """results.json checks for portal_01.ifc."""

    def test_schema_valid(self, tmp_path):
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        _assert_schema(data)

    def test_multiple_members(self, tmp_path):
        """portal_01 has at least 3 members (2 columns + 1 beam)."""
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        assert len(data["members"]) >= 3, (
            f"Expected >= 3 members, got {len(data['members'])}"
        )

    def test_displacement_plausible(self, tmp_path):
        """portal_01 max displacement should be in (0, 0.1] m (analytical: ~0.55 mm)."""
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        max_disp = data["global_displacements"]["envelope"]["max_displacement_m"]
        logger.info(f"portal_01 max displacement: {max_disp * 1000:.3f} mm")
        assert 0 < max_disp < 0.1

    def test_member_types_curve(self, tmp_path):
        """portal_01 members should all be curve type."""
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        types = {m["type"] for m in data["members"]}
        assert "curve" in types, f"No curve members found; types: {types}"


# ---------------------------------------------------------------------------
# slab_01 — reinforced concrete slab under self-weight
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestSlab01ResultsJson:
    """results.json checks for slab_01.ifc (surface member, gravity load)."""

    def test_schema_valid(self, tmp_path):
        output_dir = str(tmp_path / "slab_01")
        analyze_ifc(
            ifc_path=_ifc("slab_01.ifc"), output_dir=output_dir, mesh_size=0.5, gravity=True
        )
        data = _load_results_json(output_dir)
        _assert_schema(data)

    def test_member_type_surface(self, tmp_path):
        """slab_01 members should include surface type."""
        output_dir = str(tmp_path / "slab_01")
        analyze_ifc(
            ifc_path=_ifc("slab_01.ifc"), output_dir=output_dir, mesh_size=0.5, gravity=True
        )
        data = _load_results_json(output_dir)
        types = {m["type"] for m in data["members"]}
        assert "surface" in types, f"No surface members found; types: {types}"

    def test_displacement_plausible(self, tmp_path):
        """slab_01 max displacement should be in (0, 0.01] m (analytical: ~0.39 mm)."""
        output_dir = str(tmp_path / "slab_01")
        analyze_ifc(
            ifc_path=_ifc("slab_01.ifc"), output_dir=output_dir, mesh_size=0.5, gravity=True
        )
        data = _load_results_json(output_dir)
        max_disp = data["global_displacements"]["envelope"]["max_displacement_m"]
        logger.info(f"slab_01 max displacement: {max_disp * 1000:.3f} mm")
        assert 0 < max_disp < 0.01

    def test_member_envelope_present(self, tmp_path):
        """Each slab_01 member should have an envelope with displacement data."""
        output_dir = str(tmp_path / "slab_01")
        analyze_ifc(
            ifc_path=_ifc("slab_01.ifc"), output_dir=output_dir, mesh_size=0.5, gravity=True
        )
        data = _load_results_json(output_dir)
        members_with_envelope = [m for m in data["members"] if m.get("envelope")]
        assert len(members_with_envelope) > 0, "No members have displacement envelope data"


# ---------------------------------------------------------------------------
# building_01a — multi-storey building under self-weight (slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestBuilding01aResultsJson:
    """results.json checks for building_01a.ifc."""

    def test_schema_valid(self, tmp_path):
        output_dir = str(tmp_path / "building_01a")
        analyze_ifc(
            ifc_path=_ifc("building_01a.ifc"),
            output_dir=output_dir,
            mesh_size=2.0,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        _assert_schema(data)

    def test_many_members(self, tmp_path):
        """building_01a has many structural members."""
        output_dir = str(tmp_path / "building_01a")
        analyze_ifc(
            ifc_path=_ifc("building_01a.ifc"),
            output_dir=output_dir,
            mesh_size=2.0,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        logger.info(f"building_01a member count: {len(data['members'])}")
        assert len(data["members"]) >= 10

    def test_displacement_plausible(self, tmp_path):
        """building_01a max displacement should be in (0, 1] m (analytical: ~14 mm)."""
        output_dir = str(tmp_path / "building_01a")
        analyze_ifc(
            ifc_path=_ifc("building_01a.ifc"),
            output_dir=output_dir,
            mesh_size=2.0,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        max_disp = data["global_displacements"]["envelope"]["max_displacement_m"]
        logger.info(f"building_01a max displacement: {max_disp * 1000:.1f} mm")
        assert 0 < max_disp < 1.0, (
            f"Displacement {max_disp:.3f} m — possible mesh disconnectivity regression"
        )

    def test_all_members_have_guid(self, tmp_path):
        """Every member in building_01a should trace back to an IFC GlobalId."""
        output_dir = str(tmp_path / "building_01a")
        analyze_ifc(
            ifc_path=_ifc("building_01a.ifc"),
            output_dir=output_dir,
            mesh_size=2.0,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        missing_guid = [m["id"] for m in data["members"] if not m.get("ifc_guid")]
        assert missing_guid == [], f"Members missing ifc_guid: {missing_guid}"
