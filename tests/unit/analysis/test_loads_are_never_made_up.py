"""A load that cannot be applied as given is an error or a warning, never a guess.

The load writer used to send a point load with no position to node 2, replace
a force it could not read with 1 kN downwards, and put a distributed load that
named no member on the first member of the model.
"""

import io
from unittest.mock import MagicMock

import pytest

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    _determine_load_node,
    _get_validated_force_vector,
    write_analysis_steps,
)
from ifc_structural_mechanics.domain.load import LineLoad, LoadGroup, PointLoad
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.mesh_mapper import MeshMapper
from ifc_structural_mechanics.utils.error_handling import AnalysisError, MeshingError

NODES = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (2.0, 0.0, 0.0)}


def _beam(member_id, start=(0, 0, 0), end=(2, 0, 0)):
    return CurveMember(
        id=member_id,
        geometry=[list(start), list(end)],
        material=Material(
            id="steel",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        ),
        section=Section.create_rectangular_section(
            id="s", name="Rect", width=0.1, height=0.2
        ),
    )


def _model(*loads):
    model = StructuralModel(id="model")
    model.add_member(_beam("m1"))
    case = LoadGroup(id="lc", name="Case", is_load_case=True)
    for load in loads:
        case.add_load(load)
    model.load_groups.append(case)
    return model


class TestPointLoadNode:
    def test_nearest_node_is_used(self):
        load = PointLoad(
            id="p", magnitude=1.0, direction=[0, 0, -1], position=[1, 0, 0]
        )
        assert _determine_load_node(load, NODES) == 2

    def test_no_mesh_is_an_error(self):
        load = PointLoad(
            id="p", magnitude=1.0, direction=[0, 0, -1], position=[1, 0, 0]
        )
        with pytest.raises(AnalysisError, match="p cannot be applied"):
            _determine_load_node(load, None)

    def test_no_position_is_an_error(self):
        load = MagicMock(id="p", position=None)
        with pytest.raises(AnalysisError, match="no position"):
            _determine_load_node(load, NODES)

    def test_load_moved_a_long_way_is_reported(self):
        model = _model()
        load = PointLoad(
            id="p", magnitude=1.0, direction=[0, 0, -1], position=[1, 3, 0]
        )
        assert _determine_load_node(load, NODES, model) == 2
        (warning,) = model.analysis_warnings
        assert "3.00 m from its position" in warning["message"]

    def test_load_at_a_node_is_not_reported(self):
        model = _model()
        load = PointLoad(
            id="p", magnitude=1.0, direction=[0, 0, -1], position=[1.02, 0, 0]
        )
        _determine_load_node(load, NODES, model)
        assert not getattr(model, "analysis_warnings", [])


class TestForceVector:
    def test_vector_is_returned_as_floats(self):
        load = PointLoad(
            id="p", magnitude=2.0, direction=[0, 0, -1], position=[0, 0, 0]
        )
        assert _get_validated_force_vector(load) == [0.0, 0.0, -2.0]

    def test_unreadable_force_is_an_error(self):
        load = MagicMock(id="p")
        load.get_force_vector.return_value = "nonsense"
        with pytest.raises(AnalysisError, match="no usable force vector"):
            _get_validated_force_vector(load)

    def test_short_vector_is_an_error(self):
        load = MagicMock(id="p")
        load.get_force_vector.return_value = [1.0, 2.0]
        with pytest.raises(AnalysisError, match="no usable force vector"):
            _get_validated_force_vector(load)


class TestDistributedLoads:
    def _line_load(self, member_reference=None):
        load = LineLoad(
            id="q",
            magnitude=1000.0,
            direction=[0, 0, -1],
            start_position=[0, 0, 0],
            end_position=[2, 0, 0],
        )
        if member_reference:
            load.member_reference = member_reference
        return load

    def test_load_on_no_member_is_an_error(self):
        """It used to go on the first curve member of the model."""
        with pytest.raises(AnalysisError, match="q is not assigned to a member"):
            write_analysis_steps(
                io.StringIO(), _model(self._line_load()), node_coords=NODES
            )

    def test_load_without_a_mesh_is_an_error(self):
        """It used to be written as *DLOAD, along the element's own axes."""
        with pytest.raises(AnalysisError, match="need the mesh"):
            write_analysis_steps(
                io.StringIO(), _model(self._line_load("m1")), node_coords=NODES
            )

    def test_no_dload_is_written(self):
        elements = {
            1: {"type": "B31", "nodes": [1, 2]},
            2: {"type": "B31", "nodes": [2, 3]},
        }
        out = io.StringIO()
        write_analysis_steps(
            out,
            _model(self._line_load("m1")),
            node_coords=NODES,
            element_sets={"MEMBER_m1": [1, 2]},
            elements_data=elements,
        )
        text = out.getvalue()
        assert "*DLOAD\n" not in text
        forces = [
            float(line.split(",")[2])
            for line in text.splitlines()
            if line.count(",") == 2 and line.split(",")[1].strip() == "3"
        ]
        assert sum(forces) == pytest.approx(-2000.0)


class TestElementsWithoutPhysicalGroups:
    ELEMENTS = {
        1: {"type": "B31", "nodes": [1, 2]},
        2: {"type": "B31", "nodes": [2, 3]},
    }

    def _mapper(self, *members):
        model = StructuralModel(id="model")
        for member in members:
            model.add_member(member)
        return MeshMapper(
            self.ELEMENTS, NODES, model, {}, {}, lambda member_id: member_id
        )

    def test_one_member_takes_them_all(self):
        mapper = self._mapper(_beam("m1"))
        mapper.map()
        assert mapper.element_sets["MEMBER_m1"] == [1, 2]

    def test_two_members_cannot_share_them_out(self):
        """They used to be dealt out in turn, wherever they were."""
        mapper = self._mapper(_beam("m1"), _beam("m2", (0, 1, 0), (2, 1, 0)))
        with pytest.raises(MeshingError, match="no physical groups"):
            mapper.map()
