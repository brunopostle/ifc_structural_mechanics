"""
Enhanced end-to-end test with improved error handling and debugging.
"""

import os
import pytest
import logging
from pathlib import Path

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc
from ifc_structural_mechanics.utils.temp_dir import (
    setup_temp_dir,
    cleanup_temp_dir,
    create_temp_subdir,
)

# Verbose logging and debugging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def print_file_contents(filepath):
    """Print contents of a file with error handling."""
    try:
        if os.path.exists(filepath):
            print(f"\n--- Contents of {filepath}: ---")
            try:
                # Try reading as text first
                with open(filepath, "r") as f:
                    print(f.read())
            except UnicodeDecodeError:
                # If that fails, try reading as binary
                with open(filepath, "rb") as f:
                    print(f"Binary file, first 100 bytes: {f.read(100)}")
        else:
            print(f"File not found: {filepath}")

            # Additional debugging - show directory listing
            parent_dir = os.path.dirname(filepath)
            if os.path.exists(parent_dir):
                print(f"Contents of directory {parent_dir}:")
                for item in os.listdir(parent_dir):
                    full_path = os.path.join(parent_dir, item)
                    file_type = "dir" if os.path.isdir(full_path) else "file"
                    size = (
                        os.path.getsize(full_path) if os.path.isfile(full_path) else "-"
                    )
                    print(f"  {item} ({file_type}, size: {size})")
            else:
                print(f"Parent directory {parent_dir} does not exist")
    except Exception as e:
        print(f"Error reading {filepath}: {e}")


class TestEndToEnd:
    """
    End-to-end test for IFC structural analysis workflow.
    """

    @classmethod
    def setup_class(cls):
        """
        Set up shared resources for all tests.
        """
        # Use the temp_dir utility to set up a base directory for the class
        cls.temp_base_dir = setup_temp_dir(
            prefix="end_to_end_simple_test_", keep_files=True
        )

    @classmethod
    def teardown_class(cls):
        """
        Clean up shared resources after all tests.
        """
        # Only force cleanup if the test failed
        cleanup_temp_dir(force=False)

    def test_end_to_end_successful(self):
        """
        End-to-end test that requires real Gmsh and CalculiX functionality.
        """
        # Import here to allow skipping if Gmsh is not available
        import os
        import shutil
        import datetime

        # Create a unique, persistent test directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        test_dir_name = f"ifc_test_{timestamp}"
        persistent_test_dir = Path(create_temp_subdir(prefix=test_dir_name))

        # Print the location for reference
        print(f"\nTest artifacts will be in: {persistent_test_dir}")

        # Initialize Gmsh explicitly to check if it's available
        import gmsh

        try:
            if not gmsh.isInitialized():
                gmsh.initialize()

            # Verify Gmsh is working by checking a simple operation
            gmsh.option.getNumber("General.Terminal")
        except Exception as e:
            pytest.skip(f"Gmsh initialization failed. This test requires Gmsh: {e}")

        # Check if CalculiX is available
        from ifc_structural_mechanics.config.system_config import SystemConfig

        system_config = SystemConfig()
        ccx_path = system_config.get_calculix_path()

        if not os.path.exists(ccx_path):
            pytest.skip(
                f"CalculiX executable not found at {ccx_path}. This test requires CalculiX."
            )

        # Use a real IFC file that exists in your test data directory
        ifc_path = os.path.join("tests", "test_data", "simple_beam.ifc")
        if not os.path.exists(ifc_path):
            pytest.skip(
                f"Test IFC file not found: {ifc_path}. This test requires a valid IFC file."
            )

        # Create a file to verify the directory is working
        with open(os.path.join(persistent_test_dir, "test_file.txt"), "w") as f:
            f.write("Test file to verify directory permissions")

        try:
            # Use explicit patching to ensure all temporary directories point to our persistent directory
            from unittest.mock import patch

            # Create a copy of the temp directory that won't be affected by auto-cleanup
            persistent_dir_str = str(persistent_test_dir)

            # Multiple patches to ensure directory is preserved
            patches = [
                # Patch tempfile.mkdtemp
                patch("tempfile.mkdtemp", return_value=persistent_dir_str),
                # Patch SystemConfig.get_temp_directory
                patch(
                    "ifc_structural_mechanics.config.system_config.SystemConfig.get_temp_directory",
                    return_value=persistent_dir_str,
                ),
                # Patch any potential cleanup methods
                patch(
                    "shutil.rmtree",
                    side_effect=lambda path, *args, **kwargs: (
                        None
                        if str(path).startswith(persistent_dir_str)
                        else shutil._orig_rmtree(path, *args, **kwargs)
                    ),
                ),
                # Disable os.remove for our directory
                patch(
                    "os.remove",
                    side_effect=lambda path: (
                        None
                        if str(path).startswith(persistent_dir_str)
                        else os._orig_remove(path)
                    ),
                ),
            ]

            # Apply all patches
            for p in patches:
                p.start()

            try:
                # Execute the analysis
                result = analyze_ifc(
                    ifc_path=ifc_path,
                    output_dir=persistent_dir_str,
                    analysis_type="linear_static",
                    mesh_size=0.1,
                    verbose=True,
                )

                # Check the result
                assert result["status"] == "success"
                assert "output_files" in result

                # Print file paths from the result
                print("\nResult output files:")
                for file_type, file_path in result["output_files"].items():
                    print(f"  {file_type}: {file_path}")
                    exists = os.path.exists(file_path)
                    print(f"    Exists: {exists}")
                    if exists:
                        print(f"    Size: {os.path.getsize(file_path)} bytes")

                # Make explicit copies of important files to ensure they're preserved
                for filename in ["mesh.msh", "model.inp", "analysis.inp"]:
                    src = os.path.join(persistent_dir_str, filename)
                    if os.path.exists(src):
                        # Make a copy with a .preserved extension
                        dst = os.path.join(persistent_dir_str, f"{filename}.preserved")
                        shutil.copy2(src, dst)
                        print(f"Created preserved copy: {dst}")
                    else:
                        print(f"Warning: Could not find {src} to preserve")

                # Create a marker file to indicate test completed
                with open(
                    os.path.join(persistent_dir_str, "TEST_COMPLETED.txt"), "w"
                ) as f:
                    f.write(f"Test completed at {datetime.datetime.now()}\n")
                    f.write(f"Result status: {result['status']}\n")

            finally:
                # Stop all patches
                for p in patches:
                    p.stop()

        except Exception as e:
            # Create a error marker file
            with open(os.path.join(persistent_test_dir, "TEST_FAILED.txt"), "w") as f:
                f.write(f"Test failed at {datetime.datetime.now()}\n")
                f.write(f"Error: {type(e).__name__}: {e}\n")

            # Re-raise the exception
            raise

        finally:
            # Print final location reminder
            print(f"\nTest artifacts preserved at: {persistent_test_dir}")

            # Finalize Gmsh after test
            if gmsh.isInitialized():
                try:
                    gmsh.finalize()
                except Exception as e:
                    print(f"Warning: Error finalizing Gmsh: {e}")
