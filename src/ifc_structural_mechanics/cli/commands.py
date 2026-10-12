"""
Command-line interface for IFC Structural Mechanics.

This module provides the CLI: analysis of an IFC file, with boundary condition
and load handling for structural analysis of IFC files.
"""

import json
import logging
import os
import sys

import click

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc
from ifc_structural_mechanics.utils.error_handling import (
    AnalysisError,
    MeshingError,
    ModelExtractionError,
    StructuralAnalysisError,
)
from ifc_structural_mechanics.utils.temp_dir import set_keep_temp_files

# Configure logger
logger = logging.getLogger(__name__)


@click.group()
@click.version_option()
def cli():
    """IFC Structural Analysis - Command Line Interface.

    Run structural analysis on IFC building models with improved boundary condition
    and load handling.

    Examples:
        ifc-analysis analyze path/to/model.ifc --output ./results

        ifc-analysis analyze path/to/model.ifc --output ./results --mesh-size 0.2
    """
    pass


@cli.command()
@click.argument(
    "ifc_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(file_okay=False, dir_okay=True, writable=True),
    help="Directory for analysis output files",
    required=True,
)
@click.option(
    "--analysis-type",
    "-t",
    type=click.Choice(["linear_static", "linear_buckling"]),
    default="linear_static",
    show_default=True,
    help="Type of structural analysis to perform",
)
@click.option(
    "--mesh-size",
    "-m",
    type=float,
    default=1,
    show_default=True,
    help="Default size for mesh elements (in meters)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.option("--json-output", "-j", is_flag=True, help="Output results in JSON format")
@click.option(
    "--map-entities/--no-map-entities",
    default=True,
    show_default=True,
    help="Map errors back to original IFC entities",
)
@click.option(
    "--gravity",
    is_flag=True,
    default=False,
    help=(
        "Add self-weight as a load case of its own, Gravity. For files with no "
        "load case: a load case that includes self-weight has it without this"
    ),
)
@click.option(
    "--timeout",
    type=int,
    default=600,
    show_default=True,
    help="CalculiX solver timeout in seconds (0 = no limit)",
)
@click.option(
    "--element-order",
    type=click.Choice(["1", "2"]),
    default="2",
    show_default=True,
    help="2 = quadratic elements (B32R, S6); 1 = linear (B31, S3), which is "
    "faster but needs a much finer mesh for shells",
)
@click.option(
    "--strict-connections",
    is_flag=True,
    default=False,
    help="Analyse only the connections in the IFC file. By default a beam or "
    "column lying in a slab or wall is also tied to it along its length",
)
@click.option(
    "--open-sections",
    type=click.Choice(["equivalent", "user-element"]),
    default="equivalent",
    show_default=True,
    help="How sections other than solid rectangles are analysed: as a "
    "rectangle of the same axial, bending and shear stiffness, or with "
    "CalculiX U1 elements, which stock CalculiX cannot mix with other beams "
    "or shells",
)
def analyze(
    ifc_file: str,
    output_dir: str,
    analysis_type: str = "linear_static",
    mesh_size: float = 1.0,
    verbose: bool = False,
    json_output: bool = False,
    map_entities: bool = True,
    gravity: bool = False,
    timeout: int = 600,
    element_order: str = "2",
    strict_connections: bool = False,
    open_sections: str = "equivalent",
):
    """
    Run structural analysis on an IFC file.

    IFC_FILE is the path to the IFC file to analyze.
    """
    exit_code = run_analyze(
        ifc_file,
        output_dir,
        analysis_type,
        mesh_size,
        verbose,
        json_output,
        map_entities,
        gravity,
        timeout,
        int(element_order),
        strict_connections,
        open_sections.replace("-", "_"),
    )
    set_keep_temp_files(keep_files=True)
    sys.exit(exit_code)


def run_analyze(
    ifc_file: str,
    output_dir: str,
    analysis_type: str = "linear_static",
    mesh_size: float = 1.0,
    verbose: bool = False,
    json_output: bool = False,
    map_entities: bool = True,
    gravity: bool = False,
    timeout: int = 600,
    element_order: int = 2,
    strict_connections: bool = False,
    open_sections: str = "equivalent",
) -> int:
    """
    Run the analysis and return the appropriate exit code.

    Args:
        ifc_file (str): Path to the IFC file to analyze.
        output_dir (str): Directory for analysis output files.
        analysis_type (str): Type of structural analysis to perform.
        mesh_size (float): Default size for mesh elements (in meters).
        verbose (bool): Enable verbose output.
        json_output (bool): Output results in JSON format.
        map_entities (bool): Map errors back to original IFC entities.
        gravity (bool): Include self-weight gravity loads.
        timeout (int): CalculiX solver timeout in seconds (0 = no limit).
        element_order (int): 2 for quadratic elements, 1 for linear ones.
        strict_connections (bool): Analyse only the connections in the file.
        open_sections (str): "equivalent" or "user_element".

    Returns:
        int: Exit code indicating success (0) or failure (non-zero).
    """
    # Configure logging based on verbosity
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(levelname)-8s %(message)s", stream=sys.stderr
    )

    # Print welcome message
    if not json_output:
        click.echo(click.style("IFC Structural Analysis", fg="blue", bold=True))
        click.echo(click.style(f"{'=' * 50}", fg="blue"))
        click.echo(f"Input file:    {ifc_file}")
        click.echo(f"Output directory: {output_dir}")
        click.echo(f"Analysis type: {analysis_type}")
        click.echo(f"Mesh size:     {mesh_size}")
        click.echo(click.style(f"{'=' * 50}", fg="blue"))
        click.echo("Starting analysis...")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Initialize Gmsh if available
    gmsh_initialized = False
    try:
        import gmsh

        if not gmsh.isInitialized():
            gmsh.initialize()
            gmsh_initialized = True
            if json_output:
                # Standard output is the JSON document and nothing else
                gmsh.option.setNumber("General.Terminal", 0)
            logger.info("Successfully initialized Gmsh")
    except ImportError:
        logger.warning("Gmsh Python API not found. Ensure Gmsh is properly installed.")
    except Exception as e:
        logger.warning(f"Failed to initialize Gmsh: {e}")

    try:
        result = analyze_ifc(
            ifc_path=ifc_file,
            output_dir=output_dir,
            analysis_type=analysis_type,
            mesh_size=mesh_size,
            verbose=verbose,
            gravity=gravity,
            calculix_timeout=timeout or None,
            element_order=element_order,
            strict_connections=strict_connections,
            open_sections=open_sections,
        )

        # Format and display results
        if json_output:
            # Convert paths to strings for JSON serialization
            serializable_result = _make_serializable(result)
            click.echo(json.dumps(serializable_result, indent=2))
        else:
            _display_result(result, map_entities)

        # Return appropriate exit code
        if result["status"] == "success":
            return 0
        else:
            return 1

    except ModelExtractionError as e:
        _handle_error("Model Extraction Error", e, json_output)
        return 2
    except MeshingError as e:
        _handle_error("Meshing Error", e, json_output)
        return 3
    except AnalysisError as e:
        _handle_error("Analysis Error", e, json_output)
        return 4
    except StructuralAnalysisError as e:
        _handle_error("Structural Analysis Error", e, json_output)
        return 5
    except Exception as e:
        _handle_error("Unexpected Error", e, json_output)
        return 99
    finally:
        # Clean up Gmsh if we initialized it
        if gmsh_initialized:
            try:
                import gmsh

                if gmsh.isInitialized():
                    gmsh.finalize()
                    logger.info("Finalized Gmsh")
            except Exception as e:
                logger.warning(f"Error during Gmsh cleanup: {e}")


