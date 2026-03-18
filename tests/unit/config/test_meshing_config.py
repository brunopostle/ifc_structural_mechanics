import os
import tempfile

import pytest
import yaml

from ifc_structural_mechanics.config.meshing_config import MeshingConfig


def test_meshing_config_default_initialization():
    """
    Test default initialization of MeshingConfig.
    """
    config = MeshingConfig()

    # Check global settings
    global_settings = config._config["global_settings"]
    assert "default_element_size" in global_settings
    assert "max_element_size" in global_settings
    assert "min_element_size" in global_settings

    # Check member type configurations
    member_types = config._config["member_types"]
    assert "curve_members" in member_types
    assert "surface_members" in member_types

    # Check mesh quality settings
    mesh_quality = config._config["mesh_quality"]
    assert "skewness_threshold" in mesh_quality
    assert "aspect_ratio_threshold" in mesh_quality
    assert "minimum_angle" in mesh_quality
    assert "maximum_angle" in mesh_quality


def test_meshing_config_load_from_file():
    """
    Test loading configuration from a YAML file.
    """
    # Create a temporary config file
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        config_data = {
            "global_settings": {
                "default_element_size": 0.05,
                "max_element_size": 0.5,
                "min_element_size": 0.005,
            },
            "member_types": {
                "curve_members": {
                    "element_type": "1D_quadratic",
                    "element_size": 0.05,
                    "refinement_level": 2,
                },
                "surface_members": {
                    "element_type": "2D_quadratic_triangle",
                    "element_size": 0.05,
                    "refinement_level": 1,
                },
            },
            "mesh_quality": {
                "skewness_threshold": 0.7,
                "aspect_ratio_threshold": 8.0,
                "minimum_angle": 15.0,
                "maximum_angle": 165.0,
            },
        }
        yaml.safe_dump(config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Load the configuration
        config = MeshingConfig(temp_config_path)

        # Verify loaded configuration
        global_settings = config._config["global_settings"]
        assert global_settings["default_element_size"] == 0.05
        assert global_settings["max_element_size"] == 0.5
        assert global_settings["min_element_size"] == 0.005

        # Check member type configurations
        curve_members = config._config["member_types"]["curve_members"]
        assert curve_members["element_type"] == "1D_quadratic"
        assert curve_members["element_size"] == 0.05
        assert curve_members["refinement_level"] == 2

        surface_members = config._config["member_types"]["surface_members"]
        assert surface_members["element_type"] == "2D_quadratic_triangle"
        assert surface_members["element_size"] == 0.05
        assert surface_members["refinement_level"] == 1

        # Check mesh quality settings
        mesh_quality = config._config["mesh_quality"]
        assert mesh_quality["skewness_threshold"] == 0.7
        assert mesh_quality["aspect_ratio_threshold"] == 8.0
        assert mesh_quality["minimum_angle"] == 15.0
        assert mesh_quality["maximum_angle"] == 165.0
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_meshing_config_partial_load_from_file():
    """
    Test loading a partial configuration file.
    """
    # Create a temporary config file with partial configuration
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        config_data = {
            "global_settings": {"default_element_size": 0.2},
            "member_types": {"curve_members": {"element_type": "1D_quadratic"}},
        }
        yaml.safe_dump(config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Load the configuration
        config = MeshingConfig(temp_config_path)

        # Verify configuration
        assert config._config["global_settings"]["default_element_size"] == 0.2
        # Other settings should remain at default values
        assert config._config["global_settings"]["max_element_size"] == 1.0
        assert config._config["global_settings"]["min_element_size"] == 0.01

        # Check member type configuration
        curve_members = config._config["member_types"]["curve_members"]
        assert curve_members["element_type"] == "1D_quadratic"
        # Other settings should remain at default values
        assert curve_members["element_size"] == 0.2
        assert curve_members["refinement_level"] == 0
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_meshing_config_save_config():
    """
    Test saving configuration to a YAML file.
    """
    config = MeshingConfig()

    # Create a temporary file path
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        temp_config_path = temp_config.name

    try:
        # Save the configuration
        config.save_config(temp_config_path)

        # Verify the file was created and can be read
        assert os.path.exists(temp_config_path)

        # Load and verify the saved configuration
        with open(temp_config_path, "r") as f:
            loaded_config = yaml.safe_load(f)

        # Check key configuration elements
        assert "global_settings" in loaded_config
        assert "member_types" in loaded_config
        assert "mesh_quality" in loaded_config
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_meshing_config_set_element_size():
    """
    Test setting element size for different member types.
    """
    config = MeshingConfig()

    # Set valid element sizes
    config.set_element_size("curve_members", 0.05)
    config.set_element_size("surface_members", 0.05)

    # Verify the changes
    assert config.get_element_size("curve_members") == 0.05
    assert config.get_element_size("surface_members") == 0.05

    # Try setting invalid element size
    with pytest.raises(ValueError, match="Invalid element size"):
        config.set_element_size("curve_members", 10.0)  # Too large


def test_meshing_config_set_element_type():
    """
    Test setting element type for different member types.
    """
    config = MeshingConfig()

    # Set valid element types
    config.set_element_type("curve_members", "1D_quadratic")
    config.set_element_type("surface_members", "2D_quadratic_triangle")

    # Verify the changes
    assert config.get_element_type("curve_members") == "1D_quadratic"
    assert config.get_element_type("surface_members") == "2D_quadratic_triangle"

    # Try setting invalid element type
    with pytest.raises(ValueError, match="Invalid element type"):
        config.set_element_type("curve_members", "invalid_type")


def test_meshing_config_mesh_quality_settings():
    """
    Test getting mesh quality settings.
    """
    config = MeshingConfig()

    # Get mesh quality settings
    mesh_quality = config.get_mesh_quality_settings()

    # Verify key settings exist
    assert "skewness_threshold" in mesh_quality
    assert "aspect_ratio_threshold" in mesh_quality
    assert "minimum_angle" in mesh_quality
    assert "maximum_angle" in mesh_quality


def test_meshing_config_invalid_configuration():
    """
    Test error handling for invalid configurations.
    """
    # Create a temporary config file with invalid data
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        invalid_config_data = {
            "global_settings": {
                "default_element_size": 100,  # Too large
                "max_element_size": 0.01,  # Smaller than min
            },
            "member_types": {
                "curve_members": {
                    "element_type": "invalid_type",
                    "refinement_level": 10,  # Out of range
                }
            },
            "mesh_quality": {
                "skewness_threshold": 2.0,  # Out of range
                "minimum_angle": -10,  # Invalid angle
            },
        }
        yaml.safe_dump(invalid_config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Attempt to load invalid configuration
        with pytest.raises(ValueError):
            MeshingConfig(temp_config_path)
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_meshing_config_type_conversion():
    """
    Test configuration value conversions and default handling.
    """
    # Create a temporary config file with mixed type configurations
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        config_data = {
            "global_settings": {
                "default_element_size": "0.1",  # string instead of float
                "max_element_size": 1.5,  # float
            },
            "member_types": {
                "curve_members": {"refinement_level": "2"}  # string instead of int
            },
        }
        yaml.safe_dump(config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Load the configuration
        config = MeshingConfig(temp_config_path)

        # Verify type conversion and default handling
        global_settings = config._config["global_settings"]
        assert isinstance(global_settings["default_element_size"], float)
        assert global_settings["default_element_size"] == 0.1

        curve_members = config._config["member_types"]["curve_members"]
        assert isinstance(curve_members["refinement_level"], int)
        assert curve_members["refinement_level"] == 2
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_meshing_config_default_element_type():
    """
    Test that default element types are correctly set.
    """
    config = MeshingConfig()

    # Check default element types for curve and surface members
    assert config.get_element_type("curve_members") == "1D_linear"
    assert config.get_element_type("surface_members") == "2D_linear_triangle"


def test_meshing_config_element_type_validation():
    """
    Test validation of element types for different member types.
    """
    config = MeshingConfig()

    # Verify valid element types
    for member_type, types in config.ELEMENT_TYPES.items():
        for element_type in types:
            # This should not raise an exception
            config.set_element_type(member_type, element_type)

        # Verify an error is raised for invalid element types
        with pytest.raises(ValueError, match="Invalid element type"):
            config.set_element_type(member_type, "non_existent_type")


def test_python_api_setting():
    """
    Test the use_python_api property and related methods.
    """
    config = MeshingConfig()

    # Test default value
    assert config.use_python_api is True

    # Test setting via method
    config.set_use_python_api(False)
    assert config.get_use_python_api() is False

    # Test setting via property
    config.use_python_api = True
    assert config.use_python_api is True
