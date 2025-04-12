"""
Structural connection extractor for IFC structural analysis models.

This module contains the ConnectionsExtractor class which is responsible for
extracting structural connections from IFC files and converting them into
domain model objects.
"""

import logging
from typing import List, Optional, Union, Dict

import ifcopenshell
import numpy as np

from ..domain.structural_connection import (
    StructuralConnection,
    PointConnection,
    RigidConnection,
    HingeConnection,
)

from .entity_identifier import (
    analyze_connection_type,
    get_coordinate,
    get_representation,
    get_transformation,
    transform_vectors,
    get_0D_orientation,
    get_1D_orientation,
    find_connected_elements,
)


class ConnectionsExtractor:
    """
    Extracts structural connections from IFC models.

    This class provides methods to extract structural connections from
    IFC files and convert them to domain model objects.
    """

    def __init__(
        self,
        ifc_file: Union[str, ifcopenshell.file],
        unit_scales: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize a ConnectionsExtractor.

        Args:
            ifc_file: Path to an IFC file or an ifcopenshell.file object
            unit_scales: Dictionary of unit scale factors for different unit types

        Raises:
            ValueError: If ifc_file is invalid
            FileNotFoundError: If the IFC file does not exist
        """
        self.logger = logging.getLogger(__name__)

        # Handle different input types
        if isinstance(ifc_file, str):
            try:
                self.ifc = ifcopenshell.open(ifc_file)
                self.logger.info(f"Opened IFC file: {ifc_file}")
            except Exception as e:
                self.logger.error(f"Failed to open IFC file: {e}")
                raise FileNotFoundError(f"Could not open IFC file: {ifc_file}")
        elif hasattr(ifc_file, "by_type") and callable(ifc_file.by_type):
            # This is likely an ifcopenshell.file object or a valid mock
            self.ifc = ifc_file
            self.logger.info("Using provided ifcopenshell.file object")
        else:
            self.logger.error("Invalid IFC file parameter provided")
            raise ValueError(
                "ifc_file must be a file path or an ifcopenshell.file object"
            )

        # Store unit scales
        self.unit_scales = unit_scales or {}
        self.length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)

    def extract_all_connections(self) -> List[StructuralConnection]:
        """
        Extract all structural connections from the IFC file.

        Returns:
            List of extracted structural connections as domain objects
        """
        self.logger.info("Extracting all structural connections")

        # Get all structural connection entities
        connection_entities = []

        # Find point connections
        try:
            point_connections = list(self.ifc.by_type("IfcStructuralPointConnection"))
            connection_entities.extend(point_connections)
            self.logger.info(f"Found {len(point_connections)} point connections")
        except Exception as e:
            self.logger.warning(
                f"Error finding IfcStructuralPointConnection entities: {e}"
            )

        # Find curve connections
        try:
            curve_connections = list(self.ifc.by_type("IfcStructuralCurveConnection"))
            connection_entities.extend(curve_connections)
            self.logger.info(f"Found {len(curve_connections)} curve connections")
        except Exception as e:
            self.logger.warning(
                f"Error finding IfcStructuralCurveConnection entities: {e}"
            )

        # Find surface connections
        try:
            surface_connections = list(
                self.ifc.by_type("IfcStructuralSurfaceConnection")
            )
            connection_entities.extend(surface_connections)
            self.logger.info(f"Found {len(surface_connections)} surface connections")
        except Exception as e:
            self.logger.warning(
                f"Error finding IfcStructuralSurfaceConnection entities: {e}"
            )

        # Convert entities to domain objects
        connections = []
        for entity in connection_entities:
            try:
                connection = self._create_domain_connection(entity)
                if connection:
                    connections.append(connection)
            except Exception as e:
                self.logger.error(
                    f"Error extracting connection {getattr(entity, 'GlobalId', 'unknown')}: {e}"
                )

        self.logger.info(f"Extracted {len(connections)} structural connections")
        return connections

    def extract_connection_by_id(
        self, connection_id: str
    ) -> Optional[StructuralConnection]:
        """
        Extract a specific structural connection by ID.

        Args:
            connection_id: GlobalId of the connection to extract

        Returns:
            The extracted structural connection or None if not found
        """
        self.logger.info(f"Extracting structural connection with ID: {connection_id}")

        try:
            # First try to find by GlobalId
            for entity_type in [
                "IfcStructuralPointConnection",
                "IfcStructuralCurveConnection",
                "IfcStructuralSurfaceConnection",
            ]:
                for entity in self.ifc.by_type(entity_type):
                    if entity.GlobalId == connection_id:
                        return self._create_domain_connection(entity)

            # If not found by GlobalId, try by ID
            try:
                entity = self.ifc.by_id(connection_id)
                return self._create_domain_connection(entity)
            except:
                self.logger.warning(f"Connection with ID {connection_id} not found")
                return None

        except Exception as e:
            self.logger.error(f"Error extracting connection {connection_id}: {e}")
            return None

    def _create_domain_connection(
        self, ifc_connection
    ) -> Optional[StructuralConnection]:
        """
        Create a domain connection object from an IFC connection entity.

        Args:
            ifc_connection: IFC connection entity

        Returns:
            Domain connection object or None if creation fails
        """
        try:
            connection_type = analyze_connection_type(ifc_connection)

            # Extract representation and geometry
            if ifc_connection.is_a("IfcStructuralPointConnection"):
                representation = get_representation(ifc_connection, "Vertex")
                if not representation:
                    self.logger.warning(
                        f"No representation found for {ifc_connection.GlobalId}"
                    )
                    return None

                geometry = self._extract_geometry(representation)

                # Get orientation or use default
                orientation = None
                if (
                    hasattr(ifc_connection, "ConditionCoordinateSystem")
                    and ifc_connection.ConditionCoordinateSystem
                ):
                    orientation = get_0D_orientation(
                        ifc_connection.ConditionCoordinateSystem
                    )

                if not orientation:
                    orientation = np.eye(3).tolist()

                # Apply transformation if available
                transformation = None
                if (
                    hasattr(ifc_connection, "ObjectPlacement")
                    and ifc_connection.ObjectPlacement
                ):
                    transformation = get_transformation(ifc_connection.ObjectPlacement)

                if transformation:
                    try:
                        geometry = transform_vectors(geometry, transformation)
                        orientation = transform_vectors(
                            [orientation], transformation, include_translation=False
                        )[0]
                    except Exception as e:
                        self.logger.warning(f"Error applying transformation: {e}")

                # Apply unit scale to geometry
                if isinstance(geometry, list):
                    if all(isinstance(g, list) for g in geometry):
                        # List of points
                        geometry = [
                            [c * self.length_scale for c in point] for point in geometry
                        ]
                    else:
                        # Single point
                        geometry = [c * self.length_scale for c in geometry]

                # Create the appropriate connection type
                if connection_type == "point":
                    connection = PointConnection(ifc_connection.GlobalId, geometry)
                elif connection_type == "rigid":
                    connection = RigidConnection(ifc_connection.GlobalId, geometry)
                elif connection_type == "hinge":
                    # Extract rotation axis from orientation
                    rotation_axis = orientation[
                        2
                    ]  # Z-axis is typically the rotation axis
                    connection = HingeConnection(
                        ifc_connection.GlobalId, geometry, rotation_axis
                    )
                else:
                    connection = PointConnection(ifc_connection.GlobalId, geometry)

            elif ifc_connection.is_a("IfcStructuralCurveConnection"):
                representation = get_representation(ifc_connection, "Edge")
                if not representation:
                    self.logger.warning(
                        f"No representation found for {ifc_connection.GlobalId}"
                    )
                    return None

                geometry = self._extract_geometry(representation)

                # Get orientation or use default
                orientation = None
                if hasattr(ifc_connection, "Axis") and ifc_connection.Axis:
                    orientation = get_1D_orientation(geometry, ifc_connection.Axis)

                if not orientation:
                    orientation = np.eye(3).tolist()

                # Apply transformation if available
                transformation = None
                if (
                    hasattr(ifc_connection, "ObjectPlacement")
                    and ifc_connection.ObjectPlacement
                ):
                    transformation = get_transformation(ifc_connection.ObjectPlacement)

                if transformation:
                    try:
                        geometry = transform_vectors(geometry, transformation)
                        orientation = transform_vectors(
                            [orientation], transformation, include_translation=False
                        )[0]
                    except Exception as e:
                        self.logger.warning(f"Error applying transformation: {e}")

                # Apply unit scale to geometry
                if isinstance(geometry, list):
                    if all(isinstance(g, list) for g in geometry):
                        # List of points
                        geometry = [
                            [c * self.length_scale for c in point] for point in geometry
                        ]
                    else:
                        # Single point
                        geometry = [c * self.length_scale for c in geometry]

                # For curve connections, use midpoint as position
                if len(geometry) == 2:
                    midpoint = [(geometry[0][i] + geometry[1][i]) / 2 for i in range(3)]
                else:
                    midpoint = geometry[0] if geometry else [0.0, 0.0, 0.0]

                # Create the appropriate connection type
                if connection_type == "rigid":
                    connection = RigidConnection(ifc_connection.GlobalId, midpoint)
                elif connection_type == "hinge":
                    rotation_axis = orientation[2] if orientation else [0.0, 0.0, 1.0]
                    connection = HingeConnection(
                        ifc_connection.GlobalId, midpoint, rotation_axis
                    )
                else:
                    connection = PointConnection(ifc_connection.GlobalId, midpoint)

            # Default case - point connection
            else:
                connection = PointConnection(ifc_connection.GlobalId, [0.0, 0.0, 0.0])

            # Add connected members to the connection
            try:
                connected_elements = find_connected_elements(ifc_connection)
                for element_id in connected_elements:
                    connection.connect_member(element_id)
            except Exception as e:
                self.logger.warning(f"Error finding connected elements: {e}")

            return connection

        except Exception as e:
            self.logger.error(f"Error creating domain connection: {e}")
            return None

    def _extract_geometry(self, representation):
        """
        Extract geometry from a representation.

        Args:
            representation: IFC representation

        Returns:
            Geometry data (will be scaled to SI units by the calling method)
        """
        if not representation or not representation.Items:
            return [0.0, 0.0, 0.0]

        item = representation.Items[0]

        if item.is_a("IfcEdge"):
            return [
                get_coordinate(item.EdgeStart.VertexGeometry),
                get_coordinate(item.EdgeEnd.VertexGeometry),
            ]

        elif item.is_a("IfcFaceSurface"):
            if hasattr(item, "Bounds") and item.Bounds and len(item.Bounds) > 0:
                if hasattr(item.Bounds[0], "Bound") and hasattr(
                    item.Bounds[0].Bound, "EdgeList"
                ):
                    edges = item.Bounds[0].Bound.EdgeList
                    coords = []
                    for edge in edges:
                        if hasattr(edge, "EdgeElement") and hasattr(
                            edge.EdgeElement, "EdgeStart"
                        ):
                            coords.append(
                                get_coordinate(
                                    edge.EdgeElement.EdgeStart.VertexGeometry
                                )
                            )
                    return coords

        elif item.is_a("IfcVertexPoint"):
            if hasattr(item, "VertexGeometry"):
                return get_coordinate(item.VertexGeometry)

        # Default
        return [0.0, 0.0, 0.0]

    def _extract_position(self, ifc_connection) -> List[float]:
        """
        Extract the position of a connection from its IFC representation.

        Args:
            ifc_connection: IFC connection entity

        Returns:
            [x, y, z] position coordinates in SI units
        """
        try:
            if (
                hasattr(ifc_connection, "ObjectPlacement")
                and ifc_connection.ObjectPlacement
            ):
                placement = ifc_connection.ObjectPlacement
                if (
                    hasattr(placement, "RelativePlacement")
                    and placement.RelativePlacement
                ):
                    relative = placement.RelativePlacement
                    if hasattr(relative, "Location") and relative.Location:
                        location = relative.Location
                        coords = location.Coordinates
                        # Convert to SI units
                        return [
                            coords[0] * self.length_scale,
                            coords[1] * self.length_scale,
                            (coords[2] if len(coords) > 2 else 0.0) * self.length_scale,
                        ]

            # Extract from representation as fallback
            representation = None
            if ifc_connection.is_a("IfcStructuralPointConnection"):
                representation = get_representation(ifc_connection, "Vertex")
            elif ifc_connection.is_a("IfcStructuralCurveConnection"):
                representation = get_representation(ifc_connection, "Edge")

            if representation and representation.Items:
                geometry = self._extract_geometry(representation)
                if isinstance(geometry, list):
                    if all(isinstance(g, list) for g in geometry):
                        # For curves or faces, use first point
                        # Convert to SI units
                        return [g * self.length_scale for g in geometry[0]]
                    else:
                        # For points
                        # Convert to SI units
                        return [g * self.length_scale for g in geometry]

            return [0.0, 0.0, 0.0]

        except Exception as e:
            self.logger.error(f"Error extracting connection position: {e}")
            return [0.0, 0.0, 0.0]

    def _extract_rotation_axis(self, ifc_connection) -> List[float]:
        """
        Extract the rotation axis for a hinge connection.

        Args:
            ifc_connection: IFC connection entity

        Returns:
            [x, y, z] rotation axis vector
        """
        try:
            # Try to get from condition coordinate system
            if (
                hasattr(ifc_connection, "ConditionCoordinateSystem")
                and ifc_connection.ConditionCoordinateSystem
            ):
                axes = ifc_connection.ConditionCoordinateSystem
                if (
                    hasattr(axes, "Axis")
                    and axes.Axis
                    and hasattr(axes, "RefDirection")
                    and axes.RefDirection
                ):
                    zAxis = np.array(axes.Axis.DirectionRatios)
                    zAxis = zAxis / np.linalg.norm(zAxis)

                    # Return z-axis as rotation axis
                    return zAxis.tolist()

            # Default vertical rotation axis
            return [0.0, 0.0, 1.0]

        except Exception as e:
            self.logger.error(f"Error extracting rotation axis: {e}")
            return [0.0, 0.0, 1.0]
