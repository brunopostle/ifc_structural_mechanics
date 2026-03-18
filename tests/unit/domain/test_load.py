"""
Unit tests for the load module in the domain model.
"""

import unittest

import numpy as np

from ifc_structural_mechanics.domain.load import (
    AreaLoad,
    LineLoad,
    Load,
    LoadCombination,
    LoadGroup,
    PointLoad,
)


class TestLoad(unittest.TestCase):
    """Tests for the base Load class."""

    def test_init_with_defaults(self):
        """Test initializing a Load with default values."""
        # The Load class now validates during initialization,
        # so this should raise an exception
        with self.assertRaises(ValueError):
            Load()

    def test_init_with_valid_parameters(self):
        """Test initializing a Load with valid parameters."""
        load = Load(
            id="test-load-1",
            load_type="test",
            magnitude=10.0,
            direction=[0, 0, 1],
        )
        self.assertEqual(load.id, "test-load-1")
        self.assertEqual(
            load.entity_type, "test"
        )  # Changed from load_type to entity_type
        self.assertEqual(load.magnitude, 10.0)
        np.testing.assert_array_equal(load.direction, np.array([0, 0, 1]))

    def test_auto_id_generation(self):
        """Test that an ID is automatically generated if not provided."""
        load = Load(
            load_type="test",
            magnitude=10.0,
            direction=[0, 0, 1],
        )
        self.assertIsNotNone(load.id)
        self.assertTrue(isinstance(load.id, str))

    def test_direction_normalization(self):
        """Test that the direction vector is normalized."""
        load = Load(
            load_type="test",
            magnitude=10.0,
            direction=[0, 0, 2],
        )
        np.testing.assert_array_equal(load.direction, np.array([0, 0, 1]))

    def test_get_force_vector(self):
        """Test getting the force vector."""
        load = Load(
            load_type="test",
            magnitude=10.0,
            direction=[0, 0, 1],
        )
        np.testing.assert_array_equal(load.get_force_vector(), np.array([0, 0, 10.0]))

    def test_vector_magnitude(self):
        """Test using a vector magnitude."""
        load = Load(
            load_type="test",
            magnitude=[5.0, 10.0, 15.0],
            direction=[0, 0, 1],
        )
        np.testing.assert_array_equal(load.magnitude, np.array([5.0, 10.0, 15.0]))

    def test_validation_failures(self):
        """Test validation failures."""
        # Missing load type
        with self.assertRaises(ValueError):
            # We expect validation to fail because there's no load type
            Load(magnitude=10.0, direction=[0, 0, 1], load_type=None)

        # Missing magnitude
        with self.assertRaises(ValueError):
            # We expect validation to fail because there's no magnitude
            Load(load_type="test", direction=[0, 0, 1], magnitude=None)

        # Missing direction
        with self.assertRaises(ValueError):
            # We expect validation to fail because there's no direction
            Load(load_type="test", magnitude=10.0, direction=None)

        # Invalid direction size
        with self.assertRaises(ValueError):
            # We expect validation to fail because direction size is wrong
            Load(load_type="test", magnitude=10.0, direction=[1, 2, 3, 4])


class TestPointLoad(unittest.TestCase):
    """Tests for the PointLoad class."""

    def test_init_with_valid_parameters(self):
        """Test initializing a PointLoad with valid parameters."""
        point_load = PointLoad(
            id="test-point-load-1",
            magnitude=10.0,
            direction=[0, 0, 1],
            position=[1, 2, 3],
        )
        self.assertEqual(point_load.id, "test-point-load-1")
        self.assertEqual(
            point_load.entity_type, "point"
        )  # Changed from load_type to entity_type
        self.assertEqual(point_load.magnitude, 10.0)
        np.testing.assert_array_equal(point_load.direction, np.array([0, 0, 1]))
        self.assertEqual(point_load.position, (1, 2, 3))  # Now a tuple

    def test_validation_failures(self):
        """Test PointLoad validation failures."""
        # Missing position
        with self.assertRaises(ValueError):
            # We expect validation to fail because there's no position
            PointLoad(magnitude=10.0, direction=[0, 0, 1], position=None)

        # Invalid position size
        with self.assertRaises(ValueError):
            # We expect validation to fail because position size is wrong
            PointLoad(magnitude=10.0, direction=[0, 0, 1], position=[1, 2, 3, 4])


