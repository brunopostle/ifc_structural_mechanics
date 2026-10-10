"""Per-member results are attributed through the result file's own elements."""

from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.result import DisplacementResult, StressResult
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter


def _material():
    return Material(
        id="mat", name="Steel", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
    )


def _model():
    """A beam (elements 1, 2; mesh nodes 1-3) and a slab (element 3; nodes 3-5)."""
    model = StructuralModel(id="model")
    model.add_member(
        CurveMember(
            id="beam",
            geometry=[[0, 0, 0], [2, 0, 0]],
            material=_material(),
            section=Section.create_rectangular_section("s", "s", width=0.2, height=0.3),
        )
    )
    model.add_member(
        SurfaceMember(
            id="slab",
            geometry=[(2, 0, 0), (4, 0, 0), (4, 2, 0)],
            material=_material(),
            thickness=Thickness(id="t", name="t", value=0.2),
        )
    )
    model.set_analysis_elements("beam", [1, 2])
    model.set_analysis_elements("slab", [3])
    model.register_node_memberships([1, 2, 3], "beam")
    model.register_node_memberships([3, 4, 5], "slab")
    return model


def _displacement(node, uz, load_case="Dead"):
    result = DisplacementResult(reference_element=node)
    result.set_translations([0.0, 0.0, uz])
    result.add_metadata("load_case", load_case)
    return result


def _stress(node, sxx, load_case="Dead"):
    result = StressResult(reference_element=node)
    for name, value in zip(
        ("sxx", "syy", "szz", "sxy", "syz", "sxz"), (sxx, 0, 0, 0, 0, 0)
    ):
        result.add_value(name, float(value))
    result.add_metadata("load_case", load_case)
    return result


# The solver's numbering of the solids it expands the elements into
EXPANDED = {1: [101, 102, 103, 104], 2: [103, 104, 105, 106], 3: [201, 202, 203]}


def _members(parsed, element_nodes=None, model=None):
    exporter = ResultsExporter(model or _model(), parsed, element_nodes=element_nodes)
    return {m["id"]: m for m in exporter._build()["members"]}


def _parsed(displacements=(), stresses=()):
    return {"displacement": list(displacements), "stress": list(stresses)}


class TestExpandedElements:
    def test_beam_takes_the_nodes_of_its_expanded_elements(self):
        parsed = _parsed([_displacement(105, 0.004), _displacement(201, 0.009)])
        members = _members(parsed, EXPANDED)

        assert members["beam"]["by_load_case"]["Dead"]["max_displacement_m"] == 0.004
        assert members["slab"]["by_load_case"]["Dead"]["max_displacement_m"] == 0.009

    def test_mesh_node_numbers_are_not_used_for_expanded_elements(self):
        """Node 2 is a mesh node of the beam, but in the result file it is not."""
        parsed = _parsed([_displacement(2, 0.5), _displacement(101, 0.001)])
        members = _members(parsed, EXPANDED)

        assert members["beam"]["envelope"]["max_displacement_m"] == 0.001

    def test_stress_is_reported_per_load_case(self):
        parsed = _parsed(
            stresses=[_stress(102, 3e6, "Dead"), _stress(102, 5e6, "Live")]
        )
        members = _members(parsed, EXPANDED)

        by_case = members["beam"]["by_load_case"]
        assert by_case["Dead"]["max_von_mises_Pa"] == 3e6
        assert by_case["Live"]["max_von_mises_Pa"] == 5e6
        assert members["beam"]["envelope"]["max_von_mises_Pa"] == 5e6

    def test_member_without_results_has_no_envelope(self):
        members = _members(_parsed([_displacement(105, 0.004)]), EXPANDED)

        assert "envelope" not in members["slab"]


class TestElementsTheResultFileDoesNotList:
    def test_member_falls_back_to_its_mesh_nodes(self):
        """U1 user elements are reported on the nodes they were given."""
        parsed = _parsed([_displacement(2, 0.003), _displacement(201, 0.009)])
        members = _members(parsed, {3: [201, 202, 203]})

        assert members["beam"]["envelope"]["max_displacement_m"] == 0.003

    def test_node_at_a_joint_counts_for_both_members(self):
        parsed = _parsed([_displacement(3, 0.007)])
        members = _members(parsed, {})

        assert members["beam"]["envelope"]["max_displacement_m"] == 0.007
        assert members["slab"]["envelope"]["max_displacement_m"] == 0.007

    def test_without_connectivity_mesh_nodes_are_used(self):
        parsed = _parsed([_displacement(1, 0.002)])
        members = _members(parsed)

        assert members["beam"]["envelope"]["max_displacement_m"] == 0.002


class TestSetAnalysisElements:
    def test_replaces_the_earlier_registration(self):
        model = _model()
        model.set_analysis_elements("beam", [7, 8, 9])

        assert model.get_member("beam").analysis_element_ids == [7, 8, 9]
        assert model.analysis_element_to_member[8] == "beam"
        assert 1 not in model.analysis_element_to_member

    def test_element_passed_to_another_member_stays_with_it(self):
        model = _model()
        model.set_analysis_elements("slab", [2, 3])
        model.set_analysis_elements("beam", [1])

        assert model.analysis_element_to_member[2] == "slab"

    def test_member_nodes_keep_every_owner(self):
        model = _model()

        assert model.member_nodes["beam"] == {1, 2, 3}
        assert model.member_nodes["slab"] == {3, 4, 5}
