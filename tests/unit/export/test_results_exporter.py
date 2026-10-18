"""Tests for ResultsExporter.

Covers per-member section force grouping, utilisation ratio computation,
and the global displacement/reaction builders.
"""

import json
from unittest.mock import MagicMock

import pytest

from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter
from ifc_structural_mechanics.utils.error_handling import ResultProcessingError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _steel():
    return Material(
        id="mat1",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )


def _rect_section(w=0.2, h=0.3):
    return Section.create_rectangular_section("s1", "Rect", width=w, height=h)


def _i_section():
    b, h, tw, tf = 0.2, 0.4, 0.01, 0.015
    area = b * h - (b - tw) * (h - 2 * tf)
    return Section(
        id="i1",
        name="I",
        section_type="i",
        area=area,
        dimensions={
            "width": b,
            "height": h,
            "web_thickness": tw,
            "flange_thickness": tf,
        },
    )


def _curve_member(sec):
    return CurveMember(
        id="m1",
        geometry=[[0, 0, 0], [5, 0, 0]],
        material=_steel(),
        section=sec,
    )


def _make_exporter(member=None, parsed_results=None, limits=None):
    model = StructuralModel(id="test")
    if member is not None:
        model.add_member(member)
    exporter = ResultsExporter(
        domain_model=model,
        parsed_results=parsed_results
        or {"displacement": [], "stress": [], "reaction": [], "section_forces": []},
        limits=limits,
    )
    return exporter


def _sf_record(element_id, load_case, N=0.0, T=0.0, Mf1=0.0, Mf2=0.0, Vf1=0.0, Vf2=0.0):
    return {
        "element_id": element_id,
        "load_case": load_case,
        "N": N,
        "T": T,
        "Mf1": Mf1,
        "Mf2": Mf2,
        "Vf1": Vf1,
        "Vf2": Vf2,
    }


# ---------------------------------------------------------------------------
# _member_section_forces
# ---------------------------------------------------------------------------


class TestMemberSectionForces:
    def test_returns_max_per_load_case(self):
        exporter = _make_exporter()
        elem_ids = {1, 2}
        records = [
            _sf_record(1, "Dead", N=1000.0, Mf1=5000.0),
            _sf_record(2, "Dead", N=1500.0, Mf1=3000.0),
        ]
        exporter.parsed_results["section_forces"] = records
        result = exporter._member_section_forces(elem_ids)
        assert "Dead" in result
        assert result["Dead"]["max_N_N"] == pytest.approx(1500.0)
        assert result["Dead"]["max_Mf1_Nm"] == pytest.approx(5000.0)

    def test_filters_by_element_id(self):
        exporter = _make_exporter()
        exporter.parsed_results["section_forces"] = [
            _sf_record(1, "Dead", N=1000.0),
            _sf_record(99, "Dead", N=9999.0),  # not in elem_ids
        ]
        result = exporter._member_section_forces({1})
        assert result["Dead"]["max_N_N"] == pytest.approx(1000.0)

    def test_skips_non_dict_records(self):
        exporter = _make_exporter()
        exporter.parsed_results["section_forces"] = ["not a dict", None, 42]
        result = exporter._member_section_forces({1})
        assert result == {}

    def test_multiple_load_cases(self):
        exporter = _make_exporter()
        exporter.parsed_results["section_forces"] = [
            _sf_record(1, "Dead", Mf1=1000.0),
            _sf_record(1, "Live", Mf1=2000.0),
        ]
        result = exporter._member_section_forces({1})
        assert set(result.keys()) == {"Dead", "Live"}
        assert result["Live"]["max_Mf1_Nm"] == pytest.approx(2000.0)

    def test_empty_elem_ids_returns_empty(self):
        exporter = _make_exporter()
        exporter.parsed_results["section_forces"] = [_sf_record(1, "Dead", N=1000.0)]
        result = exporter._member_section_forces(set())
        assert result == {}


# ---------------------------------------------------------------------------
# _member_utilisation
# ---------------------------------------------------------------------------


