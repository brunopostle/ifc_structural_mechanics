"""
Complete fix for test_analysis_workflow.py.

This includes:
1. Proper imports
2. Updated _create_simple_domain_model method
3. Using LoadGroup properly
"""

import os
import logging
from unittest import mock

from src.ifc_structural_mechanics.analysis.calculix_input import CalculixInputGenerator
from src.ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
from src.ifc_structural_mechanics.analysis.results_parser import ResultsParser
from src.ifc_structural_mechanics.domain.structural_model import StructuralModel
from src.ifc_structural_mechanics.domain.structural_member import CurveMember
from src.ifc_structural_mechanics.domain.property import Material, Section
from src.ifc_structural_mechanics.domain.load import PointLoad, LoadGroup
from src.ifc_structural_mechanics.utils.subprocess_utils import SubprocessResult
from src.ifc_structural_mechanics.utils.temp_dir import (
    setup_temp_dir,
    cleanup_temp_dir,
    create_temp_subdir,
    set_keep_temp_files,
)
from src.ifc_structural_mechanics.utils.error_handling import AnalysisError

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

set_keep_temp_files(keep_files=True)


class TestAnalysisWorkflow:
    """Integration tests for the analysis workflow."""

    @classmethod
    def setup_class(cls):
        """
        Set up shared resources for all tests.
        """
        # Use the temp_dir utility to set up a base directory for the class
        cls.temp_base_dir = setup_temp_dir(
            prefix="analysis_workflow_test_", keep_files=True
        )

    @classmethod
    def teardown_class(cls):
        """
        Clean up shared resources after all tests.
        """
        # Only force cleanup if the test failed
        cleanup_temp_dir(force=False)

    def _create_simple_domain_model(self):
        model = StructuralModel(id="test_model", name="Test Model")

        # Create material
        material = Material(
            id="steel",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            yield_strength=250e6,
        )

        # Create section
        section = Section.create_rectangular_section(
            id="beam_section", name="Rectangular Beam", width=0.1, height=0.2
        )

        # Create a simple beam member with geometry in expected format
        beam_geometry = ((0, 0, 0), (1, 0, 0))  # Using tuple format for geometry

        beam = CurveMember(
            id="beam1", geometry=beam_geometry, material=material, section=section
        )

        # Add a fixed boundary condition - IMPORTANT UPDATE
        fixed_support = {
            "id": "bc1",
            "type": "fixed",
            "position": [0, 0, 0],  # Position of the fixed support
        }
        beam.add_boundary_condition(fixed_support)

        # Create a point load at the end of the beam
        load = PointLoad(
            id="load1",
            magnitude=1000.0,
            direction=[0, -1, 0],  # Direction downward
            position=[1, 0, 0],  # Position at the end of the beam
        )

        # Create a load group instead of adding load directly to the beam
        load_group = LoadGroup(id="load_group_1", name="Main Loads")
        load_group.add_load(load)

        # Add load group to the model (not directly to the beam)
        model.add_load_group(load_group)

        # Add the beam to the model
        model.add_member(beam)

        # Manually generate nodes and elements for test
        model.nodes = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)}
        model.elements = {1: {"type": "B31", "nodes": [1, 2]}}
        model.element_sets = {"MEMBER_beam1_ELEMENTS": [1]}

        return model

    def test_analysis_workflow(self):
        """Test the complete analysis workflow from input to results using actual CalculiX."""

        # Skip the test if CalculiX is not available
        from src.ifc_structural_mechanics.utils.subprocess_utils import check_executable

        if not check_executable("ccx"):
            import pytest

            pytest.skip(
                "CalculiX (ccx) executable not found, skipping integration test"
            )

        # Use temp_dir utility for creating temporary working directory
        working_dir = create_temp_subdir(prefix="analysis_workflow_")

        # Create simple domain model
        simple_domain_model = self._create_simple_domain_model()

        # Step 1: Generate CalculiX input file
        input_generator = CalculixInputGenerator(simple_domain_model)
        input_file_path = os.path.join(working_dir, "test_model.inp")

        try:
            input_generator.generate_input_file(input_file_path)
        except Exception as e:
            # If generation fails, print the model details for debugging
            logger.error(f"Failed to generate input file: {e}")
            logger.error(f"Domain model: {simple_domain_model}")
            logger.error(f"Model members: {simple_domain_model.members}")
            raise

        # Verify input file was created
        assert os.path.exists(input_file_path), "Input file was not created"

        # Debug: Print input file contents
        with open(input_file_path, "r") as f:
            input_file_contents = f.read()
            logger.debug(f"Input file contents:\n{input_file_contents}")

            # Additional assertions to verify key sections are present
            assert "*NODE" in input_file_contents, "Node section missing"
            assert "*ELEMENT" in input_file_contents, "Element section missing"
            assert "*BEAM SECTION" in input_file_contents, "Beam section missing"
            assert "*MATERIAL" in input_file_contents, "Material section missing"
            assert "*STEP" in input_file_contents, "Step section missing"
            assert "*CLOAD" in input_file_contents, "Load section missing"

        # Step 2: Run CalculiX analysis
        # We'll run CalculiX with an appropriate timeout, as real analysis can take time
        runner = CalculixRunner(input_file_path, working_dir=working_dir)

        try:
            result_files = runner.run_analysis(timeout=30)  # 30 second timeout
        except AnalysisError as e:
            # If analysis fails, log additional details and re-raise
            logger.error(f"CalculiX analysis failed: {e}")
            logger.error(f"Error details: {e.error_details}")
            raise

        # Verify result files were found
        assert "results" in result_files, "Results file not found"
        assert "data" in result_files, "Data file not found"

        # Check that result files exist
        assert os.path.exists(result_files["results"]), "Results file does not exist"
        assert os.path.exists(result_files["data"]), "Data file does not exist"

        # Step 3: Parse results
        parser = ResultsParser(domain_model=simple_domain_model)
        parsed_results = parser.parse_results(result_files)

        # Verify results were parsed
        assert "displacement" in parsed_results, "Displacement results missing"
        assert "reaction" in parsed_results, "Reaction results missing"

        # Check that results were actually parsed
        assert len(parsed_results["displacement"]) > 0, "No displacement results parsed"
        assert len(parsed_results["reaction"]) > 0, "No reaction results parsed"

        # Verify results were added to the domain model
        assert len(simple_domain_model.results) > 0, "No results added to domain model"
