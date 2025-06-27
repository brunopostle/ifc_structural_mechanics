"""
Unit tests for the BaseMapper class.

This module contains tests for the BaseMapper class, which provides common
functionality for mapping between domain entities and tool-specific entities.
"""

import os
import tempfile
import unittest
from typing import Dict, List

from ifc_structural_mechanics.mapping.base_mapper import BaseMapper


class SimpleTestMapper(BaseMapper[str, int]):
    """
    A simple mapper implementation for testing purposes.

    This implementation handles mappings between domain entities and integer IDs.
    """

    def __init__(self):
        """Initialize a test mapper with standard entity categories."""
        super().__init__(["node", "element", "material"])
        self.element_types: Dict[str, str] = {}  # For testing _store_additional_info

    def register_node(self, domain_entity_id: str, tool_node_id: int) -> None:
        """Register a node mapping."""
        self._register_entity(domain_entity_id, "node", tool_node_id)

    def register_element(
        self, domain_entity_id: str, tool_element_id: int, element_type: str = None
    ) -> None:
        """Register an element mapping with optional element type."""
        additional_info = {"element_type": element_type} if element_type else None
        self._register_entity(
            domain_entity_id, "element", tool_element_id, additional_info
        )

    def register_material(self, domain_entity_id: str, tool_material_id: int) -> None:
        """Register a material mapping."""
        self._register_entity(domain_entity_id, "material", tool_material_id)

    def _store_additional_info(
        self,
        domain_entity_id: str,
        tool_ids: List[int],
        entity_type: str,
        additional_info: Dict[str, str],
    ) -> None:
        """Store additional information for entity mapping."""
        if entity_type == "element" and "element_type" in additional_info:
            element_type = additional_info["element_type"]
            if element_type:
                domain_key = f"{domain_entity_id}_type"
                self.element_types[domain_key] = element_type

                for tool_id in tool_ids:
                    tool_key = f"element_{tool_id}_type"
                    self.element_types[tool_key] = element_type

    def get_element_type(self, domain_id: str = None, tool_id: int = None) -> str:
        """Get the element type for a domain or tool entity ID."""
        if domain_id is not None:
            key = f"{domain_id}_type"
            return self.element_types.get(key)

        if tool_id is not None:
            key = f"element_{tool_id}_type"
            return self.element_types.get(key)

        return None

    def _get_entity_type_key(self, entity_type: str, tool_id: int) -> str:
        """Get the key for storing entity type information."""
        return f"{entity_type}_{tool_id}"

    def _prepare_data_for_serialization(self) -> Dict:
        """Prepare mapping data for serialization."""
        mapping_data = super()._prepare_data_for_serialization()
        # Add element_types to the serialized data
        mapping_data["element_types"] = self.element_types

        # Convert tool_to_domain for serialization (custom handling for int keys)
        mapping_data["tool_to_domain"] = {}
        for entity_type, mappings in self.tool_to_domain.items():
            mapping_data["tool_to_domain"][entity_type] = {
                str(tool_id): domain_id for tool_id, domain_id in mappings.items()
            }

        return mapping_data

    def _load_data_from_serialized(self, mapping_data: Dict) -> None:
        """Load mapping data from serialized form."""
        super()._load_data_from_serialized(mapping_data)

        # Load element_types
        if "element_types" in mapping_data:
            self.element_types = mapping_data["element_types"]

        # Load tool_to_domain (custom handling for int keys)
        if "tool_to_domain" in mapping_data:
            for entity_type, mappings in mapping_data["tool_to_domain"].items():
                if entity_type in self._entity_categories:
                    for tool_id_str, domain_id in mappings.items():
                        try:
                            tool_id = int(
                                tool_id_str
                            )  # Convert string keys back to integers
                            self.tool_to_domain[entity_type][tool_id] = domain_id
                        except ValueError:
                            pass  # Skip invalid conversions

    def _clear_additional_data(self) -> None:
        """Clear additional data structures used by the mapper."""
        self.element_types = {}


