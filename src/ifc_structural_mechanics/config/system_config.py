import logging
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

from ..utils import temp_dir
from .base_config import BaseConfig


class SystemConfig(BaseConfig):
    """
    System-level configuration management for IFC Structural Analysis.

    Handles system-wide settings including executable paths,
    temporary directories, and logging configuration.
    """

    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get the default configuration dictionary.

        Returns:
            Dict[str, Any]: Default configuration dictionary.
        """
        return {
            "executables": {
                "calculix": self._find_executable("ccx"),
                "gmsh": self._find_executable("gmsh"),
            },
            "temp_directory": temp_dir.get_temp_dir(),  # Use the shared temp directory
            "logging": {
                "level": logging.INFO,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "file": None,  # No file logging by default
            },
        }

    def _find_executable(self, executable_name: str) -> Optional[str]:
        """
        Find the full path of an executable.

        Args:
            executable_name (str): Name of the executable to find.

        Returns:
            Optional[str]: Full path to the executable, or None if not found.
        """
        return shutil.which(executable_name)

    def validate(self) -> None:
        """
        Validate the system configuration.

        Raises:
            ValueError: If any configuration parameter is invalid.
        """
        # Validate executables
        for exe_name, exe_path in self._config["executables"].items():
            if exe_path:
                # Check if the path exists and is a file
                # Or if the executable exists in PATH
                if not (
                    os.path.isfile(exe_path) or shutil.which(os.path.basename(exe_path))
                ):
                    # Only raise an error if the executable cannot be found at all
                    try:
                        subprocess.run(
                            [exe_path, "--version"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=True,
                        )
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        # If the executable cannot be run, try finding it in standard locations
                        standard_paths = [
                            f"/usr/bin/{exe_name}",
                            f"/usr/local/bin/{exe_name}",
                            f"/opt/bin/{exe_name}",
                        ]
                        found = False
                        for path in standard_paths:
                            if os.path.isfile(path):
                                self._config["executables"][exe_name] = path
                                found = True
                                break

                        if not found:
                            # Last resort: check PATH
                            path_executable = shutil.which(exe_name)
                            if path_executable:
                                self._config["executables"][exe_name] = path_executable
                                found = True

                        if not found:
                            raise ValueError(
                                f"{exe_name.capitalize()} executable not found: {exe_path}"
                            )

        # Validate temp directory - use the shared temp_dir module
        temp_directory = self._config["temp_directory"]
        if (
            not temp_directory
            or not os.path.exists(temp_directory)
            or not os.access(temp_directory, os.W_OK)
        ):
            # If temp directory doesn't exist or isn't writable, fall back to the shared temp dir
            self._config["temp_directory"] = temp_dir.get_temp_dir()

        # Validate logging configuration
        log_config = self._config["logging"]

        # Validate logging level - but don't convert string levels to integers in the config
        # Instead, just check if they're valid
        log_level = log_config["level"]
        if isinstance(log_level, str):
            # Ensure valid string representation of logging level
            valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if log_level.upper() not in valid_levels:
                log_config["level"] = logging.INFO  # Default to INFO if invalid
        elif isinstance(log_level, int):
            # Ensure level is a valid logging level integer
            if log_level not in [
                logging.DEBUG,
                logging.INFO,
                logging.WARNING,
                logging.ERROR,
                logging.CRITICAL,
            ]:
                log_config["level"] = logging.INFO  # Default to INFO if invalid

    def get_executable_path(self, executable: str) -> Optional[str]:
        """
        Get the path for a specific executable.

        Args:
            executable (str): Name of the executable (e.g., 'calculix', 'gmsh').

        Returns:
            Optional[str]: Path to the executable, or None if not found.
        """
        return self._config["executables"].get(executable)

    def get_gmsh_path(self) -> Optional[str]:
        """
        Get the path to the Gmsh executable.

        Returns:
            Optional[str]: Path to the Gmsh executable, or None if not found.
        """
        return self.get_executable_path("gmsh")

    def get_calculix_path(self) -> Optional[str]:
        """
        Get the path to the Calculix executable.

        Returns:
            Optional[str]: Path to the Calculix executable, or None if not found.
        """
        return self.get_executable_path("calculix")

    def get_temp_directory(self) -> str:
        """
        Get the configured temporary directory.

        Returns:
            str: Path to the temporary directory.
        """
        return self._config["temp_directory"]

    def configure_logging(self) -> logging.Logger:
        """
        Configure logging based on the system configuration.

        Returns:
            logging.Logger: Configured logger.
        """
        log_config = self._config["logging"]
        log_level = log_config["level"]

        # Convert string representation to logging level for actual logger configuration
        # but keep the original value in the config
        if isinstance(log_level, str):
            level_map = {
                "DEBUG": logging.DEBUG,
                "INFO": logging.INFO,
                "WARNING": logging.WARNING,
                "ERROR": logging.ERROR,
                "CRITICAL": logging.CRITICAL,
            }
            actual_level = level_map.get(log_level.upper(), logging.INFO)
        else:
            actual_level = log_level

        # Create logger
        logger = logging.getLogger("ifc_structural_mechanics")
        logger.setLevel(actual_level)

        # Clear any existing handlers
        logger.handlers.clear()

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(actual_level)
        console_formatter = logging.Formatter(log_config["format"])
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # File handler (if configured)
        if log_config["file"]:
            file_handler = logging.FileHandler(log_config["file"])
            file_handler.setLevel(actual_level)
            file_handler.setFormatter(console_formatter)
            logger.addHandler(file_handler)

        return logger
