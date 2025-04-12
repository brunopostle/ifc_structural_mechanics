"""
Unit tests for the DomainEntity base class.

This module contains test cases for the DomainEntity base class and related
functionality in the domain model.
"""

import unittest
import uuid
from typing import Dict, Any, List

import sys
import os
from pathlib import Path

# Add the project root to the Python path so we can import modules
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# Import directly from the file to handle possible path issues
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
)
from ifc_structural_mechanics.domain.base_entity import (
    DomainEntity,
    DomainEntityCollection,
)


class TestDomainEntity(unittest.TestCase):
    """Test cases for the DomainEntity base class."""

    def test_init_with_id(self):
        """Test initialization with a provided ID."""
        test_id = "test-123"
        entity = DomainEntity(id=test_id)
        self.assertEqual(entity.id, test_id)
        self.assertEqual(entity.entity_type, "domainentity")

    def test_init_without_id(self):
        """Test initialization without an ID (should generate UUID)."""
        entity = DomainEntity()
        # Verify the ID is a valid UUID
        try:
            uuid.UUID(entity.id)
            is_valid_uuid = True
        except ValueError:
            is_valid_uuid = False
        self.assertTrue(is_valid_uuid)

    def test_init_with_entity_type(self):
        """Test initialization with a provided entity type."""
        entity_type = "test-entity"
        entity = DomainEntity(entity_type=entity_type)
        self.assertEqual(entity.entity_type, entity_type)

    def test_validate_id(self):
        """Test ID validation."""
        # Valid ID
        entity = DomainEntity(id="valid-id")
        self.assertTrue(entity.validate())

        # Create an entity with a proper ID first (UUID is generated for None)
        entity_for_test = DomainEntity()
        # Then set the ID to None manually to test validation
        entity_for_test.id = None
        # Now validate which should fail
        with self.assertRaises(ValueError):
            entity_for_test.validate()

        # Create another entity and set ID to empty string
        entity_empty = DomainEntity()
        entity_empty.id = ""
        # Validate which should fail
        with self.assertRaises(ValueError):
            entity_empty.validate()

    def test_validate_property(self):
        """Test property validation."""
        entity = DomainEntity()

        # Test with None value (not allowed)
        with self.assertRaises(ValueError):
            entity._validate_property("test", None, allow_none=False)

        # Test with None value (allowed)
        entity._validate_property("test", None, allow_none=True)

        # Test with custom validator (passing)
        def valid_range(value):
            if not 0 <= value <= 100:
                raise ValueError("Value must be between 0 and 100")

        entity._validate_property("range_value", 50, validator=valid_range)

        # Test with custom validator (failing)
        with self.assertRaises(ValueError):
            entity._validate_property("range_value", 200, validator=valid_range)

    def test_metadata_operations(self):
        """Test metadata operations."""
        entity = DomainEntity()

        # Test adding and retrieving metadata
        entity.add_metadata("key1", "value1")
        self.assertEqual(entity.get_metadata("key1"), "value1")

        # Test has_metadata
        self.assertTrue(entity.has_metadata("key1"))
        self.assertFalse(entity.has_metadata("nonexistent"))

        # Test getting nonexistent metadata
        with self.assertRaises(KeyError):
            entity.get_metadata("nonexistent")

    def test_as_dict(self):
        """Test conversion to dictionary."""
        test_id = "test-123"
        entity_type = "test-type"
        entity = DomainEntity(id=test_id, entity_type=entity_type)
        entity.add_metadata("key1", "value1")

        result = entity.as_dict()

        self.assertEqual(result["id"], test_id)
        self.assertEqual(result["entity_type"], entity_type)
        self.assertEqual(result["metadata"]["key1"], "value1")

    def test_from_dict(self):
        """Test creation from dictionary."""
        test_id = "test-123"
        data = {"id": test_id, "metadata": {"key1": "value1", "key2": 123}}

        entity = DomainEntity.from_dict(data)

        self.assertEqual(entity.id, test_id)
        self.assertEqual(entity.get_metadata("key1"), "value1")
        self.assertEqual(entity.get_metadata("key2"), 123)

        # Test with missing ID
        with self.assertRaises(ValueError):
            DomainEntity.from_dict({})


