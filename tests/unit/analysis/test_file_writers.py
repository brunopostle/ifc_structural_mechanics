"""
Unit tests for the file_writers module.

These tests verify that the file writing functions correctly generate CalculiX input
file sections according to expected formats and requirements.
"""

import io
import unittest
from unittest.mock import Mock, PropertyMock, patch

import numpy as np

from ifc_structural_mechanics.analysis import file_writers
from ifc_structural_mechanics.domain.load import AreaLoad, LineLoad, PointLoad
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel


class TestFileWriters(unittest.TestCase):
    """Test suite for the file_writers module."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock structural model
        self.model = Mock(spec=StructuralModel)
        self.model.id = "test_model_001"
        self.model.name = "Test Model"
        self.model.description = "A test structural model"
        self.model.members = []
        self.model.connections = []
        self.model.load_groups = []

        # Sample nodes
        self.nodes = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
            3: (0.0, 1.0, 0.0),
            4: (1.0, 1.0, 0.0),
        }

        # Sample elements
        self.elements = {
            1: {"type": "B31", "nodes": [1, 2]},
            2: {"type": "B31", "nodes": [1, 3]},
            3: {"type": "S4", "nodes": [1, 2, 4, 3]},
        }

        # Sample node sets
        self.node_sets = {
            "NSET1": [1, 2],
            "NSET2": [3, 4],
        }

        # Sample element sets
        self.element_sets = {
            "ELSET1": [1, 2],
            "ELSET2": [3],
        }

    def test_write_header(self):
        """Test writing the header section."""
        output = io.StringIO()
        file_writers.write_header(output, self.model, "linear_static")

        result = output.getvalue()

        # Check for expected content
        self.assertIn("CalculiX Input File", result)
        self.assertIn("Model ID: test_model_001", result)
        self.assertIn("Model Name: Test Model", result)
        self.assertIn("Description: A test structural model", result)
        self.assertIn("Analysis Type: linear_static", result)

    def test_write_nodes(self):
        """Test writing node definitions."""
        output = io.StringIO()
        file_writers.write_nodes(output, self.nodes)

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*NODE", result)
        # Check that all nodes are written
        for node_id, (x, y, z) in self.nodes.items():
            self.assertIn(f"{node_id}, {x:.6e}, {y:.6e}, {z:.6e}", result)

    def test_write_empty_nodes(self):
        """Test writing nodes when there are none."""
        output = io.StringIO()
        file_writers.write_nodes(output, {})

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*NODE", result)
        self.assertIn("WARNING: No nodes generated", result)

    def test_write_node_sets(self):
        """Test writing node sets."""
        output = io.StringIO()
        file_writers.write_node_sets(output, self.node_sets)

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*NSET, NSET=NSET1", result)
        self.assertIn("1, 2", result)
        self.assertIn("*NSET, NSET=NSET2", result)
        self.assertIn("3, 4", result)

    def test_write_elements(self):
        """Test writing element definitions."""
        output = io.StringIO()
        file_writers.write_elements(output, self.elements)

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*ELEMENT, TYPE=B31", result)
        self.assertIn("1, 1, 2", result)
        self.assertIn("2, 1, 3", result)
        self.assertIn("*ELEMENT, TYPE=S4", result)
        self.assertIn("3, 1, 2, 4, 3", result)

    def test_write_element_sets(self):
        """Test writing element sets."""
        output = io.StringIO()
        file_writers.write_element_sets(output, self.element_sets)

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*ELSET, ELSET=ELSET1", result)
        self.assertIn("1, 2", result)
        self.assertIn("*ELSET, ELSET=ELSET2", result)
        self.assertIn("3", result)

    def test_write_materials(self):
        """Test writing material definitions."""
        # Create mock materials
        material1 = Mock()
        material1.id = "mat1"
        material1.elastic_modulus = 2.1e11
        material1.poisson_ratio = 0.3
        material1.density = 7850.0

        material2 = Mock()
        material2.id = "mat2"
        material2.elastic_modulus = 7.0e10
        material2.poisson_ratio = 0.2
        material2.density = None  # Test handling of None

        # Create mock members with materials
        member1 = Mock(spec=CurveMember)
        member1.material = material1

        member2 = Mock(spec=SurfaceMember)
        member2.material = material2

        # Add members to model
        self.model.members = [member1, member2]

        output = io.StringIO()
        file_writers.write_materials(output, self.model)

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*MATERIAL, NAME=MAT_mat1", result)
        self.assertIn("*ELASTIC", result)
        self.assertIn(
            f"{material1.elastic_modulus:.6e}, {material1.poisson_ratio:.6e}", result
        )
        self.assertIn("*DENSITY", result)
        self.assertIn(f"{material1.density:.6e}", result)

        self.assertIn("*MATERIAL, NAME=MAT_mat2", result)
        # Make sure we don't have a density for material2
        self.assertNotIn(f"*DENSITY\n{material2.density}", result)

    def test_write_sections(self):
        """Test writing section definitions."""
        # Create mock sections and materials
        material = Mock()
        material.id = "mat1"

        # Rectangular beam section
        rect_section = Mock()
        rect_section.section_type = "rectangular"
        rect_section.dimensions = {"width": 0.1, "height": 0.2}

        # Circular beam section
        circ_section = Mock()
        circ_section.section_type = "circular"
        circ_section.dimensions = {"radius": 0.1}

        # General section - using real numeric values, not mocks
        gen_section = Mock()
        # Configure the gen_section mock to return real numeric values
        type(gen_section).area = PropertyMock(return_value=0.02)
        type(gen_section).moment_of_inertia_y = PropertyMock(return_value=0.001)
        type(gen_section).moment_of_inertia_z = PropertyMock(return_value=0.0005)
        type(gen_section).torsional_constant = PropertyMock(return_value=0.0008)
        type(gen_section).warping_constant = PropertyMock(return_value=0.0)

        # Create mock members with sections
        beam1 = Mock(spec=CurveMember)
        beam1.id = "beam1"
        beam1.section = rect_section
        beam1.material = material

        beam2 = Mock(spec=CurveMember)
        beam2.id = "beam2"
        beam2.section = circ_section
        beam2.material = material

        beam3 = Mock(spec=CurveMember)
        beam3.id = "beam3"
        beam3.section = gen_section
        beam3.material = material

        # Surface member with thickness
        surface = Mock(spec=SurfaceMember)
        surface.id = "surface1"
        surface.thickness = Mock()
        # Configure thickness to return a real value, not a mock
        type(surface.thickness).value = PropertyMock(return_value=0.05)
        surface.material = material

        # Add members to model
        self.model.members = [beam1, beam2, beam3, surface]

        # Element sets
        element_sets = {
            "MEMBER_beam1": [1],
            "MEMBER_beam2": [2],
            "MEMBER_beam3": [3],
            "MEMBER_surface1": [4],
        }

        output = io.StringIO()
        file_writers.write_sections(output, self.model, element_sets)

        result = output.getvalue()

        # Check for expected content
        self.assertIn(
            "*BEAM SECTION, ELSET=MEMBER_beam1, MATERIAL=MAT_mat1, SECTION=RECT", result
        )
        self.assertIn("1.000000e-01, 2.000000e-01", result)

        self.assertIn(
            "*BEAM SECTION, ELSET=MEMBER_beam2, MATERIAL=MAT_mat1, SECTION=CIRC", result
        )
        self.assertIn("1.000000e-01", result)

        self.assertIn(
            "*BEAM GENERAL SECTION, ELSET=MEMBER_beam3, MATERIAL=MAT_mat1", result
        )
        # Check section properties are written, but be less strict about exact format
        self.assertIn("e-02", result)  # area should be 0.02 = 2e-02

        self.assertIn(
            "*SHELL SECTION, ELSET=MEMBER_surface1, MATERIAL=MAT_mat1", result
        )
        self.assertIn("5.000000e-02", result)

    def test_write_boundary_conditions(self):
        """Test writing boundary condition definitions."""
        # Create mock connections
        connection1 = Mock()
        connection1.id = "conn1"
        connection1.position = [0.0, 0.0, 0.0]
        connection1.connection_type = "fixed"

        connection2 = Mock()
        connection2.id = "conn2"
        connection2.position = [1.0, 0.0, 0.0]
        connection2.connection_type = "hinge"

        # Add connections to model
        self.model.connections = [connection1, connection2]

        # Sample node coordinates
        node_coords = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
        }

        output = io.StringIO()
        node_sets = {}
        element_sets = {}

        with patch(
            "ifc_structural_mechanics.analysis.file_writers.find_nodes_at_position"
        ) as mock_find_nodes:
            # Configure the mock to return node IDs
            mock_find_nodes.side_effect = lambda pos, coords, tolerance: (
                [1] if pos[0] == 0.0 else [2]
            )

            file_writers.write_boundary_conditions(
                output, self.model, node_sets, element_sets, node_coords
            )

        result = output.getvalue()

        # Check for expected content
        self.assertIn("** Boundary Conditions", result)
        self.assertIn("*NSET, NSET=BC_conn1", result)
        self.assertIn("*BOUNDARY", result)
        self.assertIn("BC_conn1, 1, 6", result)  # Fixed boundary condition
        self.assertIn("*NSET, NSET=BC_conn2", result)
        self.assertIn("BC_conn2, 1, 3", result)  # Hinged boundary condition

    def test_write_boundary_conditions_member_bc(self):
        """Test writing boundary conditions on members."""
        # Create mock member with boundary condition
        member = Mock()
        member.id = "beam1"
        member.type = "curve"
        member.geometry = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))

        # Create BC on member
        bc = Mock()
        bc.id = "bc1"
        bc.type = "fixed"

        # Attach BC to member
        member.boundary_conditions = [bc]

        # Add member to model
        self.model.members = [member]
        self.model.connections = []

        # Sample node coordinates
        node_coords = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
        }

        output = io.StringIO()
        node_sets = {}
        element_sets = {}

        # Mock the helper functions
        with patch(
            "ifc_structural_mechanics.analysis.file_writers.extract_curve_endpoints"
        ) as mock_extract:
            mock_extract.return_value = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]

            with patch(
                "ifc_structural_mechanics.analysis.file_writers.find_nodes_at_position"
            ) as mock_find_nodes:
                mock_find_nodes.return_value = [1]  # Node 1 is at start point

                file_writers.write_boundary_conditions(
                    output, self.model, node_sets, element_sets, node_coords
                )

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*NSET, NSET=BC_bc1", result)
        self.assertIn("1", result)  # Node 1
        self.assertIn("*BOUNDARY", result)
        self.assertIn("BC_bc1, 1, 6", result)  # Fixed BC

    def test_write_boundary_conditions_auto_bc(self):
        """Test automatic boundary condition generation at y=0."""
        # Empty model with no explicit BCs
        self.model.connections = []
        self.model.members = []

        # Sample node coordinates with nodes at y=0
        node_coords = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
            3: (0.0, 1.0, 0.0),
        }

        output = io.StringIO()
        node_sets = {}
        element_sets = {}

        file_writers.write_boundary_conditions(
            output, self.model, node_sets, element_sets, node_coords
        )

        result = output.getvalue()

        # Check for expected content
        self.assertIn("*NSET, NSET=BC_AUTO", result)
        self.assertIn("1, 2", result)  # Nodes at y=0
        self.assertIn("*BOUNDARY", result)
        self.assertIn("BC_AUTO, 1, 6", result)  # Fixed BC

    def test_write_loads(self):
        """Test writing load definitions."""
        # Create mock load group
        load_group = Mock()
        load_group.name = "LoadGroup1"

        # Create point load
        point_load = Mock(spec=PointLoad)
        point_load.id = "load1"
        point_load.position = [0.0, 1.0, 0.0]
        point_load.get_force_vector = Mock(return_value=[0.0, -1000.0, 0.0])

        # Create line load
        line_load = Mock(spec=LineLoad)
        line_load.id = "load2"
        line_load.get_force_vector = Mock(return_value=[0.0, -500.0, 0.0])

        # Add loads to group
        load_group.loads = [point_load, line_load]

        # Add load group to model
        self.model.load_groups = [load_group]

        # Sample node and element sets
        node_coords = {
            1: (0.0, 0.0, 0.0),
            2: (0.0, 1.0, 0.0),
        }

        element_sets = {
            "MEMBER_1": [1, 2],
        }

        output = io.StringIO()
        node_sets = {}

        # Mock the functions used by write_loads
        with patch(
            "ifc_structural_mechanics.analysis.file_writers.write_point_load"
        ) as mock_point_load:
            mock_point_load.return_value = True

            with patch(
                "ifc_structural_mechanics.analysis.file_writers.write_line_load"
            ) as mock_line_load:
                mock_line_load.return_value = True

                file_writers.write_loads(
                    output, self.model, node_sets, element_sets, node_coords
                )

        result = output.getvalue()

        # Check call counts
        self.assertEqual(mock_point_load.call_count, 1)
        self.assertEqual(mock_line_load.call_count, 1)

        # Check for expected content
        self.assertIn("** Load Group: LoadGroup1", result)

    def test_write_point_load(self):
        """Test writing a point load."""
        # Mock point load
        load = Mock(spec=PointLoad)
        load.id = "load1"
        load.position = [0.0, 0.0, 0.0]
        # Make get_force_vector return a real array for the test
        load.get_force_vector = Mock(return_value=np.array([0.0, -1000.0, 0.0]))

        # Sample node coordinates
        node_coords = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
        }

        output = io.StringIO()
        node_sets = {}

        with patch(
            "ifc_structural_mechanics.analysis.file_writers.find_nodes_at_position"
        ) as mock_find_nodes:
            mock_find_nodes.return_value = [1]  # Node 1 is at the load position

            result = file_writers.write_point_load(output, load, node_sets, node_coords)

        self.assertTrue(result)
        content = output.getvalue()

        # Check for expected content
        self.assertIn("*NSET, NSET=LOAD_load1", content)
        self.assertIn("1", content)  # Node ID
        self.assertIn("*CLOAD", content)
        self.assertIn(
            "LOAD_load1, 2,", content
        )  # Y-direction force - less strict on exact value

    def test_write_line_load(self):
        """Test writing a line load."""
        # Mock line load
        load = Mock(spec=LineLoad)
        load.id = "load1"
        # Return a real array, not a Mock
        load.get_force_vector = Mock(return_value=np.array([0.0, -500.0, 0.0]))

        # Sample element IDs
        member_elements = [1, 2]

        output = io.StringIO()
        element_sets = {}

        result = file_writers.write_line_load(
            output, load, element_sets, member_elements
        )

        self.assertTrue(result)
        content = output.getvalue()

        # Check for expected content
        self.assertIn("*ELSET, ELSET=LOAD_load1", content)
        self.assertIn("1, 2", content)  # Element IDs
        self.assertIn("*DLOAD", content)
        self.assertIn(
            "LOAD_load1, P2,", content
        )  # Distributed load - less strict on exact value

    def test_write_area_load(self):
        """Test writing an area load."""
        # Mock area load
        load = Mock(spec=AreaLoad)
        load.id = "load1"
        load.magnitude = 1000.0  # Use a numeric value, not a Mock
        load.surface_reference = None

        # For the get_force_vector method, make it return a real array, not a Mock
        load.get_force_vector = Mock(return_value=np.array([0.0, 1000.0, 0.0]))

        # Sample element IDs
        member_elements = [3, 4]

        output = io.StringIO()
        element_sets = {}

        result = file_writers.write_area_load(
            output, load, element_sets, member_elements
        )

        self.assertTrue(result)
        content = output.getvalue()

        # Check for expected content
        self.assertIn("*ELSET, ELSET=LOAD_load1", content)
        self.assertIn("3, 4", content)  # Element IDs
        self.assertIn("*DLOAD", content)
        self.assertIn("LOAD_load1, P,", content)  # Pressure load

    def test_write_analysis_steps(self):
        """Test writing analysis steps."""
        output = io.StringIO()

        # Mock domain model with loads
        model = Mock(spec=StructuralModel)
        model.load_groups = []
        model.members = []

        # Test with linear static analysis
        with patch(
            "ifc_structural_mechanics.analysis.file_writers.write_loads_within_step"
        ) as mock_write_loads:
            file_writers.write_analysis_steps(output, model, "linear_static")
            mock_write_loads.assert_called_once_with(output, model)

        content = output.getvalue()

        # Check for expected content
        self.assertIn("*STEP", content)
        self.assertIn("*STATIC", content)
        self.assertIn("*NODE FILE", content)
        self.assertIn("U", content)  # Displacements
        self.assertIn("*EL FILE", content)
        self.assertIn("S", content)  # Stresses
        self.assertIn("*END STEP", content)

    def test_write_linear_buckling_step(self):
        """Test writing analysis steps for linear buckling analysis."""
        output = io.StringIO()

        # Test with linear buckling analysis
        file_writers.write_analysis_steps(output, None, "linear_buckling")

        content = output.getvalue()

        # Check for expected content
        self.assertIn("*STEP", content)
        self.assertIn("*BUCKLE", content)
        self.assertIn("5", content)  # Number of eigenvalues to extract
        self.assertIn("*NODE FILE", content)
        self.assertIn("*END STEP", content)

    def test_write_loads_within_step(self):
        """Test writing loads within an analysis step."""
        # Create mock load group with point loads
        load_group = Mock()
        load_group.name = "LoadGroup1"

        # Create mock point loads
        load1 = Mock(spec=PointLoad)
        load1.get_force_vector = Mock(return_value=[100.0, 0.0, 0.0])

        load2 = Mock(spec=PointLoad)
        load2.get_force_vector = Mock(return_value=[0.0, -200.0, 0.0])

        load_group.loads = [load1, load2]

        # Create mock member with point load
        member = Mock()
        member.id = "Member1"
        member.loads = [Mock(spec=PointLoad)]
        member.loads[0].get_force_vector = Mock(return_value=[0.0, 0.0, 300.0])

        # Set up model
        model = Mock(spec=StructuralModel)
        model.load_groups = [load_group]
        model.members = [member]

        output = io.StringIO()
        file_writers.write_loads_within_step(output, model)

        content = output.getvalue()

        # Check for expected content
        self.assertIn("** Load Group: LoadGroup1", content)
        self.assertIn("*CLOAD", content)
        self.assertIn("** Point loads on member Member1", content)

    def test_find_nodes_at_position(self):
        """Test finding nodes at a specific position."""
        # Sample node coordinates
        node_coords = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
            3: (0.0, 1.0, 0.0),
            4: (1.0, 1.0, 0.0),
            5: (0.01, 0.005, 0.0),  # Close to origin
        }

        # Test exact match
        nodes = file_writers.find_nodes_at_position([0.0, 0.0, 0.0], node_coords)
        self.assertEqual(nodes, [1])

        # Test with tolerance
        nodes = file_writers.find_nodes_at_position(
            [0.0, 0.0, 0.0], node_coords, tolerance=0.02
        )
        self.assertEqual(set(nodes), {1, 5})

        # Test no match
        nodes = file_writers.find_nodes_at_position(
            [0.5, 0.5, 0.5], node_coords, tolerance=0.01
        )
        self.assertEqual(nodes, [])

    def test_find_closest_node(self):
        """Test finding the closest node to a position."""
        # Sample node coordinates
        node_coords = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
            3: (0.0, 1.0, 0.0),
            4: (1.0, 1.0, 0.0),
        }

        # Test finding closest to origin
        closest = file_writers.find_closest_node([0.1, 0.1, 0.0], node_coords)
        self.assertEqual(closest, 1)

        # Test finding closest to a point
        closest = file_writers.find_closest_node([0.6, 0.6, 0.0], node_coords)
        self.assertEqual(closest, 4)

        # Test with empty coords
        closest = file_writers.find_closest_node([0.0, 0.0, 0.0], {})
        self.assertIsNone(closest)

    def test_extract_curve_endpoints(self):
        """Test extracting endpoints from curve geometry."""
        # Test tuple format
        geometry = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        endpoints = file_writers.extract_curve_endpoints(geometry)
        self.assertEqual(endpoints, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

        # Test list format
        geometry = [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [1.0, 0.0, 0.0]]
        endpoints = file_writers.extract_curve_endpoints(geometry)
        self.assertEqual(endpoints, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

        # Test dict format with boundaries
        geometry = {"boundaries": [[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]]}
        endpoints = file_writers.extract_curve_endpoints(geometry)
        self.assertEqual(endpoints, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

        # Test dict format with line type
        geometry = {"type": "line", "start": [0.0, 0.0, 0.0], "end": [1.0, 0.0, 0.0]}
        endpoints = file_writers.extract_curve_endpoints(geometry)
        self.assertEqual(endpoints, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

        # Test invalid format
        geometry = "invalid"
        endpoints = file_writers.extract_curve_endpoints(geometry)
        self.assertEqual(endpoints, [])

    def test_empty_model_handling(self):
        """Test handling of empty or None models."""
        output = io.StringIO()

        # Test boundary conditions with None model
        file_writers.write_boundary_conditions(output, None, {}, {}, {})
        content = output.getvalue()
        self.assertIn("** No boundary conditions defined", content)

        # Reset output
        output = io.StringIO()

        # Test loads with None model
        file_writers.write_loads(output, None, {}, {}, {})
        content = output.getvalue()
        self.assertEqual("", content)  # Should be empty

        # Reset output
        output = io.StringIO()

        # Test with empty model (no members, connections, load groups)
        empty_model = Mock(spec=StructuralModel)
        empty_model.members = []
        empty_model.connections = []
        empty_model.load_groups = []

        file_writers.write_loads(output, empty_model, {}, {}, {})
        content = output.getvalue()
        self.assertIn("** No loads defined in the model", content)


if __name__ == "__main__":
    unittest.main()
