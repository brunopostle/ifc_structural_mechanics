"""
Utility functions for the IFC structural analysis extension.

This module provides common utility functions and classes used throughout
the structural analysis extension.
"""

from .error_handling import (
    AnalysisError,
    MeshingError,
    ModelExtractionError,
    ResultProcessingError,
    StructuralAnalysisError,
)
from .subprocess_utils import (
    check_executable,
    run_subprocess,
    terminate_gracefully,
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
    "terminate_gracefully",
    "check_executable",
]
