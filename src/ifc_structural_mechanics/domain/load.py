"""
Load classes for IFC structural analysis.

This module contains the domain model classes for representing loads, load groups,
and load combinations in structural analysis.
"""

from typing import List, Dict, Optional, Union, Any
import uuid
import numpy as np

from ifc_structural_mechanics.domain.base_entity import (
    DomainEntity,
    DomainEntityCollection,
)


class Load(DomainEntity):
    """Base class for all structural loads."""

    def __init__(
        self,
        id: Optional[str] = None,
        load_type: Optional[str] = None,
        magnitude: Union[float, List[float], np.ndarray] = None,
        direction: Union[List[float], np.ndarray] = None,
    ):
        """Initialize a Load object."""
        # Validate required parameters first - before any object initialization
        if load_type is None:
            raise ValueError("Load type must be specified")

        # Set instance attributes
        self.magnitude = None
        self.direction = None

        # Initialize base entity with ID and load type
        super().__init__(
            id=id,
            entity_type=load_type,
            allow_validation_bypass=True,  # Bypass base validation until we're ready
        )

        # Handle magnitude as either a scalar or vector
        if magnitude is not None:
            if isinstance(magnitude, (list, np.ndarray)) and not isinstance(
                magnitude, (int, float)
            ):
                self.magnitude = np.array(magnitude, dtype=float)
            else:
                self.magnitude = float(magnitude)

        # Convert direction to numpy array if provided
        if direction is not None:
            self.direction = np.array(direction, dtype=float)
            # Normalize direction vector if it's not a zero vector
            norm = np.linalg.norm(self.direction)
            if norm > 0:
                self.direction = self.direction / norm

        # Now validate all properties
        self.validate()

    def validate(self) -> bool:
        """Validate the load properties."""
        # First validate base entity properties
        super().validate()

        if self.magnitude is None:
            raise ValueError("Load magnitude must be specified")

        if self.direction is None:
            raise ValueError("Load direction must be specified")

        # If direction is provided, ensure it's a valid vector
        if isinstance(self.direction, np.ndarray):
            if self.direction.size not in (2, 3):
                raise ValueError("Direction must be a 2D or 3D vector")

        return True

    def get_force_vector(self) -> np.ndarray:
        """Calculate the force vector by multiplying magnitude and direction."""
        if isinstance(self.magnitude, (int, float)):
            return self.magnitude * self.direction
        else:
            # If magnitude is already a vector, return it directly
            return self.magnitude

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the load to a dictionary representation.

        Returns:
            Dictionary representation of the load.
        """
        result = super().as_dict()

        # Add load-specific properties
        if isinstance(self.magnitude, np.ndarray):
            result["magnitude"] = self.magnitude.tolist()
        else:
            result["magnitude"] = self.magnitude

        if isinstance(self.direction, np.ndarray):
            result["direction"] = self.direction.tolist()
        else:
            result["direction"] = self.direction

        return result


class PointLoad(Load):
    """A load applied at a single point."""

    def __init__(
        self,
        id: Optional[str] = None,
        magnitude: Union[float, List[float], np.ndarray] = None,
        direction: Union[List[float], np.ndarray] = None,
        position: Union[List[float], np.ndarray] = None,
    ):
        """Initialize a PointLoad object."""
        # Validate required position parameter first
        if position is None:
            raise ValueError("Point load position must be specified")

        # Validate position size
        if isinstance(position, (list, np.ndarray)) and len(position) != 3:
            raise ValueError("Position must be a 3D vector")

        # Set position attribute
        if isinstance(position, (list, np.ndarray)):
            self.position = tuple(position)
        else:
            self.position = position

        # Initialize base attributes through parent constructor
        super().__init__(
            id=id, load_type="point", magnitude=magnitude, direction=direction
        )

    def validate(self) -> bool:
        """Validate the point load properties."""
        # Validate base load properties
        super().validate()

        if self.position is None:
            raise ValueError("Point load position must be specified")

        if len(self.position) != 3:
            raise ValueError("Position must be a 3D vector")

        return True

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the point load to a dictionary representation.

        Returns:
            Dictionary representation of the point load.
        """
        result = super().as_dict()

        # Add point load-specific properties
        if isinstance(self.position, np.ndarray):
            result["position"] = self.position.tolist()
        else:
            result["position"] = self.position

        return result


