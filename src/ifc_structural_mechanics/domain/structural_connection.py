"""
Structural connection classes for the IFC structural analysis extension.

This module provides classes for representing different types of structural connections
in the domain model. These connections define how structural members are connected
to each other.
"""

import logging
from typing import Any, Dict, List, Optional

from ifc_structural_mechanics.domain.base_entity import DomainEntity


class StructuralConnection(DomainEntity):
    """Base class for structural connections between members with stiffness support."""

    def __init__(self, id: str, connection_type: str, ifc_guid: Optional[str] = None):
        """
        Initialize a structural connection.

        Args:
            id: Unique identifier for the connection
            connection_type: Type of connection (e.g., "point", "rigid", "hinge")
            ifc_guid: IFC GlobalId for traceability to source model
        """
        # Initialize instance variables first
        self.connected_members: List[str] = []  # List of member IDs
        self.stiffness_properties: Optional[Dict[str, float]] = None

        # NEW: Traceability fields for error propagation
        self.ifc_guid: Optional[str] = ifc_guid
        self.mesh_entity_ids: List[str] = []
        self.analysis_element_ids: List[int] = []

        # Then call parent constructor - bypass validation until members are connected
        super().__init__(
            id=id, entity_type=connection_type, allow_validation_bypass=True
        )

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

    def set_stiffness_properties(self, stiffness: Dict[str, float]) -> None:
        """
        Set connection stiffness properties.

        Args:
            stiffness: Dictionary of stiffness values in SI units
        """
        self.stiffness_properties = stiffness.copy() if stiffness else None

    def get_stiffness_properties(self) -> Optional[Dict[str, float]]:
        """
        Get connection stiffness properties.

        Returns:
            Dictionary of stiffness values in SI units, or None if not set
        """
        return self.stiffness_properties.copy() if self.stiffness_properties else None

    def has_stiffness_properties(self) -> bool:
        """
        Check if connection has stiffness properties.

        Returns:
            True if stiffness properties are defined, False otherwise
        """
        return (
            self.stiffness_properties is not None and len(self.stiffness_properties) > 0
        )

    def is_rigid_behavior(self) -> bool:
        """
        Check if connection behaves as rigid based on stiffness properties.

        Returns:
            True if all stiffness values are very high (rigid), False otherwise
        """
        if not self.has_stiffness_properties():
            return self.entity_type == "rigid"

        rigid_threshold = 1e12
        translational_keys = ["dx", "dy", "dz"]

        for key in translational_keys:
            if key in self.stiffness_properties:
                if self.stiffness_properties[key] < rigid_threshold:
                    return False
        return True

    def is_pinned_behavior(self) -> bool:
        """
        Check if connection behaves as pinned (no rotational stiffness).

        Returns:
            True if rotational stiffness is very low, False otherwise
        """
        if not self.has_stiffness_properties():
            return self.entity_type == "hinge"

        pinned_threshold = 1e3
        rotational_keys = ["drx", "dry", "drz"]

        for key in rotational_keys:
            if key in self.stiffness_properties:
                if self.stiffness_properties[key] > pinned_threshold:
                    return False
        return True

    def get_stiffness_unit(self, stiffness_key: str) -> str:
        """Get the appropriate unit for a stiffness property."""
        if stiffness_key in ["dx", "dy", "dz"]:
            return "N/m"
        elif stiffness_key in ["drx", "dry", "drz"]:
            return "N⋅m/rad"
        else:
            return ""

    def validate(self) -> bool:
        """
        Validate the connection with enhanced debugging.

        Returns:
            True if the connection is valid, False otherwise
        """
        logger = logging.getLogger(__name__)

        # SAFE BASE VALIDATION
        base_valid = True
        try:
            super().validate()
            logger.debug(f"Connection {self.id}: Base validation passed")
        except Exception as e:
            logger.debug(f"Connection {self.id}: Base validation failed (handled): {e}")
            base_valid = True  # We handle this gracefully

        # MEMBERS VALIDATION
        members_count = len(self.connected_members)
        members_valid = members_count >= 2
        logger.debug(
            f"Connection {self.id}: Members validation - count={members_count}, valid={members_valid}"
        )

        # STIFFNESS VALIDATION with detailed debugging
        stiffness_valid = True
        if self.stiffness_properties:
            logger.debug(
                f"Connection {self.id}: Validating stiffness properties: {self.stiffness_properties}"
            )

            for key, value in self.stiffness_properties.items():
                logger.debug(
                    f"Connection {self.id}: Checking stiffness {key}={value} (type: {type(value)})"
                )

                # Check if value is a number
                if not isinstance(value, (int, float)):
                    logger.error(
                        f"Connection {self.id}: Stiffness {key} is not numeric: {value} (type: {type(value)})"
                    )
                    stiffness_valid = False
                    break

                # Check for special float values
                if isinstance(value, float):
                    import math

                    if math.isnan(value):
                        logger.error(f"Connection {self.id}: Stiffness {key} is NaN")
                        stiffness_valid = False
                        break
                    if math.isinf(value):
                        logger.error(
                            f"Connection {self.id}: Stiffness {key} is infinite"
                        )
                        stiffness_valid = False
                        break

                # Check reasonable range
                if not (-1e20 <= value <= 1e20):
                    logger.error(
                        f"Connection {self.id}: Stiffness {key} out of range: {value}"
                    )
                    stiffness_valid = False
                    break

            logger.debug(
                f"Connection {self.id}: Stiffness validation result: {stiffness_valid}"
            )
        else:
            logger.debug(f"Connection {self.id}: No stiffness properties to validate")

        # OVERALL RESULT
        overall_valid = base_valid and members_valid and stiffness_valid
        logger.debug(
            f"Connection {self.id}: Overall validation - base={base_valid}, members={members_valid}, stiffness={stiffness_valid}, result={overall_valid}"
        )

        if not overall_valid:
            logger.error(f"Connection {self.id}: VALIDATION FAILED")
            logger.error(f"  - Base valid: {base_valid}")
            logger.error(f"  - Members valid: {members_valid} (count: {members_count})")
            logger.error(f"  - Stiffness valid: {stiffness_valid}")
            if self.stiffness_properties:
                logger.error(f"  - Stiffness data: {self.stiffness_properties}")

        return overall_valid

    def as_dict(self) -> Dict[str, Any]:
        """Convert the connection to a dictionary representation."""
        result = super().as_dict()
        result["connected_members"] = self.connected_members.copy()

        if self.has_stiffness_properties():
            result["stiffness_properties"] = self.get_stiffness_properties()
            result["behavior_analysis"] = {
                "is_rigid": self.is_rigid_behavior(),
                "is_pinned": self.is_pinned_behavior(),
                "has_stiffness": self.has_stiffness_properties(),
            }

        return result

    def __str__(self):
        stiffness_info = ""
        if self.has_stiffness_properties():
            stiffness_info = f", stiffness: {self.stiffness_properties}"
        return f"{self.entity_type} connection {self.id} ({len(self.connected_members)} members){stiffness_info}"