class TestMemberUtilisation:
    """Normal stress in the member's real section, cross-section by cross-section."""

    def _stress(self, member, records, elem_ids=frozenset({1, 2})):
        exporter = _make_exporter(member)
        exporter.parsed_results["section_forces"] = records
        return exporter._member_utilisation(set(elem_ids), member)

    def test_simple_axial_only(self):
        sec = _rect_section(w=0.2, h=0.3)
        result = self._stress(_curve_member(sec), [_sf_record(1, "Dead", N=-1000.0)])
        assert result["Dead"]["max_normal_stress_Pa"] == pytest.approx(
            1000.0 / sec.area
        )

    def test_bending_contribution(self):
        sec = _rect_section(w=0.2, h=0.3)
        result = self._stress(_curve_member(sec), [_sf_record(1, "Dead", Mf1=1.0e4)])
        expected = 1.0e4 / sec.moment_of_inertia_y * sec.dimensions["height"] / 2
        assert result["Dead"]["max_normal_stress_Pa"] == pytest.approx(expected)

    def test_forces_are_combined_where_they_occur(self):
        """The largest N and the largest M are at different cross-sections."""
        sec = _rect_section(w=0.2, h=0.3)
        records = [
            _sf_record(1, "Dead", N=6000.0, Mf1=0.0),
            _sf_record(2, "Dead", N=0.0, Mf1=300.0),
        ]
        result = self._stress(_curve_member(sec), records)
        assert result["Dead"]["max_normal_stress_Pa"] == pytest.approx(
            max(6000.0 / sec.area, 300.0 / sec.moment_of_inertia_y * 0.15)
        )

    def test_real_section_is_used_for_an_i_beam(self):
        sec = _i_section()
        sec.moment_of_inertia_y = 2.0e-4
        sec.moment_of_inertia_z = 2.0e-5
        result = self._stress(_curve_member(sec), [_sf_record(1, "Dead", Mf1=1.0e4)])
        assert result["Dead"]["max_normal_stress_Pa"] == pytest.approx(
            1.0e4 / 2.0e-4 * 0.2
        )

    def test_utilisation_needs_a_yield_strength(self):
        sec = _rect_section(w=0.2, h=0.3)
        member = _curve_member(sec)
        records = [_sf_record(1, "Dead", N=1.2e6)]
        assert "utilisation_ratio" not in self._stress(member, records)["Dead"]

        member.material.yield_strength = 250e6
        result = self._stress(member, records)
        assert result["Dead"]["utilisation_ratio"] == pytest.approx(
            1.2e6 / sec.area / 250e6
        )

    def test_other_members_elements_are_ignored(self):
        sec = _rect_section()
        records = [_sf_record(99, "Dead", N=1.0e9), _sf_record(1, "Dead", N=600.0)]
        result = self._stress(_curve_member(sec), records)
        assert result["Dead"]["max_normal_stress_Pa"] == pytest.approx(600.0 / sec.area)

    def test_no_section_returns_empty(self):
        member = MagicMock()
        member.section = None
        exporter = _make_exporter()
        assert exporter._member_utilisation({1}, member) == {}

    def test_unknown_section_type_returns_empty(self):
        """Section with unknown type → get_extreme_fibre_distances returns (None, None)."""
        sec = Section(
            id="x1",
            name="X",
            section_type="custom_unknown",
            area=0.01,
            dimensions={"width": 0.1},
        )
        assert self._stress(_curve_member(sec), [_sf_record(1, "Dead", N=1e3)]) == {}

    def test_multiple_load_cases(self):
        records = [_sf_record(1, "Dead", N=500.0), _sf_record(1, "Live", N=800.0)]
        result = self._stress(_curve_member(_rect_section()), records)
        assert set(result.keys()) == {"Dead", "Live"}


# ---------------------------------------------------------------------------
# _status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_ok_when_no_limits(self):
        exporter = _make_exporter()
        assert exporter._status({"max_displacement_m": 1.0}) == "ok"

    def test_fail_when_limit_exceeded(self):
        exporter = _make_exporter(limits={"max_displacement_m": 0.01})
        assert exporter._status({"max_displacement_m": 0.02}) == "fail"

    def test_ok_when_within_limits(self):
        exporter = _make_exporter(limits={"max_displacement_m": 0.05})
        assert exporter._status({"max_displacement_m": 0.02}) == "ok"

    def test_missing_metric_counts_as_zero(self):
        exporter = _make_exporter(limits={"max_displacement_m": 0.01})
        assert exporter._status({}) == "ok"


# ---------------------------------------------------------------------------
# export() writes valid JSON
# ---------------------------------------------------------------------------


class TestExportWritesJson:
    def test_export_creates_file(self, tmp_path):
        exporter = _make_exporter()
        out = str(tmp_path / "results.json")
        exporter.export(out)
        assert (tmp_path / "results.json").exists()
        with open(out) as fh:
            loaded = json.load(fh)
        assert loaded["schema_version"] == ResultsExporter.SCHEMA_VERSION
        assert "units" in loaded

    def test_export_returns_dict(self, tmp_path):
        exporter = _make_exporter()
        data = exporter.export(str(tmp_path / "r.json"))
        assert isinstance(data, dict)

    def test_export_member_list(self, tmp_path):
        member = _curve_member(_rect_section())
        exporter = _make_exporter(member)
        data = exporter.export(str(tmp_path / "r.json"))
        assert len(data["members"]) == 1
        assert data["members"][0]["id"] == "m1"


# ---------------------------------------------------------------------------
# Schema structure validation (g6y: stabilise JSON schema)
# ---------------------------------------------------------------------------


