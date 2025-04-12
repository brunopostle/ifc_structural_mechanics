"""
Tests for the result domain model classes.
"""

import math
import pytest
from ifc_structural_mechanics.domain.result import (
    Result,
    DisplacementResult,
    StressResult,
    StrainResult,
    ReactionForceResult,
)


class TestResult:
    """Tests for the base Result class."""

    def test_initialization(self):
        """Test initialization of a result."""
        result = Result("test-type", "element-1")
        assert result.result_type == "test-type"
        assert result.reference_element == "element-1"
        assert result.values == {}
        assert result.metadata == {}

    def test_add_get_value(self):
        """Test adding and getting result values."""
        result = Result("test-type", "element-1")

        # Add a value
        result.add_value("key1", 10.0)
        assert result.values["key1"] == 10.0
        assert result.get_value("key1") == 10.0
        assert result.has_value("key1")

        # Add another value
        result.add_value("key2", "value2")
        assert result.values["key2"] == "value2"
        assert result.get_value("key2") == "value2"
        assert result.has_value("key2")

        # Override a value
        result.add_value("key1", 20.0)
        assert result.values["key1"] == 20.0
        assert result.get_value("key1") == 20.0

        # Test getting a non-existent value
        with pytest.raises(KeyError):
            result.get_value("non-existent")

        # Test has_value for non-existent key
        assert not result.has_value("non-existent")

    def test_add_get_metadata(self):
        """Test adding and getting result metadata."""
        result = Result("test-type", "element-1")

        # Add metadata
        result.add_metadata("meta1", "data1")
        assert result.metadata["meta1"] == "data1"
        assert result.get_metadata("meta1") == "data1"

        # Add another metadata
        result.add_metadata("meta2", 42)
        assert result.metadata["meta2"] == 42
        assert result.get_metadata("meta2") == 42

        # Override metadata
        result.add_metadata("meta1", "updated")
        assert result.metadata["meta1"] == "updated"
        assert result.get_metadata("meta1") == "updated"

        # Test getting non-existent metadata
        with pytest.raises(KeyError):
            result.get_metadata("non-existent")

    def test_validation(self):
        """Test validation of results."""
        result = Result("test-type", "element-1")

        # Result with no values should be invalid
        assert not result.validate()

        # Result with values should be valid
        result.add_value("key1", 10.0)
        assert result.validate()

        # Result with empty reference_element should be invalid
        invalid_result = Result("test-type", "")
        invalid_result.add_value("key1", 10.0)
        assert not invalid_result.validate()


class TestDisplacementResult:
    """Tests for the DisplacementResult class."""

    def test_initialization(self):
        """Test initialization of a displacement result."""
        # Test with load case
        result = DisplacementResult("element-1", "load-case-1")
        assert result.result_type == "displacement"
        assert result.reference_element == "element-1"
        assert result.get_metadata("load_case") == "load-case-1"

        # Test without load case
        result = DisplacementResult("element-1")
        assert result.result_type == "displacement"
        assert result.reference_element == "element-1"
        assert not result.metadata  # No metadata if no load case

    def test_translations_rotations(self):
        """Test setting and getting translations and rotations."""
        result = DisplacementResult("element-1")

        # Set translations
        result.set_translations([1.0, 2.0, 3.0])
        assert result.get_value("tx") == 1.0
        assert result.get_value("ty") == 2.0
        assert result.get_value("tz") == 3.0
        assert result.get_translations() == [1.0, 2.0, 3.0]

        # Set rotations
        result.set_rotations([0.1, 0.2, 0.3])
        assert result.get_value("rx") == 0.1
        assert result.get_value("ry") == 0.2
        assert result.get_value("rz") == 0.3
        assert result.get_rotations() == [0.1, 0.2, 0.3]

        # Test invalid translations
        with pytest.raises(ValueError):
            result.set_translations([1.0, 2.0])  # Only 2 values

        # Test invalid rotations
        with pytest.raises(ValueError):
            result.set_rotations([0.1, 0.2, 0.3, 0.4])  # 4 values

        # Test get_translations with partial values
        partial_result = DisplacementResult("element-2")
        partial_result.add_value("tx", 1.0)
        partial_result.add_value("tz", 3.0)
        assert partial_result.get_translations() == [1.0, 0.0, 3.0]

        # Test get_rotations with no values
        assert partial_result.get_rotations() == [0.0, 0.0, 0.0]

    def test_magnitude(self):
        """Test calculating displacement magnitude."""
        result = DisplacementResult("element-1")

        # Set translations
        result.set_translations([3.0, 4.0, 0.0])

        # Test magnitude calculation (3-4-5 triangle)
        assert result.get_magnitude() == 5.0

        # Test with different values
        result.set_translations([1.0, 1.0, 1.0])
        assert result.get_magnitude() == math.sqrt(3.0)

    def test_validation(self):
        """Test validation of displacement results."""
        result = DisplacementResult("element-1")

        # Result with no displacement values should be invalid
        assert not result.validate()

        # Result with only translations should be valid
        result.set_translations([1.0, 2.0, 3.0])
        assert result.validate()

        # Result with only rotations should be valid
        result = DisplacementResult("element-1")
        result.set_rotations([0.1, 0.2, 0.3])
        assert result.validate()

        # Result with partial values should be valid
        result = DisplacementResult("element-1")
        result.add_value("tx", 1.0)
        assert result.validate()


