"""
Domain model for structural analysis.

This module contains the StructuralModel class which serves as the container for
all structural elements, connections, loads, and other entities in the structural
analysis model.
"""

from typing import List, Optional


class StructuralModel:
    """
    Container for a complete structural analysis model.

    The StructuralModel class serves as the main container for all structural elements,
    connections, loads, and other entities in the structural analysis model. It provides
    methods for adding and removing elements, as well as accessing them by ID.

    Attributes:
        id (str): Unique identifier for the model.
        name (Optional[str]): Name of the model.
        description (Optional[str]): Description of the model.
        members (List): List of structural members in the model.
        connections (List): List of structural connections in the model.
        load_groups (List): List of load groups in the model.
        load_combinations (List): List of load combinations in the model.
        results (List): List of analysis results for the model.
    """

    def __init__(
        self, id: str, name: Optional[str] = None, description: Optional[str] = None
    ):
        """
        Initialize a new StructuralModel.

        Args:
            id (str): Unique identifier for the model.
            name (Optional[str], optional): Name of the model. Defaults to None.
            description (Optional[str], optional): Description of the model. Defaults to None.

        Raises:
            ValueError: If id is empty or None.
        """
        if not id:
            raise ValueError("Model ID cannot be empty or None")

        self.id = id
        self.name = name
        self.description = description
        self.members = []
        self.connections = []
        self.load_groups = []
        self.load_combinations = []
        self.results = []

    def add_member(self, member) -> None:
        """
        Add a structural member to the model.

        Args:
            member: The structural member to add.

        Raises:
            ValueError: If a member with the same ID already exists in the model.
        """
        if self._get_element_by_id(self.members, member.id) is not None:
            raise ValueError(
                f"Member with ID '{member.id}' already exists in the model"
            )

        self.members.append(member)

    def remove_member(self, member_id: str) -> bool:
        """
        Remove a structural member from the model by its ID.

        Args:
            member_id (str): The ID of the member to remove.

        Returns:
            bool: True if the member was found and removed, False otherwise.
        """
        return self._remove_element_by_id(self.members, member_id)

    def get_member(self, member_id: str):
        """
        Get a structural member by its ID.

        Args:
            member_id (str): The ID of the member to get.

        Returns:
            The member if found, None otherwise.
        """
        return self._get_element_by_id(self.members, member_id)

    def add_connection(self, connection) -> None:
        """
        Add a structural connection to the model.

        Args:
            connection: The structural connection to add.

        Raises:
            ValueError: If a connection with the same ID already exists in the model.
        """
        if self._get_element_by_id(self.connections, connection.id) is not None:
            raise ValueError(
                f"Connection with ID '{connection.id}' already exists in the model"
            )

        self.connections.append(connection)

    def remove_connection(self, connection_id: str) -> bool:
        """
        Remove a structural connection from the model by its ID.

        Args:
            connection_id (str): The ID of the connection to remove.

        Returns:
            bool: True if the connection was found and removed, False otherwise.
        """
        return self._remove_element_by_id(self.connections, connection_id)

    def get_connection(self, connection_id: str):
        """
        Get a structural connection by its ID.

        Args:
            connection_id (str): The ID of the connection to get.

        Returns:
            The connection if found, None otherwise.
        """
        return self._get_element_by_id(self.connections, connection_id)

    def add_load_group(self, load_group) -> None:
        """
        Add a load group to the model.

        Args:
            load_group: The load group to add.

        Raises:
            ValueError: If a load group with the same ID already exists in the model.
        """
        if self._get_element_by_id(self.load_groups, load_group.id) is not None:
            raise ValueError(
                f"Load group with ID '{load_group.id}' already exists in the model"
            )

        self.load_groups.append(load_group)

    def remove_load_group(self, load_group_id: str) -> bool:
        """
        Remove a load group from the model by its ID.

        Args:
            load_group_id (str): The ID of the load group to remove.

        Returns:
            bool: True if the load group was found and removed, False otherwise.
        """
        return self._remove_element_by_id(self.load_groups, load_group_id)

    def get_load_group(self, load_group_id: str):
        """
        Get a load group by its ID.

        Args:
            load_group_id (str): The ID of the load group to get.

        Returns:
            The load group if found, None otherwise.
        """
        return self._get_element_by_id(self.load_groups, load_group_id)

    def add_load_combination(self, load_combination) -> None:
        """
        Add a load combination to the model.

        Args:
            load_combination: The load combination to add.

        Raises:
            ValueError: If a load combination with the same ID already exists in the model.
        """
        if (
            self._get_element_by_id(self.load_combinations, load_combination.id)
            is not None
        ):
            raise ValueError(
                f"Load combination with ID '{load_combination.id}' already exists in the model"
            )

        self.load_combinations.append(load_combination)

    def remove_load_combination(self, load_combination_id: str) -> bool:
        """
        Remove a load combination from the model by its ID.

        Args:
            load_combination_id (str): The ID of the load combination to remove.

        Returns:
            bool: True if the load combination was found and removed, False otherwise.
        """
        return self._remove_element_by_id(self.load_combinations, load_combination_id)

    def get_load_combination(self, load_combination_id: str):
        """
        Get a load combination by its ID.

        Args:
            load_combination_id (str): The ID of the load combination to get.

        Returns:
            The load combination if found, None otherwise.
        """
        return self._get_element_by_id(self.load_combinations, load_combination_id)

    def add_result(self, result) -> None:
        """
        Add an analysis result to the model.

        Args:
            result: The analysis result to add.

        Raises:
            ValueError: If a result with the same ID already exists in the model.
        """
        if self._get_element_by_id(self.results, result.id) is not None:
            raise ValueError(
                f"Result with ID '{result.id}' already exists in the model"
            )

        self.results.append(result)

    def remove_result(self, result_id: str) -> bool:
        """
        Remove an analysis result from the model by its ID.

        Args:
            result_id (str): The ID of the result to remove.

        Returns:
            bool: True if the result was found and removed, False otherwise.
        """
        return self._remove_element_by_id(self.results, result_id)

    def get_result(self, result_id: str):
        """
        Get an analysis result by its ID.

        Args:
            result_id (str): The ID of the result to get.

        Returns:
            The result if found, None otherwise.
        """
        return self._get_element_by_id(self.results, result_id)

    def _get_element_by_id(self, element_list: List, element_id: str):
        """
        Get an element from a list by its ID.

        Args:
            element_list (List): The list of elements to search.
            element_id (str): The ID of the element to find.

        Returns:
            The element if found, None otherwise.
        """
        for element in element_list:
            if element.id == element_id:
                return element
        return None

    def _remove_element_by_id(self, element_list: List, element_id: str) -> bool:
        """
        Remove an element from a list by its ID.

        Args:
            element_list (List): The list of elements to search.
            element_id (str): The ID of the element to remove.

        Returns:
            bool: True if the element was found and removed, False otherwise.
        """
        for i, element in enumerate(element_list):
            if element.id == element_id:
                element_list.pop(i)
                return True
        return False
