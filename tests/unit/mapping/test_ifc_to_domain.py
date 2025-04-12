"""
Unit tests for IFC to domain model mapping.
Updated to work with the new domain model API.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import uuid
import ifcopenshell

from ifc_structural_mechanics.mapping.ifc_to_domain import (
    Mapper,
    StructuralModelMapper,
    StructuralMemberMapper,
    StructuralConnectionMapper,
    MaterialMapper,
    SectionMapper,
    ThicknessMapper,
    LoadMapper,
)

from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_connection import (
    PointConnection,
    RigidConnection,
    HingeConnection,
)
from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.load import PointLoad, LineLoad, AreaLoad


class TestMapper(unittest.TestCase):
    """Tests for the base Mapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = Mapper()

        # Create a mock entity
        self.mock_entity = Mock(spec=ifcopenshell.entity_instance)
        self.mock_entity.id.return_value = "1"
        # Set up is_a to handle both general function call and specific entity type check
        self.mock_entity.is_a = MagicMock(
            side_effect=lambda x=None: x == "IfcTestEntity" if x else "IfcTestEntity"
        )
        self.mock_entity.GlobalId = "test_entity_1"
        self.mock_entity.Name = "Test Entity"

    def test_register_mapping(self):
        """Test registering a mapping."""

        class TestDomainObject:
            def __init__(self, id, name):
                self.id = id
                self.name = name

        # Register a mapping
        self.mapper.register_mapping(
            "IfcTestEntity",
            TestDomainObject,
            {"id": lambda e: e.GlobalId, "name": lambda e: e.Name},
        )

        # Check that the mapping was registered
        self.assertIn("IfcTestEntity", self.mapper._entity_mappings)
        self.assertEqual(
            self.mapper._entity_mappings["IfcTestEntity"]["target_class"],
            TestDomainObject,
        )

    def test_map_entity(self):
        """Test mapping an entity."""

        class TestDomainObject:
            def __init__(self, id, name):
                self.id = id
                self.name = name

        # Register a mapping
        self.mapper.register_mapping(
            "IfcTestEntity",
            TestDomainObject,
            {"id": lambda e: e.GlobalId, "name": lambda e: e.Name},
        )

        # Map the entity
        result = self.mapper.map_entity(self.mock_entity)

        # Check the result
        self.assertIsInstance(result, TestDomainObject)
        self.assertEqual(result.id, "test_entity_1")
        self.assertEqual(result.name, "Test Entity")

    def test_post_processor(self):
        """Test post-processing."""

        class TestDomainObject:
            def __init__(self, id, name):
                self.id = id
                self.name = name
                self.processed = False

        # Register a mapping
        self.mapper.register_mapping(
            "IfcTestEntity",
            TestDomainObject,
            {"id": lambda e: e.GlobalId, "name": lambda e: e.Name},
        )

        # Register a post-processor
        def post_processor(obj, entity):
            obj.processed = True

        self.mapper.register_post_processor(post_processor)

        # Map the entity
        result = self.mapper.map_entity(self.mock_entity)

        # Check that post-processing was applied
        self.assertTrue(result.processed)


