"""
Base mapping module for domain entities.

This module provides a base class for mapping domain model entities to tool-specific
entities (e.g., Gmsh, CalculiX), maintaining a bidirectional mapping that can be used
to trace between domain entities and their tool-specific counterparts.
"""

# Update the path if necessary based on your project structure
__module_path__ = "ifc_structural_mechanics.mapping.base_mapper"

import os
import json
import logging
from typing import Dict, List, Optional, Union, Any, TypeVar, Generic

logger = logging.getLogger(__name__)

# Define type variables for flexibility in derived classes
DomainID = TypeVar("DomainID", bound=str)  # Domain IDs are always strings
ToolID = TypeVar("ToolID")  # Tool IDs can be int, str, or tuple, depending on the tool


class BaseMapper(Generic[DomainID, ToolID]):
    """
    Base class for mapping domain model entities to tool-specific entities.

    This class provides common functionality for maintaining bidirectional mappings
    between domain model entities and their corresponding tool-specific entities.
    These mappings are essential for tracing between domain entities and tool-specific
    entities, which is particularly useful for error handling and result processing.

    Attributes:
        domain_to_tool (Dict): Maps domain entity IDs to tool-specific entity IDs
        tool_to_domain (Dict): Maps tool-specific entity IDs to domain entity IDs
        entity_types (Dict): Maps entity IDs to their types
    """

    def __init__(self, entity_categories: List[str]):
        """
        Initialize a base mapper with specified entity categories.

        Args:
            entity_categories (List[str]): List of entity categories supported by this mapper
                (e.g., ["node", "element", "material"])
        """
        # Maps domain entity IDs to tool-specific entity IDs
        self.domain_to_tool: Dict[str, Dict[DomainID, Union[ToolID, List[ToolID]]]] = {}

        # Initialize each category
        for category in entity_categories:
            self.domain_to_tool[category] = {}

        # Maps tool-specific entity IDs to domain entity IDs
        self.tool_to_domain: Dict[str, Dict[ToolID, DomainID]] = {}

        # Initialize each category
        for category in entity_categories:
            self.tool_to_domain[category] = {}

        # Maps entity IDs to their types
        self.entity_types: Dict[Union[str, ToolID], str] = {}

        # Store the entity categories for validation
        self._entity_categories = entity_categories

    def _register_entity(
        self,
        domain_entity_id: DomainID,
        entity_type: str,
        tool_entity_id: Union[ToolID, List[ToolID]],
        additional_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a mapping between a domain entity and a tool-specific entity.

        Args:
            domain_entity_id (DomainID): ID of the domain entity
            entity_type (str): Type of the entity (must be one of the categories specified at initialization)
            tool_entity_id (Union[ToolID, List[ToolID]]): Tool-specific entity ID or list of IDs
            additional_info (Optional[Dict[str, Any]]): Additional information to store with the mapping

        Raises:
            ValueError: If the entity type is invalid or if there's a mapping conflict
        """
        # Ensure the entity type is valid
        if entity_type not in self._entity_categories:
            raise ValueError(f"Invalid entity type: {entity_type}")

        # Convert to list if it's not already a list
        if not isinstance(tool_entity_id, list):
            tool_ids = [tool_entity_id]
        else:
            tool_ids = tool_entity_id

        # Check if domain entity is already mapped
        if domain_entity_id in self.domain_to_tool[entity_type]:
            existing = self.domain_to_tool[entity_type][domain_entity_id]

            # Convert existing to list if it's not already
            if not isinstance(existing, list):
                existing = [existing]

            # Create a new list with all unique IDs
            combined_ids = list(existing)
            for id in tool_ids:
                if id not in combined_ids:
                    combined_ids.append(id)

            # Store the combined list if there are multiple values
            if len(combined_ids) > 1:
                self.domain_to_tool[entity_type][domain_entity_id] = combined_ids
            else:
                self.domain_to_tool[entity_type][domain_entity_id] = combined_ids[0]
        else:
            # For new mappings, store as is
            if len(tool_ids) == 1:
                self.domain_to_tool[entity_type][domain_entity_id] = tool_ids[0]
            else:
                self.domain_to_tool[entity_type][domain_entity_id] = tool_ids

        # Register reverse mappings
        for id in tool_ids:
            self.tool_to_domain[entity_type][id] = domain_entity_id

        # Register entity type
        self.entity_types[f"{domain_entity_id}"] = entity_type
        for id in tool_ids:
            key = self._get_entity_type_key(entity_type, id)
            self.entity_types[key] = entity_type

        # Store additional information if provided
        if additional_info:
            self._store_additional_info(
                domain_entity_id, tool_ids, entity_type, additional_info
            )

    def _get_entity_type_key(self, entity_type: str, tool_id: ToolID) -> str:
        """
        Get the key used for storing entity type information.

        Args:
            entity_type (str): Type of the entity
            tool_id (ToolID): Tool-specific entity ID

        Returns:
            str: Key to use for the entity_types dictionary
        """
        # Default implementation uses a simple concatenation with underscore
        # Derived classes can override this method to create appropriate keys
        return f"{entity_type}_{tool_id}"

    def _store_additional_info(
        self,
        domain_entity_id: DomainID,
        tool_ids: List[ToolID],
        entity_type: str,
        additional_info: Dict[str, Any],
    ) -> None:
        """
        Store additional information for an entity mapping.

        This method is intended to be overridden by derived classes that need
        to store additional information, such as element types, dimensions, etc.

        Args:
            domain_entity_id (DomainID): ID of the domain entity
            tool_ids (List[ToolID]): List of tool-specific entity IDs
            entity_type (str): Type of the entity
            additional_info (Dict[str, Any]): Additional information to store
        """
        pass  # Default implementation does nothing

    def _clear_additional_data(self) -> None:
        """
        Clear any additional data structures maintained by derived classes.

        This method is called by clear() and should be overridden by derived classes
        that maintain additional data structures beyond the base mapping dictionaries.
        """
        pass  # Default implementation does nothing

    def get_tool_id(
        self, domain_entity_id: DomainID, entity_type: str
    ) -> Union[ToolID, List[ToolID]]:
        """
        Get the tool-specific entity ID(s) mapped to a domain entity.

        Args:
            domain_entity_id (DomainID): ID of the domain entity
            entity_type (str): Type of the entity

        Returns:
            Union[ToolID, List[ToolID]]: Tool-specific entity ID or list of IDs

        Raises:
            KeyError: If the domain entity is not mapped
        """
        if entity_type not in self._entity_categories:
            raise KeyError(f"Invalid entity type: {entity_type}")

        if domain_entity_id not in self.domain_to_tool[entity_type]:
            raise KeyError(
                f"Domain entity '{domain_entity_id}' of type '{entity_type}' is not mapped"
            )

        return self.domain_to_tool[entity_type][domain_entity_id]

    def get_domain_entity_id(self, tool_id: ToolID, entity_type: str) -> DomainID:
        """
        Get the domain entity ID mapped to a tool-specific entity.

        Args:
            tool_id (ToolID): Tool-specific entity ID
            entity_type (str): Type of the entity

        Returns:
            DomainID: ID of the domain entity

        Raises:
            KeyError: If the tool-specific entity is not mapped
        """
        if entity_type not in self._entity_categories:
            raise KeyError(f"Invalid entity type: {entity_type}")

        if tool_id not in self.tool_to_domain[entity_type]:
            raise KeyError(
                f"Tool-specific entity '{tool_id}' of type '{entity_type}' is not mapped"
            )

        return self.tool_to_domain[entity_type][tool_id]

    def get_entity_type(self, entity_id: Union[DomainID, ToolID]) -> str:
        """
        Get the entity type for a given identifier.

        Args:
            entity_id (Union[DomainID, ToolID]): Entity identifier

        Returns:
            str: The entity type

        Raises:
            KeyError: If the entity type is not found
        """
        if entity_id not in self.entity_types:
            raise KeyError(f"Entity type for {entity_id} not found")

        return self.entity_types[entity_id]

    def create_mapping_file(self, file_path: str) -> None:
        """
        Save the mapping information to a file.

        Args:
            file_path (str): Path where the mapping file should be saved

        Raises:
            IOError: If there's an error writing the file
        """
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

        # Prepare data for serialization - derived classes can override this method
        # to customize serialization
        mapping_data = self._prepare_data_for_serialization()

        try:
            with open(file_path, "w") as f:
                json.dump(mapping_data, f, indent=2)
            logger.info(f"Mapping saved to {file_path}")
        except Exception as e:
            raise IOError(f"Error saving mapping to {file_path}: {str(e)}")

    def load_mapping_file(self, file_path: str) -> None:
        """
        Load mapping information from a file.

        Args:
            file_path (str): Path to the mapping file

        Raises:
            IOError: If there's an error reading the file
            ValueError: If the file format is invalid
        """
        try:
            with open(file_path, "r") as f:
                mapping_data = json.load(f)

            # Reset current mappings
            self.clear()

            # Load the data - derived classes can override this method
            # to customize deserialization
            self._load_data_from_serialized(mapping_data)

            logger.info(f"Mapping loaded from {file_path}")
        except FileNotFoundError:
            raise IOError(f"Mapping file not found: {file_path}")
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON format in mapping file: {file_path}")
        except Exception as e:
            raise IOError(f"Error loading mapping from {file_path}: {str(e)}")

    def _prepare_data_for_serialization(self) -> Dict[str, Any]:
        """
        Prepare mapping data for serialization.

        This method should be overridden by derived classes to customize how
        mapping data is prepared for serialization.

        Returns:
            Dict[str, Any]: Data ready for serialization
        """
        # Default implementation just returns the mapping dictionaries
        return {
            "domain_to_tool": self.domain_to_tool,
            "tool_to_domain": {},  # Empty because it might contain non-serializable keys
            "entity_types": self.entity_types,
        }

    def _load_data_from_serialized(self, mapping_data: Dict[str, Any]) -> None:
        """
        Load mapping data from serialized form.

        This method should be overridden by derived classes to customize how
        mapping data is loaded from serialized form.

        Args:
            mapping_data (Dict[str, Any]): Serialized mapping data
        """
        # Default implementation loads domain_to_tool and entity_types
        if "domain_to_tool" in mapping_data:
            for entity_type, mappings in mapping_data["domain_to_tool"].items():
                if entity_type in self._entity_categories:
                    self.domain_to_tool[entity_type].update(mappings)

        if "entity_types" in mapping_data:
            self.entity_types.update(mapping_data["entity_types"])

    def clear(self) -> None:
        """Clear all mappings."""
        # Reset mapping dictionaries
        for category in self._entity_categories:
            self.domain_to_tool[category] = {}
            self.tool_to_domain[category] = {}
        self.entity_types = {}

        # Hook method for clearing additional data in derived classes
        self._clear_additional_data()

    def get_domain_entities_by_type(self, entity_type: str) -> List[DomainID]:
        """
        Get all domain entities of a specific type.

        Args:
            entity_type (str): Type of the entities to retrieve

        Returns:
            List[DomainID]: List of domain entity IDs of the specified type
        """
        if entity_type not in self._entity_categories:
            return []

        return list(self.domain_to_tool[entity_type].keys())

    def get_tool_entities_by_type(self, entity_type: str) -> List[ToolID]:
        """
        Get all tool-specific entities of a specific type.

        Args:
            entity_type (str): Type of the entities to retrieve

        Returns:
            List[ToolID]: List of tool-specific entity IDs of the specified type
        """
        if entity_type not in self._entity_categories:
            return []

        return list(self.tool_to_domain[entity_type].keys())
