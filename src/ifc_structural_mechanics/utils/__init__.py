"""
Utility functions for the IFC structural analysis extension.

This module provides common utility functions and classes used throughout
the structural analysis extension.
"""

from .error_handling import (
    StructuralAnalysisError,
    ModelExtractionError,
    MeshingError,
    AnalysisError,
    ResultProcessingError,
)
from .subprocess_utils import (
    run_subprocess,
    capture_output,
    terminate_gracefully,
    check_executable,
    parse_error_output,
)

__all__ = [
    # Error handling
    "StructuralAnalysisError",
    "ModelExtractionError",
    "MeshingError",
    "AnalysisError",
    "ResultProcessingError",
    # Subprocess utilities
    "run_subprocess",
    "capture_output",
    "terminate_gracefully",
    "check_executable",
    "parse_error_output",
]