class TestLineLoad(unittest.TestCase):
    """Tests for the LineLoad class."""

    def test_init_with_valid_parameters(self):
        """Test initializing a LineLoad with valid parameters."""
        line_load = LineLoad(
            id="test-line-load-1",
            magnitude=10.0,
            direction=[0, 0, 1],
            start_position=[0, 0, 0],
            end_position=[1, 1, 1],
        )
        self.assertEqual(line_load.id, "test-line-load-1")
        self.assertEqual(
            line_load.entity_type, "line"
        )  # Changed from load_type to entity_type
        self.assertEqual(line_load.magnitude, 10.0)
        np.testing.assert_array_equal(line_load.direction, np.array([0, 0, 1]))
        self.assertEqual(line_load.start_position, (0, 0, 0))  # Now a tuple
        self.assertEqual(line_load.end_position, (1, 1, 1))  # Now a tuple
        self.assertEqual(line_load.distribution, "uniform")

    def test_linear_distribution(self):
        """Test setting up a linear distribution."""
        line_load = LineLoad(
            magnitude=10.0,
            direction=[0, 0, 1],
            start_position=[0, 0, 0],
            end_position=[1, 1, 1],
            distribution="linear",
            start_magnitude=5.0,
            end_magnitude=15.0,
        )
        self.assertEqual(line_load.distribution, "linear")
        self.assertEqual(line_load.start_magnitude, 5.0)
        self.assertEqual(line_load.end_magnitude, 15.0)

    def test_get_length(self):
        """Test calculating the length of the line segment."""
        line_load = LineLoad(
            magnitude=10.0,
            direction=[0, 0, 1],
            start_position=[0, 0, 0],
            end_position=[3, 4, 0],
        )
        self.assertEqual(line_load.get_length(), 5.0)

    def test_get_magnitude_at(self):
        """Test getting the magnitude at different positions along the line."""
        # Uniform distribution
        uniform_load = LineLoad(
            magnitude=10.0,
            direction=[0, 0, 1],
            start_position=[0, 0, 0],
            end_position=[1, 1, 1],
        )
        self.assertEqual(uniform_load.get_magnitude_at(0.0), 10.0)
        self.assertEqual(uniform_load.get_magnitude_at(0.5), 10.0)
        self.assertEqual(uniform_load.get_magnitude_at(1.0), 10.0)

        # Linear distribution
        linear_load = LineLoad(
            magnitude=10.0,
            direction=[0, 0, 1],
            start_position=[0, 0, 0],
            end_position=[1, 1, 1],
            distribution="linear",
            start_magnitude=5.0,
            end_magnitude=15.0,
        )
        self.assertEqual(linear_load.get_magnitude_at(0.0), 5.0)
        self.assertEqual(linear_load.get_magnitude_at(0.5), 10.0)
        self.assertEqual(linear_load.get_magnitude_at(1.0), 15.0)

        # Invalid position
        with self.assertRaises(ValueError):
            uniform_load.get_magnitude_at(-0.1)
        with self.assertRaises(ValueError):
            uniform_load.get_magnitude_at(1.1)

    def test_validation_failures(self):
        """Test LineLoad validation failures."""
        # Missing start position
        with self.assertRaises(ValueError):
            # We expect validation to fail because there's no start position
            LineLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                start_position=None,
                end_position=[1, 1, 1],
            )

        # Missing end position
        with self.assertRaises(ValueError):
            # We expect validation to fail because there's no end position
            LineLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                start_position=[0, 0, 0],
                end_position=None,
            )

        # Invalid start position size
        with self.assertRaises(ValueError):
            # We expect validation to fail because start position size is wrong
            LineLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                start_position=[0, 0, 0, 0],
                end_position=[1, 1, 1],
            )

        # Invalid end position size
        with self.assertRaises(ValueError):
            # We expect validation to fail because end position size is wrong
            LineLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                start_position=[0, 0, 0],
                end_position=[1, 1, 1, 1],
            )

        # Invalid distribution type
        with self.assertRaises(ValueError):
            # We expect validation to fail because distribution type is invalid
            LineLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                start_position=[0, 0, 0],
                end_position=[1, 1, 1],
                distribution="invalid",
            )

        # Linear distribution without start magnitude
        with self.assertRaises(ValueError):
            # We expect validation to fail because start magnitude is required for linear distribution
            LineLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                start_position=[0, 0, 0],
                end_position=[1, 1, 1],
                distribution="linear",
                end_magnitude=15.0,
            )

        # Linear distribution without end magnitude
        with self.assertRaises(ValueError):
            # We expect validation to fail because end magnitude is required for linear distribution
            LineLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                start_position=[0, 0, 0],
                end_position=[1, 1, 1],
                distribution="linear",
                start_magnitude=5.0,
            )