class TestStructuralMemberMapper(unittest.TestCase):
    """Tests for the StructuralMemberMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = StructuralMemberMapper()

        # Create mock curve member
        self.mock_curve_member = Mock(spec=ifcopenshell.entity_instance)
        self.mock_curve_member.id.return_value = "1"
        # Set up is_a to handle both calls
        self.mock_curve_member.is_a = MagicMock(
            side_effect=lambda x=None: (
                x == "IfcStructuralCurveMember" if x else "IfcStructuralCurveMember"
            )
        )
        self.mock_curve_member.GlobalId = "curve_member_1"
        self.mock_curve_member.Name = "Beam 1"

        # Create mock surface member
        self.mock_surface_member = Mock(spec=ifcopenshell.entity_instance)
        self.mock_surface_member.id.return_value = "2"
        # Set up is_a to handle both calls
        self.mock_surface_member.is_a = MagicMock(
            side_effect=lambda x=None: (
                x == "IfcStructuralSurfaceMember" if x else "IfcStructuralSurfaceMember"
            )
        )
        self.mock_surface_member.GlobalId = "surface_member_1"
        self.mock_surface_member.Name = "Wall 1"

    @patch(
        "ifc_structural_mechanics.mapping.ifc_to_domain.curve_geometry.extract_curve_geometry"
    )
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.find_related_material")
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.find_related_profile")
    def test_map_curve_member(
        self, mock_find_profile, mock_find_material, mock_extract_curve
    ):
        """Test mapping a curve member."""
        # Mock geometry, material, and section
        mock_geometry = ((0, 0, 0), (10, 0, 0))
        mock_material_entity = Mock(spec=ifcopenshell.entity_instance)
        mock_material_entity.Name = "Steel"
        mock_material_entity.is_a = MagicMock(return_value=True)
        mock_material_entity.GlobalId = (
            "material_1"
            if hasattr(mock_material_entity, "GlobalId")
            else str(uuid.uuid4())
        )

        mock_profile_entity = Mock(spec=ifcopenshell.entity_instance)
        mock_profile_entity.is_a = MagicMock(
            side_effect=lambda x: x == "IfcRectangleProfileDef"
        )
        mock_profile_entity.GlobalId = (
            "profile_1"
            if hasattr(mock_profile_entity, "GlobalId")
            else str(uuid.uuid4())
        )
        mock_profile_entity.XDim = 0.2
        mock_profile_entity.YDim = 0.3

        # Set up mock returns
        mock_extract_curve.return_value = mock_geometry
        mock_find_material.return_value = mock_material_entity
        mock_find_profile.return_value = mock_profile_entity

        # Patch any additional dependencies
        with patch.object(
            MaterialMapper,
            "map_entity",
            return_value=Material(
                id="material_1",
                name="Steel",
                density=7850.0,
                elastic_modulus=210e9,
                poisson_ratio=0.3,
            ),
        ):
            with patch.object(
                SectionMapper,
                "map_entity",
                return_value=Section.create_rectangular_section(
                    id="section_1", name="Rectangle Section", width=0.2, height=0.3
                ),
            ):

                # Map the curve member
                result = self.mapper.map_curve_member(self.mock_curve_member)

                # Check the result
                self.assertIsInstance(result, CurveMember)
                self.assertEqual(result.id, "curve_member_1")
                self.assertEqual(result.entity_type, "curve")
                self.assertEqual(result.geometry, mock_geometry)
                self.assertIsInstance(result.material, Material)
                self.assertIsInstance(result.section, Section)

    @patch(
        "ifc_structural_mechanics.mapping.ifc_to_domain.surface_geometry.extract_surface_geometry"
    )
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.find_related_material")
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.find_related_properties")
    def test_map_surface_member(
        self, mock_find_properties, mock_find_material, mock_extract_surface
    ):
        """Test mapping a surface member."""
        # Mock geometry and material
        mock_geometry = {
            "type": "plane",
            "normal": (0, 0, 1),
            "point": (0, 0, 0),
            "x_dir": (1, 0, 0),
            "y_dir": (0, 1, 0),
            "boundaries": [[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]],
        }
        mock_material_entity = Mock(spec=ifcopenshell.entity_instance)
        mock_material_entity.Name = "Concrete"
        mock_material_entity.is_a = MagicMock(return_value=True)
        mock_material_entity.GlobalId = (
            "material_2"
            if hasattr(mock_material_entity, "GlobalId")
            else str(uuid.uuid4())
        )

        # Mock property sets with thickness
        mock_property = Mock()
        mock_property.Name = "Thickness"
        mock_property.NominalValue = Mock()
        mock_property.NominalValue.wrappedValue = 0.3

        mock_pset = Mock()
        mock_pset.HasProperties = [mock_property]

        # Set up mock returns
        mock_extract_surface.return_value = mock_geometry
        mock_find_material.return_value = mock_material_entity
        mock_find_properties.return_value = [mock_pset]

        # Patch any additional dependencies
        with patch.object(
            MaterialMapper,
            "map_entity",
            return_value=Material(
                id="material_2",
                name="Concrete",
                density=2400.0,
                elastic_modulus=30e9,
                poisson_ratio=0.2,
            ),
        ):
            with patch.object(
                ThicknessMapper,
                "map_entity",
                return_value=Thickness(
                    id="thickness_1", name="Wall Thickness", value=0.3
                ),
            ):

                # Map the surface member
                result = self.mapper.map_surface_member(self.mock_surface_member)

                # Check the result
                self.assertIsInstance(result, SurfaceMember)
                self.assertEqual(result.id, "surface_member_1")
                self.assertEqual(result.entity_type, "surface")
                self.assertEqual(result.geometry, mock_geometry)
                self.assertIsInstance(result.material, Material)
                self.assertIsInstance(result.thickness, Thickness)
                self.assertEqual(result.thickness.value, 0.3)


class TestStructuralConnectionMapper(unittest.TestCase):
    """Tests for the StructuralConnectionMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = StructuralConnectionMapper()

        # Create mock entities
        self.mock_point_connection = Mock(spec=ifcopenshell.entity_instance)
        self.mock_point_connection.id.return_value = "3"
        self.mock_point_connection.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralPointConnection"
        )
        self.mock_point_connection.GlobalId = "point_connection_1"

        # Mock location for connection
        mock_placement = Mock()
        mock_relative = Mock()
        mock_location = Mock()
        mock_coords = [1.0, 2.0, 3.0]

        mock_location.Coordinates = mock_coords
        mock_relative.Location = mock_location
        mock_placement.RelativePlacement = mock_relative
        self.mock_point_connection.ObjectPlacement = mock_placement

    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_connection")
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.analyze_connection_type")
    def test_map_point_connection(self, mock_analyze_type, mock_is_connection):
        """Test mapping a point connection."""
        # Mock connection type and validation
        mock_is_connection.return_value = True
        mock_analyze_type.return_value = "point"

        # Map the connection
        result = self.mapper.map_connection(self.mock_point_connection)

        # Check the result
        self.assertIsInstance(result, PointConnection)
        self.assertEqual(result.id, "point_connection_1")
        self.assertEqual(result.position, [1.0, 2.0, 3.0])

    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_connection")
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.analyze_connection_type")
    def test_map_rigid_connection(self, mock_analyze_type, mock_is_connection):
        """Test mapping a rigid connection."""
        # Mock connection type and validation
        mock_is_connection.return_value = True
        mock_analyze_type.return_value = "rigid"

        # Map the connection
        result = self.mapper.map_connection(self.mock_point_connection)

        # Check the result
        self.assertIsInstance(result, RigidConnection)
        self.assertEqual(result.id, "point_connection_1")
        self.assertEqual(result.position, [1.0, 2.0, 3.0])

    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_connection")
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.analyze_connection_type")
    def test_map_hinge_connection(self, mock_analyze_type, mock_is_connection):
        """Test mapping a hinge connection."""
        # Mock connection type and validation
        mock_is_connection.return_value = True
        mock_analyze_type.return_value = "hinge"

        # Mock rotation axis
        mock_cs = Mock()
        mock_axis = Mock()
        mock_axis.DirectionRatios = [0.0, 0.0, 1.0]
        mock_cs.Axis = mock_axis
        self.mock_point_connection.ConditionCoordinateSystem = mock_cs

        # Map the connection
        result = self.mapper.map_connection(self.mock_point_connection)

        # Check the result
        self.assertIsInstance(result, HingeConnection)
        self.assertEqual(result.id, "point_connection_1")
        self.assertEqual(result.position, [1.0, 2.0, 3.0])
        self.assertEqual(result.rotation_axis, [0.0, 0.0, 1.0])