class TestStressResult:
    """Tests for the StressResult class."""

    def test_initialization(self):
        """Test initialization of a stress result."""
        # Test with load case
        result = StressResult("element-1", "load-case-1")
        assert result.result_type == "stress"
        assert result.reference_element == "element-1"
        assert result.get_metadata("load_case") == "load-case-1"

        # Test without load case
        result = StressResult("element-1")
        assert result.result_type == "stress"
        assert result.reference_element == "element-1"
        assert not result.metadata  # No metadata if no load case

    def test_normal_shear_stresses(self):
        """Test setting normal and shear stresses."""
        result = StressResult("element-1")

        # Set normal stresses
        result.set_normal_stresses({"xx": 10.0, "yy": 20.0, "zz": 30.0})
        assert result.get_value("sxx") == 10.0
        assert result.get_value("syy") == 20.0
        assert result.get_value("szz") == 30.0

        # Set shear stresses
        result.set_shear_stresses({"xy": 5.0, "yz": 15.0, "xz": 25.0})
        assert result.get_value("sxy") == 5.0
        assert result.get_value("syz") == 15.0
        assert result.get_value("sxz") == 25.0

    def test_principal_stresses(self):
        """Test setting principal stresses."""
        result = StressResult("element-1")

        # Set principal stresses
        result.set_principal_stresses([100.0, 50.0, 25.0])
        assert result.get_value("s1") == 100.0
        assert result.get_value("s2") == 50.0
        assert result.get_value("s3") == 25.0

        # Test invalid principal stresses
        with pytest.raises(ValueError):
            result.set_principal_stresses([100.0, 50.0])  # Only 2 values

    def test_von_mises_stress(self):
        """Test calculating von Mises stress."""
        # Test with principal stresses
        result1 = StressResult("element-1")
        result1.set_principal_stresses([100.0, 50.0, 0.0])
        # Expected von Mises: sqrt(0.5*((100-50)^2 + (50-0)^2 + (0-100)^2))
        expected1 = math.sqrt(0.5 * ((100 - 50) ** 2 + (50 - 0) ** 2 + (0 - 100) ** 2))
        assert math.isclose(result1.get_von_mises_stress(), expected1)

        # Test with stress components
        result2 = StressResult("element-2")
        result2.set_normal_stresses({"xx": 100.0, "yy": 50.0, "zz": 0.0})
        result2.set_shear_stresses({"xy": 25.0, "yz": 15.0, "xz": 10.0})
        # Expected von Mises calculation is complex, just test that it returns a value
        assert result2.get_von_mises_stress() > 0

        # Test with insufficient data
        result3 = StressResult("element-3")
        result3.add_value("sxx", 100.0)
        with pytest.raises(ValueError):
            result3.get_von_mises_stress()

    def test_validation(self):
        """Test validation of stress results."""
        result = StressResult("element-1")

        # Result with no stress values should be invalid
        assert not result.validate()

        # Result with stress components should be valid
        result.set_normal_stresses({"xx": 10.0})
        assert result.validate()

        # Result with principal stresses should be valid
        result = StressResult("element-1")
        result.set_principal_stresses([100.0, 50.0, 0.0])
        assert result.validate()