class TestSchemaStructure:
    """Validate that the exported JSON conforms to the documented schema.

    These tests act as a contract — if the schema changes, bump
    ResultsExporter.SCHEMA_VERSION and update these tests intentionally.
    """

    CURRENT_SCHEMA_VERSION = "1.10"

    _REQUIRED_UNIT_KEYS = {"length", "force", "moment", "stress", "displacement"}
    _REQUIRED_MEMBER_KEYS = {"ifc_guid", "id", "type", "status"}
    _VALID_STATUSES = {"ok", "warning", "fail"}

    @pytest.fixture()
    def data(self, tmp_path):
        member = _curve_member(_rect_section())
        exporter = _make_exporter(member)
        return exporter.export(str(tmp_path / "schema_check.json"))

    def test_schema_version_present_and_current(self, data):
        assert data["schema_version"] == self.CURRENT_SCHEMA_VERSION

    def test_units_block_has_all_keys(self, data):
        assert self._REQUIRED_UNIT_KEYS <= set(data["units"])

    def test_units_values_are_strings(self, data):
        for key, val in data["units"].items():
            assert isinstance(val, str), f"units[{key!r}] should be a string"

    def test_model_block_has_id_and_name(self, data):
        assert "id" in data["model"]
        assert "name" in data["model"]

    def test_load_cases_is_list(self, data):
        assert isinstance(data["load_cases"], list)

    def test_members_is_list(self, data):
        assert isinstance(data["members"], list)

    def test_each_member_has_required_keys(self, data):
        for m in data["members"]:
            missing = self._REQUIRED_MEMBER_KEYS - set(m)
            assert not missing, f"Member {m.get('id')} missing keys: {missing}"

    def test_member_status_is_valid(self, data):
        for m in data["members"]:
            assert m["status"] in self._VALID_STATUSES

    def test_top_level_keys_present(self, data):
        required = {
            "schema_version",
            "units",
            "model",
            "load_cases",
            "members",
            "global_displacements",
            "global_reactions",
        }
        assert required <= set(data)


class TestBuckling:
    """A buckling analysis reports its factors, or fails (`aiz.73`)."""

    def _exporter(self, factors):
        model = StructuralModel(id="test")
        return ResultsExporter(
            domain_model=model,
            parsed_results={"displacement": [], "buckling": factors},
            analysis_type="linear_buckling",
        )

    def test_factors_are_listed_lowest_mode_first(self):
        data = self._exporter([(2, 7.5), (1, 3.25)])._build()
        assert data["analysis_type"] == "linear_buckling"
        assert data["buckling"]["modes"] == [
            {"mode": 1, "factor": 3.25},
            {"mode": 2, "factor": 7.5},
        ]

    def test_no_factors_is_an_error(self):
        with pytest.raises(ResultProcessingError, match="no buckling factors"):
            self._exporter([])._build()

    def test_static_analysis_has_no_buckling(self):
        data = _make_exporter()._build()
        assert data["analysis_type"] == "linear_static"
        assert "buckling" not in data


class TestGlobalDisplacementsLeaveOutLinks:
    """Links and arms belong to no member and are not part of the structure.

    Their expanded faces are up to 0.25 m from their axis; in building_01 one
    of them set the largest displacement of the model (aiz.92).
    """

    def _exporter(self):
        from ifc_structural_mechanics.domain.result import DisplacementResult

        model = StructuralModel(id="test")
        model.add_member(_curve_member(_rect_section()))
        model.set_analysis_elements("m1", [1])
        results = []
        for node, tz in ((1, 0.0), (2, -0.001), (3, -0.005)):
            result = DisplacementResult(reference_element=str(node), load_case="LC")
            result.set_translations([0.0, 0.0, tz])
            results.append(result)
        return ResultsExporter(
            domain_model=model,
            parsed_results={
                "displacement": results,
                "stress": [],
                "reaction": [],
                "section_forces": [],
            },
            # Element 7 is a link from the member's node 2 to its tip, node 3
            element_nodes={1: [1, 2], 7: [2, 3]},
        )

    def test_the_tip_of_a_link_is_left_out(self):
        envelope = self._exporter()._global_displacements()["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(0.001)

    def test_a_node_shared_with_a_member_is_kept(self):
        assert self._exporter()._link_nodes() == {3}


class TestSchemaDocumentation:
    """docs/results_schema.md is the schema outsiders read (94g.11)."""

    @staticmethod
    def _doc() -> str:
        with open("docs/results_schema.md") as fh:
            return fh.read()

    def test_doc_describes_this_version(self):
        version = ResultsExporter.SCHEMA_VERSION
        doc = self._doc()
        assert f"describes schema **{version}**" in doc
        assert f'"schema_version": "{version}"' in doc

    def test_changelog_has_a_line_for_this_version(self):
        assert f"\n| {ResultsExporter.SCHEMA_VERSION} | " in self._doc()

    def test_example_has_this_version(self):
        with open("docs/examples/beam_01_results.json") as fh:
            example = json.load(fh)
        assert example["schema_version"] == ResultsExporter.SCHEMA_VERSION

    def test_limits_are_in_the_file(self):
        model = StructuralModel(id="m", name="m")
        exporter = ResultsExporter(model, {}, limits={"max_displacement_m": 0.02})
        assert exporter.build()["limits"] == {"max_displacement_m": 0.02}
