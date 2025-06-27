"""
File utility functions for the IFC structural analysis extension.

This module provides utility functions for file operations,
such as creating directories, safely writing files, and working with files.
"""

from pathlib import Path
from typing import Union


def ensure_directory(path: Union[str, Path]) -> Path:
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        path (Union[str, Path]): The directory path to ensure exists.

    Returns:
        Path: The path to the directory.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