class TestMaterialMapper(unittest.TestCase):
    """Tests for the MaterialMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = MaterialMapper()

        # Create a mock material entity
        self.mock_material = Mock(spec=ifcopenshell.entity_instance)
        self.mock_material.id.return_value = "4"
        self.mock_material.is_a = MagicMock(side_effect=lambda x: x == "IfcMaterial")
        self.mock_material.GlobalId = "material_1"
        self.mock_material.Name = "Steel"

    def test_map_material(self):
        """Test mapping a material."""
        # Mock material properties
        mock_density_prop = Mock()
        mock_density_prop.Name = "MassDensity"
        mock_density_prop.NominalValue = Mock()
        mock_density_prop.NominalValue.wrappedValue = 7850.0

        mock_modulus_prop = Mock()
        mock_modulus_prop.Name = "YoungModulus"
        mock_modulus_prop.NominalValue = Mock()
        mock_modulus_prop.NominalValue.wrappedValue = 210e9

        mock_poisson_prop = Mock()
        mock_poisson_prop.Name = "PoissonRatio"
        mock_poisson_prop.NominalValue = Mock()
        mock_poisson_prop.NominalValue.wrappedValue = 0.3

        self.mock_material.HasProperties = [
            mock_density_prop,
            mock_modulus_prop,
            mock_poisson_prop,
        ]

        # Map the material
        result = self.mapper.map_material(self.mock_material)

        # Check the result
        self.assertIsInstance(result, Material)
        self.assertEqual(result.name, "Steel")
        self.assertEqual(result.density, 7850.0)
        self.assertEqual(result.elastic_modulus, 210e9)
        self.assertEqual(result.poisson_ratio, 0.3)


class TestSectionMapper(unittest.TestCase):
    """Tests for the SectionMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = SectionMapper()

        # Create mock profile entities
        self.mock_rectangle_profile = Mock(spec=ifcopenshell.entity_instance)
        self.mock_rectangle_profile.id.return_value = "5"
        self.mock_rectangle_profile.is_a = MagicMock(
            side_effect=lambda x: x == "IfcRectangleProfileDef"
        )
        self.mock_rectangle_profile.GlobalId = "profile_1"
        self.mock_rectangle_profile.Name = "Rectangle 200x300"
        self.mock_rectangle_profile.XDim = 0.2
        self.mock_rectangle_profile.YDim = 0.3

        self.mock_circle_profile = Mock(spec=ifcopenshell.entity_instance)
        self.mock_circle_profile.id.return_value = "6"
        self.mock_circle_profile.is_a = MagicMock(
            side_effect=lambda x: x == "IfcCircleProfileDef"
        )
        self.mock_circle_profile.GlobalId = "profile_2"
        self.mock_circle_profile.Name = "Circle D200"
        self.mock_circle_profile.Radius = 0.1

        self.mock_i_profile = Mock(spec=ifcopenshell.entity_instance)
        self.mock_i_profile.id.return_value = "7"
        self.mock_i_profile.is_a = MagicMock(
            side_effect=lambda x: x == "IfcIShapeProfileDef"
        )
        self.mock_i_profile.GlobalId = "profile_3"
        self.mock_i_profile.Name = "I-Beam 300x150"
        self.mock_i_profile.OverallWidth = 0.15
        self.mock_i_profile.OverallDepth = 0.3
        self.mock_i_profile.WebThickness = 0.008
        self.mock_i_profile.FlangeThickness = 0.012

    def test_map_rectangle_section(self):
        """Test mapping a rectangular section."""
        # Map the profile
        result = self.mapper.map_section(self.mock_rectangle_profile)

        # Check the result
        self.assertIsInstance(result, Section)
        self.assertEqual(result.name, "Rectangle 200x300")
        self.assertEqual(result.section_type, "rectangular")
        self.assertEqual(result.area, 0.2 * 0.3)
        self.assertEqual(result.dimensions["width"], 0.2)
        self.assertEqual(result.dimensions["height"], 0.3)

    def test_map_circle_section(self):
        """Test mapping a circular section."""
        # Map the profile
        result = self.mapper.map_section(self.mock_circle_profile)

        # Check the result
        self.assertIsInstance(result, Section)
        self.assertEqual(result.name, "Circle D200")
        self.assertEqual(result.section_type, "circular")
        self.assertAlmostEqual(result.area, 3.14159 * 0.1 * 0.1, places=5)
        self.assertEqual(result.dimensions["radius"], 0.1)

    def test_map_i_section(self):
        """Test mapping an I-section."""
        # Map the profile
        result = self.mapper.map_section(self.mock_i_profile)

        # Check the result
        self.assertIsInstance(result, Section)
        self.assertEqual(result.name, "I-Beam 300x150")
        self.assertEqual(result.section_type, "i")
        # Area should be flanges + web
        expected_area = 0.15 * 0.012 * 2 + (0.3 - 2 * 0.012) * 0.008
        self.assertAlmostEqual(result.area, expected_area, places=5)
        self.assertEqual(result.dimensions["width"], 0.15)
        self.assertEqual(result.dimensions["height"], 0.3)
        self.assertEqual(result.dimensions["web_thickness"], 0.008)
        self.assertEqual(result.dimensions["flange_thickness"], 0.012)


