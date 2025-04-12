"""
Domain model to Gmsh geometry mapping module.

This module provides functionality to map domain model entities to Gmsh geometry
entities, maintaining a bidirectional mapping that can be used to trace mesh
elements back to their original domain entities.
"""

import logging
from typing import Dict, List, Tuple, Union, Any

from ifc_structural_mechanics.mapping.base_mapper import BaseMapper

logger = logging.getLogger(__name__)


class DomainToGmshMapper(BaseMapper[str, Tuple[int, int]]):
    """
    Maps domain model entities to Gmsh geometry entities.

    This class maintains a bidirectional mapping between domain model entities
    and their corresponding Gmsh geometry entities. This mapping is essential
    for tracing mesh elements back to their original domain entities, which is
    particularly useful for error handling and result processing.

    Attributes:
        domain_to_tool (Dict): Maps domain entity IDs to Gmsh entity IDs
        tool_to_domain (Dict): Maps Gmsh entity IDs to domain entity IDs
        entity_types (Dict): Maps entity IDs to their types for both domain and Gmsh entities
    """

    def __init__(self):
        """Initialize the domain to Gmsh mapper."""
        # Define entity categories for Gmsh: point, curve, surface, volume
        super().__init__(["point", "curve", "surface", "volume"])

    def register_point(self, domain_entity_id: str, gmsh_point_id: int) -> None:
        """
        Register a mapping between a domain point entity and a Gmsh point.

        Args:
            domain_entity_id (str): ID of the domain entity
            gmsh_point_id (int): Gmsh point tag

        Raises:
            ValueError: If the domain entity is already mapped to a different Gmsh entity
        """
        # Register the mapping using BaseMapper's _register_entity
        self._register_entity(domain_entity_id, "point", (0, gmsh_point_id))

        # Manually store the entity type for the tuple key since BaseMapper
        # might be using string representation of the tuple
        self.entity_types[(0, gmsh_point_id)] = "point"

    def register_curve(
        self, domain_entity_id: str, gmsh_curve_ids: Union[int, List[int]]
    ) -> None:
        """
        Register a mapping between a domain curve entity and Gmsh curves.

        Args:
            domain_entity_id (str): ID of the domain entity
            gmsh_curve_ids (Union[int, List[int]]): Gmsh curve tag or list of tags

        Raises:
            ValueError: If the domain entity is already mapped to a different Gmsh entity
        """
        if isinstance(gmsh_curve_ids, int):
            # Register with BaseMapper
            self._register_entity(domain_entity_id, "curve", (1, gmsh_curve_ids))
            # Manually add entity type for the tuple key
            self.entity_types[(1, gmsh_curve_ids)] = "curve"
        else:
            # Convert list of IDs to list of tuples with dimension
            gmsh_tuples = [(1, curve_id) for curve_id in gmsh_curve_ids]
            self._register_entity(domain_entity_id, "curve", gmsh_tuples)
            # Manually add entity type for each tuple key
            for curve_id in gmsh_curve_ids:
                self.entity_types[(1, curve_id)] = "curve"

    def register_surface(
        self, domain_entity_id: str, gmsh_surface_ids: Union[int, List[int]]
    ) -> None:
        """
        Register a mapping between a domain surface entity and Gmsh surfaces.

        Args:
            domain_entity_id (str): ID of the domain entity
            gmsh_surface_ids (Union[int, List[int]]): Gmsh surface tag or list of tags

        Raises:
            ValueError: If the domain entity is already mapped to a different Gmsh entity
        """
        if isinstance(gmsh_surface_ids, int):
            # Register with BaseMapper
            self._register_entity(domain_entity_id, "surface", (2, gmsh_surface_ids))
            # Manually add entity type for the tuple key
            self.entity_types[(2, gmsh_surface_ids)] = "surface"
        else:
            # Convert list of IDs to list of tuples with dimension
            gmsh_tuples = [(2, surface_id) for surface_id in gmsh_surface_ids]
            self._register_entity(domain_entity_id, "surface", gmsh_tuples)
            # Manually add entity type for each tuple key
            for surface_id in gmsh_surface_ids:
                self.entity_types[(2, surface_id)] = "surface"

    def register_volume(
        self, domain_entity_id: str, gmsh_volume_ids: Union[int, List[int]]
    ) -> None:
        """
        Register a mapping between a domain volume entity and Gmsh volumes.

        Args:
            domain_entity_id (str): ID of the domain entity
            gmsh_volume_ids (Union[int, List[int]]): Gmsh volume tag or list of tags

        Raises:
            ValueError: If the domain entity is already mapped to a different Gmsh entity
        """
        if isinstance(gmsh_volume_ids, int):
            # Register with BaseMapper
            self._register_entity(domain_entity_id, "volume", (3, gmsh_volume_ids))
            # Manually add entity type for the tuple key
            self.entity_types[(3, gmsh_volume_ids)] = "volume"
        else:
            # Convert list of IDs to list of tuples with dimension
            gmsh_tuples = [(3, volume_id) for volume_id in gmsh_volume_ids]
            self._register_entity(domain_entity_id, "volume", gmsh_tuples)
            # Manually add entity type for each tuple key
            for volume_id in gmsh_volume_ids:
                self.entity_types[(3, volume_id)] = "volume"

    def get_gmsh_ids(self, domain_entity_id: str) -> List[Tuple[int, int]]:
        """
        Get all Gmsh entity IDs mapped to a domain entity.

        Args:
            domain_entity_id (str): ID of the domain entity

        Returns:
            List[Tuple[int, int]]: List of (dimension, tag) tuples for Gmsh entities

        Raises:
            KeyError: If the domain entity is not mapped
        """
        entity_type = self.get_entity_type(domain_entity_id)
        tool_ids = self.get_tool_id(domain_entity_id, entity_type)

        # Convert to list if it's not already
        if not isinstance(tool_ids, list):
            return [tool_ids]
        return tool_ids

    def get_domain_entity_id(self, gmsh_dimension: int, gmsh_id: int) -> str:
        """
        Get the domain entity ID mapped to a Gmsh entity.

        Args:
            gmsh_dimension (int): Dimension of the Gmsh entity
            gmsh_id (int): Gmsh entity tag

        Returns:
            str: ID of the domain entity

        Raises:
            KeyError: If the Gmsh entity is not mapped
        """
        gmsh_key = (gmsh_dimension, gmsh_id)

        # Get entity type based on dimension
        dimension_to_type = {0: "point", 1: "curve", 2: "surface", 3: "volume"}
        entity_type = dimension_to_type.get(gmsh_dimension)

        if not entity_type:
            raise KeyError(f"Invalid Gmsh dimension: {gmsh_dimension}")

        return super().get_domain_entity_id(gmsh_key, entity_type)

    # For backward compatibility with existing code
    @property
    def domain_to_gmsh(self):
        """
        Property to maintain backward compatibility with code that expects domain_to_gmsh.

        Returns:
            Dict: Flattened dictionary mapping domain entity IDs to Gmsh entity IDs
        """
        result = {}
        for category, mappings in self.domain_to_tool.items():
            result.update(mappings)
        return result

    @property
    def gmsh_to_domain(self):
        """
        Property to maintain backward compatibility with code that expects gmsh_to_domain.

        Returns:
            Dict: Flattened dictionary mapping Gmsh entity IDs to domain entity IDs
        """
        result = {}
        for category, mappings in self.tool_to_domain.items():
            result.update(mappings)
        return result

    def get_entity_type(self, entity_id: Union[str, Tuple[int, int]]) -> str:
        """
        Get the type of an entity.

        Args:
            entity_id (Union[str, Tuple[int, int]]): ID of the entity, either a domain ID or a (dimension, tag) tuple

        Returns:
            str: Type of the entity

        Raises:
            KeyError: If the entity type is not registered
        """
        # Check if we have the entity type directly
        if entity_id in self.entity_types:
            return self.entity_types[entity_id]

        # For Gmsh tuple keys, handle legacy lookups
        if isinstance(entity_id, tuple) and len(entity_id) == 2:
            dimension, tag = entity_id
            dimension_to_type = {0: "point", 1: "curve", 2: "surface", 3: "volume"}
            if dimension in dimension_to_type:
                # Check if this key exists in the appropriate tool_to_domain category
                entity_type = dimension_to_type[dimension]
                if entity_id in self.tool_to_domain[entity_type]:
                    return entity_type

        # If we reach here, the entity type is not registered
        if isinstance(entity_id, tuple):
            dim, tag = entity_id
            raise KeyError(
                f"Entity type for Gmsh entity ({dim}, {tag}) is not registered"
            )
        else:
            raise KeyError(
                f"Entity type for domain entity '{entity_id}' is not registered"
            )

    def _get_entity_type_key(self, entity_type: str, tool_id: Tuple[int, int]) -> str:
        """
        Override to create an appropriate key for Gmsh entity types.

        Args:
            entity_type (str): Type of the entity
            tool_id (Tuple[int, int]): Gmsh entity ID as (dimension, tag)

        Returns:
            str: Key for the entity_types dictionary
        """
        # We need to use the tuple directly as a key, not convert it to a string
        # This is important for proper lookup in the entity_types dictionary
        return tool_id

    def _prepare_data_for_serialization(self) -> Dict[str, Any]:
        """
        Override to customize serialization for Gmsh mappings.

        Returns:
            Dict[str, Any]: Data ready for serialization
        """
        # Legacy format for backward compatibility
        # This matches the original DomainToGmshMapper format
        # so that existing code can load these files

        # Flattened domain_to_gmsh mapping
        domain_to_gmsh = {}
        for category, mappings in self.domain_to_tool.items():
            for domain_id, tool_ids in mappings.items():
                if isinstance(tool_ids, list):
                    # Extract just the tag (second element) from each tuple
                    domain_to_gmsh[domain_id] = [tool_id[1] for tool_id in tool_ids]
                else:
                    # Extract just the tag (second element) from the tuple
                    domain_to_gmsh[domain_id] = tool_ids[1]

        # Flattened gmsh_to_domain mapping
        gmsh_to_domain = {}
        for category, mappings in self.tool_to_domain.items():
            for (dim, tag), domain_id in mappings.items():
                gmsh_to_domain[f"{dim}_{tag}"] = domain_id

        # Simplify entity_types for serialization
        entity_types = {}
        for entity_id, entity_type in self.entity_types.items():
            if isinstance(entity_id, tuple):
                dim, tag = entity_id
                entity_types[f"{dim}_{tag}"] = entity_type
            else:
                entity_types[entity_id] = entity_type

        return {
            "domain_to_gmsh": domain_to_gmsh,
            "gmsh_to_domain": gmsh_to_domain,
            "entity_types": entity_types,
        }

    def _load_data_from_serialized(self, mapping_data: Dict[str, Any]) -> None:
        """
        Override to customize deserialization for Gmsh mappings.

        Args:
            mapping_data (Dict[str, Any]): Serialized mapping data
        """
        # Clear existing mappings first
        self.clear()

        # First check if this is legacy format with "domain_to_gmsh"
        if "domain_to_gmsh" in mapping_data and "domain_to_tool" not in mapping_data:
            # Handle legacy format (old DomainToGmshMapper format)
            for domain_id, tool_id in mapping_data["domain_to_gmsh"].items():
                # We need to determine the entity type based on available information
                entity_type = None

                # Check if we have entity type information
                if (
                    "entity_types" in mapping_data
                    and domain_id in mapping_data["entity_types"]
                ):
                    entity_type = mapping_data["entity_types"][domain_id]

                # If not, try to infer from domain ID or other information
                if entity_type is None:
                    # Default to curve for legacy compatibility
                    entity_type = "curve"

                    # Try to infer from name conventions (point_*, curve_*, etc.)
                    for prefix in ["point_", "curve_", "surface_", "volume_"]:
                        if domain_id.startswith(prefix):
                            entity_type = prefix[:-1]  # Remove trailing underscore
                            break

                # Get dimension from entity type
                dimension = {"point": 0, "curve": 1, "surface": 2, "volume": 3}.get(
                    entity_type, 1
                )

                # Register the entity with the appropriate method
                if entity_type == "point" and not isinstance(tool_id, list):
                    self.register_point(domain_id, tool_id)
                elif entity_type == "curve":
                    self.register_curve(
                        domain_id, tool_id if isinstance(tool_id, list) else [tool_id]
                    )
                elif entity_type == "surface":
                    self.register_surface(
                        domain_id, tool_id if isinstance(tool_id, list) else [tool_id]
                    )
                elif entity_type == "volume":
                    self.register_volume(
                        domain_id, tool_id if isinstance(tool_id, list) else [tool_id]
                    )
                else:
                    # For unknown types, use the raw _register_entity method
                    if isinstance(tool_id, list):
                        tool_tuples = [(dimension, tid) for tid in tool_id]
                        self._register_entity(domain_id, entity_type, tool_tuples)
                        # Manually add entity types
                        for tid in tool_id:
                            self.entity_types[(dimension, tid)] = entity_type
                    else:
                        self._register_entity(
                            domain_id, entity_type, (dimension, tool_id)
                        )
                        # Manually add entity type
                        self.entity_types[(dimension, tool_id)] = entity_type

                    # Ensure domain entity type is set
                    self.entity_types[domain_id] = entity_type

            # Handle entity types if not already handled
            if "entity_types" in mapping_data:
                for key_str, entity_type in mapping_data["entity_types"].items():
                    try:
                        if "_" in key_str:
                            # This is a Gmsh entity key
                            dim, tag = map(int, key_str.split("_"))
                            self.entity_types[(dim, tag)] = entity_type
                        else:
                            # This is a domain entity key
                            self.entity_types[key_str] = entity_type
                    except Exception as e:
                        logger.warning(f"Invalid entity_types key {key_str}: {str(e)}")
        else:
            # Handle the new BaseMapper format
            # Handle domain_to_tool mappings
            if "domain_to_tool" in mapping_data:
                for category, mappings in mapping_data["domain_to_tool"].items():
                    if category in self._entity_categories:
                        dimension = {"point": 0, "curve": 1, "surface": 2, "volume": 3}[
                            category
                        ]
                        for domain_id, tool_id in mappings.items():
                            if isinstance(tool_id, list):
                                # Convert back to tuples with dimension
                                tuples = [(dimension, tid) for tid in tool_id]
                                self.domain_to_tool[category][domain_id] = tuples
                                # Also register entity types for each tuple
                                for tid in tool_id:
                                    self.entity_types[(dimension, tid)] = category
                            else:
                                # Convert back to tuple with dimension
                                self.domain_to_tool[category][domain_id] = (
                                    dimension,
                                    tool_id,
                                )
                                # Also register entity type for the tuple
                                self.entity_types[(dimension, tool_id)] = category

                            # Register entity type for the domain ID
                            self.entity_types[domain_id] = category

            # Handle tool_to_domain mappings
            if "tool_to_domain" in mapping_data:
                for category, mappings in mapping_data["tool_to_domain"].items():
                    if category in self._entity_categories:
                        for key_str, domain_id in mappings.items():
                            try:
                                dim, tag = map(int, key_str.split("_"))
                                self.tool_to_domain[category][(dim, tag)] = domain_id
                            except Exception as e:
                                logger.warning(
                                    f"Invalid tool_to_domain key {key_str}: {str(e)}"
                                )

            # Handle entity_types
            if "entity_types" in mapping_data:
                for key_str, entity_type in mapping_data["entity_types"].items():
                    try:
                        if "_" in key_str:
                            # This is a Gmsh entity key
                            dim, tag = map(int, key_str.split("_"))
                            self.entity_types[(dim, tag)] = entity_type
                        else:
                            # This is a domain entity key
                            self.entity_types[key_str] = entity_type
                    except Exception as e:
                        logger.warning(f"Invalid entity_types key {key_str}: {str(e)}")
