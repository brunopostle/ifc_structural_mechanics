"""
Tests for the Domain to Gmsh mapping module.

This module tests the DomainToGmshMapper class that maps domain model entities
to Gmsh geometry entities.
"""

import os
import tempfile
import unittest

from ifc_structural_mechanics.mapping.domain_to_gmsh import DomainToGmshMapper


class TestDomainToGmshMapper(unittest.TestCase):
    """Test cases for the DomainToGmshMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = DomainToGmshMapper()

    def test_register_point(self):
        """Test registration of point entities."""
        # Register a point
        self.mapper.register_point("point_1", 1)

        # Check domain to Gmsh mapping
        self.assertIn("point_1", self.mapper.domain_to_tool["point"])
        self.assertEqual((0, 1), self.mapper.domain_to_tool["point"]["point_1"])

        # Check Gmsh to domain mapping
        self.assertIn((0, 1), self.mapper.tool_to_domain["point"])
        self.assertEqual("point_1", self.mapper.tool_to_domain["point"][(0, 1)])

        # Check entity type
        self.assertEqual("point", self.mapper.entity_types["point_1"])
        self.assertEqual("point", self.mapper.entity_types[(0, 1)])

    def test_register_curve(self):
        """Test registration of curve entities."""
        # Register a curve with a single Gmsh ID
        self.mapper.register_curve("curve_1", 10)

        # Check domain to Gmsh mapping
        self.assertIn("curve_1", self.mapper.domain_to_tool["curve"])
        self.assertEqual((1, 10), self.mapper.domain_to_tool["curve"]["curve_1"])

        # Check Gmsh to domain mapping
        self.assertIn((1, 10), self.mapper.tool_to_domain["curve"])
        self.assertEqual("curve_1", self.mapper.tool_to_domain["curve"][(1, 10)])

        # Check entity type
        self.assertEqual("curve", self.mapper.entity_types["curve_1"])
        self.assertEqual("curve", self.mapper.entity_types[(1, 10)])

        # Register a curve with multiple Gmsh IDs
        self.mapper.register_curve("curve_2", [11, 12, 13])

        # Check domain to Gmsh mapping
        self.assertIn("curve_2", self.mapper.domain_to_tool["curve"])
        expected_ids = [(1, 11), (1, 12), (1, 13)]
        self.assertEqual(expected_ids, self.mapper.domain_to_tool["curve"]["curve_2"])

        # Check Gmsh to domain mapping
        self.assertIn((1, 11), self.mapper.tool_to_domain["curve"])
        self.assertEqual("curve_2", self.mapper.tool_to_domain["curve"][(1, 11)])
        self.assertIn((1, 12), self.mapper.tool_to_domain["curve"])
        self.assertEqual("curve_2", self.mapper.tool_to_domain["curve"][(1, 12)])
        self.assertIn((1, 13), self.mapper.tool_to_domain["curve"])
        self.assertEqual("curve_2", self.mapper.tool_to_domain["curve"][(1, 13)])

    def test_register_surface(self):
        """Test registration of surface entities."""
        # Register a surface
        self.mapper.register_surface("surface_1", 20)

        # Check domain to Gmsh mapping
        self.assertIn("surface_1", self.mapper.domain_to_tool["surface"])
        self.assertEqual((2, 20), self.mapper.domain_to_tool["surface"]["surface_1"])

        # Check Gmsh to domain mapping
        self.assertIn((2, 20), self.mapper.tool_to_domain["surface"])
        self.assertEqual("surface_1", self.mapper.tool_to_domain["surface"][(2, 20)])

        # Check entity type
        self.assertEqual("surface", self.mapper.entity_types["surface_1"])
        self.assertEqual("surface", self.mapper.entity_types[(2, 20)])

    def test_register_volume(self):
        """Test registration of volume entities."""
        # Register a volume
        self.mapper.register_volume("volume_1", 30)

        # Check domain to Gmsh mapping
        self.assertIn("volume_1", self.mapper.domain_to_tool["volume"])
        self.assertEqual((3, 30), self.mapper.domain_to_tool["volume"]["volume_1"])

        # Check Gmsh to domain mapping
        self.assertIn((3, 30), self.mapper.tool_to_domain["volume"])
        self.assertEqual("volume_1", self.mapper.tool_to_domain["volume"][(3, 30)])

        # Check entity type
        self.assertEqual("volume", self.mapper.entity_types["volume_1"])
        self.assertEqual("volume", self.mapper.entity_types[(3, 30)])

    def test_get_gmsh_ids(self):
        """Test getting Gmsh IDs for a domain entity."""
        # Register entities
        self.mapper.register_point("point_1", 1)
        self.mapper.register_curve("curve_1", [10, 11])

        # Get Gmsh IDs for point
        gmsh_ids = self.mapper.get_gmsh_ids("point_1")
        self.assertEqual([(0, 1)], gmsh_ids)

        # Get Gmsh IDs for curve
        gmsh_ids = self.mapper.get_gmsh_ids("curve_1")
        self.assertEqual([(1, 10), (1, 11)], sorted(gmsh_ids))

        # Test for non-existent entity
        with self.assertRaises(KeyError):
            self.mapper.get_gmsh_ids("non_existent")

    def test_get_domain_entity_id(self):
        """Test getting domain entity ID for a Gmsh entity."""
        # Register entities
        self.mapper.register_point("point_1", 1)
        self.mapper.register_curve("curve_1", [10, 11])

        # Get domain entity for point
        domain_id = self.mapper.get_domain_entity_id(0, 1)
        self.assertEqual("point_1", domain_id)

        # Get domain entity for curve
        domain_id = self.mapper.get_domain_entity_id(1, 10)
        self.assertEqual("curve_1", domain_id)

        # Test for non-existent entity
        with self.assertRaises(KeyError):
            self.mapper.get_domain_entity_id(0, 999)

    def test_get_entity_type(self):
        """Test getting entity type."""
        # Register entities
        self.mapper.register_point("point_1", 1)
        self.mapper.register_curve("curve_1", 10)

        # Get entity type for domain entity
        entity_type = self.mapper.get_entity_type("point_1")
        self.assertEqual("point", entity_type)

        # Get entity type for Gmsh entity
        entity_type = self.mapper.get_entity_type((1, 10))
        self.assertEqual("curve", entity_type)

        # Test for non-existent entity
        with self.assertRaises(KeyError):
            self.mapper.get_entity_type("non_existent")

    def test_append_to_existing_mapping(self):
        """Test appending to an existing mapping."""
        # Register a curve with a single Gmsh ID
        self.mapper.register_curve("curve_1", 10)

        # Add another Gmsh ID to the same domain entity
        self.mapper.register_curve("curve_1", 11)

        # Check domain to Gmsh mapping - should have both IDs
        self.assertIn("curve_1", self.mapper.domain_to_tool["curve"])
        expected_ids = [(1, 10), (1, 11)]
        actual_ids = self.mapper.domain_to_tool["curve"]["curve_1"]

        # Handle list ordering differences
        if isinstance(actual_ids, list):
            self.assertEqual(sorted(expected_ids), sorted(actual_ids))
        else:
            self.fail(f"Expected list of IDs, got {actual_ids}")

        # Check Gmsh to domain mapping
        self.assertEqual("curve_1", self.mapper.tool_to_domain["curve"][(1, 10)])
        self.assertEqual("curve_1", self.mapper.tool_to_domain["curve"][(1, 11)])

    def test_create_and_load_mapping_file(self):
        """Test creating and loading a mapping file."""
        # Register some entities
        self.mapper.register_point("point_1", 1)
        self.mapper.register_curve("curve_1", [10, 11])
        self.mapper.register_surface("surface_1", 20)

        # Create a temporary file
        fd, temp_path = tempfile.mkstemp()
        os.close(fd)

        try:
            # Save the mapping
            self.mapper.create_mapping_file(temp_path)

            # Create a new mapper
            new_mapper = DomainToGmshMapper()

            # Load the mapping
            new_mapper.load_mapping_file(temp_path)

            # Check specific mappings
            self.assertIn("point_1", new_mapper.domain_to_tool["point"])
            self.assertEqual((0, 1), new_mapper.domain_to_tool["point"]["point_1"])
            self.assertIn((0, 1), new_mapper.tool_to_domain["point"])
            self.assertEqual("point_1", new_mapper.tool_to_domain["point"][(0, 1)])

            # Check for curve with multiple IDs
            self.assertIn("curve_1", new_mapper.domain_to_tool["curve"])
            expected_curve_ids = [(1, 10), (1, 11)]
            actual_curve_ids = new_mapper.domain_to_tool["curve"]["curve_1"]

            # Handle list ordering differences
            if isinstance(actual_curve_ids, list):
                self.assertEqual(sorted(expected_curve_ids), sorted(actual_curve_ids))
            else:
                self.fail(f"Expected list of IDs, got {actual_curve_ids}")

        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_load_mapping_file_errors(self):
        """Test error handling when loading a mapping file."""
        # Test file not found
        with self.assertRaises(IOError):
            self.mapper.load_mapping_file("non_existent_file.json")

        # Test invalid JSON
        fd, temp_path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "w") as f:
                f.write("This is not valid JSON")

            with self.assertRaises(ValueError):
                self.mapper.load_mapping_file(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_clear(self):
        """Test clearing all mappings."""
        # Register some entities
        self.mapper.register_point("point_1", 1)
        self.mapper.register_curve("curve_1", 10)

        # Clear mappings
        self.mapper.clear()

        # Check that mappings are empty
        for category in ["point", "curve", "surface", "volume"]:
            self.assertEqual({}, self.mapper.domain_to_tool[category])
            self.assertEqual({}, self.mapper.tool_to_domain[category])
        self.assertEqual({}, self.mapper.entity_types)

    def test_get_entities_by_type(self):
        """Test getting entities by type."""
        # Register entities of different types
        self.mapper.register_point("point_1", 1)
        self.mapper.register_point("point_2", 2)
        self.mapper.register_curve("curve_1", 10)
        self.mapper.register_surface("surface_1", 20)

        # Get domain entities by type
        point_entities = self.mapper.get_domain_entities_by_type("point")
        curve_entities = self.mapper.get_domain_entities_by_type("curve")

        self.assertEqual(["point_1", "point_2"], sorted(point_entities))
        self.assertEqual(["curve_1"], curve_entities)

        # Get Gmsh entities by type
        point_gmsh = self.mapper.get_tool_entities_by_type("point")
        curve_gmsh = self.mapper.get_tool_entities_by_type("curve")

        self.assertEqual([(0, 1), (0, 2)], sorted(point_gmsh))
        self.assertEqual([(1, 10)], curve_gmsh)


if __name__ == "__main__":
    unittest.main()
