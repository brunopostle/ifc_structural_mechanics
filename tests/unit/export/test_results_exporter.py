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
        result = exporter._member_section_forces(elem_ids)
        # No records passed to exporter — use direct call with injected data
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
    def test_simple_axial_only(self):
        sec = _rect_section(w=0.2, h=0.3)
        member = _curve_member(sec)
        exporter = _make_exporter(member)
        sf_by_lc = {"Dead": {"max_N_N": 1000.0, "max_Mf1_Nm": 0.0, "max_Mf2_Nm": 0.0}}
        result = exporter._member_utilisation(sf_by_lc, member)
        # σ = N/A = 1000 / (0.06) ≈ 16667 Pa
        assert "Dead" in result
        expected_sigma = 1000.0 / sec.area
        assert result["Dead"]["max_bending_stress_Pa"] == pytest.approx(
            expected_sigma, rel=1e-4
        )

    def test_bending_contribution(self):
        sec = _rect_section(w=0.2, h=0.3)
        member = _curve_member(sec)
        exporter = _make_exporter(member)
        Mf1 = 10000.0
        sf_by_lc = {"Dead": {"max_N_N": 0.0, "max_Mf1_Nm": Mf1, "max_Mf2_Nm": 0.0}}
        result = exporter._member_utilisation(sf_by_lc, member)
        y_max = sec.dimensions["height"] / 2
        expected_sigma = Mf1 / sec.moment_of_inertia_y * y_max
        assert result["Dead"]["max_bending_stress_Pa"] == pytest.approx(
            expected_sigma, rel=1e-4
        )

    def test_no_section_returns_empty(self):
        member = MagicMock()
        member.section = None
        exporter = _make_exporter()
        result = exporter._member_utilisation({"Dead": {}}, member)
        assert result == {}

    def test_unknown_section_type_returns_empty(self):
        """Section with unknown type → get_extreme_fibre_distances returns (None, None)."""
        sec = Section(
            id="x1",
            name="X",
            section_type="custom_unknown",
            area=0.01,
            dimensions={"width": 0.1},
        )
        member = _curve_member(sec)
        exporter = _make_exporter(member)
        sf = {"Dead": {"max_N_N": 1000.0, "max_Mf1_Nm": 5000.0, "max_Mf2_Nm": 0.0}}
        result = exporter._member_utilisation(sf, member)
        assert result == {}

    def test_multiple_load_cases(self):
        sec = _rect_section()
        member = _curve_member(sec)
        exporter = _make_exporter(member)
        sf_by_lc = {
            "Dead": {"max_N_N": 500.0, "max_Mf1_Nm": 0.0, "max_Mf2_Nm": 0.0},
            "Live": {"max_N_N": 800.0, "max_Mf1_Nm": 0.0, "max_Mf2_Nm": 0.0},
        }
        result = exporter._member_utilisation(sf_by_lc, member)
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
        assert loaded["schema_version"] == "1.0"
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
