"""
Unit tests for the Domain to CalculiX mapper.

This module contains tests for the DomainToCalculixMapper class, which maps
domain model entities to CalculiX entities.
"""

import os
import tempfile
import unittest
from src.ifc_structural_mechanics.mapping.domain_to_calculix import (
    DomainToCalculixMapper,
)


class TestDomainToCalculixMapper(unittest.TestCase):
    """Test suite for the DomainToCalculixMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = DomainToCalculixMapper()

    def test_register_node(self):
        """Test registering a node mapping."""
        # Register a node mapping
        self.mapper.register_node("domain_node_1", 42)

        # Check that the mapping was registered correctly
        self.assertEqual(self.mapper.get_ccx_id("domain_node_1", "node"), 42)
        self.assertEqual(self.mapper.get_domain_entity_id(42, "node"), "domain_node_1")

    def test_register_element(self):
        """Test registering an element mapping."""
        # Register an element mapping
        self.mapper.register_element("domain_element_1", 123, "beam")

        # Check that the mapping was registered correctly
        self.assertEqual(self.mapper.get_ccx_id("domain_element_1", "element"), 123)
        self.assertEqual(
            self.mapper.get_domain_entity_id(123, "element"), "domain_element_1"
        )
        self.assertEqual(self.mapper.get_entity_type(("element", 123)), "element")

        # Check the element type (specific type like beam, shell, etc.)
        self.assertEqual(
            self.mapper.get_element_type(domain_id="domain_element_1"), "beam"
        )
        self.assertEqual(self.mapper.get_element_type(ccx_id=123), "beam")

    def test_register_material(self):
        """Test registering a material mapping."""
        # Register a material mapping
        self.mapper.register_material("domain_material_1", "MAT_1")

        # Check that the mapping was registered correctly
        self.assertEqual(
            self.mapper.get_ccx_id("domain_material_1", "material"), "MAT_1"
        )
        self.assertEqual(
            self.mapper.get_domain_entity_id("MAT_1", "material"), "domain_material_1"
        )

    def test_register_section(self):
        """Test registering a section mapping."""
        # Register a section mapping
        self.mapper.register_section("domain_section_1", "SECT_1")

        # Check that the mapping was registered correctly
        self.assertEqual(
            self.mapper.get_ccx_id("domain_section_1", "section"), "SECT_1"
        )
        self.assertEqual(
            self.mapper.get_domain_entity_id("SECT_1", "section"), "domain_section_1"
        )

    def test_register_boundary_condition(self):
        """Test registering a boundary condition mapping."""
        # Register a boundary condition mapping
        self.mapper.register_boundary_condition("domain_bc_1", "BC_1")

        # Check that the mapping was registered correctly
        self.assertEqual(self.mapper.get_ccx_id("domain_bc_1", "boundary"), "BC_1")
        self.assertEqual(
            self.mapper.get_domain_entity_id("BC_1", "boundary"), "domain_bc_1"
        )

    def test_register_load(self):
        """Test registering a load mapping."""
        # Register a load mapping
        self.mapper.register_load("domain_load_1", "LOAD_1")

        # Check that the mapping was registered correctly
        self.assertEqual(self.mapper.get_ccx_id("domain_load_1", "load"), "LOAD_1")
        self.assertEqual(
            self.mapper.get_domain_entity_id("LOAD_1", "load"), "domain_load_1"
        )

    def test_register_point(self):
        """Test registering a point mapping."""
        # Register a point mapping
        self.mapper.register_point("domain_point_1", 201)

        # Check that the mapping was registered correctly
        self.assertEqual(self.mapper.get_ccx_id("domain_point_1", "point"), 201)
        self.assertEqual(
            self.mapper.get_domain_entity_id(201, "point"), "domain_point_1"
        )

    def test_register_curve(self):
        """Test registering a curve mapping."""
        # Register a curve mapping
        self.mapper.register_curve("domain_curve_1", 301, "line")

        # Check that the mapping was registered correctly
        self.assertEqual(self.mapper.get_ccx_id("domain_curve_1", "curve"), 301)
        self.assertEqual(
            self.mapper.get_domain_entity_id(301, "curve"), "domain_curve_1"
        )
        # Check the curve type
        self.assertEqual(
            self.mapper.get_element_type(domain_id="domain_curve_1"), "line"
        )

    def test_register_surface(self):
        """Test registering a surface mapping."""
        # Register a surface mapping
        self.mapper.register_surface("domain_surface_1", 401, "shell")

        # Check that the mapping was registered correctly
        self.assertEqual(self.mapper.get_ccx_id("domain_surface_1", "surface"), 401)
        self.assertEqual(
            self.mapper.get_domain_entity_id(401, "surface"), "domain_surface_1"
        )
        # Check the surface type
        self.assertEqual(
            self.mapper.get_element_type(domain_id="domain_surface_1"), "shell"
        )

    def test_multiple_registrations(self):
        """Test registering multiple mappings for the same domain entity."""
        # Register multiple element mappings for the same domain entity
        self.mapper.register_element("domain_element_1", 123)
        self.mapper.register_element("domain_element_1", 124)

        # Check that both mappings were registered correctly
        ccx_ids = self.mapper.get_ccx_id("domain_element_1", "element")

        # For easier debugging
        print(f"ccx_ids type: {type(ccx_ids)}")
        print(f"ccx_ids value: {ccx_ids}")

        # Check that ccx_ids is a list containing both 123 and 124
        self.assertTrue(isinstance(ccx_ids, list), "Expected a list")
        self.assertEqual(
            set(ccx_ids), {123, 124}, "Expected list to contain [123, 124]"
        )

        # Check reverse mappings
        self.assertEqual(
            self.mapper.get_domain_entity_id(123, "element"), "domain_element_1"
        )
        self.assertEqual(
            self.mapper.get_domain_entity_id(124, "element"), "domain_element_1"
        )

    def test_entity_type_retrieval(self):
        """Test retrieving entity types."""
        # Register entities with different types
        self.mapper.register_node("domain_node_1", 42)
        self.mapper.register_element("domain_element_1", 123, "beam")
        self.mapper.register_material("domain_material_1", "MAT_1")

        # Check that the entity types are retrieved correctly
        self.assertEqual(self.mapper.get_entity_type(("node", 42)), "node")
        self.assertEqual(self.mapper.get_entity_type(("element", 123)), "element")
        self.assertEqual(self.mapper.get_entity_type(("material", "MAT_1")), "material")

        # Check that the element types are retrieved correctly
        self.assertEqual(
            self.mapper.get_element_type(domain_id="domain_element_1"), "beam"
        )
        self.assertEqual(self.mapper.get_element_type(ccx_id=123), "beam")

    def test_invalid_entity_type(self):
        """Test handling of invalid entity types."""
        # Try to register an entity with an invalid type
        with self.assertRaises(ValueError):
            self.mapper._register_entity("domain_invalid_1", "invalid_type", 999)

        # Try to get a CalculiX ID with an invalid type
        with self.assertRaises(KeyError):
            self.mapper.get_ccx_id("domain_node_1", "invalid_type")

        # Try to get a domain entity ID with an invalid type
        with self.assertRaises(KeyError):
            self.mapper.get_domain_entity_id(42, "invalid_type")

    def test_entity_not_found(self):
        """Test handling of entities that are not found."""
        # Try to get a CalculiX ID for a domain entity that doesn't exist
        with self.assertRaises(KeyError):
            self.mapper.get_ccx_id("nonexistent_node", "node")

        # Try to get a domain entity ID for a CalculiX entity that doesn't exist
        with self.assertRaises(KeyError):
            self.mapper.get_domain_entity_id(9999, "node")

    def test_clear_mappings(self):
        """Test clearing all mappings."""
        # Register some mappings
        self.mapper.register_node("domain_node_1", 42)
        self.mapper.register_element("domain_element_1", 123)

        # Clear all mappings
        self.mapper.clear()

        # Check that the mappings were cleared
        with self.assertRaises(KeyError):
            self.mapper.get_ccx_id("domain_node_1", "node")
        with self.assertRaises(KeyError):
            self.mapper.get_domain_entity_id(42, "node")

    def test_get_entities_by_type(self):
        """Test retrieving all entities of a specific type."""
        # Register some mappings
        self.mapper.register_node("domain_node_1", 42)
        self.mapper.register_node("domain_node_2", 43)
        self.mapper.register_element("domain_element_1", 123)
        self.mapper.register_element("domain_element_2", 124)

        # Get all domain entities of type "node"
        node_entities = self.mapper.get_domain_entities_by_type("node")
        self.assertEqual(set(node_entities), {"domain_node_1", "domain_node_2"})

        # Get all CalculiX entities of type "element"
        element_entities = self.mapper.get_ccx_entities_by_type("element")
        self.assertEqual(set(element_entities), {123, 124})

    def test_persistence(self):
        """Test saving and loading mapping information."""
        # Register some mappings
        self.mapper.register_node("domain_node_1", 42)
        self.mapper.register_element("domain_element_1", 123, "beam")
        self.mapper.register_material("domain_material_1", "MAT_1")

        # Create a temporary file for the mapping
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            mapping_file = tmp.name

        try:
            # Save the mapping information
            self.mapper.create_mapping_file(mapping_file)

            # Create a new mapper and load the mapping information
            new_mapper = DomainToCalculixMapper()
            new_mapper.load_mapping_file(mapping_file)

            # Check that the mappings were loaded correctly
            self.assertEqual(new_mapper.get_ccx_id("domain_node_1", "node"), 42)
            self.assertEqual(new_mapper.get_ccx_id("domain_element_1", "element"), 123)
            self.assertEqual(
                new_mapper.get_ccx_id("domain_material_1", "material"), "MAT_1"
            )
            self.assertEqual(
                new_mapper.get_domain_entity_id(42, "node"), "domain_node_1"
            )
            self.assertEqual(
                new_mapper.get_domain_entity_id(123, "element"), "domain_element_1"
            )
            self.assertEqual(
                new_mapper.get_domain_entity_id("MAT_1", "material"),
                "domain_material_1",
            )
            self.assertEqual(new_mapper.get_entity_type(("element", 123)), "element")

            # Check that element type information was preserved
            self.assertEqual(
                new_mapper.get_element_type(domain_id="domain_element_1"), "beam"
            )
            self.assertEqual(new_mapper.get_element_type(ccx_id=123), "beam")
        finally:
            # Clean up the temporary file
            if os.path.exists(mapping_file):
                os.remove(mapping_file)

    def test_invalid_persistence(self):
        """Test handling of invalid mapping files."""
        # Create a temporary file with invalid JSON
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            mapping_file = tmp.name
            tmp.write(b"This is not valid JSON")

        try:
            # Try to load the invalid mapping file
            with self.assertRaises(ValueError):
                self.mapper.load_mapping_file(mapping_file)

            # Try to load a nonexistent mapping file
            with self.assertRaises(IOError):
                self.mapper.load_mapping_file("nonexistent_file.json")
        finally:
            # Clean up the temporary file
            if os.path.exists(mapping_file):
                os.remove(mapping_file)

    def test_map_error_to_domain_entity(self):
        """Test mapping error messages to domain entities."""
        # Register some mappings
        self.mapper.register_element("domain_element_1", 123)
        self.mapper.register_node("domain_node_1", 42)
        self.mapper.register_material("domain_material_1", "MAT_1")

        # Test mapping an error involving an element
        error_message = "Error: element 123 has a negative jacobian determinant"
        error_context = self.mapper.map_error_to_domain_entity(error_message)
        self.assertEqual(error_context["entity_type"], "element")
        self.assertEqual(error_context["ccx_id"], "123")
        self.assertEqual(error_context["domain_id"], "domain_element_1")

        # Test mapping an error involving a node
        error_message = "Error: node 42 is not connected to any element"
        error_context = self.mapper.map_error_to_domain_entity(error_message)
        self.assertEqual(error_context["entity_type"], "node")
        self.assertEqual(error_context["ccx_id"], "42")
        self.assertEqual(error_context["domain_id"], "domain_node_1")

        # Test mapping an error involving a material
        error_message = "Error: material MAT_1 undefined"
        error_context = self.mapper.map_error_to_domain_entity(error_message)
        self.assertEqual(error_context["entity_type"], "material")
        self.assertEqual(error_context["ccx_id"], "MAT_1")
        self.assertEqual(error_context["domain_id"], "domain_material_1")

        # Test mapping an error that doesn't match any patterns
        error_message = "Error: something went wrong"
        error_context = self.mapper.map_error_to_domain_entity(error_message)
        self.assertIsNone(error_context["entity_type"])
        self.assertIsNone(error_context["ccx_id"])
        self.assertIsNone(error_context["domain_id"])

    def test_create_error_context(self):
        """Test creating error context information."""
        # Register some mappings
        self.mapper.register_element("domain_element_1", 123)
        self.mapper.register_node("domain_node_1", 42)

        # Create error context for a known element
        error_context = self.mapper.create_error_context(123, "element")
        self.assertEqual(error_context["entity_type"], "element")
        self.assertEqual(error_context["ccx_id"], 123)
        self.assertEqual(error_context["domain_id"], "domain_element_1")

        # Create error context for an unknown element
        error_context = self.mapper.create_error_context(999, "element")
        self.assertEqual(error_context["entity_type"], "element")
        self.assertEqual(error_context["ccx_id"], 999)
        self.assertIsNone(error_context["domain_id"])


if __name__ == "__main__":
    unittest.main()
