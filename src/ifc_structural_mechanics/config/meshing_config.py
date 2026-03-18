from typing import Any, Dict

from .base_config import BaseConfig


class MeshingConfig(BaseConfig):
    """
    Configuration management for meshing parameters.

    Handles element types, mesh density, and quality settings.
    """

    ELEMENT_TYPES = {
        "curve_members": [
            "1D_linear",  # 2-node linear element
            "1D_quadratic",  # 3-node quadratic element
        ],
        "surface_members": [
            "2D_linear_triangle",  # 3-node linear triangle
            "2D_linear_quadrilateral",  # 4-node linear quadrilateral
            "2D_quadratic_triangle",  # 6-node quadratic triangle
            "2D_quadratic_quadrilateral",  # 8-node quadratic quadrilateral
        ],
    }

    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get the default configuration dictionary.

        Returns:
            Dict[str, Any]: Default configuration dictionary.
        """
        return {
            "global_settings": {
                "default_element_size": 0.1,  # Default element size (meters)
                "max_element_size": 1.0,
                "min_element_size": 0.01,
                "use_python_api": True,  # Use Python API by default instead of executable
            },
            "member_types": {
                "curve_members": {
                    "element_type": "1D_linear",
                    "element_size": 0.1,
                    "refinement_level": 0,
                },
                "surface_members": {
                    "element_type": "2D_linear_triangle",
                    "element_size": 0.1,
                    "refinement_level": 0,
                },
            },
            "mesh_quality": {
                "skewness_threshold": 0.8,
                "aspect_ratio_threshold": 10.0,
                "minimum_angle": 20.0,  # degrees
                "maximum_angle": 160.0,  # degrees
            },
        }

    def _process_loaded_config(self, file_config: Dict[str, Any]) -> None:
        """
        Process the loaded configuration and merge it with the current configuration.

        Uses deep merge for meshing config to handle nested structures properly.

        Args:
            file_config (Dict[str, Any]): Configuration loaded from a file.
        """
        if file_config:
            # Use deep merge instead of simple update
            self._deep_merge(self._config, file_config)

    def _deep_merge(self, base_dict, merge_dict):
        """
        Recursively merge two dictionaries with special handling for specific keys.

        Args:
            base_dict (Dict): The base dictionary to merge into.
            merge_dict (Dict): The dictionary to merge from.
        """
        for key, value in merge_dict.items():
            if (
                isinstance(value, dict)
                and key in base_dict
                and isinstance(base_dict[key], dict)
            ):
                if key == "member_types":
                    # Special handling for member_types
                    for member_type, member_config in value.items():
                        if member_type not in base_dict[key]:
                            base_dict[key][member_type] = {}

                        # Add any global default_element_size to specific member configurations
                        global_default_size = merge_dict.get("global_settings", {}).get(
                            "default_element_size"
                        )
                        if (
                            global_default_size is not None
                            and "element_size" not in member_config
                        ):
                            member_config["element_size"] = global_default_size

                        # Recursively merge member type configurations
                        self._deep_merge(base_dict[key][member_type], member_config)
                else:
                    # Standard recursive merge for other nested dictionaries
                    self._deep_merge(base_dict[key], value)
            else:
                # Directly update or add the value
                base_dict[key] = value

    def validate(self) -> None:
        """
        Validate the meshing configuration.

        Raises:
            ValueError: If any configuration parameter is invalid.
        """
        # Type conversion and validation for global settings
        global_settings = self._config.get("global_settings", {})

        # Convert and validate numeric values
        def convert_float(value, default):
            """Convert value to float, use default if conversion fails."""
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        # Ensure global settings have default values if not provided
        default_size = convert_float(global_settings.get("default_element_size"), 0.1)
        max_size = convert_float(global_settings.get("max_element_size"), 1.0)
        min_size = convert_float(global_settings.get("min_element_size"), 0.01)

        # Update the config with converted values
        global_settings = {
            "default_element_size": default_size,
            "max_element_size": max_size,
            "min_element_size": min_size,
            "use_python_api": global_settings.get("use_python_api", True),
        }
        self._config["global_settings"] = global_settings

        # Validate element size configuration
        if not (0 < min_size <= default_size <= max_size):
            raise ValueError(
                f"Invalid element size configuration. "
                f"Must satisfy: 0 < {min_size} <= {default_size} <= {max_size}"
            )

        # Validate and set defaults for member types
        member_types = self._config.get("member_types", {})
        default_member_config = {
            "curve_members": {
                "element_type": "1D_linear",
                "element_size": default_size,
                "refinement_level": 0,
            },
            "surface_members": {
                "element_type": "2D_linear_triangle",
                "element_size": default_size,
                "refinement_level": 0,
            },
        }

        for member_type, type_config in default_member_config.items():
            # Ensure member type exists in config, use defaults if not
            if member_type not in member_types:
                member_types[member_type] = type_config.copy()

            current_config = member_types[member_type]

            # Validate and set element type
            element_type = current_config.get(
                "element_type", type_config["element_type"]
            )
            valid_types = self.ELEMENT_TYPES.get(member_type, [])
            if element_type not in valid_types:
                raise ValueError(
                    f"Invalid element type for {member_type}: {element_type}. "
                    f"Valid types: {valid_types}"
                )
            current_config["element_type"] = element_type

            # Validate and set element size
            # Use global default_element_size if element_size is not specified
            element_size = convert_float(
                current_config.get("element_size", default_size), default_size
            )

            if not (min_size <= element_size <= max_size):
                element_size = max(min_size, min(element_size, max_size))
            current_config["element_size"] = element_size

            # Validate and set refinement level
            refinement_level = current_config.get(
                "refinement_level", type_config["refinement_level"]
            )
            try:
                refinement_level = int(refinement_level)
            except (TypeError, ValueError):
                refinement_level = type_config["refinement_level"]

            if not (0 <= refinement_level <= 5):
                refinement_level = max(0, min(refinement_level, 5))
            current_config["refinement_level"] = refinement_level

        # Update member types in config
        self._config["member_types"] = member_types

        # Validate mesh quality settings
        mesh_quality = self._config.get("mesh_quality", {})
        default_mesh_quality = {
            "skewness_threshold": 0.8,
            "aspect_ratio_threshold": 10.0,
            "minimum_angle": 20.0,
            "maximum_angle": 160.0,
        }

        # Merge defaults with existing config, converting types
        for key, default_value in default_mesh_quality.items():
            if key not in mesh_quality:
                mesh_quality[key] = default_value
            else:
                # Convert to float
                try:
                    mesh_quality[key] = float(mesh_quality[key])
                except (TypeError, ValueError):
                    mesh_quality[key] = default_value

        # Skewness threshold
        skewness = mesh_quality["skewness_threshold"]
        if not (0 <= skewness <= 1):
            skewness = max(0, min(skewness, 1))
            mesh_quality["skewness_threshold"] = skewness

        # Aspect ratio threshold
        aspect_ratio = mesh_quality["aspect_ratio_threshold"]
        if aspect_ratio < 1:
            aspect_ratio = max(1, aspect_ratio)
            mesh_quality["aspect_ratio_threshold"] = aspect_ratio

        # Angle thresholds
        min_angle = mesh_quality["minimum_angle"]
        max_angle = mesh_quality["maximum_angle"]
        if not (0 <= min_angle < max_angle <= 180):
            min_angle = max(0, min(min_angle, 179))
            max_angle = max(min_angle + 1, min(max_angle, 180))
            mesh_quality["minimum_angle"] = min_angle
            mesh_quality["maximum_angle"] = max_angle

        # Update mesh quality in config
        self._config["mesh_quality"] = mesh_quality

    # Methods for use_python_api
    def get_use_python_api(self) -> bool:
        """
        Get whether to use Python API for Gmsh or the executable.

        Returns:
            bool: True if Python API should be used, False if the executable should be used.
        """
        return self._config["global_settings"].get("use_python_api", True)

    def set_use_python_api(self, use_python_api: bool):
        """
        Set whether to use Python API for Gmsh or the executable.

        Args:
            use_python_api (bool): True to use Python API, False to use executable.
        """
        self._config["global_settings"]["use_python_api"] = bool(use_python_api)

    # Property for more convenient access in the GmshRunner class
    @property
    def use_python_api(self) -> bool:
        """
        Property for accessing the use_python_api setting.

        Returns:
            bool: True if Python API should be used, False if the executable should be used.
        """
        return self.get_use_python_api()

    @use_python_api.setter
    def use_python_api(self, value: bool):
        """
        Setter for the use_python_api property.

        Args:
            value (bool): True to use Python API, False to use executable.
        """
        self.set_use_python_api(value)

    def get_element_size(self, member_type: str) -> float:
        """
        Get the element size for a specific member type.

        Args:
            member_type (str): Type of structural member.

        Returns:
            float: Recommended element size.

        Raises:
            ValueError: If the member type is not configured.
        """
        if member_type not in self._config["member_types"]:
            raise ValueError(f"No configuration found for member type: {member_type}")

        return self._config["member_types"][member_type]["element_size"]

    def get_element_type(self, member_type: str) -> str:
        """
        Get the element type for a specific member type.

        Args:
            member_type (str): Type of structural member.

        Returns:
            str: Recommended element type.

        Raises:
            ValueError: If the member type is not configured.
        """
        if member_type not in self._config["member_types"]:
            raise ValueError(f"No configuration found for member type: {member_type}")

        return self._config["member_types"][member_type]["element_type"]

    def get_mesh_quality_settings(self) -> Dict[str, float]:
        """
        Get the mesh quality settings.

        Returns:
            Dict[str, float]: Mesh quality configuration parameters.
        """
        return self._config["mesh_quality"]

    def set_element_size(self, member_type: str, element_size: float):
        """
        Set the element size for a specific member type.

        Args:
            member_type (str): Type of structural member.
            element_size (float): Desired element size.

        Raises:
            ValueError: If the member type is not configured or size is invalid.
        """
        if member_type not in self._config["member_types"]:
            raise ValueError(f"No configuration found for member type: {member_type}")

        # Validate element size against global settings
        global_settings = self._config["global_settings"]
        min_size = global_settings["min_element_size"]
        max_size = global_settings["max_element_size"]

        if not (min_size <= element_size <= max_size):
            raise ValueError(
                f"Invalid element size. " f"Must be between {min_size} and {max_size}"
            )

        # Update element size
        self._config["member_types"][member_type]["element_size"] = element_size

    def set_element_type(self, member_type: str, element_type: str):
        """
        Set the element type for a specific member type.

        Args:
            member_type (str): Type of structural member.
            element_type (str): Desired element type.

        Raises:
            ValueError: If the member type or element type is invalid.
        """
        if member_type not in self._config["member_types"]:
            raise ValueError(f"No configuration found for member type: {member_type}")

        # Validate element type
        valid_types = self.ELEMENT_TYPES.get(member_type, [])
        if element_type not in valid_types:
            raise ValueError(
                f"Invalid element type for {member_type}: {element_type}. "
                f"Valid types: {valid_types}"
            )

        # Update element type
        self._config["member_types"][member_type]["element_type"] = element_type

    def get_mesh_dimension(self) -> int:
        """
        Get the mesh dimension (1D, 2D, or 3D) to use for meshing.

        Returns:
            int: Mesh dimension (1, 2, or 3).
        """
        # Check if mesh_dimension is explicitly defined in the config
        if "mesh_dimension" in self._config.get("global_settings", {}):
            dimension = self._config["global_settings"]["mesh_dimension"]
            # Ensure it's a valid integer between 1 and 3
            try:
                dimension = int(dimension)
                if 1 <= dimension <= 3:
                    return dimension
            except (TypeError, ValueError):
                pass

        # Default to 3D if not specified or invalid
        return 3

    def get_min_element_size(self) -> float:
        """
        Get the minimum element size allowed for meshing.

        Returns:
            float: Minimum element size.
        """
        return self._config["global_settings"]["min_element_size"]

    def get_max_element_size(self) -> float:
        """
        Get the maximum element size allowed for meshing.

        Returns:
            float: Maximum element size.
        """
        return self._config["global_settings"]["max_element_size"]

    def get_additional_options(self) -> Dict[str, Any]:
        """
        Get additional meshing options to pass to Gmsh.

        Returns:
            Dict[str, Any]: Dictionary of additional options.
        """
        # Check if additional_options is defined in the config
        if "additional_options" in self._config.get("global_settings", {}):
            return self._config["global_settings"].get("additional_options", {})

        # Default to empty dict if not specified
        return {}

    def get_quality_threshold(self) -> float:
        """
        Get the minimum quality threshold for mesh elements.

        Returns:
            float: Minimum quality threshold (0.0 to 1.0).
        """
        # Quality threshold is the inverse of skewness - high quality means low skewness
        skewness = self._config["mesh_quality"]["skewness_threshold"]
        return 1.0 - skewness
