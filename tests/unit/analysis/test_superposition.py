"""A load combination's results are the factored sum of its load cases'."""

import math

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.superposition import (
    STRESS_COMPONENTS,
    combine_results,
)
from ifc_structural_mechanics.domain.result import (
    DisplacementResult,
    ReactionForceResult,
    StressResult,
)
from ifc_structural_mechanics.utils.error_handling import ResultProcessingError


def _displacement(node, case, translation):
    result = DisplacementResult(reference_element=str(node), load_case=case)
    result.set_translations(list(translation))
    return result


def _stress(node, case, components):
    result = StressResult(reference_element=str(node), load_case=case)
    for key, value in zip(STRESS_COMPONENTS, components):
        result.add_value(key, value)
    return result


def _total(case, forces):
    result = ReactionForceResult(reference_element="TOTAL", load_case=case)
    result.set_forces(list(forces))
    result.set_moments([0.0, 0.0, 0.0])
    return result


def _section(case, element, position, bending, force):
    return {
        "element_id": element,
        "load_case": case,
        "position": position,
        "distance": 1.0 + position,
        "centre": [1.0 + position, 0.0, 0.0],
        "N": 0.0,
        "Vf1": force[2],
        "Vf2": 0.0,
        "T": 0.0,
        "Mf1": bending,
        "Mf2": 0.0,
        "force": list(force),
        "moment": [0.0, bending, 0.0],
    }


def _results():
    """Two nodes, one element with two cross-sections, cases Dead and Live."""
    return {
        "displacement": [
            _displacement(1, "Dead", (0.0, 0.0, -1.0)),
            _displacement(2, "Dead", (0.0, 0.0, -2.0)),
            _displacement(1, "Live", (3.0, 0.0, 0.0)),
            _displacement(2, "Live", (4.0, 0.0, 1.0)),
        ],
        "stress": [
            _stress(1, "Dead", (100.0, 0, 0, 0, 0, 0)),
            _stress(2, "Dead", (50.0, 0, 0, 0, 0, 0)),
            _stress(1, "Live", (0, 0, 0, 30.0, 0, 0)),
            _stress(2, "Live", (-50.0, 0, 0, 0, 0, 0)),
        ],
        "section_forces": [
            _section("Dead", 7, -1.0, 10.0, (0.0, 0.0, 5.0)),
            _section("Dead", 7, 1.0, 20.0, (0.0, 0.0, 5.0)),
            _section("Live", 7, -1.0, -4.0, (1.0, 0.0, 2.0)),
            _section("Live", 7, 1.0, 6.0, (1.0, 0.0, -2.0)),
        ],
        "reaction": [_total("Dead", (0, 0, 10.0)), _total("Live", (-2.0, 0, 4.0))],
        "support_node_forces": [
            {"load_case": "Dead", "forces": {1: [0.0, 0.0, 10.0]}},
            {"load_case": "Live", "forces": {1: [-2.0, 0.0, 4.0]}},
        ],
    }


FACTORS = {"Dead": 1.35, "Live": 1.5}


