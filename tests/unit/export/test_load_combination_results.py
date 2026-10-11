"""Load combinations in results.json."""

import math

import pytest

from ifc_structural_mechanics.domain.load import LoadCombination, LoadGroup, PointLoad
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.result import (
    DisplacementResult,
    ReactionForceResult,
)
from ifc_structural_mechanics.domain.structural_connection import PointConnection
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter


def _displacement(node, case, translation):
    result = DisplacementResult(reference_element=str(node), load_case=case)
    result.set_translations(list(translation))
    return result


def _total(case, forces):
    result = ReactionForceResult(reference_element="TOTAL", load_case=case)
    result.set_forces(list(forces))
    result.set_moments([0.0, 0.0, 0.0])
    return result


def _section(case, position, bending):
    return {
        "element_id": 1,
        "load_case": case,
        "position": position,
        "distance": 2.5 * (1 + position),
        "centre": [2.5 * (1 + position), 0.0, 0.0],
        "N": 0.0,
        "Vf1": 0.0,
        "Vf2": 0.0,
        "T": 0.0,
        "Mf1": bending,
        "Mf2": 0.0,
        "force": [0.0, 0.0, 0.0],
        "moment": [0.0, bending, 0.0],
    }


def _case(case_id, name, with_load=True):
    group = LoadGroup(id=case_id, name=name, is_load_case=True)
    if with_load:
        group.add_load(
            PointLoad(
                id=f"load-{case_id}",
                magnitude=[0.0, 0.0, -1.0],
                direction=[0.0, 0.0, -1.0],
                position=[5.0, 0.0, 0.0],
            )
        )
    return group


def _model():
    """A cantilever with two solved cases and one case that has no load."""
    model = StructuralModel(id="model")
    member = CurveMember(
        id="beam",
        geometry=[[0, 0, 0], [5, 0, 0]],
        material=Material(
            id="m", name="S", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
        ),
        section=Section.create_rectangular_section("s", "r", width=0.2, height=0.3),
    )
    member.analysis_element_ids = [1]
    model.add_member(member)
    support = PointConnection("support", [0.0, 0.0, 0.0])
    support.ifc_guid = "guid-support"
    support.connect_member("beam")
    model.connections.append(support)
    model.support_nodes = {
        "support": {"nodes": {1: (0.0, 0.0, 0.0)}, "dofs": [1, 2, 3]}
    }
    model.support_node_loads = [{}, {}]
    model.applied_load_totals = [[0.0, 0.0, -10.0], [4.0, 0.0, 0.0]]
    for group in (
        _case("id-dead", "Dead"),
        _case("id-live", "Live"),
        _case("id-wind", "Wind", with_load=False),
    ):
        model.add_load_group(group)
    return model


def _parsed():
    return {
        "displacement": [
            _displacement(1, "Dead", (0.0, 0.0, 0.0)),
            _displacement(2, "Dead", (0.0, 0.0, -0.004)),
            _displacement(1, "Live", (0.0, 0.0, 0.0)),
            _displacement(2, "Live", (0.003, 0.0, 0.0)),
        ],
        "stress": [],
        "section_forces": [
            _section("Dead", -1.0, 50.0),
            _section("Dead", 1.0, 0.0),
            _section("Live", -1.0, -20.0),
            _section("Live", 1.0, 30.0),
        ],
        "reaction": [_total("Dead", (0, 0, 10.0)), _total("Live", (-4.0, 0, 0))],
        "support_node_forces": [
            {"load_case": "Dead", "forces": {1: [0.0, 0.0, 10.0]}},
            {"load_case": "Live", "forces": {1: [-4.0, 0.0, 0.0]}},
        ],
    }


def _combination(name, factors, combination_id=None):
    return LoadCombination(
        id=combination_id or f"id-{name}", name=name, load_groups=dict(factors)
    )


def _build(combinations, limits=None):
    return ResultsExporter(
        _model(),
        _parsed(),
        limits=limits,
        element_nodes={1: [1, 2]},
        load_combinations=combinations,
    )._build()


ULS = _combination("ULS", {"id-dead": 1.0, "id-live": 2.0})


