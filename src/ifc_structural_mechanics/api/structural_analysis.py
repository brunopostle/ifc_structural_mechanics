"""
Updated structural analysis API using the unified CalculiX writer.

This module provides the simplified public API for performing structural analysis
on IFC models using the unified workflow that eliminates dual element writing.
"""

import logging
import os
import shutil
from typing import Any, Dict, Optional

from ..analysis.calculix_runner import CalculixRunner
from ..analysis.output_parser import OutputParser
from ..analysis.results_parser import ResultsParser
from ..config.analysis_config import AnalysisConfig
from ..config.meshing_config import MeshingConfig
from ..config.system_config import SystemConfig
from ..domain.structural_model import StructuralModel
from ..ifc.extractor import Extractor
from ..meshing.unified_calculix_writer import run_complete_analysis_workflow
from ..utils.error_handling import (
    AnalysisError,
    MeshingError,
    ModelExtractionError,
    StructuralAnalysisError,
)
from ..utils.file_utils import ensure_directory

# Set up logger
logger = logging.getLogger(__name__)


def analyze_ifc(
    ifc_path: str,
    output_dir: str,
    analysis_type: str = "linear_static",
    mesh_size: float = 0.1,
    verbose: bool = False,
    gravity: bool = False,
) -> Dict[str, Any]:
    """
    Run a structural analysis on an IFC file using the unified workflow.

    This function performs the complete workflow from IFC model extraction
    to structural analysis with CalculiX, using the new unified approach that
    eliminates dual element writing conflicts.

    Args:
        ifc_path (str): Path to the IFC file to analyze.
        output_dir (str): Directory where the output files will be written.
        analysis_type (str, optional): Type of analysis to perform.
            Currently supported: "linear_static", "linear_buckling".
            Defaults to "linear_static".
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
            - mesh_statistics (Dict): Statistics about the generated mesh

    Raises:
        ModelExtractionError: If the model extraction from IFC fails.
        MeshingError: If the meshing process fails.
        AnalysisError: If the analysis process fails.
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
        "mesh_statistics": {},
        "model": None,
    }

    # Ensure output directory exists
    output_dir = ensure_directory(output_dir)

    try:
        # Step 1: Extract the structural model from the IFC file
        logger.info(f"Extracting structural model from {ifc_path}")
        domain_model = extract_model(ifc_path)

        # Store the model in results for later access
        result["model"] = domain_model

        # Check if the model has any members
        if not domain_model.members:
            logger.error("No structural members found in the IFC file")
            raise ModelExtractionError("No structural members found in the IFC file")

        logger.info(
            f"Extracted structural model with {len(domain_model.members)} members"
        )

        # Step 2: Create configurations
        analysis_config = create_analysis_config(analysis_type, gravity=gravity)
        meshing_config = create_meshing_config(mesh_size)
        system_config = SystemConfig()

        # Step 3: Define output file paths
        intermediate_files_dir = os.path.join(output_dir, "intermediate")
        final_inp_file = os.path.join(output_dir, "analysis.inp")

        # Step 4: Run the unified workflow (Domain Model → Gmsh → CalculiX Input)
        logger.info("Running unified analysis workflow...")

        unified_inp_file = run_complete_analysis_workflow(
            domain_model=domain_model,
            output_inp_file=final_inp_file,
            analysis_config=analysis_config,
            meshing_config=meshing_config,
            system_config=system_config,
            intermediate_files_dir=intermediate_files_dir,
        )

        logger.info(f"Generated unified CalculiX input file: {unified_inp_file}")

        # Step 5: Run the CalculiX analysis
        logger.info("Running CalculiX analysis...")
        calculix_runner = CalculixRunner(
            input_file_path=unified_inp_file,
            system_config=system_config,
            analysis_config=analysis_config,
            working_dir=output_dir,
        )

        calculix_output_files = calculix_runner.run_analysis()
        logger.info(f"CalculiX analysis completed: {calculix_output_files}")

        # Step 6: Parse results and check for errors/warnings
        logger.info("Parsing analysis results...")

        # Parse output for errors and warnings
        output_parser = OutputParser()

        # Parse the output file or captured output
        if "message" in calculix_output_files and os.path.exists(
            calculix_output_files["message"]
        ):
            with open(calculix_output_files["message"], "r") as f:
                output_text = f.read()
            parse_result = output_parser.parse_output(output_text)

            # Add warnings and errors to result
            result["warnings"] = parse_result.get("warnings", [])
            result["errors"] = parse_result.get("errors", [])

            # Check if analysis converged
            converged, reason = output_parser.check_convergence(output_text)

            if not converged:
                logger.error(f"Analysis did not converge: {reason}")
                result["errors"].append(
                    {
                        "message": f"Analysis did not converge: {reason}",
                        "severity": "critical",
                        "entity_type": None,
                        "ccx_id": None,
                        "domain_id": None,
                    }
                )
                # Don't raise exception here - let user see the results

        # Parse result files for detailed results
        if calculix_output_files:
            try:
                results_parser = ResultsParser(domain_model)
                parsed_results = results_parser.parse_results(calculix_output_files)
                result["parsed_results"] = parsed_results
                logger.info("Successfully parsed analysis results")
            except Exception as e:
                logger.warning(f"Error parsing detailed results: {e}")
                result["warnings"].append(
                    {
                        "message": f"Could not parse detailed results: {str(e)}",
                        "severity": "warning",
                        "entity_type": None,
                        "ccx_id": None,
                        "domain_id": None,
                    }
                )

        # Step 7: Copy output files to output directory and organize them
        organized_output_files = {}

        # Copy CalculiX result files
        for file_type, file_path in calculix_output_files.items():
            if os.path.exists(file_path):
                target_filename = f"calculix_output.{file_type}"
                target_path = os.path.join(output_dir, target_filename)
                shutil.copy2(file_path, target_path)
                organized_output_files[file_type] = target_path
                logger.debug(f"Copied {file_type} file to {target_path}")

        # Copy the main input file if it's not already in output_dir
        if unified_inp_file != final_inp_file and os.path.exists(unified_inp_file):
            shutil.copy2(unified_inp_file, final_inp_file)
        organized_output_files["input"] = final_inp_file

        # Copy intermediate files if they exist
        if os.path.exists(intermediate_files_dir):
            for filename in os.listdir(intermediate_files_dir):
                if filename.endswith((".msh", ".geo", ".map.json")):
                    src_path = os.path.join(intermediate_files_dir, filename)
                    dst_path = os.path.join(output_dir, filename)
                    shutil.copy2(src_path, dst_path)
                    organized_output_files[f"intermediate_{filename}"] = dst_path

        # Add organized output files to result
        result["output_files"] = organized_output_files

        # Step 8: Add mesh statistics if available
        # Note: In future versions, this could be extracted from the unified writer
        result["mesh_statistics"] = {
            "mesh_file_size": _get_file_size(
                organized_output_files.get("intermediate_mesh.msh")
            ),
            "input_file_size": _get_file_size(final_inp_file),
            "analysis_type": analysis_type,
            "mesh_size": mesh_size,
        }

        # Step 9: Determine final status
        if result["errors"]:
            # Check if errors are critical
            critical_errors = [
                e for e in result["errors"] if e.get("severity") == "critical"
            ]
            if critical_errors:
                result["status"] = "failed"
                logger.error(
                    f"Analysis failed with {len(critical_errors)} critical errors"
                )
            else:
                result["status"] = "completed_with_errors"
                logger.warning(
                    f"Analysis completed with {len(result['errors'])} non-critical errors"
                )
        else:
            result["status"] = "success"
            logger.info("Analysis completed successfully")

        return result

    except ModelExtractionError:
        # Re-raise model extraction errors
        raise

    except (MeshingError, AnalysisError) as e:
        # Handle known analysis errors
        logger.error(f"Analysis workflow error: {str(e)}")
        result["errors"].append(
            {
                "message": str(e),
                "severity": "critical",
                "entity_type": None,
                "ccx_id": None,
                "domain_id": None,
            }
        )
        result["status"] = "failed"
        return result

    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error in analysis workflow: {str(e)}")
        raise StructuralAnalysisError(f"Analysis workflow failed: {str(e)}") from e


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


def create_analysis_config(analysis_type: str, gravity: bool = False) -> AnalysisConfig:
    """
    Create an analysis configuration for the specified analysis type.

    Args:
        analysis_type (str): Type of analysis to perform.
        gravity (bool): Whether to include self-weight gravity loads.

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
    config._config["gravity"] = gravity

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

    # Ensure max_element_size is at least as large as mesh_size
    if mesh_size > config._config["global_settings"]["max_element_size"]:
        config._config["global_settings"]["max_element_size"] = mesh_size

    # Update member-specific mesh sizes
    for member_type in config._config["member_types"]:
        config._config["member_types"][member_type]["element_size"] = mesh_size

    # Validate the configuration
    config.validate()

    return config


