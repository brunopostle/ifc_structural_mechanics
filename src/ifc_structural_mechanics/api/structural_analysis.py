"""
Updated structural analysis API using the unified CalculiX writer.

This module provides the simplified public API for performing structural analysis
on IFC models using the unified workflow that eliminates dual element writing.
"""

import hashlib
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import __version__
from ..analysis.calculix_runner import CalculixRunner
from ..analysis.output_parser import solver_warnings
from ..analysis.plausibility import plausibility_warnings
from ..analysis.results_parser import BUCKLING_REFERENCE_CASE, ResultsParser
from ..config.analysis_config import AnalysisConfig
from ..config.meshing_config import MeshingConfig
from ..config.system_config import SystemConfig
from ..domain.structural_model import StructuralModel
from ..export.results_exporter import ResultsExporter
from ..ifc.extractor import Extractor
from ..meshing.unified_calculix_writer import run_complete_analysis_workflow
from ..utils.error_handling import (
    AnalysisError,
    MeshingError,
    ModelExtractionError,
    ResultProcessingError,
    StructuralAnalysisError,
)
from ..utils.file_utils import ensure_directory
from ..utils.messages import guids_of, warning

# Set up logger
logger = logging.getLogger(__name__)


def analyze_ifc(
    ifc_path: str,
    output_dir: str,
    analysis_type: str = "linear_static",
    mesh_size: float = 1.0,
    verbose: bool = False,
    gravity: bool = False,
    calculix_timeout: Optional[int] = 600,
    element_order: int = 2,
    strict_connections: bool = False,
    open_sections: str = "equivalent",
    num_modes: int = 10,
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
            Currently supported: "linear_static", "linear_buckling" and
            "modal" (natural frequencies and mode shapes).
            Defaults to "linear_static".
        mesh_size (float, optional): Default mesh size for the finite element mesh.
            Defaults to 0.1.
        verbose (bool, optional): Whether to enable verbose logging.
            Defaults to False.
        element_order (int, optional): 2 for quadratic beam and shell elements
            (B32R, S6), 1 for linear ones (B31, S3). Linear shells need a much
            finer mesh for the same accuracy; they are only worth using when a
            model is too large to solve otherwise. Defaults to 2.
        strict_connections (bool, optional): Analyse only the connections in
            the IFC file. By default a beam or column lying in a slab or wall
            is also tied to it along its length. Defaults to False.
        open_sections (str, optional): How sections other than solid
            rectangles are analysed. "equivalent" (default): a native beam
            element with a rectangle of the same axial, bending and shear
            stiffness. "user_element": CalculiX's U1 element, which stock
            CalculiX cannot mix with other beam or shell elements.
        num_modes (int, optional): How many modes a modal analysis finds,
            lowest frequency first. Defaults to 10.

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
            raise ModelExtractionError(
                "No structural members found in the IFC file", code="E-IFC-001"
            )

        logger.info(
            f"Extracted structural model with {len(domain_model.members)} members"
        )

        # Self-weight cannot be worked out for a material with no density
        weighed = [
            g.name
            for g in domain_model.load_groups
            if g.is_load_case and g.includes_self_weight
        ]
        modal = analysis_type == "modal"
        if gravity or weighed or modal:
            weightless = sorted(
                {
                    member.material.name
                    for member in domain_model.members
                    if member.material is not None and member.material.density is None
                }
            )
            if weightless:
                if modal:
                    asked = "A modal analysis takes its mass from the materials"
                elif weighed:
                    asked = (
                        "Load case " + ", ".join(weighed[:3]) + " includes self-weight"
                    )
                else:
                    asked = "Self-weight was asked for (--gravity)"
                raise ModelExtractionError(
                    f"{asked}, but these materials have no mass density "
                    "(Pset_MaterialCommon.MassDensity): " + ", ".join(weightless) + ".",
                    code="E-MAT-003",
                )
        if modal:
            result["warnings"].extend(_loads_are_not_mass(domain_model, gravity))
        elif gravity and weighed:
            result["warnings"].append(
                warning(
                    "W-LOD-003",
                    "Self-weight was asked for (--gravity) and "
                    f"{len(weighed)} load case(s) of the file already include "
                    f"it: {', '.join(weighed[:3])}"
                    + (" ..." if len(weighed) > 3 else "")
                    + ". It is analysed again as a load case of its own, "
                    "Gravity, which no combination includes.",
                )
            )

        # Step 1b: Pre-analysis model validation
        validation_warnings = _validate_model(domain_model, gravity, modal=modal)
        result["warnings"].extend(validation_warnings)

        # Step 2: Create configurations
        analysis_config = create_analysis_config(
            analysis_type,
            gravity=gravity,
            strict_connections=strict_connections,
            open_sections=open_sections,
            num_modes=num_modes,
        )
        meshing_config = create_meshing_config(mesh_size, element_order)
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
        model_warnings = getattr(domain_model, "analysis_warnings", [])
        result["warnings"].extend(model_warnings)
        warnings_passed_on = len(model_warnings)

        # Step 5: Run the CalculiX analysis
        logger.info("Running CalculiX analysis...")
        calculix_runner = CalculixRunner(
            input_file_path=unified_inp_file,
            system_config=system_config,
            analysis_config=analysis_config,
            working_dir=output_dir,
        )

        calculix_output_files = calculix_runner.run_analysis(timeout=calculix_timeout)
        logger.info(f"CalculiX analysis completed: {calculix_output_files}")

        # Step 6: What the solver had to say, then its results
        result["warnings"].extend(solver_warnings(calculix_runner.solver_output))

        # Parse result files for detailed results. An analysis whose results
        # cannot be read or written has not succeeded: that is an error, not
        # a warning beside a "success".
        results_json_path = None
        if calculix_output_files:
            try:
                load_cases = [
                    g
                    for g in domain_model.load_groups
                    if g.is_load_case and g.has_actions
                ]
                load_case_names = [g.name for g in load_cases]
                if gravity:
                    load_case_names.append("Gravity")
                if not load_case_names:
                    load_case_names = None
                if analysis_type == "linear_buckling":
                    # One step, with the loads of every case in it
                    load_case_names = [BUCKLING_REFERENCE_CASE]
                elif modal:
                    # One step, its results are modes
                    load_case_names = None
                results_parser = ResultsParser(
                    domain_model, load_case_names=load_case_names
                )
                parsed_results = results_parser.parse_results(calculix_output_files)
                result["parsed_results"] = parsed_results
                # Warnings raised while reading the results
                result["warnings"].extend(
                    getattr(domain_model, "analysis_warnings", [])[warnings_passed_on:]
                )
                logger.info("Successfully parsed analysis results")

                # Export GlobalId-keyed JSON results
                results_json_path = os.path.join(output_dir, "results.json")
                # A combination is the sum of its load cases' results, which
                # needs a step per case and a linear analysis
                combinations = list(domain_model.load_combinations)
                if combinations and analysis_type != "linear_static":
                    result["warnings"].append(
                        warning(
                            "W-LOD-006",
                            f"{len(combinations)} load combination(s) of "
                            "the file have no results: combinations are "
                            "only formed in a linear static analysis.",
                        )
                    )
                    combinations = []
                exporter = ResultsExporter(
                    domain_model,
                    parsed_results,
                    element_nodes=results_parser.element_nodes,
                    load_combinations=combinations,
                    analysis_type=analysis_type,
                    node_coordinates=results_parser.node_coordinates,
                )
                exported = exporter.build()
                result["warnings"].extend(plausibility_warnings(exported, domain_model))
                exported = _with_run_record(
                    exported,
                    run=_run_record(
                        ifc_path,
                        calculix_runner.solver_output,
                        analysis_type=analysis_type,
                        mesh_size_m=mesh_size,
                        element_order=element_order,
                        strict_connections=strict_connections,
                        open_sections=open_sections,
                        gravity=gravity,
                        **({"num_modes": num_modes} if modal else {}),
                    ),
                    warnings=result["warnings"],
                )
                ResultsExporter.write(exported, results_json_path)
            except StructuralAnalysisError:
                raise
            except Exception as e:
                raise ResultProcessingError(
                    f"The analysis ran but its results could not be read: "
                    f"{type(e).__name__}: {e}",
                    code="E-RES-001",
                ) from e

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

        if results_json_path:
            organized_output_files["results_json"] = results_json_path

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

    except (MeshingError, AnalysisError, ResultProcessingError) as e:
        # Handle known analysis errors
        logger.error(f"Analysis workflow error: {str(e)}")
        result["errors"].append(
            {
                "code": e.code,
                "message": str(e),
                "ifc_guids": list(e.ifc_guids),
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
        raise StructuralAnalysisError(
            f"Analysis workflow failed: {str(e)}", code="E-GEN-001"
        ) from e


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
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"The model cannot be extracted from the IFC file: "
            f"{type(e).__name__}: {e}",
            code="E-IFC-005",
        ) from e


def create_analysis_config(
    analysis_type: str,
    gravity: bool = False,
    strict_connections: bool = False,
    open_sections: str = "equivalent",
    num_modes: int = 10,
) -> AnalysisConfig:
    """
    Create an analysis configuration for the specified analysis type.

    Args:
        analysis_type (str): Type of analysis to perform.
        gravity (bool): Whether to include self-weight gravity loads.
        strict_connections (bool): Analyse only the connections in the file.
        open_sections (str): "equivalent" or "user_element".
        num_modes (int): How many modes a modal analysis finds.

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

    config = AnalysisConfig()
    config.set_analysis_type(analysis_type)
    config.set_gravity(gravity)
    config.set_strict_connections(strict_connections)
    config.set_open_sections(open_sections)
    if analysis_type == "modal":
        config.set_num_modes(num_modes)
    config.validate()
    return config


def create_meshing_config(mesh_size: float, element_order: int = 2) -> MeshingConfig:
    """
    Create a meshing configuration with the specified mesh size.

    Args:
        mesh_size (float): Default mesh size.
        element_order (int): 2 for quadratic elements, 1 for linear ones.

    Returns:
        MeshingConfig: The meshing configuration.

    Raises:
        ValueError: If element_order is neither 1 nor 2.
    """
    config = MeshingConfig()
    config.set_default_mesh_size(mesh_size)
    config.set_element_order(element_order)
    config.validate()
    return config


def _first_ids(members, count: int = 5) -> str:
    """The ids of the first few members, and how many more there are."""
    ids = ", ".join(str(m.id) for m in members[:count])
    if len(members) > count:
        ids += f" (and {len(members) - count} more)"
    return ids


def _validate_model(domain_model, gravity: bool, modal: bool = False) -> list:
    """
    Validate the extracted structural model and return a list of warnings.

    Checks that members have materials/sections (an error if not), that
    boundary conditions exist,
    and that loads are present (warning when gravity is the only likely source
    but --gravity was not passed).

    Args:
        domain_model: The extracted StructuralModel.
        gravity: Whether gravity self-weight was requested.
        modal: Whether the analysis is modal, which applies no load.

    Returns:
        List of warning dicts (same format as result["warnings"]).

    Raises:
        ModelExtractionError: If a member has no material, or a curve member
            no section.
    """
    warnings = []

    def _warn(code, msg, members=()):
        warnings.append(
            warning(
                code, msg, ifc_guids=guids_of(domain_model, [m.id for m in members])
            )
        )

    # The extractor refuses these; a model built by hand may still lack them
    without_material = [
        m for m in domain_model.members if not getattr(m, "material", None)
    ]
    if without_material:
        raise ModelExtractionError(
            f"{len(without_material)} member(s) have no material, so they cannot "
            f"be analysed. The first are {_first_ids(without_material)}.",
            code="E-MAT-001",
            ifc_guids=[getattr(m, "ifc_guid", None) for m in without_material],
        )
    without_section = [
        m
        for m in domain_model.members
        if getattr(m, "entity_type", None) == "curve"
        and not getattr(m, "section", None)
    ]
    if without_section:
        raise ModelExtractionError(
            f"{len(without_section)} curve member(s) have no section, so they "
            f"cannot be analysed. The first are {_first_ids(without_section)}.",
            code="E-SEC-001",
            ifc_guids=[getattr(m, "ifc_guid", None) for m in without_section],
        )

    # Warn about section approximations that affect analysis fidelity
    for member in domain_model.members:
        section = getattr(member, "section", None)
        if not section:
            continue
        for approx in getattr(section, "approximations", []):
            ifc_guid = getattr(member, "ifc_guid", None)
            guid_part = f" (IFC {ifc_guid})" if ifc_guid else ""
            warnings.append(
                warning(
                    "W-SEC-004",
                    f"Member {member.id}{guid_part}: {approx}",
                    domain_id=member.id,
                    entity_type="StructuralMember",
                    ifc_guids=[ifc_guid or member.id],
                )
            )

    # Check that at least one boundary condition (support) exists
    if not domain_model.connections:
        _warn(
            "W-SUP-007",
            "No structural connections found — the model has no supports and CalculiX "
            "will produce a singular stiffness matrix.",
        )

    # Check that loads exist; warn when gravity is the likely missing ingredient
    load_groups = getattr(domain_model, "load_groups", [])
    has_explicit_loads = any(
        getattr(g, "loads", [])
        or getattr(g, "includes_self_weight", False) is True
        or isinstance(getattr(g, "support_displacements", None), list)
        and bool(g.support_displacements)
        or isinstance(getattr(g, "temperature_loads", None), list)
        and bool(g.temperature_loads)
        for g in load_groups
    )
    # A modal analysis applies no load
    if not has_explicit_loads and not gravity and not modal:
        _warn(
            "W-LOD-001",
            "No explicit loads found in the model and --gravity was not requested. "
            "The analysis will run with zero applied loads. "
            "If self-weight is the intended load, rerun with --gravity.",
        )

    return warnings


def _loads_are_not_mass(domain_model, gravity: bool) -> List[Dict[str, Any]]:
    """The warning that a modal analysis leaves the loads of the file out.

    The mass of a modal analysis is that of the members, from the density
    of their materials. A load may stand for mass (finishes, partitions, a
    share of the imposed load), but nothing in IFC says which, so none is
    counted.
    """
    loaded = [
        g.name for g in domain_model.load_groups if g.is_load_case and g.has_actions
    ]
    if gravity:
        loaded.append("Gravity (--gravity)")
    if not loaded:
        return []
    return [
        warning(
            "W-LOD-011",
            f"{len(loaded)} load case(s) are not part of the modal analysis: "
            + ", ".join(loaded[:3])
            + (" ..." if len(loaded) > 3 else "")
            + ". The mass is that of the members' materials alone.",
        )
    ]


def _run_record(ifc_path: str, solver_output: str, **settings) -> Dict[str, Any]:
    """How the results were made, for the ``run`` of ``results.json``.

    Args:
        ifc_path: The IFC file analysed.
        solver_output: What CalculiX printed, which names its version.
        **settings: The options of ``analyze_ifc()`` that change the results.
    """
    sha256 = hashlib.sha256()
    with open(ifc_path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            sha256.update(block)
    found = re.search(r"CalculiX Version (\d[^,\s]*)", solver_output)
    return {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library": {"name": "ifc_structural_mechanics", "version": __version__},
        "solver": {"name": "CalculiX", "version": found.group(1) if found else None},
        "input_file": {
            "name": os.path.basename(ifc_path),
            "sha256": sha256.hexdigest(),
        },
        "settings": settings,
    }


def _with_run_record(
    data: Dict[str, Any], run: Dict[str, Any], warnings: list
) -> Dict[str, Any]:
    """The results with ``run`` after ``model`` and every warning at the end."""
    ordered: Dict[str, Any] = {}
    for key, value in data.items():
        ordered[key] = value
        if key == "model":
            ordered["run"] = run
    ordered.setdefault("run", run)
    ordered["warnings"] = [dict(w) for w in warnings]
    return ordered


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
