"""
Main API for structural analysis.

This module provides the primary public API for performing structural analysis
on IFC models using the CalculiX solver.
"""

import os
import logging
import shutil
from typing import Dict, Any, Optional

from ..ifc.extractor import Extractor
from ..domain.structural_model import StructuralModel
from ..meshing.gmsh_geometry import GmshGeometryConverter
from ..meshing.gmsh_runner import GmshRunner
from ..meshing.mesh_converter import MeshConverter
from ..analysis.calculix_input import CalculixInputGenerator
from ..analysis.calculix_runner import CalculixRunner
from ..analysis.results_parser import ResultsParser
from ..analysis.output_parser import OutputParser
from ..mapping.domain_to_calculix import DomainToCalculixMapper
from ..config.analysis_config import AnalysisConfig
from ..config.meshing_config import MeshingConfig
from ..config.system_config import SystemConfig
from ..utils.error_handling import (
    StructuralAnalysisError,
    ModelExtractionError,
    MeshingError,
    AnalysisError,
)
from ..utils.file_utils import ensure_directory
from ..utils import temp_dir

# Set up logger
logger = logging.getLogger(__name__)


def analyze_ifc(
    ifc_path: str,
    output_dir: str,
    analysis_type: str = "linear_static",
    mesh_size: float = 0.1,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Run a structural analysis on an IFC file.

    This function performs the complete workflow from IFC model extraction
    to structural analysis with CalculiX, and returns the analysis results.

    Args:
        ifc_path (str): Path to the IFC file to analyze.
        output_dir (str): Directory where the output files will be written.
        analysis_type (str, optional): Type of analysis to perform.
            Currently supported: "linear_static". Defaults to "linear_static".
        mesh_size (float, optional): Default mesh size for the finite element mesh.
            Defaults to 0.1.
        verbose (bool, optional): Whether to enable verbose logging.
            Defaults to False.

    Returns:
        Dict[str, Any]: Dictionary with analysis results, containing:
            - status (str): "success" or "failed"
            - warnings (List[Dict]): List of warning messages with details
            - errors (List[Dict]): List of error messages with details
            - output_files (Dict[str, str]): Dictionary of output file paths

    Raises:
        ModelExtractionError: If the model extraction from IFC fails.
        MeshingError: If the meshing process fails.
        AnalysisError: If the analysis process fails.
        ResultProcessingError: If the result processing fails.
        StructuralAnalysisError: For general errors in the analysis workflow.
        ValueError: If the analysis type is not supported.
    """
    # Configure logging level if verbose
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
        logger.setLevel(logging.INFO)

    # Validate analysis type early to fail fast
    if analysis_type not in AnalysisConfig.ANALYSIS_TYPES:
        raise ValueError(
            f"Unsupported analysis type: {analysis_type}. "
            f"Supported types: {list(AnalysisConfig.ANALYSIS_TYPES.keys())}"
        )

    # Initialize result dictionary
    result = {
        "status": "failed",
        "warnings": [],
        "errors": [],
        "output_files": {},
    }

    # Create a mapper to track entity mappings throughout the workflow
    mapper = DomainToCalculixMapper()

    # Ensure output directory exists
    output_dir = ensure_directory(output_dir)

    # Step 1: Extract the structural model from the IFC file
    logger.info(f"Extracting structural model from {ifc_path}")
    domain_model = extract_model(ifc_path)

    # Check if the model has any members
    if not domain_model.members:
        logger.error("No structural members found in the IFC file")
        raise ModelExtractionError("No structural members found in the IFC file")

    logger.info(f"Extracted structural model with {len(domain_model.members)} members")

    # Step 2: Configure analysis
    analysis_config = create_analysis_config(analysis_type)
    meshing_config = create_meshing_config(mesh_size)
    system_config = SystemConfig()

    # Use the default shared temporary directory for the analysis
    work_dir = temp_dir.get_temp_dir()
    try:
        # Step 3: Convert the domain model to Gmsh geometry
        logger.info("Converting domain model to Gmsh geometry")
        geometry_converter = GmshGeometryConverter(
            meshing_config=meshing_config,
            mapper=None,  # Using a separate mapper for Gmsh to domain mapping
        )

        geometry_converter.convert_model(domain_model)

        # Step 4: Run the meshing process
        logger.info("Running meshing process")
        gmsh_runner = GmshRunner(
            meshing_config=meshing_config, system_config=system_config
        )

        success = gmsh_runner.run_meshing()
        if not success:
            logger.error("Meshing process failed")
            raise MeshingError("Meshing process failed")

        # Generate mesh file
        mesh_file = os.path.join(work_dir, "mesh.msh")
        gmsh_runner.generate_mesh_file(mesh_file)
        logger.info(f"Generated mesh file: {mesh_file}")

        # Step 5: Convert mesh to CalculiX input format
        logger.info("Converting mesh to CalculiX input format")
        mesh_converter = MeshConverter(domain_model=domain_model, mapper=mapper)
        inp_file = os.path.join(work_dir, "model.inp")
        mesh_converter.convert_mesh(mesh_file, inp_file)
        logger.info(f"Generated CalculiX input file: {inp_file}")

        # Step 6: Generate CalculiX input file with analysis parameters
        logger.info("Generating CalculiX input file with analysis parameters")
        input_generator = CalculixInputGenerator(
            domain_model, analysis_config, inp_file
        )
        calculix_input_file = os.path.join(work_dir, "analysis.inp")
        input_generator.generate_input_file(calculix_input_file)
        logger.info(f"Generated complete CalculiX input file: {calculix_input_file}")

        # Step 7: Run the CalculiX analysis
        logger.info("Running CalculiX analysis")
        calculix_runner = CalculixRunner(
            calculix_input_file,
            system_config=system_config,
            analysis_config=analysis_config,
            working_dir=work_dir,
            mapper=mapper,
        )

        output_files = calculix_runner.run_analysis()
        logger.info(f"CalculiX analysis completed: {output_files}")

        # Step 8: Parse results
        logger.info("Parsing analysis results")

        # Parse output for errors and warnings
        output_parser = OutputParser(mapper)

        # Parse the output file or captured output
        if "message" in output_files:
            with open(output_files["message"], "r") as f:
                output_text = f.read()
            parse_result = output_parser.parse_output(output_text)

            # Add warnings and errors to result
            result["warnings"] = parse_result["warnings"]
            result["errors"] = parse_result["errors"]

            # Check if analysis converged
            converged, reason = output_parser.check_convergence(output_text)

            if not converged:
                logger.error(f"Analysis did not converge: {reason}")
                raise AnalysisError(f"Analysis did not converge: {reason}")

        # Parse result files
        results_parser = ResultsParser(domain_model)
        parsed_results = results_parser.parse_results(output_files)

        # Step 9: Copy output files to output directory
        for file_type, file_path in output_files.items():
            if os.path.exists(file_path):
                target_path = os.path.join(output_dir, os.path.basename(file_path))
                shutil.copy2(file_path, target_path)
                output_files[file_type] = target_path

        # Add output files to result
        result["output_files"] = output_files

        # Mark as success if no errors were found
        if not result["errors"]:
            result["status"] = "success"

    finally:
        # No need to explicitly clean up the temporary directory
        # unless we want to force cleanup before the program exits
        pass

    return result


def run_enhanced_analysis(
    ifc_path: str,
    output_dir: str,
    analysis_type: str = "linear_static",
    mesh_size: float = 0.1,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Run an enhanced structural analysis on an IFC file with improved boundary condition
    and load handling.

    Args:
        ifc_path (str): Path to the IFC file to analyze.
        output_dir (str): Directory where the analysis results will be saved.
        analysis_type (str): Type of structural analysis to perform.
        mesh_size (float): Size of the mesh elements.
        verbose (bool): Whether to print verbose output.

    Returns:
        Dict[str, Any]: Dictionary containing the analysis results and output file paths.

    Raises:
        StructuralAnalysisError: If an error occurs during the analysis.
    """
    try:
        # Step 1: Extract the structural model from the IFC file
        # This uses the existing IFC extraction functionality
        logger.info(f"Extracting structural model from {ifc_path}")

        # Call the existing analyze_ifc function but intercept its output
        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=output_dir,
            analysis_type=analysis_type,
            mesh_size=mesh_size,
            verbose=verbose,
        )

        # Check the results to see if we need to enhance the analysis
        if result["status"] == "success":
            # The analysis completed, but we need to check if it had proper boundary conditions
            # and loads. If not, we'll need to reprocess the output files.

            # Path to the CalculiX input file
            inp_file = next(
                (v for k, v in result["output_files"].items() if k == "data"), None
            )

            if inp_file and os.path.exists(inp_file):
                # Check if the file contains boundary conditions and loads
                with open(inp_file, "r") as f:
                    content = f.read()

                has_boundary_conditions = "*BOUNDARY" in content
                has_loads = "*CLOAD" in content or "*DLOAD" in content
                has_analysis_steps = "*STEP" in content and "*END STEP" in content

                if not (has_boundary_conditions and has_loads and has_analysis_steps):
                    logger.warning(
                        "Original analysis missing proper boundary conditions, loads, or analysis steps"
                    )
                    logger.info("Enhancing the analysis with improved handling")

                    # We need to enhance the analysis by adding proper boundary conditions and loads
                    # This would involve reprocessing the domain model and generating a new input file
                    enhanced_result = _enhance_analysis(
                        result, ifc_path, output_dir, analysis_type
                    )

                    # Return the enhanced result
                    return enhanced_result

        # If we get here, either the analysis failed or it completed successfully with proper
        # boundary conditions and loads, so we return the original result
        return result

    except Exception as e:
        logger.error(f"Error in enhanced analysis: {str(e)}")
        raise StructuralAnalysisError(f"Enhanced analysis failed: {str(e)}")


