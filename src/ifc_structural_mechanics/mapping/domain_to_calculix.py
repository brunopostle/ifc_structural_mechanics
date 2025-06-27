"""
Domain model to CalculiX mapping module.

This module provides functionality to map domain model entities to CalculiX entities,
maintaining a bidirectional mapping that can be used to trace analysis errors back
to their original domain entities.
"""

import re
import logging
from typing import Dict, List, Optional, Union, Any

from ifc_structural_mechanics.mapping.base_mapper import BaseMapper

logger = logging.getLogger(__name__)


class DomainToCalculixMapper(BaseMapper[str, Union[int, str]]):
    """
    Maps domain model entities to CalculiX entities.

    This class maintains a bidirectional mapping between domain model entities
    and their corresponding CalculiX entities. This mapping is essential for
    tracing analysis errors back to their original domain entities, which is
    particularly useful for error handling and result processing.

    Attributes:
        domain_to_tool (Dict): Maps domain entity IDs to CalculiX entity IDs
        tool_to_domain (Dict): Maps CalculiX entity IDs to domain entity IDs
        entity_types (Dict): Maps entity IDs to their types
        element_types (Dict): Maps element IDs to their specific element types
    """

    def __init__(self):
        """Initialize an empty domain to CalculiX mapper."""
        # Initialize the base mapper with the entity categories
        entity_categories = [
            "node",
            "element",
            "material",
            "section",
            "boundary",
            "load",
            "point",
            "curve",
            "surface",
        ]
        super().__init__(entity_categories)

        # Maps element IDs to their specific element types (beam, shell, etc.)
        self.element_types: Dict[str, str] = {}

        # Error patterns for mapping CalculiX errors to elements
        self.error_patterns = [
            (r"element\s+(\d+).*negative jacobian", "element"),
            (r"node\s+(\d+).*not connected", "node"),
            (r"material\s+(\w+).*undefined", "material"),
            (r"section\s+(\w+).*undefined", "section"),
        ]

    # Compatibility properties for backward compatibility
    @property
    def domain_to_ccx(self):
        """Legacy accessor for domain_to_tool for backward compatibility."""
        return self.domain_to_tool

    @property
    def ccx_to_domain(self):
        """Legacy accessor for tool_to_domain for backward compatibility."""
        return self.tool_to_domain

    def register_node(self, domain_entity_id: str, ccx_node_id: int) -> None:
        """
        Register a mapping between a domain entity and a CalculiX node.

        Args:
            domain_entity_id (str): ID of the domain entity
            ccx_node_id (int): CalculiX node ID
        """
        self._register_entity(domain_entity_id, "node", ccx_node_id)

        # Store tuple mappings for backward compatibility
        # These will be properly serialized by our _prepare_data_for_serialization method
        self.entity_types[("node", ccx_node_id)] = "node"

    def register_point(self, domain_entity_id: str, ccx_point_id: int) -> None:
        """
        Register a mapping between a domain point entity and a CalculiX point.

        Args:
            domain_entity_id (str): ID of the domain entity
            ccx_point_id (int): CalculiX point ID
        """
        self._register_entity(domain_entity_id, "point", ccx_point_id)
        # For backward compatibility with tuple access
        self.entity_types[(domain_entity_id, ccx_point_id)] = "point"
        self.entity_types[("point", ccx_point_id)] = "point"

    def register_curve(
        self,
        domain_entity_id: str,
        ccx_curve_ids: Union[int, List[int]],
        curve_type: Optional[str] = None,
    ) -> None:
        """
        Register a mapping between a domain curve entity and CalculiX curve(s).

        Args:
            domain_entity_id (str): ID of the domain entity
            ccx_curve_ids (Union[int, List[int]]): CalculiX curve ID or list of IDs
            curve_type (Optional[str]): Type of curve (e.g., 'beam', 'line'), optional
        """
        additional_info = {"curve_type": curve_type} if curve_type else None
        self._register_entity(domain_entity_id, "curve", ccx_curve_ids, additional_info)

        # Convert to list if it's not already
        if not isinstance(ccx_curve_ids, list):
            ccx_curve_ids = [ccx_curve_ids]

        # For backward compatibility with tuple access
        for curve_id in ccx_curve_ids:
            self.entity_types[(domain_entity_id, curve_id)] = "curve"
            self.entity_types[("curve", curve_id)] = "curve"

    def register_surface(
        self,
        domain_entity_id: str,
        ccx_surface_ids: Union[int, List[int]],
        surface_type: Optional[str] = None,
    ) -> None:
        """
        Register a mapping between a domain surface entity and CalculiX surface(s).

        Args:
            domain_entity_id (str): ID of the domain entity
            ccx_surface_ids (Union[int, List[int]]): CalculiX surface ID or list of IDs
            surface_type (Optional[str]): Type of surface (e.g., 'shell', 'wall'), optional
        """
        additional_info = {"surface_type": surface_type} if surface_type else None
        self._register_entity(
            domain_entity_id, "surface", ccx_surface_ids, additional_info
        )

        # Convert to list if it's not already
        if not isinstance(ccx_surface_ids, list):
            ccx_surface_ids = [ccx_surface_ids]

        # For backward compatibility with tuple access
        for surface_id in ccx_surface_ids:
            self.entity_types[(domain_entity_id, surface_id)] = "surface"
            self.entity_types[("surface", surface_id)] = "surface"

    def register_element(
        self, domain_entity_id: str, ccx_element_id: int, element_type: str = None
    ) -> None:
        """
        Register a mapping between a domain entity and a CalculiX element.

        Args:
            domain_entity_id (str): ID of the domain entity
            ccx_element_id (int): CalculiX element ID
            element_type (str, optional): Type of the element
        """
        additional_info = {"element_type": element_type} if element_type else None
        self._register_entity(
            domain_entity_id, "element", ccx_element_id, additional_info
        )

        # Store tuple mappings for backward compatibility
        self.entity_types[("element", ccx_element_id)] = "element"

    def register_material(self, domain_entity_id: str, ccx_material_id: str) -> None:
        """
        Register a mapping between a domain material and a CalculiX material.

        Args:
            domain_entity_id (str): ID of the domain material
            ccx_material_id (str): CalculiX material ID (usually a string like "MAT_1")
        """
        self._register_entity(domain_entity_id, "material", ccx_material_id)

        # For backward compatibility with tuple access
        self.entity_types[(domain_entity_id, ccx_material_id)] = "material"
        self.entity_types[("material", ccx_material_id)] = "material"

    def register_section(self, domain_entity_id: str, ccx_section_id: str) -> None:
        """
        Register a mapping between a domain section and a CalculiX section.

        Args:
            domain_entity_id (str): ID of the domain section
            ccx_section_id (str): CalculiX section ID
        """
        self._register_entity(domain_entity_id, "section", ccx_section_id)

        # For backward compatibility with tuple access
        self.entity_types[(domain_entity_id, ccx_section_id)] = "section"
        self.entity_types[("section", ccx_section_id)] = "section"

    def register_boundary_condition(
        self, domain_entity_id: str, ccx_boundary_id: str
    ) -> None:
        """
        Register a mapping between a domain boundary condition and a CalculiX boundary condition.

        Args:
            domain_entity_id (str): ID of the domain boundary condition
            ccx_boundary_id (str): CalculiX boundary condition ID
        """
        self._register_entity(domain_entity_id, "boundary", ccx_boundary_id)

        # For backward compatibility with tuple access
        self.entity_types[(domain_entity_id, ccx_boundary_id)] = "boundary"
        self.entity_types[("boundary", ccx_boundary_id)] = "boundary"

    def register_load(self, domain_entity_id: str, ccx_load_id: str) -> None:
        """
        Register a mapping between a domain load and a CalculiX load.

        Args:
            domain_entity_id (str): ID of the domain load
            ccx_load_id (str): CalculiX load ID
        """
        self._register_entity(domain_entity_id, "load", ccx_load_id)

        # For backward compatibility with tuple access
        self.entity_types[(domain_entity_id, ccx_load_id)] = "load"
        self.entity_types[("load", ccx_load_id)] = "load"

    def _store_additional_info(
        self,
        domain_entity_id: str,
        tool_ids: List[Union[int, str]],
        entity_type: str,
        additional_info: Dict[str, Any],
    ) -> None:
        """
        Store additional information for an entity mapping.

        Args:
            domain_entity_id (str): ID of the domain entity
            tool_ids (List[Union[int, str]]): List of CalculiX entity IDs
            entity_type (str): Type of the entity
            additional_info (Dict[str, Any]): Additional information to store
        """
        # Store element type information if provided
        if entity_type == "element" and "element_type" in additional_info:
            element_type = additional_info["element_type"]
            if element_type:
                domain_key = f"{domain_entity_id}_type"
                self.element_types[domain_key] = element_type

                for tool_id in tool_ids:
                    ccx_key = f"element_{tool_id}_type"
                    self.element_types[ccx_key] = element_type

        # Store curve type information if provided
        elif entity_type == "curve" and "curve_type" in additional_info:
            curve_type = additional_info["curve_type"]
            if curve_type:
                domain_key = f"{domain_entity_id}_type"
                self.element_types[domain_key] = curve_type

                for curve_id in tool_ids:
                    ccx_key = f"curve_{curve_id}_type"
                    self.element_types[ccx_key] = curve_type

        # Store surface type information if provided
        elif entity_type == "surface" and "surface_type" in additional_info:
            surface_type = additional_info["surface_type"]
            if surface_type:
                domain_key = f"{domain_entity_id}_type"
                self.element_types[domain_key] = surface_type

                for surface_id in tool_ids:
                    ccx_key = f"surface_{surface_id}_type"
                    self.element_types[ccx_key] = surface_type

    def _clear_additional_data(self) -> None:
        """Clear additional data structures maintained by this class."""
        self.element_types = {}

    def get_ccx_id(
        self, domain_entity_id: str, entity_type: str
    ) -> Union[int, str, List[int], List[str]]:
        """
        Get the CalculiX entity ID(s) mapped to a domain entity.

        Args:
            domain_entity_id (str): ID of the domain entity
            entity_type (str): Type of the entity

        Returns:
            Union[int, str, List[int], List[str]]: CalculiX entity ID or list of IDs
        """
        return self.get_tool_id(domain_entity_id, entity_type)

    def get_domain_entity_id(self, ccx_id: Union[int, str], entity_type: str) -> str:
        """
        Get the domain entity ID mapped to a CalculiX entity.

        Args:
            ccx_id (Union[int, str]): CalculiX entity ID
            entity_type (str): Type of the entity

        Returns:
            str: ID of the domain entity
        """
        return super().get_domain_entity_id(ccx_id, entity_type)

    def get_entity_type(self, entity_id):
        """
        Get the entity type for a given identifier.

        This method supports two formats:
        1. A single ID (directly gets the entity type from the dictionary)
        2. A tuple of (entity_type, id) - returns the entity_type directly

        Args:
            entity_id: Entity identifier, can be a single ID or a tuple of (entity_type, id)

        Returns:
            str: The entity type

        Raises:
            KeyError: If the entity type is not found
        """
        # Handle the tuple-style input for backward compatibility with original implementation
        if isinstance(entity_id, tuple) and len(entity_id) == 2:
            # For tuples in format (entity_type, id), just return the entity_type
            entity_type, _ = entity_id
            return entity_type

        # Try standard lookup
        try:
            return super().get_entity_type(entity_id)
        except KeyError:
            # For backward compatibility
            if entity_id in self.entity_types:
                return self.entity_types[entity_id]
            raise

    def get_element_type(
        self, domain_id: str = None, ccx_id: int = None
    ) -> Optional[str]:
        """
        Get the specific element type (beam, shell, etc.) for an element.

        Args:
            domain_id (str, optional): Domain entity ID
            ccx_id (int, optional): CalculiX element ID

        Returns:
            Optional[str]: The element type, or None if not found

        Raises:
            ValueError: If neither domain_id nor ccx_id is provided
        """
        if domain_id is None and ccx_id is None:
            raise ValueError("Either domain_id or ccx_id must be provided")

        if domain_id is not None:
            key = f"{domain_id}_type"
            return self.element_types.get(key)

        if ccx_id is not None:
            key = f"element_{ccx_id}_type"
            return self.element_types.get(key)

        return None

    def _prepare_data_for_serialization(self) -> Dict[str, Any]:
        """
        Prepare mapping data for serialization.

        Returns:
            Dict[str, Any]: Data ready for serialization
        """
        # Get the base data
        base_data = super()._prepare_data_for_serialization()

        # Add element_types dictionary
        base_data["element_types"] = self.element_types

        # Convert tool_to_domain structure to serializable format
        base_data["tool_to_domain"] = {}
        for entity_type, mappings in self.tool_to_domain.items():
            base_data["tool_to_domain"][entity_type] = {}
            for tool_id, domain_id in mappings.items():
                # Convert keys to strings for JSON serialization
                base_data["tool_to_domain"][entity_type][str(tool_id)] = domain_id

        # Create a serializable entity_types dictionary (without tuples as keys)
        serializable_entity_types = {}
        for key, value in self.entity_types.items():
            # Skip tuple keys - we'll reconstruct them on load
            if isinstance(key, tuple):
                continue
            serializable_entity_types[str(key)] = value

        # Replace the entity_types with our serializable version
        base_data["entity_types"] = serializable_entity_types

        # Add a special structure to preserve tuple mappings
        base_data["tuple_entity_types"] = []
        for key, value in self.entity_types.items():
            if isinstance(key, tuple) and len(key) == 2:
                # Store tuple (entity_type, id) as a list with its value
                entity_type, entity_id = key
                tuple_entry = {
                    "entity_type": entity_type,
                    "id": entity_id if isinstance(entity_id, str) else str(entity_id),
                    "value": value,
                }
                base_data["tuple_entity_types"].append(tuple_entry)

        return base_data

    def _load_data_from_serialized(self, mapping_data: Dict[str, Any]) -> None:
        """
        Load mapping data from serialized form.

        Args:
            mapping_data (Dict[str, Any]): Serialized mapping data
        """
        super()._load_data_from_serialized(mapping_data)

        # Load element_types
        if "element_types" in mapping_data:
            self.element_types = mapping_data["element_types"]

        # Load tool_to_domain mapping (with conversion from string keys to appropriate types)
        if "tool_to_domain" in mapping_data:
            for entity_type, mappings in mapping_data["tool_to_domain"].items():
                if entity_type not in self.tool_to_domain:
                    self.tool_to_domain[entity_type] = {}
                for tool_id_str, domain_id in mappings.items():
                    # Convert string keys back to appropriate types
                    try:
                        # Try to convert to integer if possible
                        tool_id = int(tool_id_str)
                    except ValueError:
                        # Otherwise keep as string
                        tool_id = tool_id_str
                    self.tool_to_domain[entity_type][tool_id] = domain_id

        # Restore tuple-style entity types if present in the data
        if "tuple_entity_types" in mapping_data:
            for tuple_entry in mapping_data["tuple_entity_types"]:
                entity_type = tuple_entry["entity_type"]
                entity_id_str = tuple_entry["id"]
                value = tuple_entry["value"]

                # Convert entity_id back to the appropriate type
                try:
                    # Try to convert to integer if possible
                    entity_id = int(entity_id_str)
                except ValueError:
                    # Otherwise keep as string
                    entity_id = entity_id_str

                # Store the tuple mapping
                self.entity_types[(entity_type, entity_id)] = value

    def map_error_to_domain_entity(self, error_message: str) -> Dict[str, Any]:
        """
        Parse a CalculiX error message and map it to domain entities.

        This method attempts to identify the CalculiX entity mentioned in the error,
        and then maps it back to the corresponding domain entity.

        Args:
            error_message (str): The error message to parse

        Returns:
            Dict[str, Any]: A dictionary containing information about the error,
                including entity type, CCX ID, and domain ID if available
        """
        error_context = {
            "original_message": error_message,
            "entity_type": None,
            "ccx_id": None,
            "domain_id": None,
        }

        # Try to match error patterns
        for pattern, entity_type in self.error_patterns:
            match = re.search(pattern, error_message, re.IGNORECASE)
            if match:
                ccx_id = match.group(1)
                error_context["entity_type"] = entity_type
                error_context["ccx_id"] = ccx_id

                try:
                    # Try to convert to integer for node and element types
                    if entity_type in ["node", "element"]:
                        ccx_id = int(ccx_id)

                    # Try to map back to domain entity
                    if ccx_id in self.tool_to_domain.get(entity_type, {}):
                        domain_id = self.tool_to_domain[entity_type][ccx_id]
                        error_context["domain_id"] = domain_id
                except (ValueError, KeyError):
                    pass

                # We found a match, so we can stop searching
                break

        return error_context

    def create_error_context(
        self, ccx_id: Union[int, str], entity_type: str
    ) -> Dict[str, Any]:
        """
        Create contextual information for an error.

        Args:
            ccx_id (Union[int, str]): CalculiX entity ID
            entity_type (str): Type of the entity

        Returns:
            Dict[str, Any]: A dictionary containing contextual information about the error
        """
        error_context = {
            "entity_type": entity_type,
            "ccx_id": ccx_id,
            "domain_id": None,
        }

        try:
            # Try to map back to domain entity
            if ccx_id in self.tool_to_domain.get(entity_type, {}):
                domain_id = self.tool_to_domain[entity_type][ccx_id]
                error_context["domain_id"] = domain_id
        except (ValueError, KeyError):
            pass

        return error_context

    def get_domain_entities_by_type(self, entity_type: str) -> List[str]:
        """
        Get all domain entities of a specific type.

        Args:
            entity_type (str): Type of the entities to retrieve

        Returns:
            List[str]: List of domain entity IDs of the specified type
        """
        return super().get_domain_entities_by_type(entity_type)

    def get_ccx_entities_by_type(self, entity_type: str) -> List[Union[int, str]]:
        """
        Get all CalculiX entities of a specific type.

        Args:
            entity_type (str): Type of the entities to retrieve

        Returns:
            List[Union[int, str]]: List of CalculiX entity IDs of the specified type
        """
        return self.get_tool_entities_by_type(entity_type)