class TestLinearResults:
    def test_displacements_are_added_as_vectors(self):
        combined, _, _, _ = combine_results(_results(), FACTORS, "ULS")
        by_node = {r.reference_element: r for r in combined["displacement"]}
        assert by_node["2"].get_translations() == pytest.approx(
            [1.5 * 4.0, 0.0, 1.35 * -2.0 + 1.5 * 1.0]
        )
        assert {r.metadata["load_case"] for r in combined["displacement"]} == {"ULS"}
        # The size of a sum is not the sum of the sizes
        assert by_node["1"].get_magnitude() == pytest.approx(math.hypot(4.5, 1.35))

    def test_stress_components_are_added_and_von_mises_follows(self):
        combined, _, _, _ = combine_results(_results(), FACTORS, "ULS")
        by_node = {r.reference_element: r for r in combined["stress"]}
        assert by_node["1"].values["sxx"] == pytest.approx(135.0)
        assert by_node["1"].values["sxy"] == pytest.approx(45.0)
        assert by_node["1"].get_von_mises_stress() == pytest.approx(
            math.sqrt(135.0**2 + 3 * 45.0**2)
        )
        # Opposite stresses cancel; their von Mises values would not
        assert by_node["2"].get_von_mises_stress() == pytest.approx(
            abs(1.35 * 50.0 - 1.5 * 50.0)
        )

    def test_section_forces_are_added_at_each_cross_section(self):
        combined, _, _, _ = combine_results(_results(), FACTORS, "ULS")
        records = sorted(combined["section_forces"], key=lambda r: r["position"])
        assert [r["Mf1"] for r in records] == pytest.approx(
            [1.35 * 10 - 1.5 * 4, 1.35 * 20 + 1.5 * 6]
        )
        assert [r["Vf1"] for r in records] == pytest.approx(
            [1.35 * 5 + 1.5 * 2, 1.35 * 5 - 1.5 * 2]
        )
        assert np.allclose(records[0]["force"], [1.5, 0.0, 1.35 * 5 + 1.5 * 2])
        assert np.allclose(records[0]["moment"], [0.0, 1.35 * 10 - 1.5 * 4, 0.0])
        for record in records:
            assert record["load_case"] == "ULS"
            assert record["element_id"] == 7
            assert record["distance"] == 1.0 + record["position"]

    def test_reactions_and_what_the_steps_applied(self):
        combined, node_loads, totals, _ = combine_results(
            _results(),
            FACTORS,
            "ULS",
            support_node_loads=[{1: [0.0, 0.0, -1.0]}, {}],
            applied_load_totals=[[0.0, 0.0, -10.0], [2.0, 0.0, -4.0]],
        )
        (total,) = combined["reaction"]
        assert total.get_forces() == pytest.approx([-3.0, 0.0, 19.5])
        (step,) = combined["support_node_forces"]
        assert step["load_case"] == "ULS"
        assert step["forces"][1] == pytest.approx([-3.0, 0.0, 19.5])
        assert node_loads == [{1: pytest.approx([0.0, 0.0, -1.35])}]
        assert totals == [pytest.approx([3.0, 0.0, -19.5])]

    def test_moment_of_what_the_steps_applied(self):
        *_, moments = combine_results(
            _results(),
            FACTORS,
            "ULS",
            applied_load_moments=[[0.0, 10.0, 0.0], [2.0, 0.0, -4.0]],
        )
        assert moments == [pytest.approx([3.0, 13.5, -6.0])]

    def test_no_moment_when_a_case_has_none(self):
        *_, moments = combine_results(
            _results(), FACTORS, "ULS", applied_load_moments=[[0.0, 10.0, 0.0], None]
        )
        assert moments == []

    def test_moments_at_support_nodes(self):
        results = _results()
        results["support_node_moments"] = [
            {"load_case": "Dead", "moments": {1: [0.0, 10.0, 0.0], 2: [1.0, 0.0, 0.0]}},
            {"load_case": "Live", "moments": {1: [4.0, -2.0, 0.0]}},
        ]

        combined, _, _, _ = combine_results(results, FACTORS, "ULS")

        (step,) = combined["support_node_moments"]
        assert step["load_case"] == "ULS"
        # Node 2 has no moment in one of the cases, so it has none here
        assert list(step["moments"]) == [1]
        assert step["moments"][1] == pytest.approx([6.0, 10.5, 0.0])

    def test_no_moments_when_a_case_has_none(self):
        results = _results()
        results["support_node_moments"] = [
            {"load_case": "Dead", "moments": {1: [0.0, 10.0, 0.0]}}
        ]

        combined, _, _, _ = combine_results(results, FACTORS, "ULS")

        assert combined["support_node_moments"] == []

    def test_negative_factor(self):
        combined, _, _, _ = combine_results(
            _results(), {"Dead": 1.0, "Live": -1.0}, "difference"
        )
        by_node = {r.reference_element: r for r in combined["displacement"]}
        assert by_node["1"].get_translations() == pytest.approx([-3.0, 0.0, -1.0])

    def test_one_case_alone(self):
        combined, _, _, _ = combine_results(_results(), {"Dead": 1.5}, "DCon1")
        by_node = {r.reference_element: r for r in combined["displacement"]}
        assert by_node["2"].get_translations() == pytest.approx([0.0, 0.0, -3.0])
        assert len(combined["section_forces"]) == 2

    def test_the_cases_are_left_as_they_were(self):
        results = _results()
        combine_results(results, FACTORS, "ULS")
        assert results["displacement"][0].get_translations() == [0.0, 0.0, -1.0]
        assert results["section_forces"][0]["Mf1"] == 10.0
        assert results["section_forces"][0]["force"] == [0.0, 0.0, 5.0]


class TestWhatCannotBeAdded:
    def test_case_without_results(self):
        with pytest.raises(ResultProcessingError, match="Wind has no displacements"):
            combine_results(_results(), {"Dead": 1.0, "Wind": 1.0}, "ULS")

    def test_cases_on_different_nodes(self):
        results = _results()
        results["displacement"].pop()
        with pytest.raises(ResultProcessingError, match="not at the same points"):
            combine_results(results, FACTORS, "ULS")

    def test_cases_with_different_cross_sections(self):
        results = _results()
        results["section_forces"].pop()
        with pytest.raises(ResultProcessingError, match="section force results"):
            combine_results(results, FACTORS, "ULS")

    def test_principal_stresses_alone(self):
        """They are not linear in the load."""
        results = _results()
        stress = StressResult(reference_element="1", load_case="Dead")
        stress.set_principal_stresses([1.0, 2.0, 3.0])
        results["stress"][0] = stress
        with pytest.raises(ResultProcessingError, match="only components"):
            combine_results(results, FACTORS, "ULS")