def _enhance_analysis(
    original_result: Dict,
    ifc_path: str,
    output_dir: str,
    analysis_type: str = "linear_static",
) -> Dict:
    """
    Enhance an existing analysis by adding proper boundary conditions and loads.

    Args:
        original_result (Dict): The result from the original analysis.
        ifc_path (str): Path to the IFC file.
        output_dir (str): Directory where the enhanced analysis results will be saved.
        analysis_type (str): Type of structural analysis to perform.

    Returns:
        Dict: Dictionary containing the enhanced analysis results and output file paths.
    """
    try:
        # Create a backup of the original files
        backup_dir = os.path.join(output_dir, "original_backup")
        os.makedirs(backup_dir, exist_ok=True)

        for file_type, file_path in original_result["output_files"].items():
            if os.path.exists(file_path):
                backup_path = os.path.join(backup_dir, os.path.basename(file_path))
                shutil.copy2(file_path, backup_path)
                logger.info(f"Backed up {file_type} to {backup_path}")

        # Get the paths to key files
        inp_file = original_result["output_files"].get("data", "")
        frd_file = original_result["output_files"].get("results", "")

        # Create enhanced input file with proper boundary conditions and loads
        enhanced_inp_file = os.path.join(output_dir, "enhanced_model.inp")

        # Extract the structural model
        model = extract_model(ifc_path)

        # Ensure the model has all the necessary components
        if not model.members:
            logger.warning("No structural members found in the model")
            return original_result

        # Check if the model has connections (supports)
        if not model.connections:
            logger.warning("No structural connections found in the model")
            # This is where we could infer supports from the geometry
            # For example, find nodes at y=0 and add fixed supports

        # Generate enhanced CalculiX input file
        input_generator = CalculixInputGenerator(model)
        enhanced_inp_file = input_generator.generate_input_file(enhanced_inp_file)

        # Run CalculiX with the enhanced input file
        calculix_runner = CalculixRunner(enhanced_inp_file)
        result_files = calculix_runner.run_analysis()

        # Update the result
        enhanced_result = original_result.copy()
        enhanced_result["output_files"] = result_files
        enhanced_result["status"] = "success" if result_files else "failed"

        # Add a note about the enhancement
        if "notes" not in enhanced_result:
            enhanced_result["notes"] = []
        enhanced_result["notes"].append(
            "Analysis enhanced with improved boundary condition and load handling"
        )

        return enhanced_result

    except Exception as e:
        logger.error(f"Error enhancing analysis: {str(e)}")
        # If enhancement fails, return the original result with a note
        original_result["notes"] = original_result.get("notes", []) + [
            f"Failed to enhance analysis: {str(e)}"
        ]
        return original_result


