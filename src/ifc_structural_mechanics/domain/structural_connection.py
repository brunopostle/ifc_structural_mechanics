"""
Structural connection classes for the IFC structural analysis extension.

This module provides classes for representing different types of structural connections
in the domain model. These connections define how structural members are connected
to each other.
"""

from typing import List, Optional, Dict, Any

from ifc_structural_mechanics.domain.base_entity import DomainEntity


class StructuralConnection(DomainEntity):
    """Base class for structural connections between members."""

    def __init__(self, id: str, connection_type: str):
        """
        Initialize a structural connection.

        Args:
            id: Unique identifier for the connection
            connection_type: Type of connection (e.g., "point", "rigid", "hinge")
        """
        # Initialize instance variables first
        self.connected_members: List[str] = []  # List of member IDs

        # Then call parent constructor
        super().__init__(id=id, entity_type=connection_type)

    def connect_member(self, member_id: str) -> None:
        """
        Connect a member to this connection.

        Args:
            member_id: ID of the member to connect
        """
        if member_id not in self.connected_members:
            self.connected_members.append(member_id)

    def disconnect_member(self, member_id: str) -> None:
        """
        Disconnect a member from this connection.

        Args:
            member_id: ID of the member to disconnect
        """
        if member_id in self.connected_members:
            self.connected_members.remove(member_id)

    def is_connected_to(self, member_id: str) -> bool:
        """
        Check if a member is connected to this connection.

        Args:
            member_id: ID of the member to check

        Returns:
            True if the member is connected, False otherwise
        """
        return member_id in self.connected_members

    def validate(self) -> bool:
        """
        Validate the connection.

        Returns:
            True if the connection is valid, False otherwise
        """
        # First validate the base entity properties
        super().validate()

        # Base validation: check if we have at least two connected members
        return len(self.connected_members) >= 2

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the connection to a dictionary representation.

        Returns:
            Dictionary representation of the connection.
        """
        result = super().as_dict()
        result["connected_members"] = self.connected_members.copy()
        return result


class PointConnection(StructuralConnection):
    """
    A point connection between structural members.

    Point connections represent connections at a single point in space,
    such as where beams meet at a single point.
    """

    def __init__(self, id: str, position: List[float]):
        """
        Initialize a point connection.

        Args:
            id: Unique identifier for the connection
            position: 3D coordinates [x, y, z] of the connection point
        """
        # Initialize instance variables first
        self.position = position

        # Then call parent constructor
        super().__init__(id, "point")

    def validate(self) -> bool:
        """
        Validate the point connection.

        Returns:
            True if the connection is valid, False otherwise
        """
        base_valid = super().validate()
        position_valid = len(self.position) == 3 and all(
            isinstance(p, (int, float)) for p in self.position
        )
        return base_valid and position_valid

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the point connection to a dictionary representation.

        Returns:
            Dictionary representation of the point connection.
        """
        result = super().as_dict()
        result["position"] = self.position
        return result


class RigidConnection(StructuralConnection):
    """
    A rigid connection between structural members.

    Rigid connections transfer all forces and moments between the connected members,
    with no relative displacement or rotation allowed.
    """

    def __init__(self, id: str, position: Optional[List[float]] = None):
        """
        Initialize a rigid connection.

        Args:
            id: Unique identifier for the connection
            position: Optional 3D coordinates [x, y, z] of the connection point
        """
        # Initialize instance variables first
        self.position = position

        # Then call parent constructor
        super().__init__(id, "rigid")

    def validate(self) -> bool:
        """
        Validate the rigid connection.

        Returns:
            True if the connection is valid, False otherwise
        """
        base_valid = super().validate()
        position_valid = True

        if self.position is not None:
            position_valid = len(self.position) == 3 and all(
                isinstance(p, (int, float)) for p in self.position
            )

        return base_valid and position_valid

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the rigid connection to a dictionary representation.

        Returns:
            Dictionary representation of the rigid connection.
        """
        result = super().as_dict()
        if self.position is not None:
            result["position"] = self.position
        return result


class HingeConnection(StructuralConnection):
    """
    A hinge connection between structural members.

    Hinge connections transfer forces but allow relative rotation between
    the connected members.
    """

    def __init__(
        self,
        id: str,
        position: List[float],
        rotation_axis: Optional[List[float]] = None,
    ):
        """
        Initialize a hinge connection.

        Args:
            id: Unique identifier for the connection
            position: 3D coordinates [x, y, z] of the connection point
            rotation_axis: Optional 3D vector [x, y, z] defining the axis of rotation
        """
        # Initialize instance variables first
        self.position = position
        self.rotation_axis = rotation_axis

        # Then call parent constructor
        super().__init__(id, "hinge")

    def validate(self) -> bool:
        """
        Validate the hinge connection.

        Returns:
            True if the connection is valid, False otherwise
        """
        base_valid = super().validate()
        position_valid = len(self.position) == 3 and all(
            isinstance(p, (int, float)) for p in self.position
        )

        axis_valid = True
        if self.rotation_axis is not None:
            axis_valid = len(self.rotation_axis) == 3 and all(
                isinstance(a, (int, float)) for a in self.rotation_axis
            )

        return base_valid and position_valid and axis_valid

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the hinge connection to a dictionary representation.

        Returns:
            Dictionary representation of the hinge connection.
        """
        result = super().as_dict()
        result["position"] = self.position
        if self.rotation_axis is not None:
            result["rotation_axis"] = self.rotation_axis
        return result
