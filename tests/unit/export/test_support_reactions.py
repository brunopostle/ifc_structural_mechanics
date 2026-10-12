"""The reaction at each support in results.json."""

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.plausibility import balance_warnings
from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.result import ReactionForceResult
from ifc_structural_mechanics.domain.structural_connection import PointConnection
from ifc_structural_mechanics.domain.structural_member import (
    CurveMember,
    SurfaceMember,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter

RIGID = 1e20
LENGTH = 5.0


def _material():
    return Material(
        id="m", name="Steel", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
    )


def _beam(member_id="beam", start=(0, 0, 0), end=(LENGTH, 0, 0)):
    member = CurveMember(
        id=member_id,
        geometry=[list(start), list(end)],
        material=_material(),
        section=Section.create_rectangular_section("s", "r", width=0.2, height=0.3),
    )
    return member


def _support(connection_id, position, members=("beam",)):
    support = PointConnection(connection_id, [float(c) for c in position])
    support.ifc_guid = f"guid-{connection_id}"
    for member_id in members:
        support.connect_member(member_id)
    return support


def _record(element_id, distance, centre, force, moment, case="Dead"):
    return {
        "element_id": element_id,
        "load_case": case,
        "position": 0.0,
        "distance": distance,
        "centre": list(centre),
        "force": list(force),
        "moment": list(moment),
    }


def _export(model, node_forces, section_forces=(), case="Dead"):
    steps = [{"load_case": case, "forces": node_forces}]
    exporter = ResultsExporter(
        model,
        {
            "displacement": [],
            "stress": [],
            "reaction": [],
            "section_forces": list(section_forces),
            "support_node_forces": steps,
        },
    )
    return exporter._supports()


def _model(*supports, members=None):
    model = StructuralModel(id="model")
    for member in members if members is not None else [_beam()]:
        model.add_member(member)
    for support, _ in supports:
        model.add_connection(support)
    model.support_nodes = {
        support.id: record for support, record in supports if record is not None
    }
    return model


class TestForces:
    def test_forces_of_a_supports_nodes_are_summed(self):
        """A beam and a shell node at one point are one support."""
        support = _support("a", (0, 0, 0))
        model = _model((support, {"nodes": {1: (0, 0, 0), 7: (0, 0, 0)}, "dofs": [3]}))

        (entry,) = _export(
            model, {1: [1.0, 2.0, 30.0], 7: [0.0, 0.0, 12.0], 9: [5, 5, 5]}
        )

        assert entry["ifc_guid"] == "guid-a"
        assert entry["type"] == "point"
        assert entry["position_m"] == [0.0, 0.0, 0.0]
        assert entry["restrained"] == ["tz"]
        reaction = entry["by_load_case"]["Dead"]
        assert (reaction["fx_N"], reaction["fy_N"], reaction["fz_N"]) == (1, 2, 42)
        assert reaction["resultant_N"] == pytest.approx(np.sqrt(1 + 4 + 42**2))

    def test_skew_support_names_what_it_holds_in_its_own_axes(self):
        """A roller on a 3:4 incline holds its normal, which is no global axis."""
        support = _support("a", (0, 0, 0))
        support.local_axes = [[0.8, 0.0, 0.6], [0.0, 1.0, 0.0], [-0.6, 0.0, 0.8]]
        record = {
            "nodes": {1: (0, 0, 0)},
            "dofs": [2],
            "translations": [[0.0, 1.0, 0.0], [-0.75, 0.0, 1.0]],
            "rotations": [],
        }

        (entry,) = _export(_model((support, record)), {1: [-60.0, 0.0, 80.0]})

        assert entry["restrained"] == ["ty"]
        assert entry["restrained_in_axes"] == ["ty", "tz"]
        in_axes = entry["by_load_case_in_axes"]["Dead"]
        assert in_axes["fz_N"] == pytest.approx(100.0)
        assert in_axes["fx_N"] == pytest.approx(0.0)

    def test_load_applied_at_the_node_is_taken_off(self):
        """The solver gives the force in the structure, not the reaction.

        Measured: 100 N down on a node held vertically reads as no force
        there, and 70 N along a free direction reads as 70 N.
        """
        support = _support("a", (0, 0, 0))
        model = _model((support, {"nodes": {5: (0, 0, 0)}, "dofs": [2, 3]}))
        model.support_node_loads = [{5: [70.0, 0.0, -100.0]}]

        (entry,) = _export(model, {5: [70.0, 0.0, 0.0]})

        reaction = entry["by_load_case"]["Dead"]
        assert reaction["fx_N"] == pytest.approx(0.0)
        assert reaction["fz_N"] == pytest.approx(100.0)

    def test_global_total_is_corrected_the_same_way(self):
        support = _support("a", (0, 0, 0))
        model = _model((support, {"nodes": {5: (0, 0, 0)}, "dofs": [3]}))
        model.support_node_loads = [{5: [0.0, 0.0, -100.0]}]
        total = ReactionForceResult(reference_element="TOTAL")
        total.set_forces([0.0, 0.0, 900.0])
        total.set_moments([0.0, 0.0, 0.0])
        total.add_metadata("load_case", "Dead")
        exporter = ResultsExporter(
            model,
            {"displacement": [], "stress": [], "reaction": [total]},
        )

        for _ in range(2):  # building twice must not correct twice
            reactions = exporter._global_reactions()
        assert reactions["total"]["fz_N"] == pytest.approx(1000.0)
        assert reactions["by_load_case"]["Dead"]["fz_N"] == pytest.approx(1000.0)

    def test_node_shared_by_two_supports_is_counted_once(self):
        first, second = _support("a", (0, 0, 0)), _support("b", (0, 0, 0))
        record = {"nodes": {1: (0, 0, 0)}, "dofs": [1, 2, 3]}
        model = _model((first, record), (second, dict(record)))

        entries = _export(model, {1: [0.0, 0.0, 10.0]})

        assert [e["by_load_case"]["Dead"]["fz_N"] for e in entries] == [10.0, 0.0]

    def test_connection_that_is_not_a_support_is_left_out(self):
        support, joint = _support("a", (0, 0, 0)), _support("j", (LENGTH, 0, 0))
        model = _model(
            (support, {"nodes": {1: (0, 0, 0)}, "dofs": [1, 2, 3]}), (joint, None)
        )

        assert [e["id"] for e in _export(model, {1: [0.0, 0.0, 1.0]})] == ["a"]

    def test_no_supports_block_without_nodal_forces(self):
        support = _support("a", (0, 0, 0))
        model = _model((support, {"nodes": {1: (0, 0, 0)}, "dofs": [3]}))
        exporter = ResultsExporter(model, {"displacement": [], "stress": []})

        assert exporter._supports() == []


class TestLineSupport:
    def test_position_is_mid_edge_and_forces_have_a_moment_about_it(self):
        support = _support("line", (0, 0, 0))
        support.edge = [[0.0, 0.0, 0.0], [0.0, 4.0, 0.0]]
        nodes = {1: (0.0, 0.0, 0.0), 2: (0.0, 2.0, 0.0), 3: (0.0, 4.0, 0.0)}
        model = _model((support, {"nodes": nodes, "dofs": [1, 2, 3]}))

        (entry,) = _export(model, {1: [0, 0, 10.0], 2: [0, 0, 40.0], 3: [0, 0, 30.0]})

        assert entry["type"] == "line"
        assert entry["position_m"] == [0.0, 2.0, 0.0]
        assert entry["moments"] == "none_restrained"
        reaction = entry["by_load_case"]["Dead"]
        assert reaction["fz_N"] == 80.0
        # 30 N at +2 m and 10 N at -2 m along Y, both upwards
        assert reaction["mx_Nm"] == pytest.approx(2.0 * 30.0 - 2.0 * 10.0)
        assert reaction["my_Nm"] == pytest.approx(0.0)

    def test_reaction_is_also_given_in_the_supports_own_axes(self):
        support = _support("line", (0, 0, 0))
        support.edge = [[0.0, 0.0, 0.0], [0.0, 4.0, 0.0]]
        support.local_axes = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
        model = _model((support, {"nodes": {1: (0.0, 2.0, 0.0)}, "dofs": [1, 2, 3]}))

        (entry,) = _export(model, {1: [3.0, 5.0, 7.0]})

        assert entry["axes"]["x"] == [0.0, 1.0, 0.0]
        local = entry["by_load_case_in_axes"]["Dead"]
        assert (local["fx_N"], local["fy_N"], local["fz_N"]) == (5.0, 7.0, 3.0)
        assert "resultant_N" not in local


class TestMoments:
    """The solver has no reaction moments; member end forces stand in."""

    FIXED = {"nodes": {1: (0, 0, 0)}, "dofs": [1, 2, 3, 4, 5, 6]}

    def _cantilever(self, support_at_start=True):
        beam = _beam()
        beam.analysis_element_ids = [1, 2]
        position = (0, 0, 0) if support_at_start else (LENGTH, 0, 0)
        return beam, _support("a", position)

    def test_support_at_the_start_of_a_member(self):
        """A tip load of 100 N down on a 5 m cantilever: +100 and -500 about Y.

        The record at the root is what the beam exerts on the support there:
        100 N down and a moment of +500 about Y.
        """
        beam, support = self._cantilever()
        model = _model((support, self.FIXED), members=[beam])
        records = [
            _record(1, 0.0, (0, 0, 0), (0, 0, -100.0), (0, 500.0, 0)),
            _record(2, LENGTH, (LENGTH, 0, 0), (0, 0, -100.0), (0, 0, 0)),
        ]

        (entry,) = _export(model, {1: [0.0, 0.0, 100.0]}, records)

        assert entry["moments"] == "member_end_forces"
        reaction = entry["by_load_case"]["Dead"]
        assert reaction["my_Nm"] == pytest.approx(-500.0)
        assert reaction["mx_Nm"] == reaction["mz_Nm"] == 0.0

    def test_support_at_the_end_of_a_member(self):
        """The same cantilever drawn from its tip to its root."""
        beam, support = self._cantilever(support_at_start=False)
        model = _model(
            (support, {"nodes": {1: (LENGTH, 0, 0)}, "dofs": [1, 2, 3, 4, 5, 6]}),
            members=[beam],
        )
        # At the root the part beyond is the support: it pushes up 100 N and
        # turns the beam by +500 about Y (the load is at x = 0, behind it)
        records = [
            _record(1, 0.0, (0, 0, 0), (0, 0, 100.0), (0, 0, 0)),
            _record(2, LENGTH, (LENGTH, 0, 0), (0, 0, 100.0), (0, 500.0, 0)),
        ]

        (entry,) = _export(model, {1: [0.0, 0.0, 100.0]}, records)

        assert entry["by_load_case"]["Dead"]["my_Nm"] == pytest.approx(500.0)

    def test_end_forces_are_moved_to_the_support(self):
        """An end 0.2 m above the support: its shear has a lever arm."""
        beam = _beam(start=(0, 0, 0.2), end=(LENGTH, 0, 0.2))
        beam.analysis_element_ids = [1]
        support = _support("a", (0, 0, 0))
        model = _model((support, self.FIXED), members=[beam])
        records = [
            _record(1, 0.0, (0, 0, 0.2), (-50.0, 0, 0), (0, 0, 0)),
            _record(1, LENGTH, (LENGTH, 0, 0.2), (-50.0, 0, 0), (0, 0, 0)),
        ]

        (entry,) = _export(model, {1: [50.0, 0.0, 0.0]}, records)

        # 50 N along +X acting 0.2 m up: (0, 0, 0.2) x (50, 0, 0) = +10 about Y
        assert entry["by_load_case"]["Dead"]["my_Nm"] == pytest.approx(10.0)

    def test_only_restrained_rotations_carry_a_moment(self):
        beam, support = self._cantilever()
        model = _model(
            (support, {"nodes": {1: (0, 0, 0)}, "dofs": [1, 2, 3, 4]}), members=[beam]
        )
        records = [
            _record(1, 0.0, (0, 0, 0), (0, 0, 0), (-7.0, 1e-3, 0)),
            _record(2, LENGTH, (LENGTH, 0, 0), (0, 0, 0), (0, 0, 0)),
        ]

        (entry,) = _export(model, {1: [0.0, 0.0, 0.0]}, records)

        assert entry["restrained"] == ["tx", "ty", "tz", "rx"]
        reaction = entry["by_load_case"]["Dead"]
        assert reaction["mx_Nm"] == pytest.approx(7.0)
        assert reaction["my_Nm"] == 0.0

    def test_two_members_ending_at_a_support_add_up(self):
        left = _beam("left", (-LENGTH, 0, 0), (0, 0, 0))
        right = _beam("right", (0, 0, 0), (LENGTH, 0, 0))
        left.analysis_element_ids, right.analysis_element_ids = [1], [2]
        support = _support("a", (0, 0, 0), members=("left", "right"))
        model = _model((support, self.FIXED), members=[left, right])
        records = [
            _record(1, 0.0, (-LENGTH, 0, 0), (0, 0, 0), (0, 0, 0)),
            _record(1, LENGTH, (0, 0, 0), (0, 0, 0), (0, 30.0, 0)),
            _record(2, 0.0, (0, 0, 0), (0, 0, 0), (0, 100.0, 0)),
            _record(2, LENGTH, (LENGTH, 0, 0), (0, 0, 0), (0, 0, 0)),
        ]

        (entry,) = _export(model, {1: [0.0, 0.0, 0.0]}, records)

        assert entry["by_load_case"]["Dead"]["my_Nm"] == pytest.approx(30.0 - 100.0)

    def _not_computed(self, model, records=()):
        (entry,) = _export(model, {1: [0.0, 0.0, 9.0]}, records)
        assert entry["moments"] == "not_computed"
        reaction = entry["by_load_case"]["Dead"]
        assert reaction["fz_N"] == 9.0
        assert not {"mx_Nm", "my_Nm", "mz_Nm"} & set(reaction)

    def test_member_running_on_past_the_support(self):
        """Its end forces are those of a free end, not the support's."""
        beam = _beam()
        beam.analysis_element_ids = [1]
        support = _support("a", (0.1, 0, 0))
        model = _model(
            (support, {"nodes": {1: (0.1, 0, 0)}, "dofs": [1, 2, 3, 4, 5, 6]}),
            members=[beam],
        )
        records = [
            _record(1, 0.0, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
            _record(1, LENGTH, (LENGTH, 0, 0), (0, 0, 0), (0, 0, 0)),
        ]
        self._not_computed(model, records)

    def test_surface_member_at_the_support(self):
        slab = SurfaceMember(
            id="slab",
            geometry={"boundaries": [[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]]},
            thickness=Thickness("t", "t", 0.2),
            material=_material(),
        )
        support = _support("a", (0, 0, 0), members=("slab",))
        self._not_computed(_model((support, self.FIXED), members=[slab]))

    def test_member_without_section_forces(self):
        beam, support = self._cantilever()
        self._not_computed(_model((support, self.FIXED), members=[beam]))

    def test_support_that_names_no_member(self):
        support = _support("a", (0, 0, 0), members=())
        self._not_computed(_model((support, self.FIXED)))

    def test_no_rotation_held_needs_no_member(self):
        support = _support("a", (0, 0, 0), members=())
        model = _model((support, {"nodes": {1: (0, 0, 0)}, "dofs": [1, 2, 3]}))

        (entry,) = _export(model, {1: [0.0, 0.0, 9.0]})

        assert entry["moments"] == "none_restrained"
        assert entry["by_load_case"]["Dead"]["my_Nm"] == 0.0


def _total(fz, case="Dead"):
    total = ReactionForceResult(reference_element="TOTAL")
    total.set_forces([0.0, 0.0, fz])
    total.set_moments([0.0, 0.0, 0.0])
    total.add_metadata("load_case", case)
    return total


class TestSolverThatMisreportsReactions:
    """CalculiX 2.21 at a support that holds a rotation.

    Measured on a clamped column carrying 1000 N: 2.21 reports 1077 N along
    it, 2.23 reports 1000 N, and the displacements are the same.
    """

    FIXED = {"nodes": {1: (0, 0, 0)}, "dofs": [1, 2, 3, 4, 5, 6]}

    def _column(self, solver_fz, total_fz, applied=1000.0, with_records=True):
        column = _beam("beam", (0, 0, 0), (0, 0, LENGTH))
        column.analysis_element_ids = [1]
        support = _support("a", (0, 0, 0))
        model = _model((support, self.FIXED), members=[column])
        model.applied_load_totals = [[0.0, 0.0, -applied]]
        records = [
            _record(1, 0.0, (0, 0, 0), (0, 0, -1000.0), (0, 0, 0)),
            _record(1, LENGTH, (0, 0, LENGTH), (0, 0, -1000.0), (0, 0, 0)),
        ]
        exporter = ResultsExporter(
            model,
            {
                "displacement": [],
                "stress": [],
                "reaction": [_total(total_fz)],
                "section_forces": records if with_records else [],
                "support_node_forces": [
                    {"load_case": "Dead", "forces": {1: [0.0, 0.0, solver_fz]}}
                ],
            },
        )
        return exporter

    def test_solver_that_agrees_with_the_member_ends_is_used(self):
        (entry,) = self._column(1000.5, 1000.5)._supports()

        assert entry["forces"] == "solver"
        assert entry["by_load_case"]["Dead"]["fz_N"] == 1000.5

    def test_force_far_from_the_member_ends_is_replaced(self):
        """Even when the total balances: two supports' errors can cancel."""
        (entry,) = self._column(1076.6, 1000.0)._supports()

        assert entry["forces"] == "member_end_forces"
        assert entry["by_load_case"]["Dead"]["fz_N"] == pytest.approx(1000.0)

    def test_total_that_does_not_balance_replaces_it_too(self):
        (entry,) = self._column(1010.0, 1010.0)._supports()

        assert entry["forces"] == "member_end_forces"

    def test_nothing_to_replace_it_with_is_said(self):
        exporter = self._column(1076.6, 1076.6, with_records=False)

        (entry,) = exporter._supports()

        assert entry["forces"] == "unreliable"
        assert entry["by_load_case"]["Dead"]["fz_N"] == 1076.6

    def test_global_reactions_give_the_load_and_the_imbalance(self):
        reactions = self._column(1076.6, 1076.6)._global_reactions()

        entry = reactions["by_load_case"]["Dead"]
        assert entry["applied_load_N"] == [0.0, 0.0, -1000.0]
        assert entry["imbalance_N"] == pytest.approx(76.6)

    def test_warning_says_what_was_done(self):
        exporter = self._column(1076.6, 1076.6)
        results = {
            "global_reactions": exporter._global_reactions(),
            "supports": exporter._supports(),
        }

        (warning,) = balance_warnings(results)

        message = warning["message"]
        assert "do not balance the applied loads in 1 load case(s)" in message
        assert "Dead (off by 76.6 N of 1000 N)" in message
        assert "At 1 support(s) that hold a rotation the forces are taken" in message
        assert "CalculiX 2.21 and earlier" in message

    def test_warning_for_supports_nothing_could_replace(self):
        exporter = self._column(1076.6, 1076.6, with_records=False)
        results = {
            "global_reactions": exporter._global_reactions(),
            "supports": exporter._supports(),
        }

        (warning,) = balance_warnings(results)

        assert "nothing to take them from" in warning["message"]

    def test_no_warning_when_everything_agrees(self):
        exporter = self._column(1000.0, 1000.0)
        results = {
            "global_reactions": exporter._global_reactions(),
            "supports": exporter._supports(),
        }

        assert balance_warnings(results) == []

    def test_results_without_recorded_loads_are_not_judged(self):
        assert balance_warnings({"global_reactions": {"by_load_case": {}}}) == []
