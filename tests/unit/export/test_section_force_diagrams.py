"""Signed section forces along a member, as exported in results.json."""

import pytest

from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter

ELEMENT_LENGTH = 0.5


def _model(start=(0.0, 0.0, 0.0), end=(4.0, 0.0, 0.0), elements=8):
    model = StructuralModel(id="model")
    model.add_member(
        CurveMember(
            id="beam",
            geometry=[list(start), list(end)],
            material=Material(
                id="m",
                name="m",
                density=7850.0,
                elastic_modulus=210e9,
                poisson_ratio=0.3,
            ),
            section=Section.create_rectangular_section("s", "s", width=0.2, height=0.4),
        )
    )
    ids = list(range(1, elements + 1))
    model.set_analysis_elements("beam", ids)
    model.beam_section_frames = {e: ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)) for e in ids}
    return model


def _records(shear, moment=lambda x: 0.0, axial=lambda x: 0.0, elements=8, case="Dead"):
    """Records as the parser gives them, with nodal averaging between elements.

    ``shear`` may be discontinuous: it is called with a second argument, -1
    or +1, for the side of a cross-section it is wanted on. The value at a
    cross-section two elements share is the mean of the two sides.
    """
    records = []
    for index in range(elements):
        x0 = index * ELEMENT_LENGTH
        for position in (-1.0, 0.0, 1.0):
            x = x0 + (position + 1) * ELEMENT_LENGTH / 2
            interior = 0 < x < elements * ELEMENT_LENGTH
            if position == 0.0 or not interior:
                side = 1 if position < 0 else -1
                value = shear(x, side if position else 0)
            else:
                value = (shear(x, -1) + shear(x, 1)) / 2
            records.append(
                {
                    "element_id": index + 1,
                    "load_case": case,
                    "position": position,
                    "distance": x,
                    "N": axial(x),
                    "Vf1": value,
                    "Vf2": 0.0,
                    "T": 0.0,
                    "Mf1": moment(x),
                    "Mf2": 0.0,
                }
            )
    return records


def _member(records, model=None):
    exporter = ResultsExporter(
        model or _model(), {"displacement": [], "stress": [], "section_forces": records}
    )
    return exporter._build()["members"][0]


def _point_load_shear(x, side):
    """10 kN at midspan of a beam fixed at both ends."""
    if x == 2.0:
        return -1.0e4 if side <= 0 else 1.0e4
    return -1.0e4 if x < 2.0 else 1.0e4


class TestDiagram:
    def test_ordered_by_distance_with_shared_sections_listed_once(self):
        diagram = _member(_records(lambda x, side: 100.0 * x))[
            "section_force_diagrams"
        ]["Dead"]

        assert diagram["distance_m"] == pytest.approx([i * 0.25 for i in range(17)])
        assert diagram["Vf1_N"] == pytest.approx([25.0 * i for i in range(17)])

    def test_every_force_has_a_list_of_the_same_length(self):
        diagram = _member(_records(lambda x, side: 1.0))["section_force_diagrams"][
            "Dead"
        ]

        assert set(diagram) == {
            "distance_m",
            "N_N",
            "Vf1_N",
            "Vf2_N",
            "T_Nm",
            "Mf1_Nm",
            "Mf2_Nm",
        }
        assert len({len(values) for values in diagram.values()}) == 1

    def test_signs_are_kept(self):
        diagram = _member(
            _records(
                lambda x, side: -5.0, moment=lambda x: 3.0 - x, axial=lambda x: -7.0
            )
        )["section_force_diagrams"]["Dead"]

        assert diagram["Vf1_N"][0] == -5.0
        assert diagram["N_N"][0] == -7.0
        assert diagram["Mf1_Nm"][0] == 3.0 and diagram["Mf1_Nm"][-1] == -1.0

    def test_one_diagram_per_load_case(self):
        records = _records(lambda x, side: 1.0) + _records(
            lambda x, side: 2.0, case="Live"
        )

        assert set(_member(records)["section_force_diagrams"]) == {"Dead", "Live"}

    def test_records_without_a_distance_give_no_diagram(self):
        records = _records(lambda x, side: 1.0)
        for record in records:
            del record["distance"]
        member = _member(records)

        assert "section_force_diagrams" not in member
        assert member["envelope"]["section_forces"]["max_Vf1_N"] == 1.0


