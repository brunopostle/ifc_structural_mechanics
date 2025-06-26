"""
Unit tests for the Gmsh utilities module.

These tests verify the functionality of the Gmsh utility classes
including resource management, geometry conversion, and meshing operations.
"""

import os
import tempfile
import unittest
from unittest import mock
import numpy as np

# Import the module under test
from ifc_structural_mechanics.meshing.gmsh_utils import (
    GmshResourceManager,
    GmshGeometryHelper,
    GmshMeshingHelper,
    GmshExecutableRunner,
)


class TestGmshResourceManager(unittest.TestCase):
    """Tests for the GmshResourceManager class."""

    def setUp(self):
        """Set up each test with fresh mocks and isolation."""
        # Create patches for all gmsh functions used in the tests
        self.gmsh_patcher = mock.patch.multiple(
            "gmsh",
            initialize=mock.DEFAULT,
            finalize=mock.DEFAULT,
            option=mock.DEFAULT,
            model=mock.DEFAULT,
        )

        # Start all patches
        self.mock_gmsh = self.gmsh_patcher.start()

        # Configure mock_gmsh.option.getNumber
        self.mock_gmsh["option"].getNumber = mock.Mock()

        # Configure mock_gmsh.model.add
        self.mock_gmsh["model"].add = mock.Mock()

    def tearDown(self):
        """Clean up after each test."""
        # Stop all patches
        self.gmsh_patcher.stop()

    def test_initialize_not_already_running(self):
        """Test initialization when Gmsh is not already running."""
        # Setup mock to raise exception (simulating Gmsh not initialized)
        self.mock_gmsh["option"].getNumber.side_effect = Exception(
            "Gmsh has not been initialized"
        )

        # Create manager with auto_initialize=False to test initialize() directly
        manager = GmshResourceManager(auto_initialize=False)
        result = manager.initialize()

        # Verify initialize was called and result is True
        self.mock_gmsh["initialize"].assert_called_once()
        self.assertTrue(result)
        self.assertTrue(manager.is_initialized())
        self.assertTrue(manager._we_initialized)

    def test_initialize_already_running(self):
        """Test initialization when Gmsh is already running."""
        # Setup mock to return successfully (simulating Gmsh already initialized)
        self.mock_gmsh["option"].getNumber.return_value = 0

        # Create manager with auto_initialize=False to test initialize() directly
        manager = GmshResourceManager(auto_initialize=False)
        result = manager.initialize()

        # Verify initialize was not called and result is True
        self.mock_gmsh["initialize"].assert_not_called()
        self.assertTrue(result)
        self.assertTrue(manager.is_initialized())
        self.assertFalse(manager._we_initialized)

    def test_finalize(self):
        """Test finalization of Gmsh resources."""
        manager = GmshResourceManager(auto_initialize=False)

        # Set up the internal state as if we had initialized
        manager._initialized = True
        manager._we_initialized = True

        # Mock gmsh.isInitialized to return True
        with mock.patch("gmsh.isInitialized", return_value=True), mock.patch(
            "gmsh.clear"
        ) as mock_clear, mock.patch("gmsh.finalize") as mock_finalize:

            # Call finalize
            manager.finalize()

            # Verify clear and finalize were called
            mock_clear.assert_called_once()
            mock_finalize.assert_called_once()

            # Verify state is reset
            self.assertFalse(manager.is_initialized())
            self.assertFalse(manager._we_initialized)

    def test_setup_model(self):
        """Test setting up a Gmsh model."""
        # Setup mock to return successfully
        self.mock_gmsh["option"].getNumber.return_value = 0

        manager = GmshResourceManager(auto_initialize=False)
        # Manually set initialized state since we're not calling initialize()
        manager._initialized = True

        result = manager.setup_model("test_model")

        # Verify model was added
        self.mock_gmsh["model"].add.assert_called_once_with("test_model")
        self.assertTrue(result)

    def test_finalize_in_test_environment(self):
        """Test that finalize works properly in test environments."""
        manager = GmshResourceManager(auto_initialize=False)

        # Set up the internal state as if we had initialized
        manager._initialized = True
        manager._we_initialized = True

        # Mock sys.modules to NOT include pytest (simulating non-test environment)
        with mock.patch("sys.modules", {"some_module": mock.Mock()}), mock.patch(
            "gmsh.isInitialized", return_value=True
        ), mock.patch("gmsh.clear") as mock_clear, mock.patch(
            "gmsh.finalize"
        ) as mock_finalize:

            # Call finalize
            manager.finalize()

            # Verify clear and finalize were called in non-test environment
            mock_clear.assert_called_once()
            mock_finalize.assert_called_once()

    def test_context_manager(self):
        """Test using GmshResourceManager as a context manager."""
        # Setup mock to raise exception (simulating Gmsh not initialized)
        self.mock_gmsh["option"].getNumber.side_effect = Exception(
            "Gmsh has not been initialized"
        )

        with mock.patch("gmsh.isInitialized", return_value=True), mock.patch(
            "gmsh.clear"
        ) as mock_clear, mock.patch("gmsh.finalize") as mock_finalize:

            with GmshResourceManager() as manager:
                self.assertTrue(manager.is_initialized())

            # Verify initialize, clear, and finalize were called
            self.mock_gmsh["initialize"].assert_called_once()
            mock_clear.assert_called_once()
            mock_finalize.assert_called_once()

    def test_context_manager_in_test_environment(self):
        """Test context manager behavior in test environment (should suppress cleanup)."""
        # Setup mock to raise exception (simulating Gmsh not initialized)
        self.mock_gmsh["option"].getNumber.side_effect = Exception(
            "Gmsh has not been initialized"
        )

        # This test runs in the actual test environment, so finalize should be suppressed
        with GmshResourceManager() as manager:
            self.assertTrue(manager.is_initialized())

        # Verify initialize was called but finalize was suppressed due to test environment
        self.mock_gmsh["initialize"].assert_called_once()
        # Note: We don't assert finalize was called because it's suppressed in test env

    def test_destructor_safety(self):
        """Test that the destructor doesn't raise exceptions."""
        manager = GmshResourceManager(auto_initialize=False)
        manager._initialized = True
        manager._we_initialized = True

        # This should not raise any exceptions
        try:
            manager.__del__()
        except Exception as e:
            self.fail(f"Destructor raised an exception: {e}")

    def test_finalize_when_gmsh_not_initialized(self):
        """Test finalize when Gmsh is not actually initialized."""
        manager = GmshResourceManager(auto_initialize=False)
        manager._initialized = True
        manager._we_initialized = True

        # Mock gmsh.isInitialized to return False
        with mock.patch("gmsh.isInitialized", return_value=False):
            # Should not raise an exception
            manager.finalize()

            # State should still be reset
            self.assertFalse(manager.is_initialized())
            self.assertFalse(manager._we_initialized)