def extract_model(ifc_path: str) -> StructuralModel:
    """
    Extract a structural model from an IFC file.

    Args:
        ifc_path (str): Path to the IFC file.

    Returns:
        StructuralModel: The extracted structural model.

    Raises:
        ModelExtractionError: If the model extraction fails.
    """
    try:
        # Create an extractor for the IFC file
        extractor = Extractor(ifc_path)

        # Extract the structural model
        model = extractor.extract_model()

        return model
    except Exception as e:
        raise ModelExtractionError(f"Failed to extract model from IFC file: {str(e)}")


def get_entity_mapping(
    domain_model: StructuralModel, calculix_input: str
) -> DomainToCalculixMapper:
    """
    Get the mapping between CalculiX entities and IFC entities.

    Args:
        domain_model (StructuralModel): The domain model.
        calculix_input (str): Path to the CalculiX input file.

    Returns:
        DomainToCalculixMapper: The entity mapper.

    Raises:
        StructuralAnalysisError: If the mapping fails.
    """
    try:
        # Create a mesh converter which will establish the mapping
        mesh_converter = MeshConverter(domain_model)

        # Convert the mesh to establish the mapping
        mesh_converter.convert_mesh(calculix_input, calculix_input + ".tmp")

        # Return the mapper
        return mesh_converter.get_mapper()
    except Exception as e:
        raise StructuralAnalysisError(f"Failed to get entity mapping: {str(e)}")


