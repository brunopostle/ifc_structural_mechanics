"""
Unit tests for the units.py module.

This module contains tests for all the unit conversion functions in the units.py module,
ensuring they properly convert values between project units and SI units.
"""

import numpy as np
import pytest

from ifc_structural_mechanics.utils.units import (
    convert_area,
    convert_coordinates,
    convert_density,
    convert_elastic_modulus,
    convert_force,
    convert_length,
    convert_linear_stiffness,
    convert_moment,
    convert_moment_of_inertia,
    convert_point_list,
    convert_rotational_stiffness,
    convert_volume,
)


class TestUnitConversions:
    """Test class for unit conversion utilities."""

    def test_convert_length(self):
        """Test length conversion from project units to SI units."""
        # Test with a single value
        assert convert_length(1000.0, 0.001) == pytest.approx(1.0)  # 1000mm -> 1m
        assert convert_length(1.0, 1.0) == pytest.approx(1.0)  # 1m -> 1m
        assert convert_length(3.28084, 0.3048) == pytest.approx(1.0)  # 1ft -> 0.3048m

        # Test with a list of values
        lengths = [1000.0, 2000.0, 3000.0]
        expected = [1.0, 2.0, 3.0]
        result = convert_length(lengths, 0.001)
        assert all(r == pytest.approx(e) for r, e in zip(result, expected))

        # Note: Function handles zero scale factor without error, so no need to test for ZeroDivisionError

    def test_convert_coordinates(self):
        """Test coordinate conversion from project units to SI units."""
        # Test conversion of 3D coordinates
        coords = [1000.0, 2000.0, 3000.0]
        expected = [1.0, 2.0, 3.0]
        result = convert_coordinates(coords, 0.001)
        assert all(r == pytest.approx(e) for r, e in zip(result, expected))

        # Test conversion of 2D coordinates
        coords_2d = [1000.0, 2000.0]
        expected_2d = [1.0, 2.0]
        result_2d = convert_coordinates(coords_2d, 0.001)
        assert all(r == pytest.approx(e) for r, e in zip(result_2d, expected_2d))

        # Test with identity scale factor
        coords = [1.0, 2.0, 3.0]
        result = convert_coordinates(coords, 1.0)
        assert all(r == c for r, c in zip(result, coords))

    def test_convert_point_list(self):
        """Test conversion of a list of points from project units to SI units."""
        # Test conversion of a list of 3D points
        points = [[1000.0, 2000.0, 3000.0], [4000.0, 5000.0, 6000.0]]
        expected = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        result = convert_point_list(points, 0.001)

        for r_point, e_point in zip(result, expected):
            assert all(r == pytest.approx(e) for r, e in zip(r_point, e_point))

        # Test conversion of a list of 2D points
        points_2d = [[1000.0, 2000.0], [3000.0, 4000.0]]
        expected_2d = [[1.0, 2.0], [3.0, 4.0]]
        result_2d = convert_point_list(points_2d, 0.001)

        for r_point, e_point in zip(result_2d, expected_2d):
            assert all(r == pytest.approx(e) for r, e in zip(r_point, e_point))

        # Test with identity scale factor
        points = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        result = convert_point_list(points, 1.0)

        for r_point, e_point in zip(result, points):
            assert all(r == pytest.approx(e) for r, e in zip(r_point, e_point))

    def test_convert_force(self):
        """Test force conversion from project units to SI units."""
        # Test with a single value
        assert convert_force(1000.0, 0.001) == pytest.approx(1.0)  # 1000N -> 1N
        assert convert_force(1.0, 1.0) == pytest.approx(1.0)  # 1N -> 1N
        # Use a higher relative tolerance for this conversion
        assert convert_force(0.2248, 4.44822) == pytest.approx(
            1.0, rel=1e-4
        )  # ~1lbf -> 4.45N

        # Test with a list of values
        forces = [1000.0, 2000.0, 3000.0]
        expected = [1.0, 2.0, 3.0]
        result = convert_force(forces, 0.001)
        assert all(r == pytest.approx(e) for r, e in zip(result, expected))

        # Test with numpy array
        forces_np = np.array([1000.0, 2000.0, 3000.0])
        expected_np = np.array([1.0, 2.0, 3.0])
        result_np = convert_force(forces_np, 0.001)
        assert np.allclose(result_np, expected_np)

    def test_convert_area(self):
        """Test area conversion from project units to SI units."""
        # Test with common conversions
        assert convert_area(1000000.0, 0.001) == pytest.approx(1.0)  # 1000000mm² -> 1m²
        assert convert_area(1.0, 1.0) == pytest.approx(1.0)  # 1m² -> 1m²
        assert convert_area(10.7639, 0.3048) == pytest.approx(1.0)  # ~10.76ft² -> 1m²

        # Test with different scale factors
        assert convert_area(100.0, 0.1) == pytest.approx(1.0)  # 100 * (0.1)² = 1.0
        assert convert_area(25.0, 0.2) == pytest.approx(1.0)  # 25 * (0.2)² = 1.0

    def test_convert_volume(self):
        """Test volume conversion from project units to SI units."""
        # Test with common conversions
        assert convert_volume(1000000000.0, 0.001) == pytest.approx(
            1.0
        )  # 1e9 mm³ -> 1m³
        assert convert_volume(1.0, 1.0) == pytest.approx(1.0)  # 1m³ -> 1m³
        assert convert_volume(35.3147, 0.3048) == pytest.approx(1.0)  # ~35.31ft³ -> 1m³

        # Test with different scale factors
        assert convert_volume(1000.0, 0.1) == pytest.approx(1.0)  # 1000 * (0.1)³ = 1.0
        assert convert_volume(125.0, 0.2) == pytest.approx(1.0)  # 125 * (0.2)³ = 1.0

    def test_convert_moment_of_inertia(self):
        """Test moment of inertia conversion from project units to SI units."""
        # Test with common conversions
        assert convert_moment_of_inertia(1000000000000.0, 0.001) == pytest.approx(
            1.0
        )  # 1e12 mm⁴ -> 1m⁴
        assert convert_moment_of_inertia(1.0, 1.0) == pytest.approx(1.0)  # 1m⁴ -> 1m⁴

        # Test with different scale factors
        assert convert_moment_of_inertia(10000.0, 0.1) == pytest.approx(
            1.0
        )  # 10000 * (0.1)⁴ = 1.0
        assert convert_moment_of_inertia(625.0, 0.2) == pytest.approx(
            1.0
        )  # 625 * (0.2)⁴ = 1.0

    def test_convert_density(self):
        """Test density conversion from project units to SI units."""
        # Test with common conversions (kg/m³)
        assert convert_density(1.0, 1.0) == pytest.approx(1.0)  # 1kg/m³ -> 1kg/m³

        # Based on the implementation, convert_density(value, unit_scale) converts units
        # where larger unit_scale means larger units (mm -> m), so 1kg/mm³ would be
        # a much denser material in SI units (kg/m³)
        assert convert_density(1.0, 0.001) == pytest.approx(1e9)  # 1kg/mm³ -> 1e9kg/m³

        # Test with realistic values
        # Density of steel is ~7850 kg/m³
        assert convert_density(7.85e-6, 0.001, 1.0) == pytest.approx(
            7850.0
        )  # 7.85e-6 kg/mm³ -> 7850 kg/m³

        # Test with both length and mass scale factors
        # When converting from g/cm³ to kg/m³:
        # - Mass scale: 0.001 (g -> kg)
        # - Length scale: 0.01 (cm -> m)
        # For example, water is 1 g/cm³, which is 1000 kg/m³
        assert convert_density(1.0, 0.01, 0.001) == pytest.approx(
            1000.0
        )  # 1g/cm³ -> 1000kg/m³

    def test_convert_elastic_modulus(self):
        """Test elastic modulus conversion from project units to SI units."""
        # Test with common conversions (Pa = N/m²)
        assert convert_elastic_modulus(1.0, 1.0, 1.0) == pytest.approx(
            1.0
        )  # 1Pa -> 1Pa

        # Based on implementation, convert_elastic_modulus uses:
        # value * (force_scale / (unit_scale**2))
        # So for 1000 N/mm² with force_scale=1.0 and unit_scale=0.001:
        # 1000 * (1.0 / (0.001**2)) = 1000 * 1e6 = 1e9 Pa
        assert convert_elastic_modulus(1000.0, 1.0, 0.001) == pytest.approx(
            1e9
        )  # 1000N/mm² -> 1e9Pa

        # Test with realistic values
        # Steel elastic modulus is ~210 GPa = 210e9 Pa
        assert convert_elastic_modulus(210000.0, 1.0, 0.001) == pytest.approx(
            210e9
        )  # 210000 N/mm² -> 210e9 Pa

    def test_convert_linear_stiffness(self):
        """Test linear stiffness conversion from project units to SI units."""
        # Test with common conversions (N/m)
        assert convert_linear_stiffness(1.0, 1.0, 1.0) == pytest.approx(
            1.0
        )  # 1N/m -> 1N/m

        # Based on implementation, convert_linear_stiffness uses:
        # value * (force_scale / unit_scale)
        # So for 1000 N/mm with force_scale=1.0 and unit_scale=0.001:
        # 1000 * (1.0 / 0.001) = 1000 * 1000 = 1e6 N/m
        assert convert_linear_stiffness(1000.0, 1.0, 0.001) == pytest.approx(
            1e6
        )  # 1000N/mm -> 1e6N/m

        # Test with different scale factors
        assert convert_linear_stiffness(10.0, 0.1, 0.1) == pytest.approx(
            10.0
        )  # 10 * (0.1 / 0.1) = 10.0
        assert convert_linear_stiffness(20.0, 0.5, 0.1) == pytest.approx(
            100.0
        )  # 20 * (0.5 / 0.1) = 100.0

    def test_convert_rotational_stiffness(self):
        """Test rotational stiffness conversion from project units to SI units."""
        # Test with common conversions (N·m/rad)
        assert convert_rotational_stiffness(1.0, 1.0, 1.0) == pytest.approx(
            1.0
        )  # 1N·m/rad -> 1N·m/rad
        assert convert_rotational_stiffness(1.0, 1.0, 0.001) == pytest.approx(
            0.001
        )  # 1N·mm/rad -> 0.001N·m/rad

        # Test with different force and length scale factors
        assert convert_rotational_stiffness(10.0, 0.1, 0.1) == pytest.approx(
            0.1
        )  # 10 * 0.1 * 0.1 = 0.1
        assert convert_rotational_stiffness(20.0, 0.5, 0.1) == pytest.approx(
            1.0
        )  # 20 * 0.5 * 0.1 = 1.0

    def test_convert_moment(self):
        """Test moment conversion from project units to SI units."""
        # Test with common conversions (N·m)
        assert convert_moment(1.0, 1.0, 1.0) == pytest.approx(1.0)  # 1N·m -> 1N·m
        assert convert_moment(1000.0, 1.0, 0.001) == pytest.approx(
            1.0
        )  # 1000N·mm -> 1N·m

        # Test with different force and length scale factors
        assert convert_moment(10.0, 0.1, 0.1) == pytest.approx(
            0.1
        )  # 10 * 0.1 * 0.1 = 0.1
        assert convert_moment(20.0, 0.5, 0.1) == pytest.approx(
            1.0
        )  # 20 * 0.5 * 0.1 = 1.0

    def test_edge_cases(self):
        """Test edge cases for conversion functions."""
        # Test with zero values
        assert convert_length(0.0, 1.0) == 0.0
        assert convert_force(0.0, 1.0) == 0.0
        assert convert_area(0.0, 1.0) == 0.0
        assert convert_volume(0.0, 1.0) == 0.0
        assert convert_moment_of_inertia(0.0, 1.0) == 0.0
        assert convert_density(0.0, 1.0) == 0.0
        assert convert_elastic_modulus(0.0, 1.0, 1.0) == 0.0
        assert convert_linear_stiffness(0.0, 1.0, 1.0) == 0.0
        assert convert_rotational_stiffness(0.0, 1.0, 1.0) == 0.0
        assert convert_moment(0.0, 1.0, 1.0) == 0.0

        # Test with negative values
        assert convert_length(-10.0, 0.1) == -1.0
        assert convert_force(-10.0, 0.1) == -1.0

        # Test with very small scale factors
        assert convert_length(1.0, 1e-6) == pytest.approx(1e-6)

        # Test with very large scale factors
        assert convert_length(1.0, 1e6) == pytest.approx(1e6)


if __name__ == "__main__":
    pytest.main(["-v"])