class PointConnection(StructuralConnection):
    """A point connection between structural members."""

    def __init__(self, id: str, position: List[float], ifc_guid: Optional[str] = None):
        self.position = position
        super().__init__(id, "point", ifc_guid)

    def validate(self) -> bool:
        base_valid = super().validate()
        position_valid = (
            isinstance(self.position, list)
            and len(self.position) == 3
            and all(isinstance(p, (int, float)) for p in self.position)
        )
        return base_valid and position_valid

    def as_dict(self) -> Dict[str, Any]:
        result = super().as_dict()
        result["position"] = self.position
        return result


class RigidConnection(StructuralConnection):
    """A rigid connection between structural members."""

    def __init__(
        self,
        id: str,
        position: Optional[List[float]] = None,
        ifc_guid: Optional[str] = None,
    ):
        self.position = position
        super().__init__(id, "rigid", ifc_guid)

    def validate(self) -> bool:
        base_valid = super().validate()
        position_valid = True

        if self.position is not None:
            position_valid = (
                isinstance(self.position, list)
                and len(self.position) == 3
                and all(isinstance(p, (int, float)) for p in self.position)
            )

        return base_valid and position_valid

    def as_dict(self) -> Dict[str, Any]:
        result = super().as_dict()
        if self.position is not None:
            result["position"] = self.position
        return result