class TestAreaLoad(unittest.TestCase):
    """Tests for the AreaLoad class."""

    def test_init_with_valid_parameters(self):
        """Test initializing an AreaLoad with valid parameters."""
        area_load = AreaLoad(
            id="test-area-load-1",
            magnitude=10.0,
            direction=[0, 0, 1],
            surface_reference="surface-1",
        )
        self.assertEqual(area_load.id, "test-area-load-1")
        self.assertEqual(
            area_load.entity_type, "area"
        )  # Changed from load_type to entity_type
        self.assertEqual(area_load.magnitude, 10.0)
        np.testing.assert_array_equal(area_load.direction, np.array([0, 0, 1]))
        self.assertEqual(area_load.surface_reference, "surface-1")
        self.assertEqual(area_load.distribution, "uniform")

    def test_custom_distribution(self):
        """Test setting a custom distribution."""
        area_load = AreaLoad(
            magnitude=10.0,
            direction=[0, 0, 1],
            surface_reference="surface-1",
            distribution="custom",
        )
        self.assertEqual(area_load.distribution, "custom")

    def test_validation_failures(self):
        """Test AreaLoad validation failures."""
        # Missing surface reference
        with self.assertRaises(ValueError):
            # We expect validation to fail because there's no surface reference
            AreaLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                surface_reference=None,
            )

        # Invalid distribution type
        with self.assertRaises(ValueError):
            # We expect validation to fail because distribution type is invalid
            AreaLoad(
                magnitude=10.0,
                direction=[0, 0, 1],
                surface_reference="surface-1",
                distribution="invalid",
            )


class TestLoadGroup(unittest.TestCase):
    """Tests for the LoadGroup class."""

    def setUp(self):
        """Set up test loads."""
        self.load1 = PointLoad(
            id="load-1",
            magnitude=10.0,
            direction=[0, 0, 1],
            position=[1, 2, 3],
        )
        self.load2 = PointLoad(
            id="load-2",
            magnitude=20.0,
            direction=[0, 1, 0],
            position=[4, 5, 6],
        )

    def test_init_with_valid_parameters(self):
        """Test initializing a LoadGroup with valid parameters."""
        load_group = LoadGroup(
            id="test-group-1",
            name="Test Group",
            description="A test load group",
            loads=[self.load1, self.load2],
        )
        self.assertEqual(load_group.id, "test-group-1")
        self.assertEqual(load_group.name, "Test Group")
        self.assertEqual(load_group.description, "A test load group")
        self.assertEqual(len(load_group.loads), 2)
        self.assertIn(self.load1, load_group.loads)
        self.assertIn(self.load2, load_group.loads)

    def test_auto_id_and_name_generation(self):
        """Test that an ID and name are automatically generated if not provided."""
        load_group = LoadGroup()
        self.assertIsNotNone(load_group.id)
        self.assertTrue(isinstance(load_group.id, str))
        self.assertTrue(load_group.name.startswith("LoadGroup-"))

    def test_add_load(self):
        """Test adding a load to the group."""
        load_group = LoadGroup(name="Test Group")
        self.assertEqual(len(load_group), 0)

        load_group.add_load(self.load1)
        self.assertEqual(len(load_group), 1)
        self.assertIn(self.load1, load_group.loads)

        # Adding the same load again should have no effect
        load_group.add_load(self.load1)
        self.assertEqual(len(load_group), 1)

        load_group.add_load(self.load2)
        self.assertEqual(len(load_group), 2)
        self.assertIn(self.load2, load_group.loads)

    def test_remove_load(self):
        """Test removing a load from the group."""
        load_group = LoadGroup(loads=[self.load1, self.load2])
        self.assertEqual(len(load_group), 2)

        # Remove an existing load
        result = load_group.remove_load(self.load1)
        self.assertTrue(result)
        self.assertEqual(len(load_group), 1)
        self.assertNotIn(self.load1, load_group.loads)
        self.assertIn(self.load2, load_group.loads)

        # Try to remove a load that's not in the group
        result = load_group.remove_load(self.load1)
        self.assertFalse(result)
        self.assertEqual(len(load_group), 1)

    def test_get_load_by_id(self):
        """Test getting a load by its ID."""
        load_group = LoadGroup(loads=[self.load1, self.load2])

        # Get an existing load
        load = load_group.get_load_by_id("load-1")
        self.assertEqual(load, self.load1)

        # Try to get a load that's not in the group
        load = load_group.get_load_by_id("non-existent-load")
        self.assertIsNone(load)

    def test_clear(self):
        """Test clearing all loads from the group."""
        load_group = LoadGroup(loads=[self.load1, self.load2])
        self.assertEqual(len(load_group), 2)

        load_group.clear()
        self.assertEqual(len(load_group), 0)
        self.assertEqual(load_group.loads, [])


