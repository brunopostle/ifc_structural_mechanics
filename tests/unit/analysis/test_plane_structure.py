"""Finding plane trusses and frames, and what holds them in their plane."""

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.analysis.plane_structure import (  # noqa: E402
    out_of_plane_freedoms,
    plane_normal,
    spinning_members,
)
from ifc_structural_mechanics.domain.property import (  # noqa: E402
    Material,
    Thickness,
)
from ifc_structural_mechanics.domain.structural_member import (  # noqa: E402
    SurfaceMember,
)
from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from tests.helpers import (  # noqa: E402
    PLANE_FIXED,
    PLANE_FIXED_2D,
    PLANE_PIN,
    PLANE_PIN_2D,
    PLANE_ROLLER,
    PLANE_ROLLER_2D,
    plane_model,
)

X, Y, Z = 0, 1, 2

TRUSS_NODES = {"A": (0, 0), "B": (4, 0), "C": (8, 0), "D": (2, 3), "E": (6, 3)}
TRUSS_MEMBERS = [
    ("A", "B"),
    ("B", "C"),
    ("A", "D"),
    ("D", "B"),
    ("B", "E"),
    ("E", "C"),
    ("D", "E"),
]
PORTAL_NODES = {"A": (0, 0), "B": (0, 3), "C": (4, 3), "D": (4, 0)}
PORTAL_MEMBERS = [("A", "B"), ("B", "C"), ("C", "D")]
BEAM_NODES = {"A": (0, 0), "B": (2, 0), "C": (4, 0)}
BEAM_MEMBERS = [("A", "B"), ("B", "C")]


def _model(tmp_path, nodes, members, supports, loads=None, **kwargs):
    path = plane_model(
        str(tmp_path / "plane.ifc"),
        nodes,
        members,
        supports,
        loads if loads is not None else {"B": (0.0, -1000.0)},
        **kwargs,
    )
    return Extractor(path).extract_model()


def _truss(tmp_path, supports, **kwargs):
    return _model(tmp_path, TRUSS_NODES, TRUSS_MEMBERS, supports, **kwargs)


def _portal(tmp_path, supports, **kwargs):
    kwargs.setdefault("hinged", False)
    return _model(tmp_path, PORTAL_NODES, PORTAL_MEMBERS, supports, **kwargs)


