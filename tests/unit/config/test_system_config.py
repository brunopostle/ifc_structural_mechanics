import os
import tempfile

import yaml


def test_system_config_custom_temp_directory():
    """
    Test that custom temp directory from config file is respected when valid.
    """
    # Create a temporary directory that is guaranteed to be writable
    with tempfile.TemporaryDirectory() as custom_temp_dir:

        # Import the temp_dir module
        from ifc_structural_mechanics.utils import temp_dir

        # Initialize the temp_dir module if it's not already initialized
        # This ensures we have a valid shared temp directory to compare against
        temp_dir.setup_temp_dir(keep_files=True)

        # Create a temporary config file with a custom temp directory
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".yaml"
        ) as temp_config:
            config_data = {"temp_directory": custom_temp_dir}
            yaml.safe_dump(config_data, temp_config)
            temp_config_path = temp_config.name

        try:
            # Load the configuration with the custom temp directory
            from ifc_structural_mechanics.config.system_config import SystemConfig

            config = SystemConfig(temp_config_path)

            # Verify that the custom temp directory is used
            assert config.get_temp_directory() == custom_temp_dir

            # Now test with a non-writable path
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".yaml"
            ) as temp_config2:
                config_data = {"temp_directory": "/path/that/doesnt/exist/hopefully"}
                yaml.safe_dump(config_data, temp_config2)
                temp_config_path2 = temp_config2.name

            try:
                # Load the configuration with an invalid temp directory
                config2 = SystemConfig(temp_config_path2)

                # Get the actual temp directory from the temp_dir module
                expected_temp_dir = temp_dir.get_temp_dir()

                # Verify that it falls back to the default temp directory from temp_dir module
                assert config2.get_temp_directory() == expected_temp_dir

            finally:
                # Clean up the second temporary file
                os.unlink(temp_config_path2)

        finally:
            # Clean up the first temporary file
            os.unlink(temp_config_path)


def test_system_config_save_and_load():
    """
    Test saving and loading SystemConfig.
    """
    # Create a temporary directory for the test
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = os.path.join(temp_dir, "system_config.yaml")

        # Import the system config
        from ifc_structural_mechanics.config.system_config import SystemConfig

        # Create a config
        config = SystemConfig()

        # Set a custom logging level
        config._config["logging"]["level"] = "DEBUG"

        # Save the config
        config.save_config(config_path)

        # Load the saved config
        loaded_config = SystemConfig(config_path)

        # Verify the loaded config has the custom logging level
        assert loaded_config._config["logging"]["level"] == "DEBUG"


def test_system_config_executables():
    """
    Test executable path handling.
    """
    from ifc_structural_mechanics.config.system_config import SystemConfig

    # Create a config
    config = SystemConfig()

    # Test getting executable paths
    calculix_path = config.get_calculix_path()
    gmsh_path = config.get_gmsh_path()

    # These might be None if the executables aren't in PATH
    # Just test that the methods run and return values of the expected type
    assert calculix_path is None or isinstance(calculix_path, str)
    assert gmsh_path is None or isinstance(gmsh_path, str)

    # Test the generic method
    assert config.get_executable_path("calculix") == calculix_path
    assert config.get_executable_path("gmsh") == gmsh_path

    # Test getting a non-existent executable
    assert config.get_executable_path("non_existent") is None


def test_system_config_logging():
    """
    Test the logging configuration.
    """
    import logging

    from ifc_structural_mechanics.config.system_config import SystemConfig

    # Create a config
    config = SystemConfig()

    # Configure logging
    logger = config.configure_logging()

    # Verify logger is properly configured
    assert isinstance(logger, logging.Logger)
    assert logger.name == "ifc_structural_mechanics"

    # Test with string logging level
    config._config["logging"]["level"] = "DEBUG"
    logger = config.configure_logging()
    assert logger.level == logging.DEBUG

    # Test with integer logging level
    config._config["logging"]["level"] = logging.WARNING
    logger = config.configure_logging()
    assert logger.level == logging.WARNING