class TestThicknessMapper(unittest.TestCase):
    """Tests for the ThicknessMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = ThicknessMapper()

        # Create a mock entity with thickness
        self.mock_wall = Mock(spec=ifcopenshell.entity_instance)
        self.mock_wall.id.return_value = "8"
        self.mock_wall.is_a = MagicMock(side_effect=lambda x: x == "IfcWall")
        self.mock_wall.GlobalId = "wall_1"
        self.mock_wall.Name = "Wall 1"
        self.mock_wall.Thickness = 0.25

    def test_map_thickness(self):
        """Test mapping thickness."""
        # Map the thickness
        result = self.mapper.map_thickness(self.mock_wall)

        # Check the result
        self.assertIsInstance(result, Thickness)
        self.assertEqual(result.value, 0.25)
        self.assertFalse(result.is_variable)


class TestLoadMapper(unittest.TestCase):
    """Tests for the LoadMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = LoadMapper()

        # Create mock load entities
        self.mock_point_load = Mock(spec=ifcopenshell.entity_instance)
        self.mock_point_load.id.return_value = "9"
        self.mock_point_load.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralPointAction"
        )
        self.mock_point_load.GlobalId = "load_1"
        self.mock_point_load.ForceX = 1000.0
        self.mock_point_load.ForceY = 0.0
        self.mock_point_load.ForceZ = -2000.0

        self.mock_line_load = Mock(spec=ifcopenshell.entity_instance)
        self.mock_line_load.id.return_value = "10"
        self.mock_line_load.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralLineLoad"
        )
        self.mock_line_load.GlobalId = "load_2"
        self.mock_line_load.ForceX = 0.0
        self.mock_line_load.ForceY = 0.0
        self.mock_line_load.ForceZ = -5000.0

        self.mock_area_load = Mock(spec=ifcopenshell.entity_instance)
        self.mock_area_load.id.return_value = "11"
        self.mock_area_load.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralAreaLoad"
        )
        self.mock_area_load.GlobalId = "load_3"
        self.mock_area_load.ForceX = 0.0
        self.mock_area_load.ForceY = 0.0
        self.mock_area_load.ForceZ = -10000.0

    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_load")
    def test_map_point_load(self, mock_is_load):
        """Test mapping a point load."""
        # Set up mock validation
        mock_is_load.return_value = True

        # Map the load
        result = self.mapper.map_load(self.mock_point_load)

        # Check the result
        self.assertIsInstance(result, PointLoad)
        self.assertEqual(result.id, "load_1")
        self.assertEqual(result.magnitude[0], 1000.0)
        self.assertEqual(result.magnitude[1], 0.0)
        self.assertEqual(result.magnitude[2], -2000.0)

    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_load")
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.find_member_endpoints")
    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_curve_member")
    def test_map_line_load(
        self, mock_is_curve_member, mock_find_endpoints, mock_is_load
    ):
        """Test mapping a line load."""
        # Set up mock validation
        mock_is_load.return_value = True
        mock_is_curve_member.return_value = True
        mock_find_endpoints.return_value = [(0, 0, 0), (10, 0, 0)]

        # Mock endpoints for line load
        mock_action = Mock()
        mock_assign = Mock()
        mock_member = Mock()
        mock_member.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralCurveMember"
        )
        mock_member.GlobalId = "curve_member_1"

        mock_assign.RelatingElement = mock_member
        mock_action.AssignedToStructuralItem = [mock_assign]
        mock_action.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralCurveAction"
        )

        mock_rel = Mock()
        mock_rel.RelatedStructuralActivity = mock_action

        self.mock_line_load.AppliedLoads = [mock_rel]

        # Map the load
        result = self.mapper.map_load(self.mock_line_load)

        # Check the result
        self.assertIsInstance(result, LineLoad)
        self.assertEqual(result.id, "load_2")
        self.assertEqual(result.magnitude[2], -5000.0)
        self.assertEqual(result.start_position, (0, 0, 0))
        self.assertEqual(result.end_position, (10, 0, 0))

    @patch("ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_load")
    @patch(
        "ifc_structural_mechanics.mapping.ifc_to_domain.is_structural_surface_member"
    )
    def test_map_area_load(self, mock_is_surface_member, mock_is_load):
        """Test mapping an area load."""
        # Set up mock validation
        mock_is_load.return_value = True
        mock_is_surface_member.return_value = True

        # Mock surface reference for area load
        mock_action = Mock()
        mock_assign = Mock()
        mock_member = Mock()
        mock_member.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralSurfaceMember"
        )
        mock_member.GlobalId = "surface_member_1"

        mock_assign.RelatingElement = mock_member
        mock_action.AssignedToStructuralItem = [mock_assign]
        mock_action.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralSurfaceAction"
        )

        mock_rel = Mock()
        mock_rel.RelatedStructuralActivity = mock_action

        self.mock_area_load.AppliedLoads = [mock_rel]

        # Map the load
        result = self.mapper.map_load(self.mock_area_load)

        # Check the result
        self.assertIsInstance(result, AreaLoad)
        self.assertEqual(result.id, "load_3")
        self.assertEqual(result.magnitude[2], -10000.0)
        self.assertEqual(result.surface_reference, "surface_member_1")