def _make_serializable(result: dict) -> dict:
    """
    Convert a result dictionary to a JSON-serializable format.

    The domain model and the parsed result objects are left out: they are
    Python objects for callers of the API. What they hold is in results.json.

    Args:
        result: The analysis result dictionary.

    Returns:
        A JSON-serializable version of the result.
    """
    serializable = {}

    for key, value in result.items():
        if key in ("model", "parsed_results"):
            continue
        if key == "output_files":
            # Convert file paths to strings
            serializable[key] = {k: str(v) for k, v in value.items()}
        else:
            serializable[key] = value

    return serializable


def _display_result(result: dict, map_entities: bool = True) -> None:
    """
    Display the analysis result in human-readable format.

    Args:
        result: The analysis result dictionary.
        map_entities: Whether to display mapped entity references.
    """
    status = result["status"]
    status_color = "green" if status == "success" else "red"

    click.echo("\nAnalysis Results:")
    click.echo(click.style(f"Status: {status}", fg=status_color, bold=True))

    # Display notes if available
    if "notes" in result and result["notes"]:
        click.echo("\nNotes:")
        for note in result["notes"]:
            click.echo(f"  • {note}")

    # Display warnings
    if result.get("warnings"):
        click.echo("\nWarnings:")
        for i, warning in enumerate(result["warnings"], 1):
            message = warning.get("message", "Unknown warning")
            click.echo(click.style(f"  {i}. {message}", fg="yellow"))

            # Add entity reference if available and mapping is enabled
            if map_entities and warning.get("domain_id"):
                entity_type = warning.get("entity_type", "entity")
                domain_id = warning.get("domain_id")
                click.echo(f"     Reference: {entity_type} {domain_id}")

    # Display errors
    if result.get("errors"):
        click.echo("\nErrors:")
        for i, error in enumerate(result["errors"], 1):
            message = error.get("message", "Unknown error")
            click.echo(click.style(f"  {i}. {message}", fg="red"))

            # Add entity reference if available and mapping is enabled
            if map_entities and error.get("domain_id"):
                entity_type = error.get("entity_type", "entity")
                domain_id = error.get("domain_id")
                click.echo(f"     Reference: {entity_type} {domain_id}")

    # Display output files
    if result.get("output_files"):
        click.echo("\nOutput Files:")
        for file_type, file_path in result["output_files"].items():
            click.echo(f"  {file_type}: {file_path}")


