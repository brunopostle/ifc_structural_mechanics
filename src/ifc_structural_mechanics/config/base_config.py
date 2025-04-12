from typing import Dict, Any, Optional, Union, Callable, Type, TypeVar, cast
import yaml
import os
from abc import ABC, abstractmethod

T = TypeVar("T")


class BaseConfig(ABC):
    """
    Base configuration class for IFC Structural Analysis.

    Provides common functionality for configuration management including
    loading from files, saving to files, validation, and type conversion.

    This class is designed to be subclassed by specific configuration
    classes like AnalysisConfig, MeshingConfig, and SystemConfig.
    """

    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration with default values and optional file loading.

        Args:
            config_file (Optional[str]): Path to a custom configuration file.

        Raises:
            FileNotFoundError: If the specified configuration file does not exist.
            ValueError: If there's an error parsing the configuration file.
        """
        # Initialize default configuration
        self._config: Dict[str, Any] = self._get_default_config()

        # Load configuration from file if provided
        if config_file:
            self.load_config(config_file)

        # Validate the configuration
        self.validate()

    @abstractmethod
    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get the default configuration dictionary.

        This method must be implemented by subclasses to provide their
        default configuration values.

        Returns:
            Dict[str, Any]: Default configuration dictionary.
        """
        pass

    @abstractmethod
    def validate(self) -> None:
        """
        Validate the configuration and apply default values where needed.

        This method must be implemented by subclasses to validate their
        specific configuration parameters.

        Raises:
            ValueError: If any configuration parameter is invalid.
        """
        pass

    def load_config(self, config_file: str) -> None:
        """
        Load configuration from a YAML file.

        Args:
            config_file (str): Path to the configuration file.

        Raises:
            FileNotFoundError: If the configuration file does not exist.
            ValueError: If there's an error parsing the YAML file.
        """
        try:
            with open(config_file, "r") as f:
                file_config = yaml.safe_load(f)

            # Process the loaded configuration
            self._process_loaded_config(file_config)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing configuration file: {e}")

    def _process_loaded_config(self, file_config: Dict[str, Any]) -> None:
        """
        Process the loaded configuration and merge it with the current configuration.

        By default, this method does a simple update of the configuration dictionary.
        Subclasses can override this method to implement more complex merging strategies.

        Args:
            file_config (Dict[str, Any]): Configuration loaded from a file.
        """
        if file_config:
            self._config.update(file_config)

    def deep_merge(self, base_dict: Dict[str, Any], merge_dict: Dict[str, Any]) -> None:
        """
        Recursively merge two dictionaries.

        Args:
            base_dict (Dict[str, Any]): The base dictionary to merge into.
            merge_dict (Dict[str, Any]): The dictionary to merge from.
        """
        for key, value in merge_dict.items():
            if (
                isinstance(value, dict)
                and key in base_dict
                and isinstance(base_dict[key], dict)
            ):
                # Recursively merge nested dictionaries
                self.deep_merge(base_dict[key], value)
            else:
                # Directly update or add the value
                base_dict[key] = value

    def save_config(self, config_file: str) -> None:
        """
        Save current configuration to a YAML file.

        Args:
            config_file (str): Path to save the configuration file.
        """
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, "w") as f:
            yaml.safe_dump(self._config, f)

    def convert_value(self, value: Any, expected_type: Type[T], default_value: T) -> T:
        """
        Convert a value to the expected type, returning default if conversion fails.

        Args:
            value: Value to convert.
            expected_type: Expected type for the value.
            default_value: Default value to use if conversion fails.

        Returns:
            Converted value of expected_type, or default_value if conversion fails.
        """
        if value is None:
            return default_value

        if isinstance(value, expected_type):
            return cast(T, value)

        try:
            return expected_type(value)
        except (TypeError, ValueError):
            return default_value

    def ensure_value_in_range(
        self,
        value: Union[int, float],
        min_value: Union[int, float],
        max_value: Union[int, float],
    ) -> Union[int, float]:
        """
        Ensure a numeric value is within the specified range.

        Args:
            value: Value to check.
            min_value: Minimum allowed value.
            max_value: Maximum allowed value.

        Returns:
            Value clamped to the specified range.
        """
        return max(min_value, min(value, max_value))

    def validate_dict_keys(
        self,
        config_dict: Dict[str, Any],
        default_dict: Dict[str, Any],
        converter_map: Optional[Dict[str, Callable[[Any], Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Validate and ensure all keys from default_dict exist in config_dict.

        Args:
            config_dict: Dictionary to validate.
            default_dict: Dictionary with default values.
            converter_map: Optional map of key names to converter functions.

        Returns:
            Updated config_dict with all required keys and converted values.
        """
        result = config_dict.copy()

        for key, default_value in default_dict.items():
            # Ensure key exists
            if key not in result:
                result[key] = default_value
                continue

            # Apply type conversion if converter is provided
            if converter_map and key in converter_map:
                result[key] = converter_map[key](result[key])
            elif isinstance(default_value, (int, float, str, bool)) and not isinstance(
                result[key], type(default_value)
            ):
                # Basic type conversion for primitive types
                try:
                    result[key] = type(default_value)(result[key])
                except (TypeError, ValueError):
                    result[key] = default_value

            # Recursively validate nested dictionaries
            if isinstance(default_value, dict) and isinstance(result[key], dict):
                result[key] = self.validate_dict_keys(
                    result[key], default_value, converter_map
                )

        return result