class TestJumps:
    def test_step_under_a_point_load_is_restored(self):
        """The solver's averaged value at the load is zero; both sides are listed."""
        diagram = _member(_records(_point_load_shear))["section_force_diagrams"]["Dead"]

        at_load = [i for i, d in enumerate(diagram["distance_m"]) if d == 2.0]
        assert len(at_load) == 2
        assert [diagram["Vf1_N"][i] for i in at_load] == pytest.approx([-1.0e4, 1.0e4])
        assert 0.0 not in [round(v) for v in diagram["Vf1_N"]]

    def test_uniform_load_has_no_jumps(self):
        diagram = _member(_records(lambda x, side: 500.0 * (x - 2.0)))[
            "section_force_diagrams"
        ]["Dead"]

        assert len(diagram["distance_m"]) == len(set(diagram["distance_m"]))

    def test_point_load_on_top_of_a_uniform_load(self):
        def shear(x, side):
            return 500.0 * (x - 2.0) + _point_load_shear(x, side)

        diagram = _member(_records(shear))["section_force_diagrams"]["Dead"]

        at_load = [i for i, d in enumerate(diagram["distance_m"]) if d == 2.0]
        assert [diagram["Vf1_N"][i] for i in at_load] == pytest.approx([-1.0e4, 1.0e4])

    def test_bending_moment_is_never_split(self):
        """It has a kink under a point load, not a jump."""
        diagram = _member(
            _records(_point_load_shear, moment=lambda x: 1.0e4 * abs(x - 2.0) - 1.0e4)
        )["section_force_diagrams"]["Dead"]

        at_load = [i for i, d in enumerate(diagram["distance_m"]) if d == 2.0]
        assert [diagram["Mf1_Nm"][i] for i in at_load] == pytest.approx(
            [-1.0e4, -1.0e4]
        )

    def test_short_members_are_left_averaged(self):
        """With fewer than four elements there is no telling what is normal."""
        records = _records(
            lambda x, side: (
                (-1.0 if x < 0.5 else 1.0) if x != 0.5 else -float(side or 1)
            ),
            elements=2,
        )
        diagram = _member(records, _model(end=(1.0, 0.0, 0.0), elements=2))[
            "section_force_diagrams"
        ]["Dead"]

        assert len(diagram["distance_m"]) == len(set(diagram["distance_m"]))


class TestSummary:
    def test_tension_and_compression_are_told_apart(self):
        member = _member(
            _records(lambda x, side: 0.0, axial=lambda x: 300.0 - 200.0 * x)
        )
        forces = member["by_load_case"]["Dead"]["section_forces"]

        assert forces["max_tension_N"] == pytest.approx(300.0)
        assert forces["max_compression_N"] == pytest.approx(500.0)
        assert forces["max_N_N"] == pytest.approx(500.0)

    def test_member_in_tension_only_has_no_compression(self):
        member = _member(_records(lambda x, side: 0.0, axial=lambda x: 50.0))

        assert member["envelope"]["section_forces"]["max_compression_N"] == 0.0


class TestAxes:
    def test_x_runs_from_start_to_end_and_2_completes_the_set(self):
        axes = _member(_records(lambda x, side: 1.0))["section_axes"]

        assert axes == {
            "x": [1.0, 0.0, 0.0],
            "1": [0.0, 0.0, 1.0],
            "2": [0.0, -1.0, 0.0],
        }

    def test_x_follows_the_member_not_the_elements(self):
        model = _model(start=(4.0, 0.0, 0.0), end=(0.0, 0.0, 0.0))

        axes = _member(_records(lambda x, side: 1.0), model)["section_axes"]

        assert axes["x"] == [-1.0, 0.0, 0.0]
        assert axes["2"] == [0.0, 1.0, 0.0]
