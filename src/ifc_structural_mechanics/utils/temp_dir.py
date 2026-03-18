"""
Shared temporary directory management for IFC Structural Analysis.

This module provides functions to create, get, and clean up a shared temporary directory
that can be used consistently across different components of the library.
"""

import atexit
import logging
import os
import shutil
import tempfile
from typing import Optional

# Set up logger
logger = logging.getLogger(__name__)

# Global variable to hold the shared temporary directory path
_SHARED_TEMP_DIR: Optional[str] = None
_KEEP_TEMP_FILES: bool = False


def setup_temp_dir(
    base_dir: Optional[str] = None,
    prefix: str = "ifc_structural_mechanics_",
    keep_files: bool = False,
) -> str:
    """
    Set up a shared temporary directory for the library.

    This function creates a temporary directory that will be used by different parts
    of the library. If a directory is already set up, it returns the existing one.

    Args:
        base_dir (Optional[str]): Base directory where the temporary directory should be created.
            If None, the system's default temporary directory will be used.
        prefix (str): Prefix for the temporary directory name.
        keep_files (bool): If True, temporary files won't be deleted when the program exits.
            This is useful for debugging purposes.

    Returns:
        str: Path to the shared temporary directory.
    """
    global _SHARED_TEMP_DIR, _KEEP_TEMP_FILES

    # If we already have a temp dir and it exists, just return it
    if _SHARED_TEMP_DIR is not None and os.path.exists(_SHARED_TEMP_DIR):
        return _SHARED_TEMP_DIR

    # Set the keep_files flag
    _KEEP_TEMP_FILES = keep_files

    # Create a new temporary directory
    if base_dir:
        # Make sure the base directory exists
        os.makedirs(base_dir, exist_ok=True)
        _SHARED_TEMP_DIR = tempfile.mkdtemp(prefix=prefix, dir=base_dir)
    else:
        _SHARED_TEMP_DIR = tempfile.mkdtemp(prefix=prefix)

    # Register cleanup function if not keeping files
    if not keep_files:
        atexit.register(_cleanup_temp_dir)

    logger.info(f"Set up shared temporary directory: {_SHARED_TEMP_DIR}")
    return _SHARED_TEMP_DIR


def get_temp_dir() -> str:
    """
    Get the path to the shared temporary directory.

    If no shared temporary directory has been set up yet, this function will set one up.

    Returns:
        str: Path to the shared temporary directory.
    """
    if _SHARED_TEMP_DIR is None or not os.path.exists(_SHARED_TEMP_DIR):
        return setup_temp_dir()
    return _SHARED_TEMP_DIR


def create_temp_file(
    suffix: str = None, prefix: str = None, content: str = None
) -> str:
    """
    Create a temporary file in the shared temporary directory.

    Args:
        suffix (str, optional): File suffix (extension).
        prefix (str, optional): File prefix.
        content (str, optional): Content to write to the file.

    Returns:
        str: Path to the created temporary file.
    """
    temp_dir = get_temp_dir()
    fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=temp_dir)

    try:
        if content is not None:
            with os.fdopen(fd, "w") as f:
                f.write(content)
        else:
            os.close(fd)
    except Exception:
        os.close(fd)
        raise

    return temp_path


def create_temp_subdir(prefix: str = "subdir_") -> str:
    """
    Create a subdirectory within the shared temporary directory.

    Args:
        prefix (str, optional): Prefix for the subdirectory name.

    Returns:
        str: Path to the created subdirectory.
    """
    temp_dir = get_temp_dir()
    subdir = tempfile.mkdtemp(prefix=prefix, dir=temp_dir)
    return subdir


def cleanup_temp_dir(force: bool = False) -> None:
    """
    Clean up the shared temporary directory.

    Args:
        force (bool): If True, the directory will be removed even if keep_files is True.
    """
    global _SHARED_TEMP_DIR

    if _SHARED_TEMP_DIR is not None and os.path.exists(_SHARED_TEMP_DIR):
        # Don't delete if we're keeping files, unless forced
        if _KEEP_TEMP_FILES and not force:
            logger.info(f"Keeping shared temporary directory: {_SHARED_TEMP_DIR}")
            return

        try:
            shutil.rmtree(_SHARED_TEMP_DIR)
            logger.info(f"Removed shared temporary directory: {_SHARED_TEMP_DIR}")
        except Exception as e:
            logger.warning(
                f"Failed to remove temporary directory {_SHARED_TEMP_DIR}: {e}"
            )

        _SHARED_TEMP_DIR = None


def _cleanup_temp_dir() -> None:
    """Internal cleanup function registered with atexit."""
    cleanup_temp_dir()


def set_keep_temp_files(keep_files: bool) -> None:
    """
    Set whether to keep temporary files after program exit.

    Args:
        keep_files (bool): If True, temporary files won't be deleted.
    """
    global _KEEP_TEMP_FILES

    # If we're switching from keep=False to keep=True, unregister cleanup
    if keep_files:
        try:
            atexit.unregister(_cleanup_temp_dir)
        except Exception:
            # It's okay if the function wasn't registered
            pass

    # If we're switching from keep=True to keep=False, register cleanup
    elif not keep_files:
        atexit.register(_cleanup_temp_dir)

    _KEEP_TEMP_FILES = keep_files