class TestListing:
    def test_no_combinations_no_keys(self):
        data = _build([])
        assert "load_combinations" not in data
        assert "by_load_combination" not in data["members"][0]
        assert "by_load_combination" not in data["global_reactions"]

    def test_factors_are_keyed_by_load_case_name(self):
        data = _build([ULS])
        assert data["load_combinations"] == [
            {"name": "ULS", "ifc_guid": "id-ULS", "factors": {"Dead": 1.0, "Live": 2.0}}
        ]
        assert data["load_cases"] == ["Dead", "Live"]

    def test_case_without_loads_is_named_and_adds_nothing(self):
        data = _build([_combination("W", {"id-dead": 1.0, "id-wind": 1.4})])
        (listed,) = data["load_combinations"]
        assert listed["factors"] == {"Dead": 1.0, "Wind": 1.4}
        assert listed["cases_without_loads"] == ["Wind"]
        member = data["members"][0]
        assert member["by_load_combination"]["W"]["max_displacement_m"] == (
            member["by_load_case"]["Dead"]["max_displacement_m"]
        )

    def test_combination_of_cases_without_loads_is_listed_without_results(self):
        data = _build([_combination("W", {"id-wind": 1.4})])
        assert data["load_combinations"][0]["cases_without_loads"] == ["Wind"]
        assert "by_load_combination" not in data["members"][0]

    def test_two_combinations_of_one_name_are_told_apart(self):
        data = _build(
            [
                _combination("ULS", {"id-dead": 1.0}, "first"),
                _combination("ULS", {"id-dead": 2.0}, "second"),
            ]
        )
        names = [c["name"] for c in data["load_combinations"]]
        assert names == ["ULS", "ULS (second)"]
        by_combination = data["members"][0]["by_load_combination"]
        assert by_combination["ULS (second)"]["max_displacement_m"] == pytest.approx(
            2 * by_combination["ULS"]["max_displacement_m"]
        )


class TestMemberResults:
    def test_displacement_is_of_the_summed_vectors(self):
        member = _build([ULS])["members"][0]
        assert member["by_load_combination"]["ULS"][
            "max_displacement_m"
        ] == pytest.approx(math.hypot(0.006, 0.004))

    def test_largest_moment_is_of_the_summed_diagram(self):
        """Dead peaks at the start and Live at the end; 50 + 2 x 30 is no moment."""
        member = _build([ULS])["members"][0]
        forces = member["by_load_combination"]["ULS"]["section_forces"]
        assert forces["max_Mf1_Nm"] == pytest.approx(60.0)
        diagram = member["section_force_diagrams_by_combination"]["ULS"]
        assert diagram["distance_m"] == [0.0, 5.0]
        assert diagram["Mf1_Nm"] == pytest.approx([10.0, 60.0])
        assert set(member["section_force_diagrams"]) == {"Dead", "Live"}

    def test_envelopes_are_kept_apart(self):
        member = _build([ULS, _combination("SLS", {"id-dead": 1.0})])["members"][0]
        assert member["envelope"]["max_displacement_m"] == pytest.approx(0.004)
        assert member["combination_envelope"]["max_displacement_m"] == pytest.approx(
            math.hypot(0.006, 0.004)
        )
        assert member["combination_envelope"]["section_forces"][
            "max_Mf1_Nm"
        ] == pytest.approx(60.0)
        assert member["envelope"]["section_forces"]["max_Mf1_Nm"] == pytest.approx(50.0)

    def test_limit_exceeded_only_by_a_combination_fails_the_member(self):
        limits = {"max_displacement_m": 0.005}
        assert _build([], limits)["members"][0]["status"] == "ok"
        assert _build([ULS], limits)["members"][0]["status"] == "fail"


class TestGlobalResults:
    def test_reactions_and_balance(self):
        reactions = _build([ULS])["global_reactions"]
        values = reactions["by_load_combination"]["ULS"]
        assert (values["fx_N"], values["fz_N"]) == pytest.approx((-8.0, 10.0))
        assert values["applied_load_N"] == pytest.approx([8.0, 0.0, -10.0])
        assert values["imbalance_N"] == pytest.approx(0.0, abs=1e-12)
        assert set(reactions["by_load_case"]) == {"Dead", "Live"}

    def test_displacements(self):
        displacements = _build([ULS])["global_displacements"]
        assert displacements["by_load_combination"]["ULS"][
            "max_displacement_m"
        ] == pytest.approx(math.hypot(0.006, 0.004))
        assert displacements["envelope"]["max_displacement_m"] == pytest.approx(0.004)

    def test_support_reactions(self):
        (support,) = _build([ULS])["supports"]
        values = support["by_load_combination"]["ULS"]
        assert (values["fx_N"], values["fz_N"]) == pytest.approx((-8.0, 10.0))
        assert values["resultant_N"] == pytest.approx(math.hypot(8.0, 10.0))
        assert set(support["by_load_case"]) == {"Dead", "Live"}