class LineLoad(Load):
    """A load applied along a line segment."""

    def __init__(
        self,
        id: Optional[str] = None,
        magnitude: Union[float, List[float], np.ndarray] = None,
        direction: Union[List[float], np.ndarray] = None,
        start_position: Union[List[float], np.ndarray] = None,
        end_position: Union[List[float], np.ndarray] = None,
        distribution: str = "uniform",
        start_magnitude: Union[float, List[float], np.ndarray] = None,
        end_magnitude: Union[float, List[float], np.ndarray] = None,
    ):
        """Initialize a LineLoad object."""
        # Validate required parameters first
        if start_position is None:
            raise ValueError("Line load start position must be specified")

        if end_position is None:
            raise ValueError("Line load end position must be specified")

        if distribution not in ["uniform", "linear", "custom"]:
            raise ValueError("Distribution must be 'uniform', 'linear', or 'custom'")

        if distribution == "linear":
            if start_magnitude is None:
                raise ValueError(
                    "Start magnitude must be specified for linear distribution"
                )

            if end_magnitude is None:
                raise ValueError(
                    "End magnitude must be specified for linear distribution"
                )

        # Set line-specific attributes
        if isinstance(start_position, (list, np.ndarray)) and len(start_position) != 3:
            raise ValueError("Start position must be a 3D vector")

        if isinstance(start_position, (list, np.ndarray)):
            self.start_position = tuple(start_position)
        else:
            self.start_position = start_position

        if isinstance(end_position, (list, np.ndarray)) and len(end_position) != 3:
            raise ValueError("End position must be a 3D vector")

        if isinstance(end_position, (list, np.ndarray)):
            self.end_position = tuple(end_position)
        else:
            self.end_position = end_position

        self.distribution = distribution
        self._explicit_start_magnitude = start_magnitude is not None
        self._explicit_end_magnitude = end_magnitude is not None

        # For linear distribution, store start and end magnitudes
        self.start_magnitude = None
        self.end_magnitude = None

        if distribution == "linear":
            if start_magnitude is not None:
                if isinstance(start_magnitude, (list, np.ndarray)):
                    self.start_magnitude = np.array(start_magnitude, dtype=float)
                else:
                    self.start_magnitude = float(start_magnitude)

            if end_magnitude is not None:
                if isinstance(end_magnitude, (list, np.ndarray)):
                    self.end_magnitude = np.array(end_magnitude, dtype=float)
                else:
                    self.end_magnitude = float(end_magnitude)

        # Initialize base attributes through parent constructor
        super().__init__(
            id=id, load_type="line", magnitude=magnitude, direction=direction
        )

        # Now set start/end magnitude if they weren't explicitly provided
        if distribution == "linear":
            if self.start_magnitude is None:
                self.start_magnitude = self.magnitude
            if self.end_magnitude is None:
                self.end_magnitude = self.magnitude

    def validate(self) -> bool:
        """Validate the line load properties."""
        # Validate base load properties
        super().validate()

        if self.start_position is None:
            raise ValueError("Line load start position must be specified")

        if self.end_position is None:
            raise ValueError("Line load end position must be specified")

        if len(self.start_position) != 3:
            raise ValueError("Start position must be a 3D vector")

        if len(self.end_position) != 3:
            raise ValueError("End position must be a 3D vector")

        if self.distribution not in ["uniform", "linear", "custom"]:
            raise ValueError("Distribution must be 'uniform', 'linear', or 'custom'")

        if self.distribution == "linear":
            if not self._explicit_start_magnitude:
                raise ValueError(
                    "Start magnitude must be specified for linear distribution"
                )

            if not self._explicit_end_magnitude:
                raise ValueError(
                    "End magnitude must be specified for linear distribution"
                )

        return True

    def get_length(self) -> float:
        """Calculate the length of the line segment."""
        return np.linalg.norm(
            np.array(self.end_position) - np.array(self.start_position)
        )

    def get_magnitude_at(self, position: float) -> float:
        """Calculate the magnitude at a position along the line."""
        if not 0 <= position <= 1:
            raise ValueError("Position must be between 0 and 1")

        if self.distribution == "uniform":
            return self.magnitude
        elif self.distribution == "linear":
            return self.start_magnitude + position * (
                self.end_magnitude - self.start_magnitude
            )
        else:
            raise NotImplementedError("Custom distribution not yet implemented")

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the line load to a dictionary representation.

        Returns:
            Dictionary representation of the line load.
        """
        result = super().as_dict()

        # Add line load-specific properties
        result["distribution"] = self.distribution

        if isinstance(self.start_position, np.ndarray):
            result["start_position"] = self.start_position.tolist()
        else:
            result["start_position"] = self.start_position

        if isinstance(self.end_position, np.ndarray):
            result["end_position"] = self.end_position.tolist()
        else:
            result["end_position"] = self.end_position

        if self.distribution == "linear":
            if isinstance(self.start_magnitude, np.ndarray):
                result["start_magnitude"] = self.start_magnitude.tolist()
            else:
                result["start_magnitude"] = self.start_magnitude

            if isinstance(self.end_magnitude, np.ndarray):
                result["end_magnitude"] = self.end_magnitude.tolist()
            else:
                result["end_magnitude"] = self.end_magnitude

        return result


class AreaLoad(Load):
    """A load applied over a surface area."""

    def __init__(
        self,
        id: Optional[str] = None,
        magnitude: Union[float, List[float], np.ndarray] = None,
        direction: Union[List[float], np.ndarray] = None,
        surface_reference: str = None,
        distribution: str = "uniform",
    ):
        """Initialize an AreaLoad object."""
        # Validate required parameters first
        if surface_reference is None:
            raise ValueError("Area load surface reference must be specified")

        if distribution not in ["uniform", "custom"]:
            raise ValueError("Distribution must be 'uniform' or 'custom'")

        # Set area-specific attributes
        self.surface_reference = surface_reference
        self.distribution = distribution

        # Initialize base attributes through parent constructor
        super().__init__(
            id=id, load_type="area", magnitude=magnitude, direction=direction
        )

    def validate(self) -> bool:
        """Validate the area load properties."""
        # Validate base load properties
        super().validate()

        if self.surface_reference is None:
            raise ValueError("Area load surface reference must be specified")

        if self.distribution not in ["uniform", "custom"]:
            raise ValueError("Distribution must be 'uniform' or 'custom'")

        return True

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the area load to a dictionary representation.

        Returns:
            Dictionary representation of the area load.
        """
        result = super().as_dict()

        # Add area load-specific properties
        result["surface_reference"] = self.surface_reference
        result["distribution"] = self.distribution

        return result


