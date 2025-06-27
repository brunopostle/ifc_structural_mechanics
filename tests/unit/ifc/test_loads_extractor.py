"""
Unit tests for the loads extractor module.

Updated to work with the actual public interface of the LoadsExtractor class
and match the IFC specification for load hierarchies.
"""

import numpy as np
from unittest.mock import MagicMock, patch

from ifc_structural_mechanics.ifc.loads_extractor import LoadsExtractor
from ifc_structural_mechanics.domain.load import (
    PointLoad,
    LineLoad,
    AreaLoad,
)


class TestLoadsExtractor:
    """Test cases for LoadsExtractor class."""

    def setup_method(self):
        """Set up mock IFC file for testing."""
        # Create a mock IFC file
        self.mock_ifc = MagicMock()
        self.mock_ifc._mock_name = "MockIFC"  # Flag for test mode

        # Create mock point load (IFC4 style)
        self.point_load = MagicMock()
        self.point_load.GlobalId = "pl1"
        self.point_load.is_a.return_value = False  # Default
        self.point_load.is_a.side_effect = lambda x: x == "IfcStructuralPointAction"
        self.point_load.ForceX = 1000.0
        self.point_load.ForceY = 0.0
        self.point_load.ForceZ = -2000.0
        # Add moment components for IFC4
        self.point_load.MomentX = 0.0
        self.point_load.MomentY = 0.0
        self.point_load.MomentZ = 0.0

        # Set up AppliedLoad for the point_load to handle extraction more robustly
        self.point_load_applied = MagicMock()
        self.point_load_applied.ForceX = 1000.0
        self.point_load_applied.ForceY = 0.0
        self.point_load_applied.ForceZ = -2000.0
        self.point_load_applied.is_a = lambda x: x == "IfcStructuralLoadSingleForce"
        self.point_load.AppliedLoad = self.point_load_applied

        # Create mock line load (IFC4 style)
        self.line_load = MagicMock()
        self.line_load.GlobalId = "ll1"
        self.line_load.is_a.return_value = False  # Default
        self.line_load.is_a.side_effect = lambda x: x == "IfcStructuralLinearAction"
        self.line_load.ForceX = 0.0
        self.line_load.ForceY = 0.0
        self.line_load.ForceZ = -5000.0
        # Add moment components for IFC4
        self.line_load.MomentX = 0.0
        self.line_load.MomentY = 0.0
        self.line_load.MomentZ = 0.0

        # Set up AppliedLoad for the line_load to handle extraction more robustly
        self.line_load_applied = MagicMock()
        self.line_load_applied.ForceX = 0.0
        self.line_load_applied.ForceY = 0.0
        self.line_load_applied.ForceZ = -5000.0
        self.line_load_applied.is_a = lambda x: x == "IfcStructuralLoadSingleForce"
        self.line_load.AppliedLoad = self.line_load_applied

        # Create mock area load (IFC4 style)
        self.area_load = MagicMock()
        self.area_load.GlobalId = "al1"
        self.area_load.is_a.return_value = False  # Default
        self.area_load.is_a.side_effect = lambda x: x == "IfcStructuralPlanarAction"
        self.area_load.ForceX = 0.0
        self.area_load.ForceY = 0.0
        self.area_load.ForceZ = -2000.0
        # Add moment components for IFC4
        self.area_load.MomentX = 0.0
        self.area_load.MomentY = 0.0
        self.area_load.MomentZ = 0.0

        # Set up AppliedLoad for the area_load to handle extraction more robustly
        self.area_load_applied = MagicMock()
        self.area_load_applied.ForceX = 0.0
        self.area_load_applied.ForceY = 0.0
        self.area_load_applied.ForceZ = -2000.0
        self.area_load_applied.is_a = lambda x: x == "IfcStructuralLoadSingleForce"
        self.area_load.AppliedLoad = self.area_load_applied

        # Setup mock load group (IFC4 style)
        self.load_group = MagicMock()
        self.load_group.GlobalId = "lg1"
        self.load_group.Name = "Test Load Group"
        self.load_group.Description = "A test load group"
        self.load_group.PredefinedType = "LOAD_GROUP"
        self.load_group.is_a = lambda x: x == "IfcStructuralLoadGroup"

        # Setup RelAssignsToGroup for LOAD_GROUP relationship with loads
        self.rel_assigns_to_group = MagicMock()
        self.rel_assigns_to_group.RelatingGroup = self.load_group
        self.rel_assigns_to_group.RelatedObjects = [self.point_load, self.line_load]

        # Setup mock load case (IFC4 style)
        self.load_case = MagicMock()
        self.load_case.GlobalId = "lc1"
        self.load_case.Name = "Test Load Case"
        self.load_case.Description = "A test load case"
        self.load_case.PredefinedType = "LOAD_CASE"
        self.load_case.is_a = lambda x: x == "IfcStructuralLoadCase"

        # Setup RelAssignsToGroup for LOAD_CASE relationship with load groups
        self.rel_assigns_to_case = MagicMock()
        self.rel_assigns_to_case.RelatingGroup = self.load_case
        self.rel_assigns_to_case.RelatedObjects = [self.load_group, self.area_load]

        # Setup mock load combination (IFC4 style)
        self.load_combination = MagicMock()
        self.load_combination.GlobalId = "lc2"
        self.load_combination.Name = "Test Load Combination"
        self.load_combination.Description = "A test load combination"
        self.load_combination.PredefinedType = "LOAD_COMBINATION"
        self.load_combination.is_a = lambda x: x == "IfcStructuralLoadGroup"

        # Create RelAssignsToGroup for combinations (should only contain load cases)
        self.rel_assigns_to_combo = MagicMock()
        self.rel_assigns_to_combo.RelatingGroup = self.load_combination
        self.rel_assigns_to_combo.RelatedObjects = [self.load_case]
        self.rel_assigns_to_combo.Factor = 1.5

        # Mock by_type to return our mock entities
        def mock_by_type(entity_type):
            if entity_type == "IfcStructuralPointAction":
                return [self.point_load]
            elif entity_type == "IfcStructuralLinearAction":
                return [self.line_load]
            elif entity_type == "IfcStructuralPlanarAction":
                return [self.area_load]
            elif entity_type == "IfcStructuralLoadGroup":
                # Return both groups and combinations for the tests
                if (
                    hasattr(self, "mock_return_load_combination")
                    and self.mock_return_load_combination
                ):
                    return [self.load_group, self.load_combination]
                return [self.load_group]
            elif entity_type == "IfcRelAssignsToGroup":
                rel_list = [self.rel_assigns_to_group, self.rel_assigns_to_case]
                if (
                    hasattr(self, "mock_return_load_combination")
                    and self.mock_return_load_combination
                ):
                    rel_list.append(self.rel_assigns_to_combo)
                return rel_list
            elif entity_type == "IfcStructuralLoadCase":
                return [self.load_case]
            return []

        self.mock_ifc.by_type.side_effect = mock_by_type

        # Set up mock line for line load
        self._setup_mock_line_element(self.line_load)

        # Create extractor with mock IFC file
        self.extractor = LoadsExtractor(self.mock_ifc)

    def _setup_mock_line_element(self, load):
        """Helper to set up mock line element for line load."""
        # Create a mock structural member for the line load to apply to
        member = MagicMock()
        member.GlobalId = "member1"
        member.is_a.return_value = True  # is_a returns True for any input

        # Mock geometry endpoints
        from_point = [0.0, 0.0, 0.0]
        to_point = [10.0, 0.0, 0.0]

        # Mock relationship to member
        applied_rel = MagicMock()
        applied_rel.RelatingElement = member
        load.AppliedOn = [applied_rel]

        # Create patch function for find_member_endpoints
        def mock_endpoints(m, unit_scale=None):
            return [from_point, to_point]

        # Apply patch
        patch(
            "ifc_structural_mechanics.ifc.loads_extractor.find_member_endpoints",
            side_effect=mock_endpoints,
        ).start()

    def test_extract_all_loads(self):
        """Test extracting all loads."""
        # Call the public method
        loads = self.extractor.extract_all_loads()

        # Verify results
        assert len(loads) == 3

        point_load = next((l for l in loads if l.id == "pl1"), None)
        assert isinstance(point_load, PointLoad)
        # Check force components with our simplified implementation
        assert np.array_equal(point_load.magnitude, np.array([1000.0, 0.0, -2000.0]))
        # Direction should be the normalized force vector
        assert np.allclose(
            point_load.direction, np.array([0.4472, 0.0, -0.8944]), atol=1e-4
        )

        line_load = next((l for l in loads if l.id == "ll1"), None)
        assert isinstance(line_load, LineLoad)
        # Check force components with our simplified implementation
        assert np.array_equal(line_load.magnitude, np.array([0.0, 0.0, -5000.0]))
        # Direction should be unit vector in Z direction
        assert np.array_equal(line_load.direction, np.array([0.0, 0.0, -1.0]))
        assert line_load.start_position == tuple(
            [0.0, 0.0, 0.0]
        ) or line_load.start_position == [0.0, 0.0, 0.0]
        assert line_load.end_position == tuple(
            [10.0, 0.0, 0.0]
        ) or line_load.end_position == [10.0, 0.0, 0.0]

        area_load = next((l for l in loads if l.id == "al1"), None)
        assert isinstance(area_load, AreaLoad)
        # Check force components with our simplified implementation
        assert np.array_equal(area_load.magnitude, np.array([0.0, 0.0, -2000.0]))
        # Direction should be unit vector in Z direction
        assert np.array_equal(area_load.direction, np.array([0.0, 0.0, -1.0]))

    def test_extract_load_groups(self):
        """Test extracting load groups according to IFC spec."""
        # Call the public method
        groups = self.extractor.extract_load_groups()

        # Verify we get both the regular load group and the load case
        assert len(groups) == 2

        # Find each type of group
        regular_group = next((g for g in groups if g.id == "lg1"), None)
        load_case = next((g for g in groups if g.id == "lc1"), None)

        # Verify regular load group properties
        assert regular_group is not None
        assert regular_group.id == "lg1"
        assert regular_group.name == "Test Load Group"
        assert regular_group.description == "A test load group"
        # Regular load group should contain the point and line loads
        assert len(regular_group.loads) == 2
        load_ids = [load.id for load in regular_group.loads]
        assert "pl1" in load_ids
        assert "ll1" in load_ids

        # Verify load case properties
        assert load_case is not None
        assert load_case.id == "lc1"
        assert load_case.name == "Test Load Case"
        assert load_case.description == "A test load case"
        # Load case should include all loads from the load group it references
        # plus the area load assigned directly
        assert len(load_case.loads) >= 1
        load_ids = [load.id for load in load_case.loads]
        assert "al1" in load_ids  # Area load is directly assigned

    def test_extract_load_combinations(self):
        """Test extracting load combinations according to IFC spec."""
        # Enable returning the load combination in the mock
        self.mock_return_load_combination = True

        # Call the public method
        combinations = self.extractor.extract_load_combinations()

        # Verify results - should find the combination
        assert len(combinations) == 1

        # Check combination properties
        combination = combinations[0]
        assert combination.id == "lc2"
        assert combination.name == "Test Load Combination"
        assert combination.description == "A test load combination"

        # Should reference the load case
        assert "lc1" in combination.load_groups
        # Should use the specified factor
        assert abs(combination.load_groups["lc1"] - 1.5) < 0.01

    def test_point_load_creation(self):
        """Test point load is created correctly from IFC."""
        # Use the extract_all_loads method to get a point load
        loads = self.extractor.extract_all_loads()
        point_load = next((l for l in loads if l.id == "pl1"), None)

        # Verify the point load properties
        assert isinstance(point_load, PointLoad)
        assert point_load.id == "pl1"
        assert np.array_equal(point_load.magnitude, np.array([1000.0, 0.0, -2000.0]))
        assert np.allclose(
            point_load.direction, np.array([0.4472, 0.0, -0.8944]), atol=1e-4
        )

    def test_line_load_creation(self):
        """Test line load is created correctly from IFC."""
        # Use the extract_all_loads method to get a line load
        loads = self.extractor.extract_all_loads()
        line_load = next((l for l in loads if l.id == "ll1"), None)

        # Verify the line load properties
        assert isinstance(line_load, LineLoad)
        assert line_load.id == "ll1"
        assert np.array_equal(line_load.magnitude, np.array([0.0, 0.0, -5000.0]))
        assert np.array_equal(line_load.direction, np.array([0.0, 0.0, -1.0]))
        # Check the position - could be list or tuple
        assert line_load.start_position == tuple(
            [0.0, 0.0, 0.0]
        ) or line_load.start_position == [0.0, 0.0, 0.0]
        assert line_load.end_position == tuple(
            [10.0, 0.0, 0.0]
        ) or line_load.end_position == [10.0, 0.0, 0.0]

    def test_area_load_creation(self):
        """Test area load is created correctly from IFC."""
        # Need to patch the surface reference extraction method
        with patch.object(
            self.extractor, "_extract_surface_reference", return_value="surface_1"
        ):
            # Use the extract_all_loads method to get an area load
            loads = self.extractor.extract_all_loads()
            area_load = next((l for l in loads if l.id == "al1"), None)

            # Verify the area load properties
            assert isinstance(area_load, AreaLoad)
            assert area_load.id == "al1"
            assert np.array_equal(area_load.magnitude, np.array([0.0, 0.0, -2000.0]))
            assert np.array_equal(area_load.direction, np.array([0.0, 0.0, -1.0]))
            assert area_load.surface_reference == "surface_1"

    def test_error_handling(self):
        """Test error handling when extractor encounters issues."""
        # Configure IFC to raise an exception
        self.mock_ifc.by_type.side_effect = Exception("Test error")

        # Call the method - should not raise an exception
        loads = self.extractor.extract_all_loads()

        # Verify empty result
        assert loads == []

    def test_no_default_load_group(self):
        """Test that no default group is created when no load groups exist."""
        # Mock that no load groups exist but loads do
        original_side_effect = self.mock_ifc.by_type.side_effect

        def new_side_effect(entity_type):
            if (
                entity_type == "IfcStructuralLoadGroup"
                or entity_type == "IfcStructuralLoadCase"
            ):
                return []
            else:
                # Call the original side_effect for other entity types
                for et in [
                    "IfcStructuralPointAction",
                    "IfcStructuralLinearAction",
                    "IfcStructuralPlanarAction",
                ]:
                    if entity_type == et:
                        return original_side_effect(et)
            return []

        self.mock_ifc.by_type.side_effect = new_side_effect

        # Call the method
        groups = self.extractor.extract_load_groups()

        # Verify no groups are created
        assert len(groups) == 0
