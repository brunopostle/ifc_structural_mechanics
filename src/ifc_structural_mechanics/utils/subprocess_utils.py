"""
Subprocess utility functions for the IFC structural analysis extension.

This module provides robust functions for managing subprocesses,
capturing their output, and handling errors.
"""

import os
import re
import subprocess
import logging
from typing import Dict, List, Optional, Tuple

from .error_handling import StructuralAnalysisError

# Set up logger
logger = logging.getLogger(__name__)


class SubprocessResult:
    """
    Container for subprocess execution results.

    This class stores the outputs and return code from a subprocess execution,
    providing easy access to the results.
    """

    def __init__(self, return_code: int, stdout: str, stderr: str, command: List[str]):
        """
        Initialize a SubprocessResult.

        Args:
            return_code (int): The subprocess return code.
            stdout (str): The standard output from the subprocess.
            stderr (str): The standard error output from the subprocess.
            command (List[str]): The command that was executed.
        """
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.command = command

    @property
    def success(self) -> bool:
        """
        Check if the subprocess executed successfully.

        Returns:
            bool: True if the return code is 0, False otherwise.
        """
        return self.return_code == 0


def run_subprocess(
    command: List[str],
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> SubprocessResult:
    """
    Run a subprocess with robust error handling.

    This function executes a subprocess, captures its output,
    and handles timeouts and errors.

    Args:
        command (List[str]): The command to execute.
        timeout (Optional[int]): Timeout in seconds for the subprocess execution.
        cwd (Optional[str]): Working directory for the subprocess.
        env (Optional[Dict[str, str]]): Environment variables for the subprocess.

    Returns:
        SubprocessResult: The result of the subprocess execution.

    Raises:
        StructuralAnalysisError: If the subprocess cannot be run.
        TimeoutError: If the subprocess times out.
    """
    logger.debug(f"Running command: {' '.join(command)}")

    # Create environment with current environment plus any additions
    subprocess_env = os.environ.copy()
    if env:
        subprocess_env.update(env)

    try:
        # Start the subprocess
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=subprocess_env,
        )

        # Wait for process to complete with timeout
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return_code = process.returncode
        except subprocess.TimeoutExpired:
            # Timeout occurred, terminate process
            terminate_gracefully(process)
            raise TimeoutError(f"Subprocess timed out after {timeout} seconds")

        # Log output
        logger.debug(f"Subprocess return code: {return_code}")
        if stdout:
            logger.debug(f"Subprocess stdout: {stdout[:1000]}")
        if stderr:
            logger.debug(f"Subprocess stderr: {stderr[:1000]}")

        return SubprocessResult(return_code, stdout, stderr, command)

    except FileNotFoundError:
        # Executable not found
        raise StructuralAnalysisError(f"Executable not found: {command[0]}")
    except PermissionError:
        # No permission to execute
        raise StructuralAnalysisError(f"No permission to execute: {command[0]}")
    except Exception as e:
        # Other errors
        raise StructuralAnalysisError(f"Error running subprocess: {str(e)}")


def capture_output(process: subprocess.Popen) -> Tuple[str, str]:
    """
    Capture and parse subprocess output.

    Args:
        process (subprocess.Popen): The subprocess to capture output from.

    Returns:
        Tuple[str, str]: The stdout and stderr output from the subprocess.
    """
    stdout, stderr = process.communicate()

    # Convert bytes to string if needed
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")

    return stdout, stderr


def terminate_gracefully(process: subprocess.Popen, timeout: int = 5) -> None:
    """
    Terminate a subprocess gracefully.

    First tries SIGTERM, then SIGKILL if the process doesn't terminate.

    Args:
        process (subprocess.Popen): The subprocess to terminate.
        timeout (int): Timeout in seconds to wait for graceful termination.
    """

    logger.debug(f"Terminating process {process.pid}")

    # Try graceful termination
    process.terminate()

    # Wait for process to terminate
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Process didn't terminate gracefully, force kill
        logger.debug(
            f"Process {process.pid} did not terminate gracefully, sending SIGKILL"
        )
        process.kill()
        process.wait()


def check_executable(executable: str) -> bool:
    """
    Check if an executable exists and is accessible.

    Args:
        executable (str): The executable to check.

    Returns:
        bool: True if the executable exists and is accessible, False otherwise.
    """
    # If executable is a full path, check directly
    if os.path.isabs(executable):
        return os.path.isfile(executable) and os.access(executable, os.X_OK)

    # Check if executable is in PATH
    for path in os.environ["PATH"].split(os.pathsep):
        exe_path = os.path.join(path, executable)
        if os.path.isfile(exe_path) and os.access(exe_path, os.X_OK):
            return True

    return False


def parse_error_output(output: str) -> List[str]:
    """
    Parse error messages from subprocess output.

    Args:
        output (str): The output to parse.

    Returns:
        List[str]: A list of error messages found in the output.
    """
    error_messages = []

    # Look for common error patterns
    error_patterns = [
        r"[Ee]rror:.*",
        r"[Ff]atal:.*",
        r"[Cc]ritical:.*",
        r"Exception:.*",
        r".*failed.*",
    ]

    # Extract error messages
    for pattern in error_patterns:
        matches = re.findall(pattern, output)
        error_messages.extend(matches)

    return error_messages