class TestStructuralModelMapper(unittest.TestCase):
    """Tests for the StructuralModelMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = StructuralModelMapper()

        # Create a mock IFC file
        self.mock_ifc_file = Mock(spec=ifcopenshell.file)

        # Mock project information
        mock_project = Mock()
        mock_project.Name = "Test Project"

        # Mock entities to be found in the file
        mock_curve_member = Mock()
        mock_curve_member.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralCurveMember"
        )
        mock_curve_member.GlobalId = "curve_member_1"

        mock_surface_member = Mock()
        mock_surface_member.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralSurfaceMember"
        )
        mock_surface_member.GlobalId = "surface_member_1"

        mock_connection = Mock()
        mock_connection.is_a = MagicMock(
            side_effect=lambda x: x == "IfcStructuralPointConnection"
        )
        mock_connection.GlobalId = "connection_1"

        # Mock by_type method
        def mock_by_type(entity_type):
            if entity_type == "IfcProject":
                return [mock_project]
            elif entity_type == "IfcStructuralCurveMember":
                return [mock_curve_member]
            elif entity_type == "IfcStructuralSurfaceMember":
                return [mock_surface_member]
            elif entity_type == "IfcStructuralPointConnection":
                return [mock_connection]
            else:
                return []

        self.mock_ifc_file.by_type = mock_by_type

    @patch(
        "ifc_structural_mechanics.mapping.ifc_to_domain.StructuralMemberMapper.map_curve_member"
    )
    @patch(
        "ifc_structural_mechanics.mapping.ifc_to_domain.StructuralMemberMapper.map_surface_member"
    )
    @patch(
        "ifc_structural_mechanics.mapping.ifc_to_domain.StructuralConnectionMapper.map_connection"
    )
    def test_map_model(self, mock_map_connection, mock_map_surface, mock_map_curve):
        """Test mapping a structural model."""
        # Mock domain objects
        mock_curve_domain = Mock(spec=CurveMember)
        mock_curve_domain.id = "curve_member_1"

        mock_surface_domain = Mock(spec=SurfaceMember)
        mock_surface_domain.id = "surface_member_1"

        mock_connection_domain = Mock(spec=PointConnection)
        mock_connection_domain.id = "connection_1"

        # Set up mock returns
        mock_map_curve.return_value = mock_curve_domain
        mock_map_surface.return_value = mock_surface_domain
        mock_map_connection.return_value = mock_connection_domain

        # Map the model
        result = self.mapper.map_model(self.mock_ifc_file)

        # Check the result
        self.assertEqual(result.name, "Test Project")
        self.assertEqual(len(result.members), 2)
        self.assertEqual(len(result.connections), 1)
        self.assertEqual(result.members[0], mock_curve_domain)
        self.assertEqual(result.members[1], mock_surface_domain)
        self.assertEqual(result.connections[0], mock_connection_domain)


if __name__ == "__main__":
    unittest.main()
