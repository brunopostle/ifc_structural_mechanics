"""
Unit tests for the structural analysis API.
"""

import pytest
from unittest.mock import patch, MagicMock

from ifc_structural_mechanics.api.structural_analysis import (
    analyze_ifc,
    extract_model,
    get_entity_mapping,
    create_analysis_config,
    create_meshing_config,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.utils.error_handling import (
    ModelExtractionError,
    MeshingError,
    AnalysisError,
)
from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.mapping.domain_to_calculix import DomainToCalculixMapper


# Mock the domain model for tests
@pytest.fixture
def mock_domain_model():
    model = StructuralModel(id="test_model", name="Test Model")

    # Add a curve member
    curve_member = CurveMember(
        id="curve_1",
        geometry=[(0, 0, 0), (10, 0, 0)],
        material=MagicMock(),
        section=MagicMock(),
    )
    model.add_member(curve_member)

    # Add a surface member
    surface_member = SurfaceMember(
        id="surface_1",
        geometry={"boundaries": [[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]]},
        material=MagicMock(),
        thickness=MagicMock(),
    )
    model.add_member(surface_member)

    return model


# Test the extract_model function
@patch("ifc_structural_mechanics.api.structural_analysis.Extractor")
def test_extract_model(mock_extractor_class):
    # Set up the mock
    mock_extractor = MagicMock()
    mock_extractor_class.return_value = mock_extractor

    mock_model = MagicMock()
    mock_extractor.extract_model.return_value = mock_model

    # Call the function
    result = extract_model("path/to/test.ifc")

    # Check the result
    assert result == mock_model
    mock_extractor_class.assert_called_once_with("path/to/test.ifc")
    mock_extractor.extract_model.assert_called_once()


# Test the extract_model function with an error
@patch("ifc_structural_mechanics.api.structural_analysis.Extractor")
def test_extract_model_error(mock_extractor_class):
    # Set up the mock to raise an exception
    mock_extractor = MagicMock()
    mock_extractor_class.return_value = mock_extractor
    mock_extractor.extract_model.side_effect = Exception("Test error")

    # Call the function and check for exception
    with pytest.raises(ModelExtractionError) as excinfo:
        extract_model("path/to/test.ifc")

    assert "Failed to extract model from IFC file" in str(excinfo.value)


# Test the get_entity_mapping function
@patch("ifc_structural_mechanics.api.structural_analysis.MeshConverter")
def test_get_entity_mapping(mock_mesh_converter_class, mock_domain_model):
    # Set up the mock
    mock_mesh_converter = MagicMock()
    mock_mesh_converter_class.return_value = mock_mesh_converter

    mock_mapper = MagicMock()
    mock_mesh_converter.get_mapper.return_value = mock_mapper

    # Call the function
    result = get_entity_mapping(mock_domain_model, "path/to/input.inp")

    # Check the result
    assert result == mock_mapper
    mock_mesh_converter_class.assert_called_once_with(mock_domain_model)
    mock_mesh_converter.convert_mesh.assert_called_once()
    mock_mesh_converter.get_mapper.assert_called_once()


# Test the create_analysis_config function
def test_create_analysis_config():
    # Test with a valid analysis type
    config = create_analysis_config("linear_static")
    assert isinstance(config, AnalysisConfig)
    assert config.get_analysis_type() == "linear_static"

    # Test with an invalid analysis type
    with pytest.raises(ValueError) as excinfo:
        create_analysis_config("invalid_type")

    assert "Unsupported analysis type" in str(excinfo.value)


# Test the create_meshing_config function
def test_create_meshing_config():
    # Test with a valid mesh size
    config = create_meshing_config(0.05)
    assert isinstance(config, MeshingConfig)
    assert config._config["global_settings"]["default_element_size"] == 0.05

    # Check that member types have the correct mesh size
    for member_type in config._config["member_types"]:
        assert config._config["member_types"][member_type]["element_size"] == 0.05


# Main analyze_ifc function tests


# Test successful analysis
@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshGeometryConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.MeshConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixInputGenerator")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.OutputParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ResultsParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
@patch("os.path.exists")
@patch("shutil.copy2")
def test_analyze_ifc_success(
    mock_copy,
    mock_exists,
    mock_ensure_directory,
    mock_results_parser_class,
    mock_output_parser_class,
    mock_calculix_runner_class,
    mock_calculix_input_generator_class,
    mock_mesh_converter_class,
    mock_gmsh_runner_class,
    mock_gmsh_geometry_converter_class,
    mock_extract_model,
    mock_domain_model,
):
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"

    # We'll use the actual temp_dir module
    from ifc_structural_mechanics.utils import temp_dir

    # Initialize the temp_dir module for testing
    test_temp_dir = temp_dir.setup_temp_dir(keep_files=True)

    # Mock the extraction
    mock_extract_model.return_value = mock_domain_model

    # Mock the geometry conversion
    mock_gmsh_geometry_converter = MagicMock()
    mock_gmsh_geometry_converter_class.return_value = mock_gmsh_geometry_converter

    # Mock the meshing
    mock_gmsh_runner = MagicMock()
    mock_gmsh_runner_class.return_value = mock_gmsh_runner
    mock_gmsh_runner.run_meshing.return_value = True

    # Mock the mesh conversion
    mock_mesh_converter = MagicMock()
    mock_mesh_converter_class.return_value = mock_mesh_converter

    # Mock the input generator
    mock_calculix_input_generator = MagicMock()
    mock_calculix_input_generator_class.return_value = mock_calculix_input_generator

    # Mock the calculix runner
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_output_files = {"results": "work_dir/test.frd", "message": "work_dir/test.msg"}
    mock_calculix_runner.run_analysis.return_value = mock_output_files

    # Mock the output parsing
    mock_output_parser = MagicMock()
    mock_output_parser_class.return_value = mock_output_parser
    mock_output_parser.parse_output.return_value = {"warnings": [], "errors": []}
    mock_output_parser.check_convergence.return_value = (True, "Converged")

    # Mock the results parsing
    mock_results_parser = MagicMock()
    mock_results_parser_class.return_value = mock_results_parser

    # Mock file operations
    mock_exists.return_value = True

    # Open file mock
    mock_open = MagicMock()
    mock_open.return_value.__enter__.return_value.read.return_value = "Output text"

    with patch("builtins.open", mock_open):
        # Call the function
        result = analyze_ifc(
            ifc_path="path/to/test.ifc",
            output_dir="output_dir",
            analysis_type="linear_static",
            mesh_size=0.1,
            verbose=True,
        )

    # Check the result
    assert result["status"] == "success"
    assert "output_files" in result
    assert len(result["warnings"]) == 0
    assert len(result["errors"]) == 0

    # Verify workflow
    mock_extract_model.assert_called_once_with("path/to/test.ifc")
    mock_gmsh_geometry_converter.convert_model.assert_called_once_with(
        mock_domain_model
    )
    mock_gmsh_runner.run_meshing.assert_called_once()
    mock_mesh_converter.convert_mesh.assert_called_once()
    mock_calculix_input_generator.generate_input_file.assert_called_once()
    mock_calculix_runner.run_analysis.assert_called_once()
    mock_output_parser.parse_output.assert_called_once()
    mock_output_parser.check_convergence.assert_called_once()


# Test model extraction error
@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
def test_analyze_ifc_extraction_error(mock_ensure_directory, mock_extract_model):
    # Set up mock to raise an exception
    mock_ensure_directory.return_value = "output_dir"
    mock_extract_model.side_effect = ModelExtractionError("Test extraction error")

    # Call the function and expect exception
    with pytest.raises(ModelExtractionError):
        result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Verify error handling
    mock_extract_model.assert_called_once_with("path/to/test.ifc")


# Test meshing error
@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshGeometryConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
def test_analyze_ifc_meshing_error(
    mock_ensure_directory,
    mock_gmsh_runner_class,
    mock_gmsh_geometry_converter_class,
    mock_extract_model,
    mock_domain_model,
):
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"

    # We'll use the actual temp_dir module
    from ifc_structural_mechanics.utils import temp_dir

    # Initialize the temp_dir module for testing
    test_temp_dir = temp_dir.setup_temp_dir(keep_files=True)

    # Mock the extraction
    mock_extract_model.return_value = mock_domain_model

    # Mock the geometry conversion
    mock_gmsh_geometry_converter = MagicMock()
    mock_gmsh_geometry_converter_class.return_value = mock_gmsh_geometry_converter

    # Mock the meshing to fail
    mock_gmsh_runner = MagicMock()
    mock_gmsh_runner_class.return_value = mock_gmsh_runner
    mock_gmsh_runner.run_meshing.return_value = False

    # Call the function and expect exception
    with pytest.raises(MeshingError):
        result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Verify error handling
    mock_extract_model.assert_called_once_with("path/to/test.ifc")
    mock_gmsh_geometry_converter.convert_model.assert_called_once_with(
        mock_domain_model
    )
    mock_gmsh_runner.run_meshing.assert_called_once()


# Test analysis error
@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshGeometryConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.MeshConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixInputGenerator")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
def test_analyze_ifc_analysis_error(
    mock_ensure_directory,
    mock_calculix_runner_class,
    mock_calculix_input_generator_class,
    mock_mesh_converter_class,
    mock_gmsh_runner_class,
    mock_gmsh_geometry_converter_class,
    mock_extract_model,
    mock_domain_model,
):
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"

    # We'll use the actual temp_dir module
    from ifc_structural_mechanics.utils import temp_dir

    # Initialize the temp_dir module for testing
    test_temp_dir = temp_dir.setup_temp_dir(keep_files=True)

    # Mock the extraction
    mock_extract_model.return_value = mock_domain_model

    # Mock the geometry conversion
    mock_gmsh_geometry_converter = MagicMock()
    mock_gmsh_geometry_converter_class.return_value = mock_gmsh_geometry_converter

    # Mock the meshing
    mock_gmsh_runner = MagicMock()
    mock_gmsh_runner_class.return_value = mock_gmsh_runner
    mock_gmsh_runner.run_meshing.return_value = True

    # Mock the mesh conversion
    mock_mesh_converter = MagicMock()
    mock_mesh_converter_class.return_value = mock_mesh_converter

    # Mock the input generator
    mock_calculix_input_generator = MagicMock()
    mock_calculix_input_generator_class.return_value = mock_calculix_input_generator

    # Mock the calculix runner to fail
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_calculix_runner.run_analysis.side_effect = AnalysisError("Test analysis error")

    # Call the function and expect exception
    with pytest.raises(AnalysisError):
        result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Verify error handling
    mock_extract_model.assert_called_once_with("path/to/test.ifc")
    mock_gmsh_geometry_converter.convert_model.assert_called_once_with(
        mock_domain_model
    )
    mock_gmsh_runner.run_meshing.assert_called_once()
    mock_mesh_converter.convert_mesh.assert_called_once()
    mock_calculix_input_generator.generate_input_file.assert_called_once()
    mock_calculix_runner.run_analysis.assert_called_once()


# Test analysis with warnings
@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshGeometryConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.MeshConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixInputGenerator")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.OutputParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ResultsParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
@patch("os.path.exists")
@patch("shutil.copy2")
def test_analyze_ifc_with_warnings(
    mock_copy,
    mock_exists,
    mock_ensure_directory,
    mock_results_parser_class,
    mock_output_parser_class,
    mock_calculix_runner_class,
    mock_calculix_input_generator_class,
    mock_mesh_converter_class,
    mock_gmsh_runner_class,
    mock_gmsh_geometry_converter_class,
    mock_extract_model,
    mock_domain_model,
):
    # Set up mocks similar to success test
    mock_ensure_directory.return_value = "output_dir"

    # We'll use the actual temp_dir module
    from ifc_structural_mechanics.utils import temp_dir

    # Initialize the temp_dir module for testing
    test_temp_dir = temp_dir.setup_temp_dir(keep_files=True)

    # Mock the extraction
    mock_extract_model.return_value = mock_domain_model

    # Mock the geometry conversion
    mock_gmsh_geometry_converter = MagicMock()
    mock_gmsh_geometry_converter_class.return_value = mock_gmsh_geometry_converter

    # Mock the meshing
    mock_gmsh_runner = MagicMock()
    mock_gmsh_runner_class.return_value = mock_gmsh_runner
    mock_gmsh_runner.run_meshing.return_value = True

    # Mock the mesh conversion
    mock_mesh_converter = MagicMock()
    mock_mesh_converter_class.return_value = mock_mesh_converter

    # Mock the input generator
    mock_calculix_input_generator = MagicMock()
    mock_calculix_input_generator_class.return_value = mock_calculix_input_generator

    # Mock the calculix runner
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_output_files = {"results": "work_dir/test.frd", "message": "work_dir/test.msg"}
    mock_calculix_runner.run_analysis.return_value = mock_output_files

    # Mock the output parsing - include warnings
    mock_output_parser = MagicMock()
    mock_output_parser_class.return_value = mock_output_parser
    mock_warnings = [
        {
            "message": "Test warning",
            "severity": "warning",
            "entity_type": None,
            "ccx_id": None,
            "domain_id": None,
        }
    ]
    mock_output_parser.parse_output.return_value = {
        "warnings": mock_warnings,
        "errors": [],
    }
    mock_output_parser.check_convergence.return_value = (True, "Converged")

    # Mock the results parsing
    mock_results_parser = MagicMock()
    mock_results_parser_class.return_value = mock_results_parser

    # Mock file operations
    mock_exists.return_value = True

    # Open file mock
    mock_open = MagicMock()
    mock_open.return_value.__enter__.return_value.read.return_value = "Output text"

    with patch("builtins.open", mock_open):
        # Call the function
        result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Check the result
    assert result["status"] == "success"
    assert "output_files" in result
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["message"] == "Test warning"
    assert len(result["errors"]) == 0


# Test entity mapping preservation
@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshGeometryConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.GmshRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.MeshConverter")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixInputGenerator")
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.OutputParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ResultsParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
@patch("os.path.exists")
@patch("shutil.copy2")
def test_analyze_ifc_entity_mapping(
    mock_copy,
    mock_exists,
    mock_ensure_directory,
    mock_results_parser_class,
    mock_output_parser_class,
    mock_calculix_runner_class,
    mock_calculix_input_generator_class,
    mock_mesh_converter_class,
    mock_gmsh_runner_class,
    mock_gmsh_geometry_converter_class,
    mock_extract_model,
    mock_domain_model,
):
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"

    # We'll use the actual temp_dir module
    from ifc_structural_mechanics.utils import temp_dir

    # Initialize the temp_dir module for testing
    test_temp_dir = temp_dir.setup_temp_dir(keep_files=True)

    # Mock the extraction
    mock_extract_model.return_value = mock_domain_model

    # Mock the geometry conversion
    mock_gmsh_geometry_converter = MagicMock()
    mock_gmsh_geometry_converter_class.return_value = mock_gmsh_geometry_converter

    # Mock the meshing
    mock_gmsh_runner = MagicMock()
    mock_gmsh_runner_class.return_value = mock_gmsh_runner
    mock_gmsh_runner.run_meshing.return_value = True

    # Mock the mesh conversion with mapping
    mock_mesh_converter = MagicMock()
    mock_mesh_converter_class.return_value = mock_mesh_converter

    # Create a real mapper and set up the mapping
    mapper = DomainToCalculixMapper()
    mapper.register_element("curve_1", 1, "beam")
    mapper.register_element("surface_1", 2, "shell")
    mock_mesh_converter.get_mapper.return_value = mapper

    # Mock the input generator
    mock_calculix_input_generator = MagicMock()
    mock_calculix_input_generator_class.return_value = mock_calculix_input_generator

    # Mock the calculix runner
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_output_files = {"results": "work_dir/test.frd", "message": "work_dir/test.msg"}
    mock_calculix_runner.run_analysis.return_value = mock_output_files

    # Mock the output parsing with errors that reference entities
    mock_output_parser = MagicMock()
    mock_output_parser_class.return_value = mock_output_parser
    mock_errors = [
        {
            "message": "Error in element 1",
            "severity": "critical",
            "entity_type": "element",
            "ccx_id": 1,
            "domain_id": "curve_1",
        }
    ]
    mock_output_parser.parse_output.return_value = {
        "warnings": [],
        "errors": mock_errors,
    }
    mock_output_parser.check_convergence.return_value = (False, "Not converged")

    # Mock the results parsing
    mock_results_parser = MagicMock()
    mock_results_parser_class.return_value = mock_results_parser

    # Mock file operations
    mock_exists.return_value = True

    # Open file mock
    mock_open = MagicMock()
    mock_open.return_value.__enter__.return_value.read.return_value = "Output text"

    # We expect this to raise an AnalysisError due to convergence failure
    with patch("builtins.open", mock_open):
        try:
            result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")
        except AnalysisError:
            # This is expected - check that errors were added before the exception was raised
            assert mock_output_parser.parse_output.called
            assert mock_output_parser.check_convergence.called

            # Verify the mapper was passed to the calculix runner
            mock_calculix_runner_class.assert_called_once()
            _, kwargs = mock_calculix_runner_class.call_args
            assert "mapper" in kwargs
            assert kwargs["mapper"] is not None

            # Test passes if we get here
            return

    # If we get here, the test failed
    pytest.fail("AnalysisError was not raised")


# Test empty model error
@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
def test_analyze_ifc_empty_model(mock_ensure_directory, mock_extract_model):
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"

    # Create an empty model
    empty_model = StructuralModel(id="empty", name="Empty Model")
    mock_extract_model.return_value = empty_model

    # Call the function and expect exception
    with pytest.raises(ModelExtractionError):
        analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Verify error handling
    mock_extract_model.assert_called_once_with("path/to/test.ifc")


# Test unsupported analysis type
def test_analyze_ifc_unsupported_analysis_type():
    # Test with an invalid analysis type
    with pytest.raises(ValueError) as excinfo:
        analyze_ifc(
            ifc_path="path/to/test.ifc",
            output_dir="output_dir",
            analysis_type="unsupported_type",
        )

    # Check that the error message contains the expected text
    assert "Unsupported analysis type" in str(excinfo.value)
