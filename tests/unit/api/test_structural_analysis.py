"""
Updated unit tests for the structural analysis API using the unified CalculiX writer.

These tests verify the simplified workflow that eliminates dual element writing.
"""

import pytest
from unittest.mock import patch, MagicMock

from ifc_structural_mechanics.api.structural_analysis import (
    analyze_ifc,
    extract_model,
    create_analysis_config,
    create_meshing_config,
    analyze_ifc_simple,
    run_enhanced_analysis,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.utils.error_handling import (
    ModelExtractionError,
    MeshingError,
    AnalysisError,
    StructuralAnalysisError,
)
from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from ifc_structural_mechanics.config.meshing_config import MeshingConfig


# Mock the domain model for tests
@pytest.fixture
def mock_domain_model():
    """Create a mock domain model for testing."""
    model = StructuralModel(id="test_model", name="Test Model")

    # Create material
    material = Material(
        id="steel_1",
        name="Steel",
        elastic_modulus=210e9,
        poisson_ratio=0.3,
        density=7850.0,
    )

    # Create section
    section = Section.create_rectangular_section(
        id="rect_section", name="Rectangular Section", width=0.2, height=0.3
    )

    # Create thickness
    thickness = Thickness(id="slab_thickness", name="Slab Thickness", value=0.15)

    # Add a curve member
    curve_member = CurveMember(
        id="beam_1",
        geometry=((0, 0, 0), (10, 0, 0)),
        material=material,
        section=section,
    )
    model.add_member(curve_member)

    # Add a surface member
    surface_member = SurfaceMember(
        id="slab_1",
        geometry={"boundaries": [[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]]},
        material=material,
        thickness=thickness,
    )
    model.add_member(surface_member)

    return model


# Test the extract_model function
@patch("ifc_structural_mechanics.api.structural_analysis.Extractor")
def test_extract_model(mock_extractor_class):
    """Test model extraction from IFC file."""
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
    """Test model extraction error handling."""
    # Set up the mock to raise an exception
    mock_extractor = MagicMock()
    mock_extractor_class.return_value = mock_extractor
    mock_extractor.extract_model.side_effect = Exception("Test error")

    # Call the function and check for exception
    with pytest.raises(ModelExtractionError) as excinfo:
        extract_model("path/to/test.ifc")

    assert "Failed to extract model from IFC file" in str(excinfo.value)


# Test the create_analysis_config function
def test_create_analysis_config():
    """Test analysis configuration creation."""
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
    """Test meshing configuration creation."""
    # Test with a valid mesh size
    config = create_meshing_config(0.05)
    assert isinstance(config, MeshingConfig)
    assert config._config["global_settings"]["default_element_size"] == 0.05

    # Check that member types have the correct mesh size
    for member_type in config._config["member_types"]:
        assert config._config["member_types"][member_type]["element_size"] == 0.05


# Main analyze_ifc function tests with unified workflow


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch(
    "ifc_structural_mechanics.api.structural_analysis.run_complete_analysis_workflow"
)
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.OutputParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ResultsParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
@patch("os.path.exists")
@patch("os.listdir")
@patch("shutil.copy2")
def test_analyze_ifc_success_unified(
    mock_copy,
    mock_listdir,
    mock_exists,
    mock_ensure_directory,
    mock_results_parser_class,
    mock_output_parser_class,
    mock_calculix_runner_class,
    mock_unified_workflow,
    mock_extract_model,
    mock_domain_model,
):
    """Test successful analysis using the unified workflow."""
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"
    mock_extract_model.return_value = mock_domain_model

    # Mock the unified workflow
    unified_inp_file = "output_dir/analysis.inp"
    mock_unified_workflow.return_value = unified_inp_file

    # Mock the CalculiX runner
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_output_files = {
        "results": "output_dir/analysis.frd",
        "data": "output_dir/analysis.dat",
        "message": "output_dir/analysis.msg",
    }
    mock_calculix_runner.run_analysis.return_value = mock_output_files

    # Mock the output parsing
    mock_output_parser = MagicMock()
    mock_output_parser_class.return_value = mock_output_parser
    mock_output_parser.parse_output.return_value = {"warnings": [], "errors": []}
    mock_output_parser.check_convergence.return_value = (True, "Converged")

    # Mock the results parsing
    mock_results_parser = MagicMock()
    mock_results_parser_class.return_value = mock_results_parser

    # Mock file operations - be more careful about file existence
    def mock_exists_side_effect(path):
        # Mock that most output files exist, but not intermediate directory
        if "intermediate" in path:
            return False
        # Mock that CalculiX output files exist
        if any(
            name in path
            for name in ["analysis.frd", "analysis.dat", "analysis.msg", "analysis.inp"]
        ):
            return True
        return False

    mock_exists.side_effect = mock_exists_side_effect
    mock_listdir.return_value = []  # Empty intermediate directory

    # Open file mock
    with patch("builtins.open", MagicMock()) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "Output text"

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
    assert "mesh_statistics" in result

    # Verify the unified workflow was called
    mock_extract_model.assert_called_once_with("path/to/test.ifc")
    mock_unified_workflow.assert_called_once()

    # Verify the unified workflow was called with correct arguments
    call_args = mock_unified_workflow.call_args
    assert call_args[1]["domain_model"] == mock_domain_model
    assert call_args[1]["output_inp_file"] == "output_dir/analysis.inp"

    # Verify CalculiX runner was called
    mock_calculix_runner.run_analysis.assert_called_once()
    mock_output_parser.parse_output.assert_called_once()
    mock_output_parser.check_convergence.assert_called_once()


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
def test_analyze_ifc_extraction_error(mock_extract_model):
    """Test model extraction error in unified workflow."""
    # Set up mock to raise an exception
    mock_extract_model.side_effect = ModelExtractionError("Test extraction error")

    # Call the function and expect exception
    with pytest.raises(ModelExtractionError):
        analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch(
    "ifc_structural_mechanics.api.structural_analysis.run_complete_analysis_workflow"
)
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
def test_analyze_ifc_meshing_error_unified(
    mock_ensure_directory, mock_unified_workflow, mock_extract_model, mock_domain_model
):
    """Test meshing error in unified workflow."""
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"
    mock_extract_model.return_value = mock_domain_model

    # Mock the unified workflow to fail with MeshingError
    mock_unified_workflow.side_effect = MeshingError("Meshing failed")

    # Call the function - should not raise exception but return failed result
    result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Check that result indicates failure
    assert result["status"] == "failed"
    assert len(result["errors"]) > 0
    assert any("Meshing failed" in error["message"] for error in result["errors"])


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch(
    "ifc_structural_mechanics.api.structural_analysis.run_complete_analysis_workflow"
)
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
def test_analyze_ifc_analysis_error_unified(
    mock_ensure_directory,
    mock_calculix_runner_class,
    mock_unified_workflow,
    mock_extract_model,
    mock_domain_model,
):
    """Test CalculiX analysis error in unified workflow."""
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"
    mock_extract_model.return_value = mock_domain_model

    # Mock the unified workflow to succeed
    mock_unified_workflow.return_value = "output_dir/analysis.inp"

    # Mock the CalculiX runner to fail
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_calculix_runner.run_analysis.side_effect = AnalysisError("Analysis failed")

    # Call the function - should not raise exception but return failed result
    result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Check that result indicates failure
    assert result["status"] == "failed"
    assert len(result["errors"]) > 0
    assert any("Analysis failed" in error["message"] for error in result["errors"])


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch(
    "ifc_structural_mechanics.api.structural_analysis.run_complete_analysis_workflow"
)
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.OutputParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
@patch("os.path.exists")
@patch("shutil.copy2")
def test_analyze_ifc_with_warnings_unified(
    mock_copy,
    mock_exists,
    mock_ensure_directory,
    mock_output_parser_class,
    mock_calculix_runner_class,
    mock_unified_workflow,
    mock_extract_model,
    mock_domain_model,
):
    """Test analysis with warnings in unified workflow."""
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"
    mock_extract_model.return_value = mock_domain_model
    mock_unified_workflow.return_value = "output_dir/analysis.inp"

    # Mock CalculiX runner
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_output_files = {"message": "output_dir/analysis.msg"}
    mock_calculix_runner.run_analysis.return_value = mock_output_files

    # Mock output parsing with warnings
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

    # Mock file operations to avoid file not found errors
    def mock_exists_side_effect(path):
        if "analysis.msg" in path:
            return True
        return False

    mock_exists.side_effect = mock_exists_side_effect

    # Avoid copy errors by making copy2 not fail
    mock_copy.return_value = None

    # Mock file reading
    with patch("builtins.open", MagicMock()) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "Output text"

        # Call the function
        result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Check the result
    assert result["status"] == "success"
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["message"] == "Test warning"
    assert len(result["errors"]) == 0


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
def test_analyze_ifc_empty_model(mock_extract_model):
    """Test analysis with empty model."""
    # Create an empty model
    empty_model = StructuralModel(id="empty", name="Empty Model")
    mock_extract_model.return_value = empty_model

    # Call the function and expect exception
    with pytest.raises(ModelExtractionError):
        analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")


def test_analyze_ifc_unsupported_analysis_type():
    """Test analysis with unsupported analysis type."""
    # Test with an invalid analysis type
    with pytest.raises(ValueError) as excinfo:
        analyze_ifc(
            ifc_path="path/to/test.ifc",
            output_dir="output_dir",
            analysis_type="unsupported_type",
        )

    # Check that the error message contains the expected text
    assert "Unsupported analysis type" in str(excinfo.value)


# Test convenience functions


@patch("ifc_structural_mechanics.api.structural_analysis.analyze_ifc")
def test_analyze_ifc_simple(mock_analyze_ifc):
    """Test the simplified analysis function."""
    # Mock successful analysis
    mock_analyze_ifc.return_value = {"status": "success"}

    result = analyze_ifc_simple("test.ifc", "output_dir")
    assert result is True

    # Mock failed analysis
    mock_analyze_ifc.return_value = {"status": "failed"}

    result = analyze_ifc_simple("test.ifc", "output_dir")
    assert result is False

    # Mock exception
    mock_analyze_ifc.side_effect = Exception("Test error")

    result = analyze_ifc_simple("test.ifc", "output_dir")
    assert result is False


@patch("ifc_structural_mechanics.api.structural_analysis.analyze_ifc")
def test_run_enhanced_analysis_backward_compatibility(mock_analyze_ifc):
    """Test that run_enhanced_analysis maintains backward compatibility."""
    # Mock successful analysis
    expected_result = {"status": "success", "warnings": [], "errors": []}
    mock_analyze_ifc.return_value = expected_result

    result = run_enhanced_analysis(
        ifc_path="test.ifc",
        output_dir="output_dir",
        analysis_type="linear_static",
        mesh_size=0.1,
        verbose=True,
    )

    assert result == expected_result
    mock_analyze_ifc.assert_called_once_with(
        ifc_path="test.ifc",
        output_dir="output_dir",
        analysis_type="linear_static",
        mesh_size=0.1,
        verbose=True,
    )


# Test error propagation in unified workflow


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch(
    "ifc_structural_mechanics.api.structural_analysis.run_complete_analysis_workflow"
)
def test_unexpected_error_handling(
    mock_unified_workflow, mock_extract_model, mock_domain_model
):
    """Test handling of unexpected errors."""
    mock_extract_model.return_value = mock_domain_model

    # Mock an unexpected error in the unified workflow
    mock_unified_workflow.side_effect = RuntimeError("Unexpected error")

    with pytest.raises(StructuralAnalysisError) as excinfo:
        analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    assert "Analysis workflow failed" in str(excinfo.value)
    assert "Unexpected error" in str(excinfo.value)


# Test file organization in results


@patch("ifc_structural_mechanics.api.structural_analysis.extract_model")
@patch(
    "ifc_structural_mechanics.api.structural_analysis.run_complete_analysis_workflow"
)
@patch("ifc_structural_mechanics.api.structural_analysis.CalculixRunner")
@patch("ifc_structural_mechanics.api.structural_analysis.OutputParser")
@patch("ifc_structural_mechanics.api.structural_analysis.ensure_directory")
@patch("os.path.exists")
@patch("os.listdir")
@patch("shutil.copy2")
def test_file_organization(
    mock_copy,
    mock_listdir,
    mock_exists,
    mock_ensure_directory,
    mock_output_parser_class,
    mock_calculix_runner_class,
    mock_unified_workflow,
    mock_extract_model,
    mock_domain_model,
):
    """Test that output files are properly organized."""
    # Set up mocks
    mock_ensure_directory.return_value = "output_dir"
    mock_extract_model.return_value = mock_domain_model
    mock_unified_workflow.return_value = "output_dir/analysis.inp"

    # Mock CalculiX runner
    mock_calculix_runner = MagicMock()
    mock_calculix_runner_class.return_value = mock_calculix_runner
    mock_output_files = {
        "results": "temp_dir/analysis.frd",
        "data": "temp_dir/analysis.dat",
    }
    mock_calculix_runner.run_analysis.return_value = mock_output_files

    # Mock output parser
    mock_output_parser = MagicMock()
    mock_output_parser_class.return_value = mock_output_parser
    mock_output_parser.parse_output.return_value = {"warnings": [], "errors": []}
    mock_output_parser.check_convergence.return_value = (True, "Converged")

    # Mock file operations - control which files "exist"
    def mock_exists_side_effect(path):
        # Only the original CalculiX output files exist
        if "temp_dir" in path and ("analysis.frd" in path or "analysis.dat" in path):
            return True
        if "analysis.inp" in path:
            return True
        if "intermediate" in path:
            return True  # Intermediate directory exists
        return False

    mock_exists.side_effect = mock_exists_side_effect
    mock_listdir.return_value = ["mesh.msh", "mapping.json"]

    # Mock copy to avoid errors
    mock_copy.return_value = None

    # Call the function
    result = analyze_ifc(ifc_path="path/to/test.ifc", output_dir="output_dir")

    # Check that files were organized properly
    assert "output_files" in result
    assert "results" in result["output_files"]
    assert "data" in result["output_files"]
    assert "input" in result["output_files"]

    # Verify files were attempted to be copied
    assert mock_copy.call_count >= 2  # At least results and data files


if __name__ == "__main__":
    pytest.main(["-v", __file__])
