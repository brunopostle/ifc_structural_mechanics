"""Helpers shared by tests that build a domain model by hand."""

from ifc_structural_mechanics.domain.structural_connection import RigidConnection

RIGID = 1e20


def fixed_support(position, member_id, connection_id="support"):
    """A fully fixed support holding one member.

    A model without a support cannot be analysed, and the writer no longer
    invents one (it used to fix every node at y = 0).
    """
    support = RigidConnection(connection_id, [float(c) for c in position])
    support.set_stiffness_properties(
        {key: RIGID for key in ("dx", "dy", "dz", "drx", "dry", "drz")}
    )
    support.connect_member(member_id)
    return support
