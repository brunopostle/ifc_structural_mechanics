"""Movements of the whole structure that no support resists (``zb7``)."""

from types import SimpleNamespace

import numpy as np

from ifc_structural_mechanics.analysis.rigid_body import describe, free_movements
from ifc_structural_mechanics.domain.structural_connection import RigidConnection

FIXED, FREE = 1e20, 0.0
# Bonsai's supports in Two_Span_Beam.ifc: free along x and about y
SLIDING = (FREE, FIXED, FIXED, FIXED, FREE, FIXED)
PINNED = (FIXED, FIXED, FIXED, FREE, FREE, FREE)
VERTICAL_ONLY = (FREE, FREE, FIXED, FREE, FREE, FREE)


def _support(x, fixity, name="s"):
    connection = RigidConnection(name, [x, 0.0, 0.0])
    connection.set_stiffness_properties(
        dict(zip(("dx", "dy", "dz", "drx", "dry", "drz"), fixity))
    )
    connection.connect_member("beam")
    return connection


def _beam(*supports, length=8.0):
    """A straight beam along x on supports at the given x."""
    return SimpleNamespace(
        members=[SimpleNamespace(geometry=[[0.0, 0.0, 0.0], [length, 0.0, 0.0]])],
        connections=[
            _support(x, fixity, f"s{n}") for n, (x, fixity) in enumerate(supports)
        ],
    )


def test_beam_sliding_along_its_length():
    """``Two_Span_Beam.ifc``: three supports, all free along x."""
    (movement,) = free_movements(_beam((0.0, SLIDING), (4.0, SLIDING), (8.0, SLIDING)))
    assert describe(movement) == "along x"


def test_one_support_holding_it_is_enough():
    assert free_movements(_beam((0.0, PINNED), (4.0, SLIDING), (8.0, SLIDING))) == []


def test_beam_on_balls_spins_about_its_axis():
    """Translations held at both ends leave the rotation about the beam."""
    (movement,) = free_movements(_beam((0.0, PINNED), (8.0, PINNED)))
    assert describe(movement) == "about an axis along x through (4, 0, 0) m"


def test_a_hold_of_the_writer_resists():
    """The writer holds such a beam against spinning (``W-SUP-001``)."""
    model = _beam((0.0, PINNED), (8.0, PINNED))
    assert free_movements(model, held_rotations=[np.eye(3)[0]]) == []


def test_torsion_hold_on_the_support_resists():
    model = _beam((0.0, PINNED), (8.0, PINNED))
    model.connections[0].torsion_hold_axes = [[1.0, 0.0, 0.0]]
    assert free_movements(model) == []


def test_plane_hold_resists_what_leaves_the_plane():
    """Held across the x-z plane, a beam on vertical supports can still
    slide along itself and spin about itself; nothing else."""
    model = _beam((0.0, VERTICAL_ONLY), (8.0, VERTICAL_ONLY))
    found = sorted(
        describe(m) for m in free_movements(model, plane_normal=np.eye(3)[1])
    )
    assert found == ["about an axis along x through (4, 0, 0) m", "along x"]


def test_rotation_off_the_middle_is_placed_on_its_axis():
    """Pinned at one end and held up at the other, a beam along x spins
    about itself and can turn about z, through the pin."""
    model = _beam((0.0, PINNED), (8.0, VERTICAL_ONLY))
    model.connections[0].torsion_hold_axes = [[1.0, 0.0, 0.0]]
    (movement,) = free_movements(model)
    assert describe(movement) == "about an axis along z through (0, 0, 0) m"


def test_nothing_without_members():
    assert free_movements(SimpleNamespace(members=[], connections=[])) == []


def _plan(supports):
    """A 6 m x 4 m floor on four columns 3 m tall, supports at their feet.

    ``supports`` gives each corner's fixity, in the order (0, 0), (6, 0),
    (6, 4), (0, 4).
    """
    corners = [(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)]
    members = [
        SimpleNamespace(geometry=[[x, y, 0.0], [x, y, 3.0]]) for x, y in corners
    ] + [
        SimpleNamespace(geometry=[[*a, 3.0], [*b, 3.0]])
        for a, b in zip(corners, corners[1:] + corners[:1])
    ]
    connections = []
    for n, ((x, y), fixity) in enumerate(zip(corners, supports)):
        connection = RigidConnection(f"c{n}", [x, y, 0.0])
        connection.set_stiffness_properties(
            dict(zip(("dx", "dy", "dz", "drx", "dry", "drz"), fixity))
        )
        connection.connect_member(f"column{n}")
        connections.append(connection)
    return SimpleNamespace(members=members, connections=connections)


def test_building_with_every_support_released_in_x():
    """Not only a beam: every column foot of a frame free along x."""
    released = (FREE, FIXED, FIXED, FIXED, FIXED, FIXED)
    (movement,) = free_movements(_plan([released] * 4))
    assert describe(movement) == "along x"


def test_building_turning_about_its_one_horizontal_restraint():
    """Held horizontally at one corner only, the plan turns about it."""
    pinned_feet = [PINNED] + [VERTICAL_ONLY] * 3
    (movement,) = free_movements(_plan(pinned_feet))
    # Through the corner, at the height of the model's middle
    assert describe(movement) == "about an axis along z through (0, 0, 2.25) m"
    # That corner stays where it is; the opposite one moves across
    translation, rotation, centre = movement
    assert np.allclose(translation + np.cross(rotation, -centre), [0, 0, 0])


def test_the_axis_is_right_whichever_way_it_is_found():
    """Pinned at the far corner: the axis there, not mirrored."""
    pinned_feet = [VERTICAL_ONLY, VERTICAL_ONLY, PINNED, VERTICAL_ONLY]
    (movement,) = free_movements(_plan(pinned_feet))
    assert describe(movement) == "about an axis along z through (6, 4, 2.25) m"


def test_building_held_horizontally_at_two_corners():
    assert free_movements(_plan([PINNED, PINNED] + [VERTICAL_ONLY] * 2)) == []
