"""
CalculiX runner module for the IFC structural analysis extension.

This module provides functionality to run CalculiX analyses, monitor the execution,
handle errors, and collect result files.
"""

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.analysis_config import AnalysisConfig
from ..config.system_config import SystemConfig
from ..utils.error_handling import AnalysisError
from ..utils.subprocess_utils import run_subprocess
from ..utils.temp_dir import create_temp_subdir
from .output_parser import OutputParser

# Set up logger
logger = logging.getLogger(__name__)


class CalculixRunner:
    """
    Manages the execution of CalculiX analysis.

    This class handles running CalculiX as a subprocess, monitoring its execution,
    handling errors, and collecting result files.
    """

    def __init__(
        self,
        input_file_path: str,
        system_config: Optional[SystemConfig] = None,
        analysis_config: Optional[AnalysisConfig] = None,
        working_dir: Optional[str] = None,
    ):
        """
        Initialize the CalculiX runner.

        Args:
            input_file_path (str): Path to the CalculiX input file (.inp).
            system_config (Optional[SystemConfig]): System configuration.
                If not provided, a default one will be created.
            analysis_config (Optional[AnalysisConfig]): Analysis configuration.
                If not provided, a default one will be created.
            working_dir (Optional[str]): Working directory for the analysis.
                If not provided, a temporary directory will be used.

        Raises:
            AnalysisError: If the input file does not exist or other initialization errors.
        """
        # Validate input file
        self.input_file_path = Path(input_file_path)
        if not self.input_file_path.exists():
            raise AnalysisError(f"Input file not found: {input_file_path}")

        # Initialize configurations
        self.system_config = system_config or SystemConfig()
        self.analysis_config = analysis_config or AnalysisConfig()

        # Set up working directory - use shared temp directory system
        if working_dir:
            # Use provided working directory
            self.working_dir = Path(working_dir)
            os.makedirs(self.working_dir, exist_ok=True)
        else:
            # Create a subdirectory within the shared temp directory
            self.working_dir = Path(create_temp_subdir(prefix="calculix_analysis_"))

        # Get CalculiX executable path
        self.ccx_path = self.system_config.get_calculix_path()
        if not self.ccx_path:
            raise AnalysisError(
                "CalculiX executable (ccx) not found. "
                "Please install CalculiX or specify the path in the system configuration."
            )

        # Initialize result file paths
        self.result_files = {}
        self.base_name = self.input_file_path.stem
        self._process_result = None

    @property
    def solver_output(self) -> str:
        """What CalculiX printed during the last run; empty before one."""
        if self._process_result is None:
            return ""
        return self._process_result.stdout or ""

    def run_analysis(self, timeout: Optional[int] = None) -> Dict[str, str]:
        """
        Run the CalculiX analysis.

        The input file is run as it was written: it is never edited, swapped
        for another file or run a second time.

        Args:
            timeout (Optional[int]): Timeout in seconds for the analysis.
                Default is None (no timeout).

        Returns:
            Dict[str, str]: Dictionary of result file paths by type.

        Raises:
            AnalysisError: If the analysis fails.
        """
        logger.info(f"Running CalculiX analysis for {self.input_file_path}")

        os.makedirs(self.working_dir, exist_ok=True)
        target_path = self.working_dir / self.input_file_path.name
        # Always this run's input: a file of the same name left by an earlier
        # run must not be solved in its place
        if target_path.resolve() != self.input_file_path.resolve():
            try:
                shutil.copy2(self.input_file_path, target_path)
            except OSError as e:
                raise AnalysisError(
                    f"Failed to copy input file to working directory: {e}"
                ) from e

        if not target_path.exists():
            raise AnalysisError(f"Input file not found: {target_path}")

        command = self._prepare_command()

        try:
            self._process_result = run_subprocess(
                command, timeout=timeout, cwd=str(self.working_dir)
            )
        except AnalysisError:
            self.result_files = self._collect_result_files()
            raise
        except Exception as e:
            self.result_files = self._collect_result_files()
            raise AnalysisError(f"CalculiX analysis failed: {str(e)}") from e

        # Whatever was written is kept for inspection, failed run or not
        self.result_files = self._collect_result_files()

        if not self._process_result.success:
            errors = self._handle_output(
                self._process_result.stdout, self._process_result.stderr
            )
            error_output = self._process_result.stdout + self._process_result.stderr
            self._raise_if_known_gen3delem_user_element_bug(error_output, target_path)
            self._raise_if_singular_system(error_output, target_path)
            raise AnalysisError(
                f"CalculiX analysis failed with return code {self._process_result.return_code}",
                error_details=errors,
            )

        # Check for convergence issues using the shared OutputParser logic
        converged, reason = OutputParser().check_convergence(
            self._process_result.stdout
        )
        if not converged:
            raise AnalysisError(f"CalculiX analysis did not converge: {reason}")

        logger.info("CalculiX analysis completed successfully")
        return self.result_files

    @staticmethod
    def _raise_if_singular_system(error_output: str, input_file_path: Path) -> None:
        """Diagnose a solver abort during factorisation, which CalculiX leaves silent.

        When the stiffness matrix is singular the SPOOLES factorisation aborts
        the process: the last thing CalculiX prints is "Factoring the system of
        equations", with no ``*ERROR`` line and no "Job finished". Without this
        check the user only sees a bare return code.

        Raises AnalysisError naming the likely cause. If the model mixes U1 and
        B31 beams the message says so, because CalculiX does not transfer
        rotation between them at a shared node (ifc_structural_mechanics-aiz.14).
        """
        if "Factoring the system of equations" not in error_output:
            return
        if "*ERROR" in error_output or "Job finished" in error_output:
            return
        message = (
            "CalculiX stopped while factorising the stiffness matrix and "
            "reported no error, which normally means the matrix is singular: "
            "the structure, or part of it, is a mechanism. Check that the "
            "supports restrain every rigid-body motion (including a member "
            "spinning about its own axis), that members meant to be connected "
            "share a connection, and that end releases do not leave a member "
            "free to rotate."
        )
        try:
            inp_text = input_file_path.read_text()
        except OSError:
            inp_text = ""
        element_types = set(
            re.findall(r"(?im)^\*ELEMENT\s*,.*?TYPE\s*=\s*(\w+)", inp_text)
        )
        if "U1" in element_types and element_types & {"B31", "B32", "B32R"}:
            message += (
                " This model mixes U1 beams (I/T/L/C sections) with native "
                "beams; CalculiX transfers no moment between the two at a "
                "shared node, so those joints act as pins and can turn a "
                "frame into a mechanism."
            )
        raise AnalysisError(message)

    @staticmethod
    def _raise_if_known_gen3delem_user_element_bug(
        error_output: str, input_file_path: Path
    ) -> None:
        """Detect a known CalculiX 2.23 crash and fail with an actionable message.

        CalculiX's gen3delem.f never assigns a node count for *USER ELEMENT
        (TYPE=U1) entries — its lakon-prefix filter excludes C3D/D/G/E/MASS
        types but not 'U'. Whenever a model mixes a U1 element with *any*
        other 1D/2D element (B31, S3, ...), the loop reuses whatever node
        count a previously-processed element left behind, then reads the
        (deliberately unset) SECTION=GENERAL thickness for the U1 element and
        aborts with "gen3delem: first thickness ... is zero". This has been
        confirmed by patching and rebuilding CalculiX 2.23 (still present
        upstream as of 2026-07) — it is not something this project's .inp
        writer can work around, since the crash is independent of element
        ID ordering. See patches/calculix-gen3delem-user-element.patch.

        Raises AnalysisError instead of letting the generic, misleading CCX
        message reach the user when this specific combination is detected.
        """
        if "gen3delem" not in error_output or "thickness" not in error_output:
            return
        try:
            inp_text = input_file_path.read_text()
        except OSError:
            return
        element_types = set(
            re.findall(r"(?im)^\*ELEMENT\s*,.*?TYPE\s*=\s*(\w+)", inp_text)
        )
        if "U1" in element_types and len(element_types) > 1:
            raise AnalysisError(
                "CalculiX crashed in gen3delem with 'first thickness ... is "
                "zero'. This model mixes U1 (user-element) beams with other "
                f"element types ({sorted(element_types)}); CalculiX 2.23 has "
                "a confirmed bug where its gen3delem.f never recognises "
                "TYPE=U1 elements, causing it to misread an unrelated, "
                "always-unset thickness value whenever a U1 element "
                "coexists with any other 1D/2D element in the same model. "
                "This cannot be fixed by reordering or rewriting the .inp "
                "file. Apply patches/calculix-gen3delem-user-element.patch "
                "to your CalculiX source and rebuild, or avoid sections "
                "that require a U1 element (I/T/L/C profiles, or members "
                "affected by overlapping-geometry retyping) in models that "
                "also contain native B31/S3 elements."
            )

    def _prepare_command(self) -> List[str]:
        """
        Prepare the CalculiX command.

        Returns:
            List[str]: Command list ready for subprocess execution.
        """
        command = [self.ccx_path, "-i", self.base_name]
        logger.info(f"CalculiX command: {' '.join(command)}")
        return command

    def _handle_output(self, stdout: str, stderr: str) -> List[Dict[str, Any]]:
        """
        Collect the error lines of CalculiX's output.

        Args:
            stdout (str): Standard output from CalculiX.
            stderr (str): Standard error output from CalculiX.

        Returns:
            List[Dict[str, Any]]: One ``{"message": ...}`` per error line.
        """
        error_patterns = [
            r"(?i)error.*",
            r"(?i)fatal error.*",
            r"(?i)exceeded.*",
            r"(?i)failed to converge.*",
            r"(?i)zero pivot.*",
        ]

        combined_output = stdout + "\n" + stderr
        error_details = []
        for pattern in error_patterns:
            for match in re.findall(pattern, combined_output, re.MULTILINE):
                error_details.append({"message": match.strip()})

        if error_details:
            logger.error(
                "CalculiX errors found: "
                + "\n".join(detail["message"] for detail in error_details)
            )
        elif stderr:
            logger.warning(f"CalculiX stderr output: {stderr}")
            error_details.append({"message": stderr})

        return error_details

    def _collect_result_files(self) -> Dict[str, str]:
        """
        Collect and categorize result files from the analysis.

        Only the files of this run are taken (those named after the input
        file); another analysis may have left its own in the directory.

        Returns:
            Dict[str, str]: Dictionary of result file paths by type.
        """
        file_extensions = {
            "frd": "results",  # Main results file
            "dat": "data",  # General data
            "cvg": "convergence",  # Convergence data
            "sta": "status",  # Status file
            "msg": "message",  # Message file
        }

        result_files = {}
        for ext, file_type in file_extensions.items():
            file_path = self.working_dir / f"{self.base_name}.{ext}"
            if file_path.exists():
                result_files[file_type] = str(file_path)

        logger.info(f"Collected CalculiX result files: {list(result_files.keys())}")
        return result_files