class TestBaseMapper(unittest.TestCase):
    """Test cases for the BaseMapper class."""

    def setUp(self):
        """Set up a new mapper instance for each test."""
        self.mapper = SimpleTestMapper()

    def test_init(self):
        """Test that the mapper initializes with the correct structure."""
        self.assertIn("node", self.mapper.domain_to_tool)
        self.assertIn("element", self.mapper.domain_to_tool)
        self.assertIn("material", self.mapper.domain_to_tool)

        self.assertIn("node", self.mapper.tool_to_domain)
        self.assertIn("element", self.mapper.tool_to_domain)
        self.assertIn("material", self.mapper.tool_to_domain)

        self.assertEqual({}, self.mapper.entity_types)

    def test_register_node(self):
        """Test registering a node mapping."""
        self.mapper.register_node("node1", 101)

        # Test domain_to_tool mapping
        self.assertEqual(101, self.mapper.domain_to_tool["node"]["node1"])

        # Test tool_to_domain mapping
        self.assertEqual("node1", self.mapper.tool_to_domain["node"][101])

        # Test entity_types
        self.assertEqual("node", self.mapper.entity_types["node1"])
        self.assertEqual("node", self.mapper.entity_types["node_101"])

    def test_register_element_with_type(self):
        """Test registering an element mapping with an element type."""
        self.mapper.register_element("elem1", 201, "beam")

        # Test domain_to_tool mapping
        self.assertEqual(201, self.mapper.domain_to_tool["element"]["elem1"])

        # Test tool_to_domain mapping
        self.assertEqual("elem1", self.mapper.tool_to_domain["element"][201])

        # Test entity_types
        self.assertEqual("element", self.mapper.entity_types["elem1"])
        self.assertEqual("element", self.mapper.entity_types["element_201"])

        # Test element_types
        self.assertEqual("beam", self.mapper.get_element_type(domain_id="elem1"))
        self.assertEqual("beam", self.mapper.get_element_type(tool_id=201))

    def test_register_multiple_mappings(self):
        """Test registering multiple tool IDs for a single domain entity."""
        self.mapper.register_node("node1", 101)
        self.mapper._register_entity("node1", "node", 102)

        # Test that domain_to_tool contains a list
        self.assertIsInstance(self.mapper.domain_to_tool["node"]["node1"], list)
        self.assertIn(101, self.mapper.domain_to_tool["node"]["node1"])
        self.assertIn(102, self.mapper.domain_to_tool["node"]["node1"])

        # Test tool_to_domain mappings
        self.assertEqual("node1", self.mapper.tool_to_domain["node"][101])
        self.assertEqual("node1", self.mapper.tool_to_domain["node"][102])

    def test_register_with_list(self):
        """Test registering with a list of tool IDs."""
        self.mapper._register_entity("node1", "node", [101, 102])

        # Test that domain_to_tool contains a list
        self.assertIsInstance(self.mapper.domain_to_tool["node"]["node1"], list)
        self.assertIn(101, self.mapper.domain_to_tool["node"]["node1"])
        self.assertIn(102, self.mapper.domain_to_tool["node"]["node1"])

        # Test tool_to_domain mappings
        self.assertEqual("node1", self.mapper.tool_to_domain["node"][101])
        self.assertEqual("node1", self.mapper.tool_to_domain["node"][102])

    def test_get_tool_id(self):
        """Test getting tool IDs for a domain entity."""
        self.mapper.register_node("node1", 101)
        self.mapper._register_entity("node1", "node", 102)

        # Test getting a list of IDs
        tool_ids = self.mapper.get_tool_id("node1", "node")
        self.assertIsInstance(tool_ids, list)
        self.assertIn(101, tool_ids)
        self.assertIn(102, tool_ids)

        # Test getting a single ID
        self.mapper.register_node("node2", 103)
        self.assertEqual(103, self.mapper.get_tool_id("node2", "node"))

    def test_get_tool_id_not_mapped(self):
        """Test getting tool ID for a domain entity that isn't mapped."""
        with self.assertRaises(KeyError):
            self.mapper.get_tool_id("nonexistent", "node")

    def test_get_tool_id_invalid_type(self):
        """Test getting tool ID with an invalid entity type."""
        with self.assertRaises(KeyError):
            self.mapper.get_tool_id("node1", "invalid_type")

    def test_get_domain_entity_id(self):
        """Test getting domain entity ID for a tool entity."""
        self.mapper.register_node("node1", 101)
        self.assertEqual("node1", self.mapper.get_domain_entity_id(101, "node"))

    def test_get_domain_entity_id_not_mapped(self):
        """Test getting domain entity ID for a tool entity that isn't mapped."""
        with self.assertRaises(KeyError):
            self.mapper.get_domain_entity_id(999, "node")

    def test_get_domain_entity_id_invalid_type(self):
        """Test getting domain entity ID with an invalid entity type."""
        with self.assertRaises(KeyError):
            self.mapper.get_domain_entity_id(101, "invalid_type")

    def test_get_entity_type(self):
        """Test getting entity type."""
        self.mapper.register_node("node1", 101)
        self.assertEqual("node", self.mapper.get_entity_type("node1"))
        self.assertEqual("node", self.mapper.get_entity_type("node_101"))

    def test_get_entity_type_not_found(self):
        """Test getting entity type for an entity that isn't registered."""
        with self.assertRaises(KeyError):
            self.mapper.get_entity_type("nonexistent")

    def test_clear(self):
        """Test clearing all mappings."""
        self.mapper.register_node("node1", 101)
        self.mapper.register_element("elem1", 201, "beam")
        self.mapper.clear()

        # Check that all mappings are cleared
        self.assertEqual({}, self.mapper.domain_to_tool["node"])
        self.assertEqual({}, self.mapper.domain_to_tool["element"])
        self.assertEqual({}, self.mapper.tool_to_domain["node"])
        self.assertEqual({}, self.mapper.tool_to_domain["element"])
        self.assertEqual({}, self.mapper.entity_types)
        self.assertEqual({}, self.mapper.element_types)

    def test_get_domain_entities_by_type(self):
        """Test getting all domain entities of a specific type."""
        self.mapper.register_node("node1", 101)
        self.mapper.register_node("node2", 102)
        self.mapper.register_element("elem1", 201)

        nodes = self.mapper.get_domain_entities_by_type("node")
        self.assertIn("node1", nodes)
        self.assertIn("node2", nodes)
        self.assertEqual(2, len(nodes))

        elements = self.mapper.get_domain_entities_by_type("element")
        self.assertIn("elem1", elements)
        self.assertEqual(1, len(elements))

    def test_get_tool_entities_by_type(self):
        """Test getting all tool entities of a specific type."""
        self.mapper.register_node("node1", 101)
        self.mapper.register_node("node2", 102)
        self.mapper.register_element("elem1", 201)

        node_ids = self.mapper.get_tool_entities_by_type("node")
        self.assertIn(101, node_ids)
        self.assertIn(102, node_ids)
        self.assertEqual(2, len(node_ids))

        element_ids = self.mapper.get_tool_entities_by_type("element")
        self.assertIn(201, element_ids)
        self.assertEqual(1, len(element_ids))

    def test_invalid_entity_type(self):
        """Test providing an invalid entity type."""
        with self.assertRaises(ValueError):
            self.mapper._register_entity("test", "invalid_type", 999)

    def test_file_operations(self):
        """Test saving and loading mapping information to/from a file."""
        # Register some mappings
        self.mapper.register_node("node1", 101)
        self.mapper.register_element("elem1", 201, "beam")
        self.mapper.register_material("mat1", 301)

        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file_path = temp_file.name

        try:
            # Save the mapping
            self.mapper.create_mapping_file(file_path)

            # Create a new mapper and load the mapping
            new_mapper = SimpleTestMapper()
            new_mapper.load_mapping_file(file_path)

            # Check that the mappings are loaded correctly
            self.assertEqual(101, new_mapper.get_tool_id("node1", "node"))
            self.assertEqual(201, new_mapper.get_tool_id("elem1", "element"))
            self.assertEqual(301, new_mapper.get_tool_id("mat1", "material"))

            self.assertEqual("node1", new_mapper.get_domain_entity_id(101, "node"))
            self.assertEqual("elem1", new_mapper.get_domain_entity_id(201, "element"))
            self.assertEqual("mat1", new_mapper.get_domain_entity_id(301, "material"))

            self.assertEqual("beam", new_mapper.get_element_type(domain_id="elem1"))
            self.assertEqual("beam", new_mapper.get_element_type(tool_id=201))
        finally:
            # Clean up the temporary file
            if os.path.exists(file_path):
                os.remove(file_path)

    def test_file_operations_error_handling(self):
        """Test error handling in file operations."""
        # Test loading a non-existent file
        with self.assertRaises(IOError):
            self.mapper.load_mapping_file("/nonexistent/path/to/file.json")

        # Test loading an invalid JSON file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"invalid json")
            file_path = temp_file.name

        try:
            with self.assertRaises(ValueError):
                self.mapper.load_mapping_file(file_path)
        finally:
            os.remove(file_path)


if __name__ == "__main__":
    unittest.main()
