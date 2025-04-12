"""Structural model domain class.

This module defines the core StructuralModel class that serves as the
container for all structural elements, connections, loads, and properties.
"""

from typing import Optional


class StructuralModel:
    """Container for a complete structural analysis model.

    The StructuralModel serves as the central container for all entities
    in a structural analysis model, including members, connections, loads,
    load combinations, and analysis results.

    Attributes:
        id: Unique identifier for the model
        name: Optional name for the model
        description: Optional description of the model
        members: List of structural members in the model
        connections: List of structural connections in the model
        load_groups: List of load groups in the model
        load_combinations: List of load combinations in the model
        results: List of analysis results for the model
    """

    def __init__(
        self, id: str, name: Optional[str] = None, description: Optional[str] = None
    ):
        """Initialize a new StructuralModel.

        Args:
            id: Unique identifier for the model
            name: Optional name for the model
            description: Optional description of the model
        """
        self.id = id
        self.name = name
        self.description = description
        self.members = []  # Structural members
        self.connections = []  # Structural connections
        self.load_groups = []  # Load groups
        self.load_combinations = []  # Load combinations
        self.results = []  # Analysis results

    def add_member(self, member) -> None:
        """Add a structural member to the model.

        Args:
            member: The structural member to add
        """
        self.members.append(member)

    def add_connection(self, connection) -> None:
        """Add a structural connection to the model.

        Args:
            connection: The structural connection to add
        """
        self.connections.append(connection)

    def add_load_group(self, load_group) -> None:
        """Add a load group to the model.

        Args:
            load_group: The load group to add
        """
        self.load_groups.append(load_group)

    def add_load_combination(self, load_combination) -> None:
        """Add a load combination to the model.

        Args:
            load_combination: The load combination to add
        """
        self.load_combinations.append(load_combination)

    def add_result(self, result) -> None:
        """Add an analysis result to the model.

        Args:
            result: The analysis result to add
        """
        self.results.append(result)

    def get_member_by_id(self, member_id: str):
        """Get a structural member by its ID.

        Args:
            member_id: The ID of the member to retrieve

        Returns:
            The structural member with the given ID, or None if not found
        """
        for member in self.members:
            if member.id == member_id:
                return member
        return None

    def get_connection_by_id(self, connection_id: str):
        """Get a structural connection by its ID.

        Args:
            connection_id: The ID of the connection to retrieve

        Returns:
            The structural connection with the given ID, or None if not found
        """
        for connection in self.connections:
            if connection.id == connection_id:
                return connection
        return None

    def get_load_group_by_id(self, load_group_id: str):
        """Get a load group by its ID.

        Args:
            load_group_id: The ID of the load group to retrieve

        Returns:
            The load group with the given ID, or None if not found
        """
        for load_group in self.load_groups:
            if load_group.id == load_group_id:
                return load_group
        return None

    def get_load_combination_by_id(self, load_combination_id: str):
        """Get a load combination by its ID.

        Args:
            load_combination_id: The ID of the load combination to retrieve

        Returns:
            The load combination with the given ID, or None if not found
        """
        for load_combination in self.load_combinations:
            if load_combination.id == load_combination_id:
                return load_combination
        return None

    def __repr__(self) -> str:
        """Return a string representation of the model.

        Returns:
            A string representation of the model
        """
        return (
            f"StructuralModel(id={self.id}, name={self.name}, "
            f"members={len(self.members)}, connections={len(self.connections)}, "
            f"load_groups={len(self.load_groups)}, "
            f"load_combinations={len(self.load_combinations)}, "
            f"results={len(self.results)})"
        )
