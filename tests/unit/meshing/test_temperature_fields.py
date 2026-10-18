"""Nodal temperatures of heated members (``aiz.98``).

CalculiX takes a temperature gradient in the element's own axes: across a
beam along its tangent (first node to last) times its section's 1 axis,
across a shell along the normal of its node order. Each turns over with the
element (measured on 2.21 and 2.23), so the writer turns the elements of a
member with a gradient to run the way the member does.
"""

import numpy as np

from ifc_structural_mechanics.domain.load import LoadGroup, TemperatureLoad
from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _material():
    return Material(
        id="steel",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
        thermal_expansion_coefficient=1.2e-5,
    )


def _writer(member, load):
    model = StructuralModel(id="model")
    model.add_member(member)
    group = LoadGroup(id="heat", name="Heat", is_load_case=True)
    group.add_load(load)
    model.add_load_group(group)
    writer = UnifiedCalculixWriter(domain_model=model)
    writer.element_sets = {"MEMBER_M1": [1, 2]}
    writer.short_id_map = {member.id: "M1"}
    writer._get_short_id = lambda member_id: "M1"
    return writer


def _beam():
    return CurveMember(
        id="beam",
        geometry=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        material=_material(),
        section=Section.create_rectangular_section(
            id="rect", name="Rect", width=0.1, height=0.2
        ),
        # x along the member, y = z x x, z = global Y
        local_axis=((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    )


class TestBeams:
    def _writer(self, load):
        writer = _writer(_beam(), load)
        writer.nodes = {n: (0.5 * (n - 1), 0.0, 0.0) for n in range(1, 6)}
        # The second element runs backwards
        writer.elements = {
            1: {"type": "B32R", "nodes": [1, 2, 3]},
            2: {"type": "B32R", "nodes": [5, 4, 3]},
        }
        return writer

    def test_elements_against_the_member_are_turned(self):
        writer = self._writer(TemperatureLoad("t", "beam", delta_t_z=10.0))
        writer._prepare_temperature_loads()
        assert writer.elements[1]["nodes"] == [1, 2, 3]
        assert writer.elements[2]["nodes"] == [3, 4, 5]

    def test_uniform_change_leaves_them(self):
        writer = self._writer(TemperatureLoad("t", "beam", delta_t_constant=10.0))
        writer._prepare_temperature_loads()
        assert writer.elements[2]["nodes"] == [5, 4, 3]

    def test_fields(self):
        """Field 3 along tangent x 1 axis, field 4 along the 1 axis: here
        the section's 1 axis is local z, so field 4 is dTZ over the depth,
        and tangent x z = -y takes dTY over the width with its sign
        turned."""
        writer = self._writer(
            TemperatureLoad(
                "t", "beam", delta_t_constant=5.0, delta_t_y=2.0, delta_t_z=10.0
            )
        )
        writer._prepare_temperature_loads()
        frame = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        writer.domain_model.beam_section_frames = {1: frame, 2: frame}
        (field,) = writer._temperature_fields().values()
        for node in range(1, 6):
            np.testing.assert_allclose(field[node], (5.0, -2.0 / 0.1, 10.0 / 0.2))

    def test_loads_on_one_member_add_up(self):
        writer = self._writer(TemperatureLoad("t", "beam", delta_t_constant=5.0))
        writer.domain_model.load_groups[0].add_load(
            TemperatureLoad("u", "beam", delta_t_constant=3.0)
        )
        writer._prepare_temperature_loads()
        (field,) = writer._temperature_fields().values()
        for node in range(1, 6):
            np.testing.assert_allclose(field[node], (8.0, 0.0, 0.0))


class TestShells:
    def test_elements_against_the_normal_are_turned(self):
        slab = SurfaceMember(
            id="slab",
            geometry=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            material=_material(),
            thickness=Thickness(id="t", name="t", value=0.2),
        )
        slab.normal = [0.0, 0.0, 1.0]
        writer = _writer(slab, TemperatureLoad("t", "slab", delta_t_z=10.0))
        writer.nodes = {
            1: (0, 0, 0),
            2: (1, 0, 0),
            3: (1, 1, 0),
            4: (0.5, 0, 0),
            5: (1, 0.5, 0),
            6: (0.5, 0.5, 0),
            7: (0, 1, 0),
            8: (0.5, 1, 0),
            9: (0, 0.5, 0),
        }
        writer.elements = {
            1: {"type": "S6", "nodes": [1, 2, 3, 4, 5, 6]},
            # Clockwise seen from +z: its normal is -z
            2: {"type": "S6", "nodes": [1, 7, 3, 9, 8, 6]},
        }
        writer._prepare_temperature_loads()
        assert writer.elements[1]["nodes"] == [1, 2, 3, 4, 5, 6]
        assert writer.elements[2]["nodes"] == [1, 3, 7, 6, 8, 9]
        for element in (1, 2):
            assert writer._element_direction(element)[2] > 0
        (field,) = writer._temperature_fields().values()
        for node in writer.nodes:
            np.testing.assert_allclose(field[node], (0.0, 10.0 / 0.2, 0.0))