class TestStrainResult:
    """Tests for the StrainResult class."""

    def test_initialization(self):
        """Test initialization of a strain result."""
        # Test with load case
        result = StrainResult("element-1", "load-case-1")
        assert result.result_type == "strain"
        assert result.reference_element == "element-1"
        assert result.get_metadata("load_case") == "load-case-1"

        # Test without load case
        result = StrainResult("element-1")
        assert result.result_type == "strain"
        assert result.reference_element == "element-1"
        assert not result.metadata  # No metadata if no load case

    def test_normal_shear_strains(self):
        """Test setting normal and shear strains."""
        result = StrainResult("element-1")

        # Set normal strains
        result.set_normal_strains({"xx": 0.001, "yy": 0.002, "zz": 0.003})
        assert result.get_value("exx") == 0.001
        assert result.get_value("eyy") == 0.002
        assert result.get_value("ezz") == 0.003

        # Set shear strains
        result.set_shear_strains({"xy": 0.0005, "yz": 0.0015, "xz": 0.0025})
        assert result.get_value("exy") == 0.0005
        assert result.get_value("eyz") == 0.0015
        assert result.get_value("exz") == 0.0025

    def test_principal_strains(self):
        """Test setting principal strains."""
        result = StrainResult("element-1")

        # Set principal strains
        result.set_principal_strains([0.01, 0.005, 0.0025])
        assert result.get_value("e1") == 0.01
        assert result.get_value("e2") == 0.005
        assert result.get_value("e3") == 0.0025

        # Test invalid principal strains
        with pytest.raises(ValueError):
            result.set_principal_strains([0.01, 0.005, 0.0025, 0.0])  # 4 values

    def test_equivalent_strain(self):
        """Test calculating equivalent strain."""
        # Test with principal strains
        result1 = StrainResult("element-1")
        result1.set_principal_strains([0.01, 0.005, 0.0])
        # Just test that it returns a value (calculation is tested in StressResult)
        assert result1.get_equivalent_strain() > 0

        # Test with strain components
        result2 = StrainResult("element-2")
        result2.set_normal_strains({"xx": 0.01, "yy": 0.005, "zz": 0.0})
        result2.set_shear_strains({"xy": 0.0025, "yz": 0.0015, "xz": 0.001})
        assert result2.get_equivalent_strain() > 0

        # Test with insufficient data
        result3 = StrainResult("element-3")
        result3.add_value("exx", 0.01)
        with pytest.raises(ValueError):
            result3.get_equivalent_strain()

    def test_validation(self):
        """Test validation of strain results."""
        result = StrainResult("element-1")

        # Result with no strain values should be invalid
        assert not result.validate()

        # Result with strain components should be valid
        result.set_normal_strains({"xx": 0.001})
        assert result.validate()

        # Result with principal strains should be valid
        result = StrainResult("element-1")
        result.set_principal_strains([0.01, 0.005, 0.0])
        assert result.validate()


class TestReactionForceResult:
    """Tests for the ReactionForceResult class."""

    def test_initialization(self):
        """Test initialization of a reaction force result."""
        # Test with load case
        result = ReactionForceResult("element-1", "load-case-1")
        assert result.result_type == "reaction"
        assert result.reference_element == "element-1"
        assert result.get_metadata("load_case") == "load-case-1"

        # Test without load case
        result = ReactionForceResult("element-1")
        assert result.result_type == "reaction"
        assert result.reference_element == "element-1"
        assert not result.metadata  # No metadata if no load case

    def test_forces_moments(self):
        """Test setting and getting forces and moments."""
        result = ReactionForceResult("element-1")

        # Set forces
        result.set_forces([100.0, 200.0, 300.0])
        assert result.get_value("fx") == 100.0
        assert result.get_value("fy") == 200.0
        assert result.get_value("fz") == 300.0
        assert result.get_forces() == [100.0, 200.0, 300.0]

        # Set moments
        result.set_moments([50.0, 60.0, 70.0])
        assert result.get_value("mx") == 50.0
        assert result.get_value("my") == 60.0
        assert result.get_value("mz") == 70.0
        assert result.get_moments() == [50.0, 60.0, 70.0]

        # Test invalid forces
        with pytest.raises(ValueError):
            result.set_forces([100.0, 200.0, 300.0, 400.0])  # 4 values

        # Test invalid moments
        with pytest.raises(ValueError):
            result.set_moments([50.0, 60.0])  # Only 2 values

        # Test get_forces with partial values
        partial_result = ReactionForceResult("element-2")
        partial_result.add_value("fx", 100.0)
        partial_result.add_value("fz", 300.0)
        assert partial_result.get_forces() == [100.0, 0.0, 300.0]

        # Test get_moments with no values
        assert partial_result.get_moments() == [0.0, 0.0, 0.0]

    def test_magnitudes(self):
        """Test calculating force and moment magnitudes."""
        result = ReactionForceResult("element-1")

        # Set forces and moments
        result.set_forces([3.0, 4.0, 0.0])
        result.set_moments([5.0, 12.0, 0.0])

        # Test force magnitude calculation (3-4-5 triangle)
        assert result.get_force_magnitude() == 5.0

        # Test moment magnitude calculation (5-12-13 triangle)
        assert result.get_moment_magnitude() == 13.0

    def test_validation(self):
        """Test validation of reaction force results."""
        result = ReactionForceResult("element-1")

        # Result with no reaction values should be invalid
        assert not result.validate()

        # Result with only forces should be valid
        result.set_forces([100.0, 200.0, 300.0])
        assert result.validate()

        # Result with only moments should be valid
        result = ReactionForceResult("element-1")
        result.set_moments([50.0, 60.0, 70.0])
        assert result.validate()

        # Result with partial values should be valid
        result = ReactionForceResult("element-1")
        result.add_value("fx", 100.0)
        assert result.validate()
