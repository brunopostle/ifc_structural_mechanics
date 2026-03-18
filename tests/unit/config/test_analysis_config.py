import os
import tempfile

import pytest
import yaml

from ifc_structural_mechanics.config.analysis_config import AnalysisConfig


def test_analysis_config_default_initialization():
    """
    Test default initialization of AnalysisConfig.
    """
    config = AnalysisConfig()

    # Check default analysis type
    assert config.get_analysis_type() == "linear_static"

    # Check default solver parameters
    solver_params = config.get_solver_params()
    assert "max_iterations" in solver_params
    assert "convergence_tolerance" in solver_params

    # Check default result output settings
    result_output = config.get_result_output_settings()
    assert "displacement" in result_output
    assert "stress" in result_output
    assert result_output["displacement"] is True
    assert result_output["stress"] is True


def test_analysis_config_load_from_file():
    """
    Test loading configuration from a YAML file.
    """
    # Create a temporary config file
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        config_data = {
            "analysis_type": "linear_buckling",
            "solver_params": {"num_eigenvalues": 10, "solver_method": "lanczos_plus"},
            "result_output": {
                "displacement": False,
                "stress": True,
                "strain": True,
                "reaction_forces": True,
            },
        }
        yaml.safe_dump(config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Load the configuration
        config = AnalysisConfig(temp_config_path)

        # Verify loaded configuration
        assert config.get_analysis_type() == "linear_buckling"

        solver_params = config.get_solver_params()
        assert solver_params["num_eigenvalues"] == 10

        result_output = config.get_result_output_settings()
        assert result_output["displacement"] is False
        assert result_output["stress"] is True
        assert result_output["strain"] is True
        assert result_output["reaction_forces"] is True
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_analysis_config_partial_load_from_file():
    """
    Test loading a partial configuration file.
    """
    # Create a temporary config file with partial configuration
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        config_data = {"result_output": {"displacement": False}}
        yaml.safe_dump(config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Load the configuration
        config = AnalysisConfig(temp_config_path)

        # Verify configuration
        result_output = config.get_result_output_settings()
        assert result_output["displacement"] is False
        # Other outputs should remain at default values
        assert result_output["stress"] is True
        assert result_output["strain"] is False
        assert result_output["reaction_forces"] is False
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_analysis_config_set_result_output():
    """
    Test modifying result output settings.
    """
    config = AnalysisConfig()

    # Initially displacement and stress are True
    assert config.get_result_output_settings()["displacement"] is True
    assert config.get_result_output_settings()["stress"] is True

    # Disable displacement results
    config.set_result_output("displacement", False)
    assert config.get_result_output_settings()["displacement"] is False

    # Enable strain results
    config.set_result_output("strain", True)
    assert config.get_result_output_settings()["strain"] is True


def test_analysis_config_invalid_result_output():
    """
    Test error handling for invalid result output settings.
    """
    config = AnalysisConfig()

    # Try to set invalid result type
    with pytest.raises(ValueError, match="Invalid result output type"):
        config.set_result_output("invalid_type", True)


def test_analysis_config_invalid_configuration():
    """
    Test error handling for invalid configurations.
    """
    # Create a temporary config file with invalid data
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        invalid_config_data = {
            "analysis_type": "non_existent_type",
            "solver_params": {"max_iterations": "not_an_integer"},
            "result_output": {"displacement": "not_a_boolean"},
        }
        yaml.safe_dump(invalid_config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Attempt to load invalid configuration
        with pytest.raises(ValueError):
            AnalysisConfig(temp_config_path)
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_analysis_config_supported_analysis_types():
    """
    Test the supported analysis types.
    """
    # Check that all predefined analysis types have necessary attributes
    for analysis_type, type_config in AnalysisConfig.ANALYSIS_TYPES.items():
        # Verify key attributes
        assert "description" in type_config
        assert "default_solver_params" in type_config

        # Verify solver parameters exist
        assert isinstance(type_config["default_solver_params"], dict)
        assert len(type_config["default_solver_params"]) > 0


def test_analysis_config_type_conversion():
    """
    Test that configuration values are appropriately converted.
    """
    # Create a temporary config file with mixed type configurations
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".yaml"
    ) as temp_config:
        config_data = {
            "solver_params": {
                "max_iterations": "200",  # string instead of int
                "convergence_tolerance": 1e-4,  # float
            }
        }
        yaml.safe_dump(config_data, temp_config)
        temp_config_path = temp_config.name

    try:
        # Load the configuration
        config = AnalysisConfig(temp_config_path)

        # Verify type conversion
        solver_params = config.get_solver_params()
        assert isinstance(solver_params["max_iterations"], int)
        assert solver_params["max_iterations"] == 200
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)


def test_analysis_config_save_config():
    """
    Test saving configuration to a YAML file.
    """
    config = AnalysisConfig()

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
        assert "analysis_type" in loaded_config
        assert "solver_params" in loaded_config
        assert "result_output" in loaded_config
    finally:
        # Clean up the temporary file
        os.unlink(temp_config_path)