class TestLoadCombination(unittest.TestCase):
    """Tests for the LoadCombination class."""

    def setUp(self):
        """Set up test load groups."""
        self.load1 = PointLoad(
            id="load-1",
            magnitude=10.0,
            direction=[0, 0, 1],
            position=[1, 2, 3],
        )
        self.load2 = PointLoad(
            id="load-2",
            magnitude=20.0,
            direction=[0, 1, 0],
            position=[4, 5, 6],
        )

        self.group1 = LoadGroup(
            id="group-1",
            name="Dead Load",
            loads=[self.load1],
        )

        self.group2 = LoadGroup(
            id="group-2",
            name="Live Load",
            loads=[self.load2],
        )

    def test_init_with_valid_parameters(self):
        """Test initializing a LoadCombination with valid parameters."""
        load_combo = LoadCombination(
            id="test-combo-1",
            name="Test Combination",
            description="A test load combination",
            load_groups={"group-1": 1.2, "group-2": 1.6},
        )
        self.assertEqual(load_combo.id, "test-combo-1")
        self.assertEqual(load_combo.name, "Test Combination")
        self.assertEqual(load_combo.description, "A test load combination")
        self.assertEqual(len(load_combo), 2)
        self.assertEqual(load_combo.load_groups["group-1"], 1.2)
        self.assertEqual(load_combo.load_groups["group-2"], 1.6)

    def test_auto_id_and_name_generation(self):
        """Test that an ID and name are automatically generated if not provided."""
        load_combo = LoadCombination()
        self.assertIsNotNone(load_combo.id)
        self.assertTrue(isinstance(load_combo.id, str))
        self.assertTrue(load_combo.name.startswith("Combination-"))

    def test_add_load_group(self):
        """Test adding a load group to the combination."""
        load_combo = LoadCombination(name="Test Combination")
        self.assertEqual(len(load_combo), 0)

        # Add by reference
        load_combo.add_load_group(self.group1, 1.2)
        self.assertEqual(len(load_combo), 1)
        self.assertEqual(load_combo.load_groups[self.group1.id], 1.2)

        # Add by ID
        load_combo.add_load_group("group-2", 1.6)
        self.assertEqual(len(load_combo), 2)
        self.assertEqual(load_combo.load_groups["group-2"], 1.6)

        # Adding with default factor
        load_combo = LoadCombination()
        load_combo.add_load_group(self.group1)
        self.assertEqual(load_combo.load_groups[self.group1.id], 1.0)

    def test_remove_load_group(self):
        """Test removing a load group from the combination."""
        load_combo = LoadCombination(
            load_groups={"group-1": 1.2, "group-2": 1.6},
        )
        self.assertEqual(len(load_combo), 2)

        # Remove by reference
        result = load_combo.remove_load_group(self.group1)
        self.assertTrue(result)
        self.assertEqual(len(load_combo), 1)
        self.assertNotIn(self.group1.id, load_combo.load_groups)
        self.assertIn("group-2", load_combo.load_groups)

        # Remove by ID
        result = load_combo.remove_load_group("group-2")
        self.assertTrue(result)
        self.assertEqual(len(load_combo), 0)

        # Try to remove a group that's not in the combination
        result = load_combo.remove_load_group("non-existent-group")
        self.assertFalse(result)

    def test_get_factor(self):
        """Test getting the factor for a load group."""
        load_combo = LoadCombination(
            load_groups={"group-1": 1.2, "group-2": 1.6},
        )

        # Get by reference
        factor = load_combo.get_factor(self.group1)
        self.assertEqual(factor, 1.2)

        # Get by ID
        factor = load_combo.get_factor("group-2")
        self.assertEqual(factor, 1.6)

        # Try to get a factor for a group that's not in the combination
        factor = load_combo.get_factor("non-existent-group")
        self.assertIsNone(factor)

    def test_update_factor(self):
        """Test updating the factor for a load group."""
        load_combo = LoadCombination(
            load_groups={"group-1": 1.2, "group-2": 1.6},
        )

        # Update by reference
        result = load_combo.update_factor(self.group1, 1.4)
        self.assertTrue(result)
        self.assertEqual(load_combo.load_groups[self.group1.id], 1.4)

        # Update by ID
        result = load_combo.update_factor("group-2", 1.8)
        self.assertTrue(result)
        self.assertEqual(load_combo.load_groups["group-2"], 1.8)

        # Try to update a factor for a group that's not in the combination
        result = load_combo.update_factor("non-existent-group", 2.0)
        self.assertFalse(result)

    def test_clear(self):
        """Test clearing all load groups from the combination."""
        load_combo = LoadCombination(
            load_groups={"group-1": 1.2, "group-2": 1.6},
        )
        self.assertEqual(len(load_combo), 2)

        load_combo.clear()
        self.assertEqual(len(load_combo), 0)
        self.assertEqual(load_combo.load_groups, {})


if __name__ == "__main__":
    unittest.main()