class LoadGroup(DomainEntity):
    """A group of loads that are applied together."""

    def __init__(
        self,
        id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        loads: Optional[List[Load]] = None,
    ):
        """Initialize a LoadGroup object."""
        # Initialize base entity
        super().__init__(id=id, entity_type="load_group")

        # Set load group specific attributes
        self.name = name if name is not None else f"LoadGroup-{self.id[:8]}"
        self.description = description
        self.loads = loads if loads is not None else []

    def add_load(self, load: Load) -> None:
        """Add a load to the group."""
        if load not in self.loads:
            self.loads.append(load)

    def remove_load(self, load: Load) -> bool:
        """Remove a load from the group."""
        if load in self.loads:
            self.loads.remove(load)
            return True
        return False

    def get_load_by_id(self, load_id: str) -> Optional[Load]:
        """Get a load by its ID."""
        for load in self.loads:
            if load.id == load_id:
                return load
        return None

    def clear(self) -> None:
        """Remove all loads from the group."""
        self.loads.clear()

    def __len__(self) -> int:
        """Get the number of loads in the group."""
        return len(self.loads)

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the load group to a dictionary representation.

        Returns:
            Dictionary representation of the load group.
        """
        result = super().as_dict()

        # Add load group specific properties
        result["name"] = self.name
        if self.description:
            result["description"] = self.description
        result["loads"] = [load.as_dict() for load in self.loads]

        return result


class LoadCombination(DomainEntity):
    """A combination of load groups with factors."""

    def __init__(
        self,
        id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        load_groups: Optional[Dict[str, float]] = None,
    ):
        """Initialize a LoadCombination object."""
        # Initialize base entity
        super().__init__(id=id, entity_type="load_combination")

        # Set load combination specific attributes
        self.name = name if name is not None else f"Combination-{self.id[:8]}"
        self.description = description
        self.load_groups = load_groups if load_groups is not None else {}

    def add_load_group(
        self, load_group: Union[LoadGroup, str], factor: float = 1.0
    ) -> None:
        """Add a load group to the combination with a factor."""
        load_group_id = (
            load_group.id if isinstance(load_group, LoadGroup) else load_group
        )
        self.load_groups[load_group_id] = factor

    def remove_load_group(self, load_group: Union[LoadGroup, str]) -> bool:
        """Remove a load group from the combination."""
        load_group_id = (
            load_group.id if isinstance(load_group, LoadGroup) else load_group
        )
        if load_group_id in self.load_groups:
            del self.load_groups[load_group_id]
            return True
        return False

    def get_factor(self, load_group: Union[LoadGroup, str]) -> Optional[float]:
        """Get the factor for a load group."""
        load_group_id = (
            load_group.id if isinstance(load_group, LoadGroup) else load_group
        )
        return self.load_groups.get(load_group_id)

    def update_factor(self, load_group: Union[LoadGroup, str], factor: float) -> bool:
        """Update the factor for a load group."""
        load_group_id = (
            load_group.id if isinstance(load_group, LoadGroup) else load_group
        )
        if load_group_id in self.load_groups:
            self.load_groups[load_group_id] = factor
            return True
        return False

    def clear(self) -> None:
        """Remove all load groups from the combination."""
        self.load_groups.clear()

    def __len__(self) -> int:
        """Get the number of load groups in the combination."""
        return len(self.load_groups)

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the load combination to a dictionary representation.

        Returns:
            Dictionary representation of the load combination.
        """
        result = super().as_dict()

        # Add load combination specific properties
        result["name"] = self.name
        if self.description:
            result["description"] = self.description
        result["load_groups"] = self.load_groups.copy()

        return result
