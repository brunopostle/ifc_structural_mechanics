"""
Test module for shared temporary directory management.

This module demonstrates how to use the shared temporary directory management
in tests, ensuring that temporary files are managed consistently.
"""

import os
import shutil
import tempfile
import unittest

from ifc_structural_mechanics.utils.temp_dir import (
    setup_temp_dir,
    get_temp_dir,
    cleanup_temp_dir,
    set_keep_temp_files,
    create_temp_file,
    create_temp_subdir,
)


class TestTempDirManagement(unittest.TestCase):
    """Test case for temporary directory management."""

    @classmethod
    def setUpClass(cls):
        """Set up shared resources for all tests in this class."""
        # Create a custom base directory for tests
        cls.test_base_dir = tempfile.mkdtemp(prefix="ifc_test_")

        # Set up the shared temporary directory with the custom base
        # This ensures all tests use the same temp directory
        cls.temp_dir = setup_temp_dir(
            base_dir=cls.test_base_dir,
            prefix="test_temp_",
            keep_files=False,  # Set to True during development for debugging
        )

        # Verify the temp directory was created
        assert os.path.exists(cls.temp_dir), "Temp directory not created"

    @classmethod
    def tearDownClass(cls):
        """Clean up shared resources after all tests are done."""
        # Clean up the temporary directory
        cleanup_temp_dir(force=True)

        # Remove the test base directory
        if os.path.exists(cls.test_base_dir):
            shutil.rmtree(cls.test_base_dir)

    def test_get_temp_dir(self):
        """Test that get_temp_dir returns the correct directory."""
        temp_dir = get_temp_dir()
        self.assertEqual(temp_dir, self.__class__.temp_dir)
        self.assertTrue(os.path.exists(temp_dir))

    def test_create_temp_file(self):
        """Test creating a temporary file within the shared directory."""
        # Create a temp file with content
        content = "Test content"
        temp_file = create_temp_file(suffix=".txt", prefix="test_", content=content)

        # Verify the file exists and has the correct content
        self.assertTrue(os.path.exists(temp_file))
        self.assertTrue(os.path.isfile(temp_file))

        with open(temp_file, "r") as f:
            self.assertEqual(f.read(), content)

        # Verify the file is within our shared temp directory
        self.assertTrue(temp_file.startswith(get_temp_dir()))

    def test_create_temp_subdir(self):
        """Test creating a subdirectory within the shared directory."""
        # Create a temp subdirectory
        subdir = create_temp_subdir(prefix="test_subdir_")

        # Verify the subdirectory exists
        self.assertTrue(os.path.exists(subdir))
        self.assertTrue(os.path.isdir(subdir))

        # Verify it's within our shared temp directory
        self.assertTrue(subdir.startswith(get_temp_dir()))

        # Test creating a file within the subdirectory
        test_file = os.path.join(subdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("Test")

        self.assertTrue(os.path.exists(test_file))

    def test_keep_temp_files_setting(self):
        """Test the keep_temp_files setting."""
        # Get the current setting
        current_keep = hasattr(self.__class__, "temp_dir") and os.path.exists(
            self.__class__.temp_dir
        )

        # Change the setting temporarily
        set_keep_temp_files(True)

        # Create a temp file
        temp_file = create_temp_file(suffix=".txt", prefix="keep_test_")

        # Clean up, but it shouldn't delete because keep_files is True
        cleanup_temp_dir()

        # Verify the file still exists
        self.assertTrue(os.path.exists(temp_file))

        # Now force cleanup
        cleanup_temp_dir(force=True)

        # Set up again with original setting
        setup_temp_dir(
            base_dir=self.__class__.test_base_dir, prefix="test_temp_", keep_files=False
        )


# More complex integration test that simulates a typical workflow
class TestTempDirIntegration(unittest.TestCase):
    """Integration test for temporary directory with analysis components."""

    def setUp(self):
        """Set up for each test."""
        # Set up a new temporary directory for each test
        self.temp_dir = setup_temp_dir(prefix="integration_test_")

    def tearDown(self):
        """Clean up after each test."""
        cleanup_temp_dir(force=True)

    def test_analysis_workflow(self):
        """Test a simplified analysis workflow."""
        # Create a mock input file
        input_file = create_temp_file(
            suffix=".inp",
            prefix="model_",
            content="""
        ** Test model
        *NODE
        1, 0.0, 0.0, 0.0
        2, 1.0, 0.0, 0.0
        *ELEMENT, TYPE=B31
        1, 1, 2
        """,
        )

        # Create subdirectories for different steps
        mesh_dir = create_temp_subdir(prefix="mesh_")
        analysis_dir = create_temp_subdir(prefix="analysis_")

        # Simulate mesh generation
        mesh_file = os.path.join(mesh_dir, "mesh.msh")
        with open(mesh_file, "w") as f:
            f.write("# Mock mesh file")

        self.assertTrue(os.path.exists(mesh_file))

        # Simulate analysis execution
        result_file = os.path.join(analysis_dir, "results.frd")
        with open(result_file, "w") as f:
            f.write("# Mock results file")

        self.assertTrue(os.path.exists(result_file))

        # All files should be in subdirectories of our shared temp dir
        shared_temp_dir = get_temp_dir()
        self.assertTrue(input_file.startswith(shared_temp_dir))
        self.assertTrue(mesh_dir.startswith(shared_temp_dir))
        self.assertTrue(analysis_dir.startswith(shared_temp_dir))

        # Test that we can find all created files by listing the temp dir
        all_files = []
        for root, dirs, files in os.walk(shared_temp_dir):
            for file in files:
                all_files.append(os.path.join(root, file))

        self.assertIn(input_file, all_files)
        self.assertIn(mesh_file, all_files)
        self.assertIn(result_file, all_files)


if __name__ == "__main__":
    unittest.main()