class TestGmshGeometryHelper(unittest.TestCase):
    """Tests for the GmshGeometryHelper class."""

    def test_convert_point(self):
        """Test converting a point to numpy array."""
        # Test with list
        point_list = [1.0, 2.0, 3.0]
        np_point = GmshGeometryHelper.convert_point(point_list)
        self.assertIsInstance(np_point, np.ndarray)
        np.testing.assert_array_equal(np_point, np.array([1.0, 2.0, 3.0]))

        # Test with numpy array
        point_array = np.array([4.0, 5.0, 6.0])
        np_point = GmshGeometryHelper.convert_point(point_array)
        self.assertIsInstance(np_point, np.ndarray)
        np.testing.assert_array_equal(np_point, np.array([4.0, 5.0, 6.0]))

        # Test with unsupported type
        with self.assertRaises(NotImplementedError):
            GmshGeometryHelper.convert_point("not a point")

    def test_convert_curve(self):
        """Test converting a curve to list of points."""
        # Test with tuple of two points
        curve_tuple = ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
        points = GmshGeometryHelper.convert_curve(curve_tuple)
        self.assertEqual(len(points), 2)
        np.testing.assert_array_equal(points[0], np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(points[1], np.array([4.0, 5.0, 6.0]))

        # Test with list of points
        curve_list = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        points = GmshGeometryHelper.convert_curve(curve_list)
        self.assertEqual(len(points), 3)
        np.testing.assert_array_equal(points[0], np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(points[2], np.array([7.0, 8.0, 9.0]))

        # Test with dict format
        curve_dict = {"type": "line", "start": [1.0, 2.0, 3.0], "end": [4.0, 5.0, 6.0]}
        points = GmshGeometryHelper.convert_curve(curve_dict)
        self.assertEqual(len(points), 2)
        np.testing.assert_array_equal(points[0], np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(points[1], np.array([4.0, 5.0, 6.0]))

        # Test with boundaries dict format
        curve_boundaries = {
            "boundaries": [[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]]
        }
        points = GmshGeometryHelper.convert_curve(curve_boundaries)
        self.assertEqual(len(points), 3)
        np.testing.assert_array_equal(points[0], np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(points[2], np.array([7.0, 8.0, 9.0]))

    def test_convert_surface(self):
        """Test converting a surface to list of boundary points."""
        # Test with list of points
        surface_list = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        points = GmshGeometryHelper.convert_surface(surface_list)
        self.assertEqual(len(points), 3)
        np.testing.assert_array_equal(points[0], np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(points[2], np.array([7.0, 8.0, 9.0]))

        # Test with boundaries dict format
        surface_boundaries = {
            "boundaries": [
                [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0], [1.0, 2.0, 3.0]]
            ]
        }
        points = GmshGeometryHelper.convert_surface(surface_boundaries)
        self.assertEqual(len(points), 4)
        np.testing.assert_array_equal(points[0], np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(points[3], np.array([1.0, 2.0, 3.0]))

        # Test with plane dict format with boundaries
        plane_dict = {
            "type": "plane",
            "boundaries": [[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]],
        }
        points = GmshGeometryHelper.convert_surface(plane_dict)
        self.assertEqual(len(points), 3)
        np.testing.assert_array_equal(points[0], np.array([1.0, 2.0, 3.0]))

        # Test with plane dict format with normal and point
        plane_dict = {
            "type": "plane",
            "normal": [0.0, 0.0, 1.0],
            "point": [0.0, 0.0, 0.0],
        }
        points = GmshGeometryHelper.convert_surface(plane_dict)
        self.assertEqual(len(points), 4)  # Rectangle has 4 corners

    def test_create_rectangle_in_plane(self):
        """Test creating a rectangle in a plane defined by point and normal."""
        point = np.array([0.0, 0.0, 0.0])
        normal = np.array([0.0, 0.0, 1.0])
        size = 2.0

        # Create rectangle
        corners = GmshGeometryHelper.create_rectangle_in_plane(point, normal, size)

        # Should have 4 corners
        self.assertEqual(len(corners), 4)

        # All corners should be in the XY plane (z=0) since normal is in Z direction
        for corner in corners:
            self.assertAlmostEqual(corner[2], 0.0)

        # Check size (the distance between opposite corners should be size)
        diagonal = np.linalg.norm(corners[0] - corners[2])
        self.assertAlmostEqual(diagonal, size * np.sqrt(2))  # Square diagonal length


class TestGmshMeshingHelper(unittest.TestCase):
    """Tests for the GmshMeshingHelper class."""

    def setUp(self):
        """Set up each test."""
        # Mock gmsh.model.mesh.setSize
        self.mesh_patcher = mock.patch("gmsh.model.mesh.setSize")
        self.mock_set_size = self.mesh_patcher.start()

        # Mock for gmsh.model.mesh.setTransfiniteCurve
        self.transfinite_patcher = mock.patch("gmsh.model.mesh.setTransfiniteCurve")
        self.mock_set_transfinite = self.transfinite_patcher.start()

    def tearDown(self):
        """Clean up after each test."""
        self.mesh_patcher.stop()
        self.transfinite_patcher.stop()

    def test_apply_mesh_size(self):
        """Test applying mesh size to a geometric entity."""
        # Mock the resource manager
        mock_manager = mock.MagicMock()
        mock_manager.is_initialized.return_value = True

        result = GmshMeshingHelper.apply_mesh_size(
            dimension=1, entity_tag=42, size=2.0, resource_manager=mock_manager
        )

        # Verify set_size was called correctly
        self.mock_set_size.assert_called_once_with([(1, 42)], 2.0)
        self.assertTrue(result)

    def test_get_algorithm_code(self):
        """Test conversion of algorithm name to Gmsh code."""
        # Test known algorithms
        self.assertEqual(GmshMeshingHelper.get_algorithm_code("Delaunay"), 5)
        self.assertEqual(GmshMeshingHelper.get_algorithm_code("MeshAdapt"), 1)
        self.assertEqual(GmshMeshingHelper.get_algorithm_code("Frontal"), 6)

        # Test unknown algorithm (should default to Delaunay)
        self.assertEqual(
            GmshMeshingHelper.get_algorithm_code("NonExistentAlgorithm"), 5
        )

    def test_set_transfinite_curve(self):
        """Test setting transfinite curve property."""
        result = GmshMeshingHelper.set_transfinite_curve(tag=10, num_points=5)

        # Verify method was called correctly
        self.mock_set_transfinite.assert_called_once_with(10, 5)
        self.assertTrue(result)

    def test_validate_mesh_quality(self):
        """Test mesh quality validation."""
        # Create a temporary mesh file
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(b"Test mesh file content")
            tmp_path = tmp_file.name

        try:
            # Test with valid file
            self.assertTrue(GmshMeshingHelper.validate_mesh_quality(tmp_path))

            # Test with non-existent file
            self.assertFalse(
                GmshMeshingHelper.validate_mesh_quality("/tmp/nonexistent_file.msh")
            )

            # Test with empty file
            with open(tmp_path, "w") as f:
                f.write("")
            self.assertFalse(GmshMeshingHelper.validate_mesh_quality(tmp_path))
        finally:
            # Clean up
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestGmshExecutableRunner(unittest.TestCase):
    """Tests for the GmshExecutableRunner class."""

    def setUp(self):
        """Set up each test."""
        # Mock run_subprocess
        self.subprocess_patcher = mock.patch(
            "ifc_structural_mechanics.meshing.gmsh_utils.run_subprocess"
        )
        self.mock_run_subprocess = self.subprocess_patcher.start()

    def tearDown(self):
        """Clean up after each test."""
        self.subprocess_patcher.stop()

    def test_run_gmsh_command(self):
        """Test running Gmsh as a subprocess."""
        # Mock subprocess result
        mock_result = mock.MagicMock()
        mock_result.stdout = "Gmsh success output"
        mock_result.stderr = ""
        self.mock_run_subprocess.return_value = mock_result

        # Test successful command
        success, stdout, stderr = GmshExecutableRunner.run_gmsh_command(
            cmd=["gmsh", "test.geo", "-o", "test.msh"]
        )

        # Verify subprocess was called correctly
        self.mock_run_subprocess.assert_called_once_with(
            ["gmsh", "test.geo", "-o", "test.msh"], timeout=None
        )
        self.assertTrue(success)
        self.assertEqual(stdout, "Gmsh success output")
        self.assertEqual(stderr, "")

    def test_handle_gmsh_output(self):
        """Test handling of Gmsh subprocess output."""
        # Test success case
        self.assertTrue(
            GmshExecutableRunner.handle_gmsh_output(
                stdout="Info: Mesh generation completed.", stderr=""
            )
        )

        # Test error in stdout
        self.assertFalse(
            GmshExecutableRunner.handle_gmsh_output(
                stdout="Error: Failed to create mesh.", stderr=""
            )
        )

        # Test error in stderr
        self.assertFalse(
            GmshExecutableRunner.handle_gmsh_output(
                stdout="", stderr="Fatal error: cannot initialize Gmsh"
            )
        )


if __name__ == "__main__":
    unittest.main()