class TestPlaneNormal:
    def test_truss_in_the_x_z_plane(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        assert plane_normal(model) == Y

    def test_load_across_the_plane_makes_it_a_space_structure(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER}, load_y=1.0)
        assert plane_normal(model) is None

    def test_gravity_across_the_plane_makes_it_a_space_structure(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        assert plane_normal(model, gravity_direction=[0.0, 0.0, -1.0]) == Y
        assert plane_normal(model, gravity_direction=[0.0, -1.0, 0.0]) is None

    def test_self_weight_of_a_load_case_counts_as_a_load(self, tmp_path):
        """It is a direction, whatever the size of the forces beside it."""
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        (case,) = [group for group in model.load_groups if group.loads]
        case.self_weight_coefficients = [0.0, 0.0, -1.0]
        assert plane_normal(model) == Y
        case.self_weight_coefficients = [0.0, -1.0, 0.0]
        assert plane_normal(model) is None

    def test_member_out_of_the_plane(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        model.members[0].geometry[1][Y] = 0.5
        assert plane_normal(model) is None

    def test_surface_member(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        material = Material(
            id="m", name="C", density=2400.0, elastic_modulus=3e10, poisson_ratio=0.2
        )
        model.add_member(
            SurfaceMember(
                id="wall",
                geometry={"boundaries": [[[0, 0, 0], [8, 0, 0], [8, 0, 3], [0, 0, 3]]]},
                thickness=Thickness(id="t", name="t", value=0.2),
                material=material,
            )
        )
        assert plane_normal(model) is None

    def test_section_turned_out_of_the_plane(self, tmp_path):
        """Its bending in the plane would push it out of it."""
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        member = model.members[0]
        skew = 0.5**0.5
        member.local_axis = (
            member.local_axis[0],
            member.local_axis[1],
            (0.0, skew, skew),
        )
        assert plane_normal(model) is None

    def test_support_on_an_incline_in_the_plane(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        # A pin is the same in any axes: only the roller is turned
        for connection in model.connections:
            connection.local_axes = [[0.8, 0, 0.6], [0, 1, 0], [-0.6, 0, 0.8]]
        assert plane_normal(model) == Y

    def test_support_tilted_out_of_the_plane(self, tmp_path):
        """What it holds would push the structure out of its plane."""
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        for connection in model.connections:
            connection.local_axes = [[0.8, 0.6, 0], [-0.6, 0.8, 0], [0, 0, 1]]
        assert plane_normal(model) is None

    def test_straight_run_takes_the_plane_of_its_loads(self, tmp_path):
        supports = {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D}
        model = _model(tmp_path, BEAM_NODES, BEAM_MEMBERS, supports, hinged=False)
        assert plane_normal(model) == Y

    def test_straight_run_loaded_both_ways_is_in_no_plane(self, tmp_path):
        supports = {"A": PLANE_PIN, "C": PLANE_ROLLER}
        model = _model(
            tmp_path, BEAM_NODES, BEAM_MEMBERS, supports, hinged=False, load_y=1.0
        )
        assert plane_normal(model) is None

    def test_straight_run_loaded_along_itself_only(self, tmp_path):
        supports = {"A": PLANE_PIN, "C": PLANE_ROLLER}
        model = _model(
            tmp_path,
            BEAM_NODES,
            BEAM_MEMBERS,
            supports,
            loads={"B": (1000.0, 0.0)},
            hinged=False,
        )
        assert plane_normal(model) is None


class TestOutOfPlaneFreedoms:
    def test_fully_fixed_portal_stands(self, tmp_path):
        model = _portal(tmp_path, {"A": PLANE_FIXED, "D": PLANE_FIXED})
        assert out_of_plane_freedoms(model, Y) == 0

    def test_portal_on_pins_falls_over(self, tmp_path):
        """About the line through its feet."""
        model = _portal(tmp_path, {"A": PLANE_PIN, "D": PLANE_PIN})
        assert out_of_plane_freedoms(model, Y) == 1

    def test_portal_held_as_in_two_dimensions(self, tmp_path):
        """Across the plane, and about the two axes in it."""
        model = _portal(tmp_path, {"A": PLANE_FIXED_2D, "D": PLANE_FIXED_2D})
        assert out_of_plane_freedoms(model, Y) == 3

    def test_rigid_truss_on_pin_and_roller_falls_over(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER}, hinged=False)
        assert out_of_plane_freedoms(model, Y) == 1

    def test_pinned_truss(self, tmp_path):
        """Three joints nothing holds across the plane, and seven bars spin."""
        model = _truss(tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER})
        assert out_of_plane_freedoms(model, Y) == 10

    def test_pinned_truss_held_as_in_two_dimensions(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D})
        assert out_of_plane_freedoms(model, Y) == 12

    def test_beam_on_two_dimensional_supports(self, tmp_path):
        supports = {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D}
        model = _model(tmp_path, BEAM_NODES, BEAM_MEMBERS, supports, hinged=False)
        assert out_of_plane_freedoms(model, Y) == 3


class TestSpinningMembers:
    def test_every_pinned_bar_spins_and_is_held_at_a_pinned_end(self, tmp_path):
        model = _truss(tmp_path, {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D})
        holds = spinning_members(model, Y)
        assert sorted(member_id for _, member_id in holds) == sorted(
            member.id for member in model.members
        )
        for connection, member_id in holds:
            assert member_id in connection.connected_members
            assert connection.released_dofs_by_member[member_id]

    def test_rigid_frame_has_none(self, tmp_path):
        model = _portal(tmp_path, {"A": PLANE_FIXED_2D, "D": PLANE_FIXED_2D})
        assert spinning_members(model, Y) == []

    def test_straight_run_spins_as_one_and_is_held_once_at_a_support(self, tmp_path):
        """Each member counts as held by the other; together they turn."""
        supports = {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D}
        model = _model(tmp_path, BEAM_NODES, BEAM_MEMBERS, supports, hinged=False)
        ((connection, member_id),) = spinning_members(model, Y)
        assert connection.stiffness_properties
        assert member_id in connection.connected_members

    def test_straight_run_held_in_torsion_at_a_support_does_not_spin(self, tmp_path):
        held = (True, False, True, True, False, False)
        supports = {"A": held, "C": PLANE_ROLLER_2D}
        model = _model(tmp_path, BEAM_NODES, BEAM_MEMBERS, supports, hinged=False)
        assert spinning_members(model, Y) == []
