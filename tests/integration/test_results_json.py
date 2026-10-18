"""Integration tests: results.json content produced by ResultsExporter.

Asserts that analyze_ifc() writes a well-formed results.json keyed to IFC
GlobalIds with correct structure, plausible displacement values, and the
right number of members for each example model.

Fast models (beam_01, portal_01, slab_01) run as part of the normal suite.
building_02 is marked slow.
"""

import hashlib
import json
import logging
import os
import re
import shutil

import pytest

from ifc_structural_mechanics import __version__
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
    assert data.get("schema_version") == "1.12"
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
        """beam_01 max displacement should be in (0, 0.01] m (by hand: 0.43 mm)."""
        output_dir = str(tmp_path / "beam_01")
        analyze_ifc(ifc_path=_ifc("beam_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        global_disp = data.get("global_displacements", {})
        envelope = global_disp.get("envelope", {})
        max_disp = envelope.get("max_displacement_m", None)
        assert (
            max_disp is not None
        ), "global_displacements.envelope.max_displacement_m missing"
        logger.info(f"beam_01 max displacement: {max_disp * 1000:.3f} mm")
        assert max_disp > 0, "Zero displacement — analysis may not have run"
        assert (
            max_disp < 0.01
        ), f"Displacement {max_disp * 1000:.2f} mm unexpectedly large"

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

    def test_run_and_warnings_recorded(self, tmp_path):
        """A report has to state how the results were made and every warning
        (94g.11); a viewer goes by the input's hash and the warnings' GlobalIds."""
        output_dir = str(tmp_path / "beam_01")
        path = _ifc("beam_01.ifc")
        result = analyze_ifc(ifc_path=path, output_dir=output_dir, mesh_size=0.5)
        data = _load_results_json(output_dir)
        with open(path, "rb") as fh:
            sha256 = hashlib.sha256(fh.read()).hexdigest()
        run = data["run"]
        assert run["input_file"] == {"name": "beam_01.ifc", "sha256": sha256}
        assert run["library"]["version"] == __version__
        assert re.fullmatch(r"\d+\.\d+.*", run["solver"]["version"])
        assert run["settings"] == {
            "analysis_type": "linear_static",
            "mesh_size_m": 0.5,
            "element_order": 2,
            "strict_connections": False,
            "open_sections": "equivalent",
            "gravity": False,
        }
        assert data["limits"] == {}
        assert data["warnings"] == result["warnings"]
        beam = data["members"][0]["ifc_guid"]
        rectangles = [w for w in data["warnings"] if w["code"] == "W-SEC-001"]
        assert rectangles and beam in rectangles[0]["ifc_guids"]

    def test_example_in_the_docs_has_this_shape(self, tmp_path):
        """docs/examples/beam_01_results.json is what consumers develop
        against: it must have every key a fresh run has, and no other."""
        output_dir = str(tmp_path / "beam_01")
        analyze_ifc(ifc_path=_ifc("beam_01.ifc"), output_dir=output_dir, mesh_size=0.5)
        with open(os.path.join("docs", "examples", "beam_01_results.json")) as fh:
            example = json.load(fh)
        assert _keys(example) == _keys(_load_results_json(output_dir)), (
            "Regenerate docs/examples/beam_01_results.json "
            "(see docs/results_schema.md)"
        )


def _keys(value, path: str = "") -> set:
    """Every key path in a JSON value; list items are merged."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(f"{path}.{key}")
            found |= _keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            found |= _keys(item, f"{path}[]")
    return found


# ---------------------------------------------------------------------------
# portal_01 — portal frame with horizontal load
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestPortal01ResultsJson:
    """results.json checks for portal_01.ifc."""

    def test_schema_valid(self, tmp_path):
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(
            ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5
        )
        data = _load_results_json(output_dir)
        _assert_schema(data)

    def test_multiple_members(self, tmp_path):
        """portal_01 has at least 3 members (2 columns + 1 beam)."""
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(
            ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5
        )
        data = _load_results_json(output_dir)
        assert (
            len(data["members"]) >= 3
        ), f"Expected >= 3 members, got {len(data['members'])}"

    def test_displacement_plausible(self, tmp_path):
        """portal_01 max displacement should be in (0, 0.1] m (analytical: ~0.55 mm)."""
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(
            ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5
        )
        data = _load_results_json(output_dir)
        max_disp = data["global_displacements"]["envelope"]["max_displacement_m"]
        logger.info(f"portal_01 max displacement: {max_disp * 1000:.3f} mm")
        assert 0 < max_disp < 0.1

    def test_member_types_curve(self, tmp_path):
        """portal_01 members should all be curve type."""
        output_dir = str(tmp_path / "portal_01")
        analyze_ifc(
            ifc_path=_ifc("portal_01.ifc"), output_dir=output_dir, mesh_size=0.5
        )
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
            ifc_path=_ifc("slab_01.ifc"),
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        _assert_schema(data)

    def test_member_type_surface(self, tmp_path):
        """slab_01 members should include surface type."""
        output_dir = str(tmp_path / "slab_01")
        analyze_ifc(
            ifc_path=_ifc("slab_01.ifc"),
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        types = {m["type"] for m in data["members"]}
        assert "surface" in types, f"No surface members found; types: {types}"

    def test_displacement_plausible(self, tmp_path):
        """slab_01 max displacement should be in (0, 0.01] m (analytical: ~0.39 mm)."""
        output_dir = str(tmp_path / "slab_01")
        analyze_ifc(
            ifc_path=_ifc("slab_01.ifc"),
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        max_disp = data["global_displacements"]["envelope"]["max_displacement_m"]
        logger.info(f"slab_01 max displacement: {max_disp * 1000:.3f} mm")
        assert 0 < max_disp < 0.01

    def test_member_envelope_present(self, tmp_path):
        """Each slab_01 member should have an envelope with displacement data."""
        output_dir = str(tmp_path / "slab_01")
        analyze_ifc(
            ifc_path=_ifc("slab_01.ifc"),
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )
        data = _load_results_json(output_dir)
        members_with_envelope = [m for m in data["members"] if m.get("envelope")]
        assert (
            len(members_with_envelope) > 0
        ), "No members have displacement envelope data"


# ---------------------------------------------------------------------------
# building_02 — multi-storey building under self-weight (slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestBuilding02ResultsJson:
    """results.json checks for building_02.ifc."""

    def test_schema_valid(self, building_02_run):
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        _assert_schema(data)

    def test_many_members(self, building_02_run):
        """building_02 has many structural members."""
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        logger.info(f"building_02 member count: {len(data['members'])}")
        assert len(data["members"]) >= 10

    def test_displacement_plausible(self, building_02_run):
        """building_02 max displacement should be in (0, 1] m."""
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        max_disp = data["global_displacements"]["envelope"]["max_displacement_m"]
        logger.info(f"building_02 max displacement: {max_disp * 1000:.1f} mm")
        assert (
            0 < max_disp < 1.0
        ), f"Displacement {max_disp:.3f} m — possible mesh disconnectivity regression"

    def test_every_member_has_results_for_every_load_case(self, building_02_run):
        """Beams and columns as well as slabs and walls."""
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        cases = set(data["load_cases"])
        assert cases == {"Dead", "Live", "Extra_dead"}
        incomplete = [
            m["id"]
            for m in data["members"]
            if not all(
                "max_displacement_m" in m.get("by_load_case", {}).get(case, {})
                for case in cases
            )
        ]
        assert incomplete == []

    def test_every_beam_and_column_has_section_forces(self, building_02_run):
        """And a normal stress from them, for every load case."""
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        curves = [m for m in data["members"] if m["type"] == "curve"]
        assert len(curves) == 640
        for member in curves:
            for case in data["load_cases"]:
                entry = member["by_load_case"][case]
                assert set(entry["section_forces"]) == {
                    "max_N_N",
                    "max_T_Nm",
                    "max_Mf1_Nm",
                    "max_Mf2_Nm",
                    "max_Vf1_N",
                    "max_Vf2_N",
                    "max_tension_N",
                    "max_compression_N",
                }
                assert entry["max_normal_stress_Pa"] >= 0

    def test_every_beam_and_column_has_force_diagrams(self, building_02_run):
        """Signed forces along the member for each load case, and their axes."""
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        for member in (m for m in data["members"] if m["type"] == "curve"):
            assert set(member["section_axes"]) == {"x", "1", "2"}
            assert set(member["section_force_diagrams"]) == set(data["load_cases"])
            for diagram in member["section_force_diagrams"].values():
                distances = diagram["distance_m"]
                assert len(distances) >= 3
                assert distances == sorted(distances)
                assert len({len(values) for values in diagram.values()}) == 1

    def test_results_file_stays_a_reasonable_size(self, building_02_run):
        """Under 4 MB for each load case and combination (2.3 MB as measured).

        The file's 17 combinations each have what a load case has, so its
        size goes with their number.
        """
        _, output_dir = building_02_run
        size = os.path.getsize(os.path.join(output_dir, "results.json"))
        data = _load_results_json(output_dir)
        states = len(data["load_cases"]) + len(data["load_combinations"])
        assert states == 20
        assert size < 4e6 * states, f"results.json is {size / 1e6:.1f} MB"

    def test_combinations_are_the_sums_of_their_cases(self, building_02_run):
        """Reactions add up exactly; 1.4D+1.6L is the largest of the file's.

        ``Dead`` is the weight of the members and nothing else, and it is in
        the sum.
        """
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        reactions = data["global_reactions"]
        (listed,) = [c for c in data["load_combinations"] if c["name"] == "1.4D+1.6L"]
        assert listed["factors"] == {"Dead": 1.4, "Extra_dead": 1.4, "Live": 1.6}
        assert "cases_without_loads" not in listed
        cases = reactions["by_load_case"]
        assert cases["Dead"]["fz_N"] > cases["Extra_dead"]["fz_N"]
        combined = reactions["by_load_combination"]["1.4D+1.6L"]
        assert combined["fz_N"] == pytest.approx(
            1.4 * (cases["Dead"]["fz_N"] + cases["Extra_dead"]["fz_N"])
            + 1.6 * cases["Live"]["fz_N"],
            rel=1e-9,
        )
        assert combined["imbalance_N"] < 1e-6 * combined["fz_N"]
        # 51 supports: their moments about the origin balance the loads' too
        for values in list(cases.values()) + [combined]:
            turning = max(abs(v) for v in values["applied_moment_Nm"])
            assert turning > values["fz_N"]
            assert values["moment_imbalance_Nm"] < 1e-6 * turning
        largest = max(
            values["max_displacement_m"]
            for values in data["global_displacements"]["by_load_combination"].values()
        )
        assert (
            data["global_displacements"]["by_load_combination"]["1.4D+1.6L"][
                "max_displacement_m"
            ]
            == largest
        )
        members = [m for m in data["members"] if "by_load_combination" in m]
        assert len(members) == len(data["members"])
        assert all(len(m["by_load_combination"]) == 17 for m in members)

    def test_surface_members_have_no_section_forces(self, building_02_run):
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        surfaces = [m for m in data["members"] if m["type"] == "surface"]
        assert not any("section_forces" in m["envelope"] for m in surfaces)

    def test_largest_member_displacement_is_the_global_one(self, building_02_run):
        """Each load case's maximum is found on some member, and on no more."""
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        for case, summary in data["global_displacements"]["by_load_case"].items():
            largest = max(
                m["by_load_case"][case]["max_displacement_m"] for m in data["members"]
            )
            assert largest == pytest.approx(summary["max_displacement_m"], rel=1e-6)

    def test_live_maximum_is_on_a_heavily_loaded_ground_slab(self, building_02_run):
        """The 16 kPa slabs at z = 3 m move most under Live, about 26 mm.

        Per-member values used to be attributed through guessed node numbers
        and put this maximum on a slab thirty metres higher up.
        """
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        worst = max(
            data["members"],
            key=lambda m: m["by_load_case"]["Live"]["max_displacement_m"],
        )
        assert worst["type"] == "surface"
        assert worst["id"] in ("3Pv5xW9inFXwJXWOhUEqxn", "2v2zbtMavCUv4$UquJwvIb")
        assert worst["by_load_case"]["Live"]["max_displacement_m"] == pytest.approx(
            0.0258, rel=0.1
        )

    def test_all_members_have_guid(self, building_02_run):
        """Every member in building_02 should trace back to an IFC GlobalId."""
        _, output_dir = building_02_run
        data = _load_results_json(output_dir)
        missing_guid = [m["id"] for m in data["members"] if not m.get("ifc_guid")]
        assert missing_guid == [], f"Members missing ifc_guid: {missing_guid}"
