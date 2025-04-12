"""
File utility functions for the IFC structural analysis extension.

This module provides utility functions for file operations,
such as creating directories, safely writing files, and working with files.
"""

import os
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Optional, Union, TextIO, BinaryIO


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


def safe_write(path: Union[str, Path], content: str, mode: str = "w") -> None:
    """
    Safely write content to a file.

    This function writes to a temporary file and then renames it,
    ensuring atomicity and preventing incomplete writes.

    Args:
        path (Union[str, Path]): The path to write to.
        content (str): The content to write.
        mode (str): The file mode to use ('w' for text, 'wb' for binary).
    """
    from ..utils import temp_dir

    path = Path(path)

    # Ensure the directory exists
    ensure_directory(path.parent)

    # Create a temporary file in the same directory
    temp_path = temp_dir.create_temp_file(suffix=".tmp")
    try:
        # Write content to the temporary file
        with open(temp_path, mode) as f:
            f.write(content)

        # Rename the temporary file to the target file
        os.replace(temp_path, path)
    except Exception:
        # Clean up the temporary file if an error occurs
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def clean_directory(path: Union[str, Path], patterns: Optional[list] = None) -> None:
    """
    Clean a directory of files matching the given patterns.

    Args:
        path (Union[str, Path]): The directory to clean.
        patterns (Optional[list]): List of file patterns to remove.
            If None, no files will be removed.
    """
    path = Path(path)
    if not path.exists() or not path.is_dir():
        return

    if patterns:
        for pattern in patterns:
            for file_path in path.glob(pattern):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                    except OSError:
                        pass


def get_file_extension(path: Union[str, Path]) -> str:
    """
    Get the file extension from a path.

    Args:
        path (Union[str, Path]): The path to get the extension from.

    Returns:
        str: The file extension (without the dot).
    """
    return os.path.splitext(str(path))[1][1:]


@contextmanager
def open_file(
    path: Union[str, Path], mode: str = "r"
) -> Generator[Union[TextIO, BinaryIO], None, None]:
    """
    Open a file with proper error handling.

    This context manager ensures the file is properly closed,
    and provides more informative error messages.

    Args:
        path (Union[str, Path]): The path to the file.
        mode (str): The mode to open the file with.

    Yields:
        Union[TextIO, BinaryIO]: The open file object.

    Raises:
        OSError: If the file cannot be opened.
    """
    path = Path(path)
    try:
        with open(path, mode) as f:
            yield f
    except OSError as e:
        # Provide more informative error message
        raise OSError(f"Failed to open file {path}: {str(e)}") from e