class TestDomainEntityCollection(unittest.TestCase):
    """Test cases for the DomainEntityCollection class."""

    def test_init(self):
        """Test initialization."""
        collection = DomainEntityCollection(entity_type="test")
        self.assertEqual(collection.entity_type, "test")
        self.assertEqual(len(collection.entities), 0)

    def test_add_entity(self):
        """Test adding entities."""
        collection = DomainEntityCollection()
        entity1 = DomainEntity(id="test1")
        entity2 = DomainEntity(id="test2")

        collection.add(entity1)
        self.assertEqual(len(collection), 1)

        collection.add(entity2)
        self.assertEqual(len(collection), 2)

        # Test adding None
        with self.assertRaises(ValueError):
            collection.add(None)

        # Test adding duplicate
        with self.assertRaises(ValueError):
            collection.add(entity1)

    def test_remove_entity(self):
        """Test removing entities."""
        collection = DomainEntityCollection()
        entity1 = DomainEntity(id="test1")
        entity2 = DomainEntity(id="test2")

        collection.add(entity1)
        collection.add(entity2)

        # Remove by entity
        result = collection.remove(entity1)
        self.assertTrue(result)
        self.assertEqual(len(collection), 1)

        # Remove by ID
        result = collection.remove("test2")
        self.assertTrue(result)
        self.assertEqual(len(collection), 0)

        # Remove nonexistent entity
        result = collection.remove("nonexistent")
        self.assertFalse(result)

    def test_get_by_id(self):
        """Test getting entities by ID."""
        collection = DomainEntityCollection()
        entity1 = DomainEntity(id="test1")
        entity2 = DomainEntity(id="test2")

        collection.add(entity1)
        collection.add(entity2)

        # Get existing entity
        result = collection.get_by_id("test1")
        self.assertIsNotNone(result)
        self.assertEqual(result.id, "test1")

        # Get nonexistent entity
        result = collection.get_by_id("nonexistent")
        self.assertIsNone(result)

    def test_clear(self):
        """Test clearing the collection."""
        collection = DomainEntityCollection()
        entity1 = DomainEntity(id="test1")
        entity2 = DomainEntity(id="test2")

        collection.add(entity1)
        collection.add(entity2)
        self.assertEqual(len(collection), 2)

        collection.clear()
        self.assertEqual(len(collection), 0)

    def test_as_dict_list(self):
        """Test conversion to list of dictionaries."""
        collection = DomainEntityCollection()
        entity1 = DomainEntity(id="test1")
        entity2 = DomainEntity(id="test2")

        entity1.add_metadata("key1", "value1")
        entity2.add_metadata("key2", "value2")

        collection.add(entity1)
        collection.add(entity2)

        result = collection.as_dict_list()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "test1")
        self.assertEqual(result[0]["metadata"]["key1"], "value1")
        self.assertEqual(result[1]["id"], "test2")
        self.assertEqual(result[1]["metadata"]["key2"], "value2")


class ConcreteEntity(DomainEntity):
    """Concrete implementation of DomainEntity for testing."""

    def __init__(self, id=None, name=None, value=None):
        """Initialize with custom properties."""
        # Set instance attributes before calling parent constructor
        # to avoid validation errors
        self.name = name
        self.value = value
        # Now call parent constructor which may trigger validation
        super().__init__(id=id, entity_type="concrete")

    def validate(self) -> bool:
        """Validate concrete entity."""
        super().validate()
        self._validate_property("name", self.name, allow_none=True)
        self._validate_property("value", self.value, allow_none=False)
        return True

    def as_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with custom properties."""
        result = super().as_dict()
        if self.name is not None:
            result["name"] = self.name
        result["value"] = self.value
        return result


class TestConcreteEntity(unittest.TestCase):
    """Test cases for the ConcreteEntity (subclass) implementation."""

    def test_concrete_init(self):
        """Test initialization of concrete entity."""
        entity = ConcreteEntity(id="test", name="Test Entity", value=123)
        self.assertEqual(entity.id, "test")
        self.assertEqual(entity.entity_type, "concrete")
        self.assertEqual(entity.name, "Test Entity")
        self.assertEqual(entity.value, 123)

    def test_concrete_validation(self):
        """Test validation in concrete entity."""
        # Valid entity
        entity = ConcreteEntity(id="test", name="Test Entity", value=123)
        self.assertTrue(entity.validate())

        # Invalid (value is None)
        with self.assertRaises(ValueError):
            ConcreteEntity(id="test", name="Test Entity", value=None)

        # Valid with None name (allowed)
        entity = ConcreteEntity(id="test", name=None, value=123)
        self.assertTrue(entity.validate())

    def test_concrete_as_dict(self):
        """Test as_dict with custom properties."""
        entity = ConcreteEntity(id="test", name="Test Entity", value=123)
        result = entity.as_dict()

        self.assertEqual(result["id"], "test")
        self.assertEqual(result["entity_type"], "concrete")
        self.assertEqual(result["name"], "Test Entity")
        self.assertEqual(result["value"], 123)


if __name__ == "__main__":
    unittest.main()