class HingeConnection(StructuralConnection):
    """A hinge connection between structural members."""

    def __init__(
        self,
        id: str,
        position: List[float],
        rotation_axis: Optional[List[float]] = None,
        ifc_guid: Optional[str] = None,
    ):
        self.position = position
        self.rotation_axis = rotation_axis
        super().__init__(id, "hinge", ifc_guid)

    def validate(self) -> bool:
        base_valid = super().validate()
        position_valid = (
            isinstance(self.position, list)
            and len(self.position) == 3
            and all(isinstance(p, (int, float)) for p in self.position)
        )

        axis_valid = True
        if self.rotation_axis is not None:
            axis_valid = (
                isinstance(self.rotation_axis, list)
                and len(self.rotation_axis) == 3
                and all(isinstance(a, (int, float)) for a in self.rotation_axis)
            )

        return base_valid and position_valid and axis_valid

    def as_dict(self) -> Dict[str, Any]:
        result = super().as_dict()
        result["position"] = self.position
        if self.rotation_axis is not None:
            result["rotation_axis"] = self.rotation_axis
        return result


class SpringConnection(StructuralConnection):
    """A spring connection with explicit stiffness properties."""

    def __init__(
        self,
        id: str,
        position: List[float],
        stiffness: Dict[str, float],
        ifc_guid: Optional[str] = None,
    ):
        self.position = position
        super().__init__(id, "spring", ifc_guid)
        self.set_stiffness_properties(stiffness)

    def get_translational_stiffness(self) -> Dict[str, float]:
        if not self.stiffness_properties:
            return {}
        return {
            k: v
            for k, v in self.stiffness_properties.items()
            if k in ["dx", "dy", "dz"]
        }

    def get_rotational_stiffness(self) -> Dict[str, float]:
        if not self.stiffness_properties:
            return {}
        return {
            k: v
            for k, v in self.stiffness_properties.items()
            if k in ["drx", "dry", "drz"]
        }

    def validate(self) -> bool:
        base_valid = super().validate()
        position_valid = (
            isinstance(self.position, list)
            and len(self.position) == 3
            and all(isinstance(p, (int, float)) for p in self.position)
        )
        stiffness_valid = self.has_stiffness_properties()
        return base_valid and position_valid and stiffness_valid

    def as_dict(self) -> Dict[str, Any]:
        result = super().as_dict()
        result["position"] = self.position
        result["translational_stiffness"] = self.get_translational_stiffness()
        result["rotational_stiffness"] = self.get_rotational_stiffness()
        return result


def create_connection_from_stiffness(
    connection_id: str,
    position: List[float],
    stiffness: Optional[Dict[str, float]] = None,
    connection_type: Optional[str] = None,
    ifc_guid: Optional[str] = None,
) -> StructuralConnection:
    """Create appropriate connection type based on stiffness properties."""

    # Ensure position is valid
    if not isinstance(position, list) or len(position) != 3:
        position = [0.0, 0.0, 0.0]
    position = [float(p) if p is not None else 0.0 for p in position]

    # If explicit type is provided, use it
    if connection_type:
        if connection_type == "rigid":
            conn = RigidConnection(connection_id, position, ifc_guid)
        elif connection_type == "hinge":
            conn = HingeConnection(connection_id, position, ifc_guid=ifc_guid)
        elif connection_type == "spring":
            if stiffness:
                conn = SpringConnection(connection_id, position, stiffness, ifc_guid)
            else:
                conn = PointConnection(connection_id, position, ifc_guid)
        else:
            conn = PointConnection(connection_id, position, ifc_guid)

        if stiffness:
            conn.set_stiffness_properties(stiffness)
        return conn

    # Auto-detect based on stiffness properties
    if not stiffness:
        return PointConnection(connection_id, position, ifc_guid)

    # Create spring connection and analyze behavior
    spring_conn = SpringConnection(connection_id, position, stiffness, ifc_guid)

    if spring_conn.is_rigid_behavior():
        rigid_conn = RigidConnection(connection_id, position, ifc_guid)
        rigid_conn.set_stiffness_properties(stiffness)
        return rigid_conn
    elif spring_conn.is_pinned_behavior():
        hinge_conn = HingeConnection(connection_id, position, [0.0, 0.0, 1.0], ifc_guid)
        hinge_conn.set_stiffness_properties(stiffness)
        return hinge_conn

    return spring_conn
