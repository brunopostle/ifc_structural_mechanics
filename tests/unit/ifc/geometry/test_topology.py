"""
Unit tests for topology utilities.
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

import ifcopenshell

from ifc_structural_mechanics.ifc.geometry.topology import (
    analyze_connection_restraints,
    analyze_connection_type,
    find_connected_elements,
    find_member_endpoints,
    find_surface_boundaries,
    find_topology_graph,
)


class TestTopologyUtilities(unittest.TestCase):
    """Tests for the topology utility functions."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock objects for testing
        self.mock_point_connection = Mock(spec=ifcopenshell.entity_instance)
        self.mock_point_connection.id.return_value = "1"
        self.mock_point_connection.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralPointConnection"
        )
        self.mock_point_connection.GlobalId = "connection_1"

        # Mock boundary conditions for hinge connection
        mock_bc = Mock()
        mock_bc.is_a = MagicMock(side_effect=lambda x: x == "IfcBoundaryNodeCondition")

        # For hinge test - set IFC4 specific rotation restraints
        # XRotational and YRotational are FREE (hinge can rotate in these directions)
        # ZRotational is FIXED (hinge is restrained in this direction)
        mock_bc.XRotational = "FREE"
        mock_bc.YRotational = "FREE"
        mock_bc.ZRotational = "FIXED"

        # Attach to connection
        self.mock_point_connection.AppliedCondition = mock_bc

        # Create mock members for topology test
        self.mock_members = []
        for i in range(3):
            mock_member = Mock(spec=ifcopenshell.entity_instance)
            mock_member.id.return_value = str(i + 2)
            mock_member.is_a = MagicMock(
                side_effect=lambda x: x == "IfcStructuralCurveMember"
            )
            mock_member.GlobalId = f"member_{i+1}"
            self.mock_members.append(mock_member)

        # Create mock relationships for topology test
        self.mock_rel_connects = []
        for i, member in enumerate(self.mock_members):
            mock_rel = Mock()
            mock_rel.RelatingElement = self.mock_point_connection
            mock_rel.RelatedElement = member
            self.mock_rel_connects.append(mock_rel)

    def test_analyze_connection_restraints(self):
        """Test the analyze_connection_restraints function."""
        # Direct test of the function
        result = analyze_connection_restraints(self.mock_point_connection)

        # According to our mock setup, it should be a hinge
        self.assertEqual(result, "hinge")

    def test_analyze_connection_type(self):
        """Test analysis of connection type."""
        # We're directly testing the implementation here
        # Because our boundary condition suggests a hinge connection,
        # The result should be 'hinge' not 'point'

        # Use the direct implementation
        result = analyze_connection_type(self.mock_point_connection)

        # Assert the result matches expected
        self.assertEqual(result, "hinge")

    @patch("ifc_structural_mechanics.ifc.geometry.topology.find_connected_elements")
    @patch("ifc_structural_mechanics.ifc.geometry.topology.network.Graph")
    @patch("ifc_structural_mechanics.ifc.geometry.topology.is_structural_member")
    @patch("ifc_structural_mechanics.ifc.geometry.topology.is_structural_connection")
    @patch("ifc_structural_mechanics.ifc.geometry.topology.is_structural_curve_member")
    @patch("ifc_structural_mechanics.ifc.geometry.topology._calculate_midpoint")
    @patch(
        "ifc_structural_mechanics.ifc.geometry.topology._extract_connection_location"
    )
    @patch("ifc_structural_mechanics.ifc.geometry.topology.find_member_endpoints")
    @patch("ifc_structural_mechanics.ifc.geometry.topology.analyze_connection_type")
    def test_find_topology_graph(
        self,
        mock_analyze_connection,
        mock_find_endpoints,
        mock_extract_location,
        mock_calculate_midpoint,
        mock_is_curve,
        mock_is_connection,
        mock_is_member,
        mock_graph_class,
        mock_find_connected,
    ):
        """Test creation of topology graph."""
        # Create a mock graph with a special add_edge method that we can track
        mock_graph = MagicMock()
        mock_graph.nodes = {}

        # For testing purposes, we'll make mock_graph.edges a property
        # that returns an actual list we can inspect
        mock_graph.edges = []

        # Configure the mock_graph_class to return our instance
        mock_graph_class.return_value = mock_graph

        # Configure the mocked functions
        mock_is_member.side_effect = lambda x: x in self.mock_members
        mock_is_connection.side_effect = lambda x: x == self.mock_point_connection
        mock_is_curve.return_value = True
        mock_calculate_midpoint.return_value = (5, 5, 5)
        mock_extract_location.return_value = (0, 0, 0)
        mock_find_endpoints.return_value = [(0, 0, 0), (10, 0, 0)]
        mock_analyze_connection.return_value = "hinge"

        # The key fix: return NO connections when find_connected_elements is called
        # This will force the fallback code path to be used
        mock_find_connected.return_value = []

        # Call the function with our test elements
        result = find_topology_graph([self.mock_point_connection] + self.mock_members)

        # Verify the result is our mock graph
        self.assertEqual(result, mock_graph)

        # Verify add_node was called for each element (1 connection + 3 members)
        self.assertEqual(mock_graph.add_node.call_count, 4)

        # Since we're using the fallback path (no connections found),
        # Only 3 edges should be created (1 for each member connected to the connection)
        self.assertEqual(mock_graph.add_edge.call_count, 3)

    def test_find_connected_elements_empty(self):
        """Test finding connected elements for empty entity."""
        # Should return empty list for None input
        result = find_connected_elements(None)
        self.assertEqual(result, [])

    @patch(
        "ifc_structural_mechanics.ifc.geometry.topology._extract_connection_location"
    )
    def test_find_connected_elements_with_relationships(self, mock_extract_location):
        """Test finding connected elements with relationships."""
        # Set up mock for location extraction
        mock_extract_location.return_value = (0, 0, 0)

        # Create a test entity with connections
        mock_entity = Mock(spec=ifcopenshell.entity_instance)

        # Patch the entity to have IFC4-style relationships
        mock_entity.ConnectedBy = [
            Mock(
                RelatedStructuralConnection=self.mock_point_connection,
                RelatedElement=self.mock_members[0],
            )
        ]
        mock_entity.ConnectedTo = [
            Mock(
                RelatingStructuralConnection=self.mock_point_connection,
                RelatingElement=self.mock_members[1],
            )
        ]

        # Use default implementation approach
        with patch(
            "ifc_structural_mechanics.ifc.geometry.topology.is_structural_member",
            return_value=True,
        ):
            # Test the function
            result = find_connected_elements(mock_entity)

            # Debug print
            print("Debugging find_connected_elements:")
            print(f"Number of connections found: {len(result)}")
            for conn in result:
                print("Connection details:")
                for k, v in conn.items():
                    print(f"  {k}: {v}")

        # Should return 2 connections (one from ConnectedBy, one from ConnectedTo)
        self.assertEqual(
            len(result),
            2,
            "Expected 2 connections, but found {}\nConnection details: {}".format(
                len(result), [str(conn) for conn in result]
            ),
        )

        # Check the structure of the result
        for item in result:
            self.assertIn("element", item)
            self.assertIn("connection", item)
            self.assertIn("type", item)
            self.assertIn("location", item)
            self.assertEqual(item["type"], "structural")

        # Verify the elements are different
        elements = [item["element"] for item in result]
        self.assertEqual(len(set(elements)), 2, "Elements should be unique")

    def test_find_member_endpoints_empty(self):
        """Test finding endpoints for empty member."""
        # Should return empty list for None input
        result = find_member_endpoints(None)
        self.assertEqual(result, [])

    @patch("ifc_structural_mechanics.ifc.geometry.topology._extract_member_geometry")
    def test_find_member_endpoints_line(self, mock_extract_geometry):
        """Test finding endpoints for a line member."""
        # Mock a line segment geometry
        start_point = (0, 0, 0)
        end_point = (10, 0, 0)
        mock_extract_geometry.return_value = (start_point, end_point)

        # Create a test member
        mock_member = Mock(spec=ifcopenshell.entity_instance)
        mock_member.id.return_value = "test_member"

        # Test the function
        result = find_member_endpoints(mock_member)

        # Should return the start and end points
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], start_point)
        self.assertEqual(result[1], end_point)

    def test_find_surface_boundaries_empty(self):
        """Test finding boundaries for empty surface."""
        # Should return empty list for None input
        result = find_surface_boundaries(None)
        self.assertEqual(result, [])
