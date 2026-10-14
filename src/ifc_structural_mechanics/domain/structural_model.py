"""
Domain model for structural analysis.

This module contains the StructuralModel class which serves as the container for
all structural elements, connections, loads, and other entities in the structural
analysis model.
"""

from typing import Dict, List, Optional, Union


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
        # Warnings raised while writing the analysis input, in result format
        self.analysis_warnings = []
        self.load_groups = []
        self.load_combinations = []
        self.results = []

        # NEW: Reverse lookup indices for error propagation (IFC GUID traceability)
        self.analysis_element_to_member: Dict[int, str] = {}  # element_id → member.id
        self.analysis_element_to_connection: Dict[int, str] = (
            {}
        )  # element_id → connection.id
        self.mesh_entity_to_member: Dict[str, str] = {}  # gmsh_id → member.id
        self.mesh_entity_to_connection: Dict[str, str] = {}  # gmsh_id → connection.id
        self.node_to_member: Dict[int, str] = {}  # node_id → member.id
        # Members analysed with a rectangle of equivalent stiffness in place
        # of their own section; set by the input writer
        self.equivalent_section_members: set = set()
        # analysis element ID → (member axis, section 1-direction) as written
        # on its beam section card; set by the input writer
        self.beam_section_frames: Dict[int, tuple] = {}
        # analysis element ID → its nodes, their positions, section,
        # 1-direction and material, as written, for every U1 element: the
        # results parser works out their nodal forces; set by the input writer
        self.user_elements: Dict[int, Dict] = {}
        # connection.id → {"nodes": {node: (x, y, z)}, "dofs": [1..6]} for
        # every support, as written to the solver; set by the input writer
        self.support_nodes: Dict[str, Dict] = {}
        # support node → (its position, {analysis element ID: positions of
        # the element's other nodes}) for every element at the node, links
        # included; set by the input writer
        self.support_node_elements: Dict[int, tuple] = {}
        # Per analysis step, the load applied directly at each support node,
        # {node: [fx, fy, fz, mx, my, mz, sx, sy, sz, px, py, pz]}: s is its
        # share of moments per length, p what of the force is point loads;
        # set by the input writer
        self.support_node_loads: List[Dict[int, List[float]]] = []
        # Per analysis step, the whole applied load [fx, fy, fz]; set by the
        # input writer
        self.applied_load_totals: List[List[float]] = []
        # Per analysis step, the moment of the applied load about the origin
        # [mx, my, mz], None where it could not be had; set by the input
        # writer
        self.applied_load_moments: List[Optional[List[float]]] = []
        # member.id → its mesh nodes; a node at a joint belongs to several
        self.member_nodes: Dict[str, set] = {}

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

    # NEW: Traceability methods for error propagation
    def register_mesh_entities(
        self, entity_id: str, mesh_ids: List[str], entity_type: str = "member"
    ) -> None:
        """
        Register mesh entity IDs for a domain entity (member or connection).

        Called by meshing module to record relationships between domain entities
        and their corresponding mesh entities.

        Args:
            entity_id: ID of the domain entity (member or connection)
            mesh_ids: List of mesh entity IDs (e.g., Gmsh entity tags)
            entity_type: Type of entity ("member" or "connection")

        Raises:
            ValueError: If entity is not found or entity_type is invalid
        """
        if entity_type == "member":
            member = self.get_member(entity_id)
            if not member:
                raise ValueError(f"Member with ID '{entity_id}' not found in model")
            member.mesh_entity_ids.extend(mesh_ids)
            for mesh_id in mesh_ids:
                self.mesh_entity_to_member[mesh_id] = entity_id
        elif entity_type == "connection":
            connection = self.get_connection(entity_id)
            if not connection:
                raise ValueError(f"Connection with ID '{entity_id}' not found in model")
            connection.mesh_entity_ids.extend(mesh_ids)
            for mesh_id in mesh_ids:
                self.mesh_entity_to_connection[mesh_id] = entity_id
        else:
            raise ValueError(
                f"Invalid entity_type: {entity_type}. Must be 'member' or 'connection'"
            )

    def register_analysis_elements(
        self, entity_id: str, element_ids: List[int], entity_type: str = "member"
    ) -> None:
        """
        Register analysis element IDs for a domain entity (member or connection).

        Called by analysis module to record relationships between domain entities
        and their corresponding analysis elements.

        Args:
            entity_id: ID of the domain entity (member or connection)
            element_ids: List of analysis element IDs (e.g., CalculiX element IDs)
            entity_type: Type of entity ("member" or "connection")

        Raises:
            ValueError: If entity is not found or entity_type is invalid
        """
        if entity_type == "member":
            member = self.get_member(entity_id)
            if not member:
                raise ValueError(f"Member with ID '{entity_id}' not found in model")
            member.analysis_element_ids.extend(element_ids)
            for elem_id in element_ids:
                self.analysis_element_to_member[elem_id] = entity_id
        elif entity_type == "connection":
            connection = self.get_connection(entity_id)
            if not connection:
                raise ValueError(f"Connection with ID '{entity_id}' not found in model")
            connection.analysis_element_ids.extend(element_ids)
            for elem_id in element_ids:
                self.analysis_element_to_connection[elem_id] = entity_id
        else:
            raise ValueError(
                f"Invalid entity_type: {entity_type}. Must be 'member' or 'connection'"
            )

    def register_node_memberships(self, node_ids: List[int], member_id: str) -> None:
        """
        Register the mesh nodes that belong to a structural member.

        Called by the meshing module after element-to-member mapping is complete,
        so that result exporters can map node-based FRD results to IFC entities.

        Args:
            node_ids: List of CalculiX node IDs belonging to this member.
            member_id: ID of the domain member that owns these nodes.
        """
        for node_id in node_ids:
            self.node_to_member[node_id] = member_id
        if node_ids:
            self.member_nodes.setdefault(member_id, set()).update(node_ids)

    def set_analysis_elements(self, member_id: str, element_ids: List[int]) -> None:
        """Replace the analysis element IDs of a member with its final list.

        Elements are registered as they are mapped, but later steps split,
        retype and reassign them. The input writer calls this once the element
        sets are final, so that results can be attributed element by element.

        Args:
            member_id: ID of the domain member.
            element_ids: The elements that make up the member in the input file.
        """
        member = self.get_member(member_id)
        if not member:
            raise ValueError(f"Member with ID '{member_id}' not found in model")
        for elem_id in member.analysis_element_ids:
            if self.analysis_element_to_member.get(elem_id) == member_id:
                del self.analysis_element_to_member[elem_id]
        member.analysis_element_ids = list(element_ids)
        for elem_id in element_ids:
            self.analysis_element_to_member[elem_id] = member_id

    def trace_error_to_ifc(self, analysis_element_id: int) -> Optional[str]:
        """
        Map a CalculiX analysis element error back to the original IFC GUID.

        This is the PRIMARY ERROR PROPAGATION METHOD that enables users to
        identify which IFC entity caused an analysis error.

        Args:
            analysis_element_id: CalculiX element ID from error message

        Returns:
            IFC GlobalId if found, None otherwise
        """
        # Check members first
        member_id = self.analysis_element_to_member.get(analysis_element_id)
        if member_id:
            member = self.get_member(member_id)
            return member.ifc_guid if member and member.ifc_guid else None

        # Check connections
        connection_id = self.analysis_element_to_connection.get(analysis_element_id)
        if connection_id:
            connection = self.get_connection(connection_id)
            return connection.ifc_guid if connection and connection.ifc_guid else None

        return None

    def get_entity_by_ifc_guid(self, ifc_guid: str) -> Optional[Union[object, object]]:
        """
        Find a domain entity (member or connection) by its IFC GUID.

        Args:
            ifc_guid: IFC GlobalId to search for

        Returns:
            The domain entity if found, None otherwise
        """
        # Search members
        for member in self.members:
            if hasattr(member, "ifc_guid") and member.ifc_guid == ifc_guid:
                return member

        # Search connections
        for connection in self.connections:
            if hasattr(connection, "ifc_guid") and connection.ifc_guid == ifc_guid:
                return connection

        return None
