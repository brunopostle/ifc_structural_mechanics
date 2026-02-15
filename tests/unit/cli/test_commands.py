"""
Updated unit tests for the CLI commands module to work with enhanced analysis.
"""

import pytest
from unittest.mock import patch
from click.testing import CliRunner

# Update these imports to match your enhanced implementation
from ifc_structural_mechanics.cli.commands import cli

# We'll use run_enhanced_analyze from original commands.py to maintain compatibility
from ifc_structural_mechanics.cli.commands import run_enhanced_analyze
from ifc_structural_mechanics.utils.error_handling import (
    ModelExtractionError,
    MeshingError,
    AnalysisError,
)


class TestEnhancedCLICommands:
    """Test suite for enhanced CLI commands."""

    @pytest.fixture
    def runner(self):
        """Create a CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def mock_analyze_ifc(self):
        """Create a mock for the analyze_ifc function with enhanced capabilities."""
        with patch(
            "ifc_structural_mechanics.api.structural_analysis.run_enhanced_analysis"
        ) as mock:
            # Default successful result
            mock.return_value = {
                "status": "success",
                "warnings": [],
                "errors": [],
                "output_files": {
                    "results": "/path/to/results.frd",
                    "data": "/path/to/data.dat",
                    "message": "/path/to/message.msg",
                },
                "notes": ["Analysis enhanced with boundary conditions and loads"],
            }
            yield mock

    @pytest.fixture
    def temp_ifc_file(self, tmp_path):
        """Create a temporary IFC file for testing."""
        ifc_file = tmp_path / "test.ifc"
        ifc_file.write_text("Dummy IFC content")
        return str(ifc_file)

    @pytest.fixture
    def temp_output_dir(self, tmp_path):
        """Create a temporary output directory for testing."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        return str(output_dir)

    def test_cli_help(self, runner):
        """Test that CLI help works."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "IFC Structural Analysis" in result.output
        assert "analyze" in result.output

    def test_analyze_help(self, runner):
        """Test that analyze command help works."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "Run structural analysis on an IFC file" in result.output
        assert "--output" in result.output
        assert "--analysis-type" in result.output
        assert "--mesh-size" in result.output
        # Check for the new enhanced option
        assert "--enhanced" in result.output

    def test_analyze_successful(self, mock_analyze_ifc, temp_ifc_file, temp_output_dir):
        """Test successful analysis run with enhanced analysis."""
        # We're going to test using a patched version of run_enhanced_analyze
        # that uses our mock_analyze_ifc
        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis",
            mock_analyze_ifc,
        ):
            exit_code = run_enhanced_analyze(
                ifc_file=temp_ifc_file,
                output_dir=temp_output_dir,
                analysis_type="linear_static",
                mesh_size=0.1,
                verbose=False,
                json_output=False,
                map_entities=True,
                enhanced=True,  # Use the enhanced analysis option
                gravity=False,
            )
            assert exit_code == 0  # Success

            # Verify enhanced analysis was called with correct parameters
            mock_analyze_ifc.assert_called_once_with(
                ifc_path=temp_ifc_file,
                output_dir=temp_output_dir,
                analysis_type="linear_static",
                mesh_size=0.1,
                verbose=False,
                gravity=False,
            )

    def test_analyze_custom_params(
        self, mock_analyze_ifc, temp_ifc_file, temp_output_dir
    ):
        """Test analysis with custom parameters."""
        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis",
            mock_analyze_ifc,
        ):
            exit_code = run_enhanced_analyze(
                ifc_file=temp_ifc_file,
                output_dir=temp_output_dir,
                analysis_type="linear_buckling",
                mesh_size=0.2,
                verbose=True,
                json_output=False,
                map_entities=True,
                enhanced=True,
                gravity=False,
            )
            assert exit_code == 0  # Success

            # Verify enhanced analysis was called with correct parameters
            mock_analyze_ifc.assert_called_once_with(
                ifc_path=temp_ifc_file,
                output_dir=temp_output_dir,
                analysis_type="linear_buckling",
                mesh_size=0.2,
                verbose=True,
                gravity=False,
            )

    def test_analyze_with_warnings(
        self, mock_analyze_ifc, temp_ifc_file, temp_output_dir
    ):
        """Test analysis with warnings."""
        # Set up mock to return warnings
        mock_analyze_ifc.return_value = {
            "status": "success",
            "warnings": [
                {
                    "message": "Large displacement detected",
                    "severity": "warning",
                    "entity_type": "element",
                    "ccx_id": 42,
                    "domain_id": "beam_7",
                }
            ],
            "errors": [],
            "output_files": {"results": "/path/to/results.frd"},
            "notes": ["Analysis included warnings but completed successfully"],
        }

        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis",
            mock_analyze_ifc,
        ):
            exit_code = run_enhanced_analyze(
                ifc_file=temp_ifc_file, output_dir=temp_output_dir, enhanced=True
            )
            assert exit_code == 0  # Success with warnings is still success

    def test_analyze_with_errors(
        self, mock_analyze_ifc, temp_ifc_file, temp_output_dir
    ):
        """Test analysis with errors."""
        # Set up mock to return errors
        mock_analyze_ifc.return_value = {
            "status": "failed",
            "warnings": [],
            "errors": [
                {
                    "message": "Negative jacobian in element",
                    "severity": "critical",
                    "entity_type": "element",
                    "ccx_id": 123,
                    "domain_id": "plate_3",
                }
            ],
            "output_files": {"message": "/path/to/message.msg"},
            "notes": ["Analysis failed with critical errors"],
        }

        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis",
            mock_analyze_ifc,
        ):
            exit_code = run_enhanced_analyze(
                ifc_file=temp_ifc_file, output_dir=temp_output_dir, enhanced=True
            )
            assert exit_code == 1  # Failure due to errors in result

    def test_analyze_with_exception(self, temp_ifc_file, temp_output_dir):
        """Test handling of exceptions."""
        # Test ModelExtractionError
        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis",
            side_effect=ModelExtractionError("Failed to extract model"),
        ):
            exit_code = run_enhanced_analyze(
                ifc_file=temp_ifc_file, output_dir=temp_output_dir, enhanced=True
            )
            assert exit_code == 2  # Exit code for ModelExtractionError

        # Test MeshingError
        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis",
            side_effect=MeshingError("Meshing failed"),
        ):
            exit_code = run_enhanced_analyze(
                ifc_file=temp_ifc_file, output_dir=temp_output_dir, enhanced=True
            )
            assert exit_code == 3  # Exit code for MeshingError

        # Test AnalysisError with error details
        error_details = [
            {
                "message": "Zero pivot detected",
                "entity_type": "element",
                "ccx_id": 456,
                "domain_id": "beam_2",
            }
        ]
        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis",
            side_effect=AnalysisError(
                "Analysis calculation failed", error_details=error_details
            ),
        ):
            exit_code = run_enhanced_analyze(
                ifc_file=temp_ifc_file, output_dir=temp_output_dir, enhanced=True
            )
            assert exit_code == 4  # Exit code for AnalysisError

    def test_enhanced_vs_standard_option(
        self, mock_analyze_ifc, temp_ifc_file, temp_output_dir
    ):
        """Test that the enhanced option routes to the correct analysis function."""
        # Set up the mocks for both enhanced and standard analysis
        with patch(
            "ifc_structural_mechanics.cli.commands.run_enhanced_analysis"
        ) as mock_enhanced:
            mock_enhanced.return_value = {
                "status": "success",
                "output_files": {},
                "notes": ["Used enhanced analysis"],
            }

            with patch(
                "ifc_structural_mechanics.cli.commands.analyze_ifc"
            ) as mock_standard:
                mock_standard.return_value = {"status": "success", "output_files": {}}

                # Test with enhanced=True
                exit_code = run_enhanced_analyze(
                    ifc_file=temp_ifc_file, output_dir=temp_output_dir, enhanced=True
                )
                assert exit_code == 0
                mock_enhanced.assert_called_once()
                mock_standard.assert_not_called()

                # Reset mocks
                mock_enhanced.reset_mock()
                mock_standard.reset_mock()

                # Test with enhanced=False
                exit_code = run_enhanced_analyze(
                    ifc_file=temp_ifc_file, output_dir=temp_output_dir, enhanced=False
                )
                assert exit_code == 0
                mock_enhanced.assert_not_called()
                mock_standard.assert_called_once()