def create_analysis_config(analysis_type: str) -> AnalysisConfig:
    """
    Create an analysis configuration for the specified analysis type.

    Args:
        analysis_type (str): Type of analysis to perform.

    Returns:
        AnalysisConfig: The analysis configuration.

    Raises:
        ValueError: If the analysis type is not supported.
    """
    # Check if the analysis type is supported before creating the config
    if analysis_type not in AnalysisConfig.ANALYSIS_TYPES:
        raise ValueError(
            f"Unsupported analysis type: {analysis_type}. "
            f"Supported types: {list(AnalysisConfig.ANALYSIS_TYPES.keys())}"
        )

    # Create a default analysis configuration
    config = AnalysisConfig()

    # Update config with the specified analysis type
    config._config["analysis_type"] = analysis_type
    config._config["solver_params"] = AnalysisConfig.ANALYSIS_TYPES[analysis_type][
        "default_solver_params"
    ]

    # Validate the configuration
    config.validate()

    return config


def create_meshing_config(mesh_size: float) -> MeshingConfig:
    """
    Create a meshing configuration with the specified mesh size.

    Args:
        mesh_size (float): Default mesh size.

    Returns:
        MeshingConfig: The meshing configuration.
    """
    # Create a default meshing configuration
    config = MeshingConfig()

    # Update the default mesh size
    config._config["global_settings"]["default_element_size"] = mesh_size

    # Update member-specific mesh sizes
    for member_type in config._config["member_types"]:
        config._config["member_types"][member_type]["element_size"] = mesh_size

    # Validate the configuration
    config.validate()

    return config
