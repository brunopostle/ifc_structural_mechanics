"""
Unit tests for the units.py module.

This module contains tests for all the unit conversion functions in the units.py module,
ensuring they properly convert values between project units and SI units.
"""

import pytest

from ifc_structural_mechanics.utils.units import (
    convert_area,
    convert_coordinates,
    convert_density,
    convert_length,
    convert_moment_of_inertia,
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

    def test_convert_area(self):
        """Test area conversion from project units to SI units."""
        # Test with common conversions
        assert convert_area(1000000.0, 0.001) == pytest.approx(1.0)  # 1000000mm² -> 1m²
        assert convert_area(1.0, 1.0) == pytest.approx(1.0)  # 1m² -> 1m²
        assert convert_area(10.7639, 0.3048) == pytest.approx(1.0)  # ~10.76ft² -> 1m²

        # Test with different scale factors
        assert convert_area(100.0, 0.1) == pytest.approx(1.0)  # 100 * (0.1)² = 1.0
        assert convert_area(25.0, 0.2) == pytest.approx(1.0)  # 25 * (0.2)² = 1.0

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

    def test_edge_cases(self):
        """Test edge cases for conversion functions."""
        # Test with zero values
        assert convert_length(0.0, 1.0) == 0.0
        assert convert_area(0.0, 1.0) == 0.0
        assert convert_moment_of_inertia(0.0, 1.0) == 0.0
        assert convert_density(0.0, 1.0) == 0.0

        # Test with negative values
        assert convert_length(-10.0, 0.1) == -1.0

        # Test with very small scale factors
        assert convert_length(1.0, 1e-6) == pytest.approx(1e-6)

        # Test with very large scale factors
        assert convert_length(1.0, 1e6) == pytest.approx(1e6)


if __name__ == "__main__":
    pytest.main(["-v"])
