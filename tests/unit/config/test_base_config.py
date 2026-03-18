import os
import tempfile
import unittest
from typing import Any, Dict

try:
    from ifc_structural_mechanics.config.base_config import BaseConfig
except ImportError:
    # If BaseConfig is not yet implemented, create a mock for testing
    from abc import ABC, abstractmethod

    class BaseConfig(ABC):
        @abstractmethod
        def _get_default_config(self) -> Dict[str, Any]:
            pass

        @abstractmethod
        def validate(self) -> None:
            pass


# Create a concrete implementation of BaseConfig for testing
class ConcreteConfig(BaseConfig):
    """
    Concrete implementation of BaseConfig for testing purposes.
    """

    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get the default configuration dictionary.

        Returns:
            Dict[str, Any]: Default configuration dictionary.
        """
        return {
            "string_param": "default",
            "int_param": 42,
            "float_param": 3.14,
            "bool_param": True,
            "nested": {
                "nested_string": "nested_default",
                "nested_int": 100,
                "nested_list": [1, 2, 3],
            },
            "range_param": 5,
        }

    def validate(self) -> None:
        """
        Validate the configuration and apply default values where needed.
        """
        # Validate and convert types
        self._config["string_param"] = self.convert_value(
            self._config.get("string_param"), str, "default"
        )
        self._config["int_param"] = self.convert_value(
            self._config.get("int_param"), int, 42
        )
        self._config["float_param"] = self.convert_value(
            self._config.get("float_param"), float, 3.14
        )
        self._config["bool_param"] = self.convert_value(
            self._config.get("bool_param"), bool, True
        )

        # Validate nested structure using validate_dict_keys
        default_nested = {
            "nested_string": "nested_default",
            "nested_int": 100,
            "nested_list": [1, 2, 3],
        }

        if "nested" not in self._config:
            self._config["nested"] = default_nested
        else:
            self._config["nested"] = self.validate_dict_keys(
                self._config["nested"], default_nested
            )

        # Validate range param
        self._config["range_param"] = self.ensure_value_in_range(
            self.convert_value(self._config.get("range_param"), int, 5), 1, 10
        )


class TestBaseConfig(unittest.TestCase):
    """
    Unit tests for the BaseConfig class.
    """

    def setUp(self):
        """Set up test cases."""
        self.config = ConcreteConfig()  # Use the concrete implementation
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        """Clean up after tests."""
        self.temp_dir.cleanup()

    def test_default_config(self):
        """Test that default configuration is properly initialized."""
        self.assertEqual(self.config._config["string_param"], "default")
        self.assertEqual(self.config._config["int_param"], 42)
        self.assertEqual(self.config._config["float_param"], 3.14)
        self.assertTrue(self.config._config["bool_param"])
        self.assertEqual(
            self.config._config["nested"]["nested_string"], "nested_default"
        )
        self.assertEqual(self.config._config["nested"]["nested_int"], 100)
        self.assertEqual(self.config._config["nested"]["nested_list"], [1, 2, 3])
        self.assertEqual(self.config._config["range_param"], 5)

    def test_save_and_load_config(self):
        """Test saving and loading configuration from a file."""
        # Create a temporary file for testing
        config_file = os.path.join(self.temp_dir.name, "test_config.yaml")

        # Modify the configuration
        self.config._config["string_param"] = "modified"
        self.config._config["int_param"] = 99

        # Save the configuration
        self.config.save_config(config_file)

        # Check that the file exists
        self.assertTrue(os.path.exists(config_file))

        # Create a new configuration instance and load from file
        new_config = ConcreteConfig(config_file)

        # Check that the loaded configuration matches the saved one
        self.assertEqual(new_config._config["string_param"], "modified")
        self.assertEqual(new_config._config["int_param"], 99)
        self.assertEqual(new_config._config["float_param"], 3.14)  # Unchanged value

    def test_nonexistent_config_file(self):
        """Test handling of nonexistent configuration file."""
        nonexistent_file = os.path.join(
            self.temp_dir.name, "definitely_does_not_exist.yaml"
        )
        # Make sure the file really doesn't exist
        if os.path.exists(nonexistent_file):
            os.remove(nonexistent_file)

        with self.assertRaises(FileNotFoundError):
            ConcreteConfig(nonexistent_file)

    def test_invalid_yaml_file(self):
        """Test handling of invalid YAML file."""
        # Create an invalid YAML file
        invalid_file = os.path.join(self.temp_dir.name, "invalid.yaml")
        with open(invalid_file, "w") as f:
            f.write("this is not valid yaml: : :")

        # Attempt to load the invalid file
        with self.assertRaises(ValueError):
            ConcreteConfig(invalid_file)

    def test_convert_value(self):
        """Test value conversion functionality."""
        # Test successful conversions
        self.assertEqual(self.config.convert_value("42", int, 0), 42)
        self.assertEqual(self.config.convert_value("3.14", float, 0.0), 3.14)
        self.assertEqual(self.config.convert_value(1, bool, False), True)
        self.assertEqual(self.config.convert_value(0, bool, True), False)

        # Test fallback to default for failed conversions
        self.assertEqual(self.config.convert_value("not_a_number", int, 99), 99)
        self.assertEqual(self.config.convert_value(None, str, "default"), "default")

        # Test already correct types pass through unchanged
        self.assertEqual(self.config.convert_value(42, int, 0), 42)
        self.assertEqual(self.config.convert_value(3.14, float, 0.0), 3.14)

    def test_ensure_value_in_range(self):
        """Test range validation functionality."""
        # Test values within range pass through unchanged
        self.assertEqual(self.config.ensure_value_in_range(5, 1, 10), 5)

        # Test values outside range are clamped
        self.assertEqual(self.config.ensure_value_in_range(0, 1, 10), 1)
        self.assertEqual(self.config.ensure_value_in_range(15, 1, 10), 10)

        # Test with float values
        self.assertEqual(self.config.ensure_value_in_range(2.5, 1.0, 5.0), 2.5)
        self.assertEqual(self.config.ensure_value_in_range(0.5, 1.0, 5.0), 1.0)

    def test_validate_dict_keys(self):
        """Test dictionary validation functionality."""
        # Test with incomplete dictionary
        incomplete = {"key1": "value1"}
        default = {"key1": "default1", "key2": "default2"}
        result = self.config.validate_dict_keys(incomplete, default)

        self.assertEqual(result["key1"], "value1")  # Original value preserved
        self.assertEqual(result["key2"], "default2")  # Default value added

        # Test with type conversion
        converter_map = {"num": int, "flag": bool}
        to_convert = {"num": "42", "flag": 1, "text": "hello"}
        default = {"num": 0, "flag": False, "text": "default"}

        result = self.config.validate_dict_keys(to_convert, default, converter_map)
        self.assertEqual(result["num"], 42)  # Converted to int
        self.assertEqual(result["flag"], True)  # Converted to bool
        self.assertEqual(result["text"], "hello")  # Unchanged

        # Test with nested dictionaries
        nested = {"level1": {"value": 10}}
        default_nested = {"level1": {"value": 0, "missing": "default"}}

        result = self.config.validate_dict_keys(nested, default_nested)
        self.assertEqual(result["level1"]["value"], 10)  # Original value preserved
        self.assertEqual(
            result["level1"]["missing"], "default"
        )  # Default added to nested dict

    def test_deep_merge(self):
        """Test deep merging of dictionaries."""
        base = {
            "key1": "value1",
            "nested": {"nested1": "original", "nested2": 100},
            "list": [1, 2, 3],
        }

        to_merge = {
            "key1": "new_value",
            "key2": "added_value",
            "nested": {"nested1": "modified", "nested3": "added"},
        }

        # Create a copy for testing
        base_copy = base.copy()
        self.config.deep_merge(base_copy, to_merge)

        # Check top-level modifications
        self.assertEqual(base_copy["key1"], "new_value")
        self.assertEqual(base_copy["key2"], "added_value")
        self.assertEqual(base_copy["list"], [1, 2, 3])  # Unchanged

        # Check nested modifications
        self.assertEqual(base_copy["nested"]["nested1"], "modified")
        self.assertEqual(base_copy["nested"]["nested2"], 100)  # Unchanged
        self.assertEqual(base_copy["nested"]["nested3"], "added")


if __name__ == "__main__":
    unittest.main()