def _handle_error(error_type: str, error: Exception, json_output: bool = False) -> None:
    """
    Handle an exception with appropriate output.

    Args:
        error_type: Type of error that occurred.
        error: The exception instance.
        json_output: Whether to output in JSON format.
    """
    if json_output:
        error_data = {
            "status": "failed",
            "error_type": error_type,
            "message": str(error),
        }

        # Add context information for structural analysis errors
        if isinstance(error, StructuralAnalysisError) and hasattr(error, "context"):
            error_data["context"] = error.context

        # Add error details for analysis errors
        if isinstance(error, AnalysisError) and hasattr(error, "error_details"):
            error_data["error_details"] = error.error_details

        click.echo(json.dumps(error_data, indent=2))
    else:
        click.echo(click.style(f"\n{error_type}:", fg="red", bold=True))
        click.echo(click.style(f"  {str(error)}", fg="red"))

        # Add context information for structural analysis errors
        if (
            isinstance(error, StructuralAnalysisError)
            and hasattr(error, "context")
            and error.context
        ):
            click.echo("\nContext:")
            for key, value in error.context.items():
                click.echo(f"  {key}: {value}")

        # Add error details for analysis errors
        if (
            isinstance(error, AnalysisError)
            and hasattr(error, "error_details")
            and error.error_details
        ):
            click.echo("\nError Details:")
            for i, detail in enumerate(error.error_details, 1):
                click.echo(
                    click.style(
                        f"  {i}. {detail.get('message', 'Unknown error')}", fg="red"
                    )
                )

                # Add entity reference if available
                if detail.get("domain_id"):
                    entity_type = detail.get("entity_type", "entity")
                    domain_id = detail.get("domain_id")
                    click.echo(f"     Reference: {entity_type} {domain_id}")


if __name__ == "__main__":
    cli()