def _get_file_size(file_path: Optional[str]) -> Optional[int]:
    """
    Get the size of a file in bytes.

    Args:
        file_path: Path to the file

    Returns:
        File size in bytes, or None if file doesn't exist
    """
    if not file_path:
        return None

    try:
        if os.path.exists(file_path):
            return os.path.getsize(file_path)
    except (OSError, FileNotFoundError):
        # File might have been moved or deleted, return None
        pass

    return None


# Simplified convenience function for common use cases
def analyze_ifc_simple(ifc_path: str, output_dir: str) -> bool:
    """
    Simplified analysis function for basic use cases.

    Args:
        ifc_path (str): Path to the IFC file to analyze
        output_dir (str): Directory where results will be saved

    Returns:
        bool: True if analysis succeeded, False otherwise
    """
    try:
        result = analyze_ifc(ifc_path, output_dir)
        return result["status"] == "success"
    except Exception as e:
        logger.error(f"Simple analysis failed: {e}")
        return False


# Migration helper for existing code
def run_enhanced_analysis(
    ifc_path: str,
    output_dir: str,
    analysis_type: str = "linear_static",
    mesh_size: float = 0.1,
    verbose: bool = False,
    gravity: bool = False,
) -> Dict[str, Any]:
    """
    Enhanced analysis function - now just calls the unified analyze_ifc.

    This function is kept for backward compatibility but now uses the
    simplified unified workflow internally.

    Args:
        ifc_path (str): Path to the IFC file to analyze.
        output_dir (str): Directory where the analysis results will be saved.
        analysis_type (str): Type of structural analysis to perform.
        mesh_size (float): Size of the mesh elements.
        verbose (bool): Whether to print verbose output.
        gravity (bool): Whether to include self-weight gravity loads.

    Returns:
        Dict[str, Any]: Dictionary containing the analysis results and output file paths.
    """
    logger.info("Using unified analysis workflow (enhanced analysis is now standard)")

    return analyze_ifc(
        ifc_path=ifc_path,
        output_dir=output_dir,
        analysis_type=analysis_type,
        mesh_size=mesh_size,
        verbose=verbose,
        gravity=gravity,
    )
