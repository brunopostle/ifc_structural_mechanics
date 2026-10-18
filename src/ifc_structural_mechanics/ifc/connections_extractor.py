"""
Structural connection extractor for IFC structural analysis models.

This module contains the ConnectionsExtractor class which is responsible for
extracting structural connections from IFC files and converting them into
domain model objects.
"""

import logging
from typing import Dict, List, Optional, Union

import ifcopenshell
import ifcopenshell.util.placement
import numpy as np

# Updated imports to use existing domain model
from ..domain.structural_connection import (
    StructuralConnection,
    create_connection_from_stiffness,
)
from ..utils.error_handling import ModelExtractionError
from .entity_identifier import (
    get_connection_input,  # Integration with get_connection_input function
)
from .entity_identifier import (
    analyze_connection_type,
    find_connected_elements,
    get_coordinate,
    get_item_transformation,
    get_representation,
    transform_vectors,
)


class ConnectionsExtractor:
    """
    Extracts structural connections from IFC models with stiffness properties.
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
            self.ifc = ifc_file
            self.logger.info("Using provided ifcopenshell.file object")
        else:
            self.logger.error("Invalid IFC file parameter provided")
            raise ModelExtractionError(
                "ifc_file must be a file path or an ifcopenshell.file object"
            )

        # Store unit scales
        self.unit_scales = unit_scales or {}
        self.length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
        self.force_scale = self.unit_scales.get("FORCEUNIT", 1.0)

    def extract_all_connections(self) -> List[StructuralConnection]:
        """
        Extract all structural connections from the IFC file.

        Returns:
            List of extracted structural connections as domain objects
        """
        self.logger.info("Extracting all structural connections")

        connections = []
        for entity_type in (
            "IfcStructuralPointConnection",
            "IfcStructuralCurveConnection",
            "IfcStructuralSurfaceConnection",
        ):
            for entity in self.ifc.by_type(entity_type):
                connections.append(self._create_domain_connection(entity))

        self.logger.info(f"Extracted {len(connections)} structural connections")
        return connections

    def extract_connection_by_id(
        self, connection_id: str
    ) -> Optional[StructuralConnection]:
        """
        Extract a specific structural connection by ID.

        Args:
            connection_id: GlobalId or numeric ID of the connection to extract

        Returns:
            The extracted structural connection or None if not found
        """
        self.logger.info(f"Extracting structural connection with ID: {connection_id}")

        for entity_type in [
            "IfcStructuralPointConnection",
            "IfcStructuralCurveConnection",
            "IfcStructuralSurfaceConnection",
        ]:
            for entity in self.ifc.by_type(entity_type):
                if getattr(entity, "GlobalId", None) == connection_id:
                    return self._create_domain_connection(entity)

        # Not a GlobalId: a numeric STEP id, perhaps
        try:
            entity = self.ifc.by_id(int(connection_id))
        except (ValueError, TypeError, RuntimeError):
            self.logger.warning(f"Connection with ID {connection_id} not found")
            return None
        return self._create_domain_connection(entity)

    def _create_domain_connection(self, ifc_connection) -> StructuralConnection:
        """
        Create a domain connection object from an IFC connection entity.

        Args:
            ifc_connection: IFC connection entity

        Returns:
            Domain connection object with stiffness properties

        Raises:
            ModelExtractionError: If the connection cannot be read or is of a
                kind the analysis does not support. A connection is never left
                out: the structure would be a different one.
        """
        connection_id = getattr(ifc_connection, "GlobalId", None) or "?"
        try:
            return self._build_domain_connection(ifc_connection)
        except ModelExtractionError as error:
            raise ModelExtractionError(
                f"Connection {connection_id} cannot be analysed. {error.message}"
            ) from error
        except Exception as error:
            raise ModelExtractionError(
                f"Connection {connection_id} cannot be read from the IFC file: "
                f"{type(error).__name__}: {error}"
            ) from error

    def _build_domain_connection(self, ifc_connection) -> StructuralConnection:
        """Create the domain connection; see ``_create_domain_connection``."""
        if not (
            ifc_connection.is_a("IfcStructuralPointConnection")
            or ifc_connection.is_a("IfcStructuralCurveConnection")
            or ifc_connection.is_a("IfcStructuralSurfaceConnection")
        ):
            raise ModelExtractionError(
                f"It is an {ifc_connection.is_a()}; only point, curve and "
                "surface connections are supported."
            )
        if ifc_connection.is_a("IfcStructuralSurfaceConnection"):
            return self._build_surface_connection(ifc_connection)

        # Extract basic connection information
        connection_id = ifc_connection.GlobalId
        connection_type = analyze_connection_type(ifc_connection)

        # Extract geometry and position
        position = self._extract_position(ifc_connection)

        # Extract stiffness properties using get_connection_input
        stiffness_props = get_connection_input(
            ifc_connection,
            self._determine_geometry_type(ifc_connection),
            self.length_scale,
            self.force_scale,
        )

        # CREATE CONNECTION WITHOUT VALIDATION
        connection = None
        # Extract IFC GUID for traceability
        ifc_guid = (
            ifc_connection.GlobalId if hasattr(ifc_connection, "GlobalId") else None
        )

        if ifc_connection.is_a("IfcStructuralPointConnection"):
            connection = create_connection_from_stiffness(
                connection_id, position, stiffness_props, connection_type, ifc_guid
            )

        elif ifc_connection.is_a("IfcStructuralCurveConnection"):
            # Handle curve connections
            representation = get_representation(ifc_connection, "Edge")
            if representation:
                geometry = self._extract_geometry(representation)
                geometry = self._apply_transformations(geometry, ifc_connection)

                if not (
                    isinstance(geometry, list)
                    and len(geometry) >= 2
                    and all(isinstance(g, list) for g in geometry)
                ):
                    raise ModelExtractionError("The ends of its edge cannot be read.")
                midpoint = [(geometry[0][i] + geometry[1][i]) / 2 for i in range(3)]

                connection = create_connection_from_stiffness(
                    connection_id,
                    midpoint,
                    stiffness_props,
                    connection_type,
                    ifc_guid,
                )
                # Keep the edge itself: a line support or line joint acts
                # along its whole length, not at its midpoint.
                connection.edge = [
                    [float(v) for v in geometry[0]],
                    [float(v) for v in geometry[1]],
                ]
            else:
                raise ModelExtractionError("It has no edge representation.")

        for member_id in find_connected_elements(ifc_connection):
            connection.connect_member(member_id)

        connection.local_axes = self._extract_local_axes(
            ifc_connection, getattr(connection, "edge", None)
        )

        # Extract per-member rotational end-releases from AppliedCondition
        release_axes: dict = {}
        end_releases = self._extract_end_releases(ifc_connection, release_axes)
        if end_releases:
            connection.released_dofs_by_member = end_releases
            connection.release_axes_by_member = release_axes
            self.logger.debug(
                f"Connection {connection_id} has end-releases: {end_releases}"
            )

        if not connection.validate():
            raise ModelExtractionError("It does not pass validation.")
        return connection

    def _build_surface_connection(self, ifc_connection) -> StructuralConnection:
        """Create the domain connection of an ``IfcStructuralSurfaceConnection``.

        Its face is the outline of the area it supports, in metres and global
        coordinates (``connection.face``); its position is the face's centre.
        The condition (``IfcBoundaryFaceCondition``) is a stiffness per area
        along each axis of the face's surface: those of the ``Position`` of
        its ``IfcPlane``, z across the face.

        Raises:
            ModelExtractionError: If its face cannot be read, it has no
                condition, or its condition treats the directions differently
                and its face has no plane to give them.
        """
        representation = get_representation(ifc_connection, "Face")
        if not representation or not representation.Items:
            raise ModelExtractionError("It has no face representation.")
        item = representation.Items[0]
        if not item.is_a("IfcFace"):
            raise ModelExtractionError(
                f"Its face representation is an {item.is_a()}, not a face."
            )
        corners = self._face_corners(item)
        transformation = get_item_transformation(ifc_connection, self.length_scale)
        face = [[float(v) * self.length_scale for v in corner] for corner in corners]
        if transformation:
            face = transform_vectors(face, transformation)
        face = [[float(v) for v in corner] for corner in face]
        if len(face) < 3:
            raise ModelExtractionError("Its face has fewer than three corners.")
        centre = np.mean(np.array(face, dtype=float), axis=0)
        normal = np.zeros(3)
        for i in range(len(face)):
            normal += np.cross(face[i], face[(i + 1) % len(face)])
        if np.linalg.norm(normal) < 1e-12:
            raise ModelExtractionError("Its face has no area.")
        normal = normal / np.linalg.norm(normal)
        if max(abs(float(np.dot(np.array(c) - centre, normal))) for c in face) > 1e-3:
            raise ModelExtractionError("Its face is not plane.")

        if not ifc_connection.AppliedCondition:
            raise ModelExtractionError(
                "It has no AppliedCondition, so it supports nothing; a surface "
                "connection cannot join members."
            )
        stiffness = get_connection_input(
            ifc_connection, "surface", self.length_scale, self.force_scale
        )
        connection = create_connection_from_stiffness(
            ifc_connection.GlobalId,
            [float(v) for v in centre],
            stiffness,
            "rigid",
            ifc_connection.GlobalId,
        )
        connection.face = face
        connection.local_axes = self._face_axes(item, transformation, stiffness)
        for member_id in find_connected_elements(ifc_connection):
            connection.connect_member(member_id)
        if not connection.validate():
            raise ModelExtractionError("It does not pass validation.")
        return connection

    @staticmethod
    def _face_corners(face) -> List[List[float]]:
        """The corners of the outer bound of an ``IfcFace``, in the file's units.

        Raises:
            ModelExtractionError: If a corner has no coordinates, or the bound
                is neither a list of edges nor a polygon.
        """
        bounds = list(face.Bounds or [])
        outer = [b for b in bounds if b.is_a("IfcFaceOuterBound")] or bounds
        if not outer:
            raise ModelExtractionError("Its face has no bound.")
        if len(bounds) > 1:
            raise ModelExtractionError(
                "Its face has an opening (more than one bound), which is not "
                "supported."
            )
        loop = outer[0].Bound
        if loop.is_a("IfcPolyLoop"):
            points = [get_coordinate(point) for point in loop.Polygon]
        elif loop.is_a("IfcEdgeLoop"):
            points = []
            for edge in loop.EdgeList:
                element = edge.EdgeElement if edge.is_a("IfcOrientedEdge") else edge
                forward = getattr(edge, "Orientation", True)
                vertex = element.EdgeStart if forward else element.EdgeEnd
                points.append(get_coordinate(vertex.VertexGeometry))
        else:
            raise ModelExtractionError(
                f"The bound of its face is an {loop.is_a()}, which is not supported."
            )
        if any(point is None for point in points):
            raise ModelExtractionError("A corner of its face has no coordinates.")
        if not outer[0].Orientation:
            points = points[::-1]
        return [list(point) for point in points]

    def _face_axes(
        self, face, transformation, stiffness
    ) -> Optional[List[List[float]]]:
        """The axes a face condition is in: those of its plane's ``Position``.

        None (the global axes) when the face has no plane and the condition
        treats the three directions alike, where the axes do not matter.

        Raises:
            ModelExtractionError: If the condition treats the directions
                differently and the face has no plane to give its axes.
        """
        surface = getattr(face, "FaceSurface", None)
        if surface is None or not surface.is_a("IfcPlane"):
            values = [(stiffness or {}).get(key, 0.0) for key in ("dx", "dy", "dz")]
            if max(values) - min(values) > 1e-9 * max(1.0, max(values)):
                raise ModelExtractionError(
                    "Its condition differs between directions, and its face has "
                    "no plane whose axes would give them."
                )
            return None
        position = surface.Position
        z_axis = np.array(
            position.Axis.DirectionRatios if position.Axis else (0.0, 0.0, 1.0),
            dtype=float,
        )
        x_axis = np.array(
            (
                position.RefDirection.DirectionRatios
                if position.RefDirection
                else (1.0, 0.0, 0.0)
            ),
            dtype=float,
        )
        if not getattr(face, "SameSense", True):
            z_axis = -z_axis
        if transformation:
            rotation = np.array(transformation["rotationMatrix"], dtype=float)
            z_axis, x_axis = rotation.dot(z_axis), rotation.dot(x_axis)
        axes = self._orthonormal_axes(x_axis, z_axis)
        if axes is None:
            raise ModelExtractionError("The axes of its face's plane are degenerate.")
        return axes

    def _extract_local_axes(
        self, ifc_connection, edge: Optional[List[List[float]]] = None
    ) -> Optional[List[List[float]]]:
        """Return the axes a connection's AppliedCondition is expressed in.

        * ``IfcStructuralPointConnection``: its ``ConditionCoordinateSystem``;
          the global axes when it has none.
        * ``IfcStructuralCurveConnection``: local x runs along the edge and
          ``Axis`` gives the side local z is on, so local y = z cross x.

        Returns:
            Three unit vectors (local x, y, z) in global coordinates, or None
            for the global axes.
        """
        try:
            rotation = None
            transformation = get_item_transformation(ifc_connection)
            if transformation:
                rotation = np.array(transformation["rotationMatrix"], dtype=float)

            if ifc_connection.is_a("IfcStructuralPointConnection"):
                axes = getattr(ifc_connection, "ConditionCoordinateSystem", None)
                if not axes and rotation is None:
                    return None
                # With no system of its own, the axes of its placement
                z_axis = np.array(
                    (
                        axes.Axis.DirectionRatios
                        if axes and axes.Axis
                        else (0.0, 0.0, 1.0)
                    ),
                    dtype=float,
                )
                x_axis = np.array(
                    (
                        axes.RefDirection.DirectionRatios
                        if axes and axes.RefDirection
                        else (1.0, 0.0, 0.0)
                    ),
                    dtype=float,
                )
                if rotation is not None:
                    z_axis, x_axis = rotation.dot(z_axis), rotation.dot(x_axis)
            elif ifc_connection.is_a("IfcStructuralCurveConnection"):
                axis = getattr(ifc_connection, "Axis", None)
                if not axis or not edge or len(edge) != 2:
                    return None
                x_axis = np.array(edge[1], dtype=float) - np.array(edge[0], dtype=float)
                z_axis = np.array(axis.DirectionRatios, dtype=float)
                if rotation is not None:
                    z_axis = rotation.dot(z_axis)
            else:
                return None

            return self._orthonormal_axes(x_axis, z_axis)
        except ModelExtractionError:
            raise
        except Exception as e:
            raise ModelExtractionError(
                f"Could not read the local axes of connection {getattr(ifc_connection, 'GlobalId', '?')}: {e}"
            ) from e

    @staticmethod
    def _orthonormal_axes(x_axis, z_axis) -> Optional[List[List[float]]]:
        """Return unit x, y, z axes from an x direction and an approximate z.

        z is made perpendicular to x and y = z cross x, the IFC convention for
        both placements and member axes. None if the directions are degenerate.
        """
        x_axis = np.array(x_axis, dtype=float)
        z_axis = np.array(z_axis, dtype=float)
        x_len = np.linalg.norm(x_axis)
        if x_len < 1e-12:
            return None
        x_axis = x_axis / x_len
        z_axis = z_axis - np.dot(z_axis, x_axis) * x_axis
        z_len = np.linalg.norm(z_axis)
        if z_len < 1e-9:
            return None
        z_axis = z_axis / z_len
        y_axis = np.cross(z_axis, x_axis)
        return [[float(v) for v in a] for a in (x_axis, y_axis, z_axis)]

    def _extract_release_axes(self, relation) -> Optional[List[List[float]]]:
        """Return the axes a member-side AppliedCondition is expressed in.

        That is the relation's ``ConditionCoordinateSystem``. Without one, IFC
        implies the member's own axes; they are worked out here for curve
        members (x along the member, ``Axis`` giving the side z is on).

        Returns:
            Three unit vectors (local x, y, z) in global coordinates, or None
            when they are the global axes or cannot be determined.
        """
        try:
            member = getattr(relation, "RelatingStructuralMember", None)
            # Directions are in the axes of the member's placement
            transformation = get_item_transformation(member)

            def placed(vector):
                if not transformation:
                    return vector
                return transformation["rotationMatrix"].dot(
                    np.array(vector, dtype=float)
                )

            axes = getattr(relation, "ConditionCoordinateSystem", None)
            if axes:
                z_axis = axes.Axis.DirectionRatios if axes.Axis else (0.0, 0.0, 1.0)
                x_axis = (
                    axes.RefDirection.DirectionRatios
                    if axes.RefDirection
                    else (1.0, 0.0, 0.0)
                )
                return self._orthonormal_axes(placed(x_axis), placed(z_axis))
            if member is None or not member.is_a("IfcStructuralCurveMember"):
                return None
            representation = get_representation(member, "Edge")
            axis = getattr(member, "Axis", None)
            if not representation or not axis:
                return None
            geometry = self._extract_geometry(representation)
            if not isinstance(geometry, list) or len(geometry) < 2:
                return None
            x_axis = np.array(geometry[-1], dtype=float) - np.array(
                geometry[0], dtype=float
            )
            return self._orthonormal_axes(placed(x_axis), placed(axis.DirectionRatios))
        except ModelExtractionError:
            raise
        except Exception as e:
            raise ModelExtractionError(
                f"Could not read the axes of relation {getattr(relation, 'GlobalId', '?')}: {e}"
            ) from e

    def _extract_end_releases(
        self, ifc_connection, axes_by_member: Optional[dict] = None
    ) -> dict:
        """Return per-member released rotation DOFs from AppliedCondition.

        Reads ``IfcRelConnectsStructuralMember.AppliedCondition`` for each
        relationship. A rotational DOF is released when its stiffness value is
        ``False`` (explicitly free) or ``0.0`` (zero-stiffness spring).

        Args:
            ifc_connection: IFC connection entity.
            axes_by_member: If given, filled with the axes each member's
                release is expressed in (see ``_extract_release_axes``).

        Returns:
            Dict mapping member IFC GlobalId → list of released DOF numbers
            (4 = Rx, 5 = Ry, 6 = Rz) in those axes. Empty dict when no releases.
        """
        result: dict = {}
        if not hasattr(ifc_connection, "ConnectsStructuralMembers"):
            return result
        for rel in ifc_connection.ConnectsStructuralMembers:
            condition = getattr(rel, "AppliedCondition", None)
            if condition is None:
                continue
            # Get the member GlobalId from the relationship
            member = getattr(rel, "RelatingStructuralMember", None)
            if member is None:
                continue
            member_id = getattr(member, "GlobalId", None)
            if member_id is None:
                continue
            released = []
            for axis_name, dof in (("X", 4), ("Y", 5), ("Z", 6)):
                # IfcBoundaryNodeCondition and IfcBoundaryEdgeCondition name
                # the same thing differently.
                attr = getattr(condition, f"RotationalStiffness{axis_name}", None)
                if attr is None:
                    attr = getattr(
                        condition, f"RotationalStiffnessByLength{axis_name}", None
                    )
                if attr is None:
                    continue
                wrapped = getattr(attr, "wrappedValue", attr)
                if wrapped is False or wrapped == 0.0:
                    released.append(dof)
            if released:
                result[member_id] = released
                if axes_by_member is not None:
                    axes_by_member[member_id] = self._extract_release_axes(rel)
        return result

    def _determine_geometry_type(self, ifc_connection) -> str:
        """
        Determine the geometry type for stiffness extraction.

        Args:
            ifc_connection: IFC connection entity

        Returns:
            Geometry type string ("point", "line", or "surface")
        """
        if ifc_connection.is_a("IfcStructuralPointConnection"):
            return "point"
        elif ifc_connection.is_a("IfcStructuralCurveConnection"):
            return "line"
        elif ifc_connection.is_a("IfcStructuralSurfaceConnection"):
            return "surface"
        else:
            self.logger.warning(
                f"Unknown connection type {ifc_connection.is_a()}, defaulting to 'point'"
            )
            return "point"

    def _extract_position(self, ifc_connection) -> List[float]:
        """
        Extract the position of a connection from its IFC representation.

        For structural connections, the position is typically stored in the
        TopologyRepresentation (VertexPoint geometry), not the ObjectPlacement.
        The ObjectPlacement is often at the origin (0,0,0) with the actual
        coordinates stored in the topology.

        Args:
            ifc_connection: IFC connection entity

        Returns:
            [x, y, z] position coordinates in SI units
        """
        # Method 1: Extract from TopologyRepresentation (VertexPoint geometry)
        # This is the primary method for structural connections
        representation = None
        if ifc_connection.is_a("IfcStructuralPointConnection"):
            representation = get_representation(ifc_connection, "Vertex")
        elif ifc_connection.is_a("IfcStructuralCurveConnection"):
            representation = get_representation(ifc_connection, "Edge")

        self.logger.debug(
            f"Connection {ifc_connection.GlobalId}: representation = {representation}"
        )

        if representation and representation.Items:
            geometry = self._extract_geometry(representation)
            self.logger.debug(
                f"Connection {ifc_connection.GlobalId}: geometry = {geometry}"
            )

            if isinstance(geometry, list) and len(geometry) > 0:
                if all(isinstance(g, list) for g in geometry):
                    # For curves or faces, use first point and convert to SI units
                    result = [g * self.length_scale for g in geometry[0]]
                    self.logger.debug(
                        f"Connection {ifc_connection.GlobalId}: Method 1 result (nested list) = {result}"
                    )
                    return result
                else:
                    # For points, convert to SI units; the vertex is in the
                    # axes of the connection's placement
                    result = transform_vectors(
                        [[g * self.length_scale for g in geometry]],
                        get_item_transformation(ifc_connection, self.length_scale),
                    )[0]
                    self.logger.debug(
                        f"Connection {ifc_connection.GlobalId}: Method 1 result (flat list) = {result}"
                    )
                    return result

        # Method 2: Fallback to ObjectPlacement if TopologyRepresentation not available
        if (
            hasattr(ifc_connection, "ObjectPlacement")
            and ifc_connection.ObjectPlacement
        ):
            matrix = ifcopenshell.util.placement.get_local_placement(
                ifc_connection.ObjectPlacement
            )
            coords = [matrix[0][3], matrix[1][3], matrix[2][3]]
            # Structural connections often have a placement at the origin and
            # their real position in the topology, so the origin tells nothing
            if any(c != 0.0 for c in coords):
                return [c * self.length_scale for c in coords]

        raise ModelExtractionError(
            "Its position cannot be found: it has no vertex or edge "
            "representation and no placement away from the origin."
        )

    def _extract_geometry(self, representation):
        """
        Extract geometry from a representation.

        Args:
            representation: IFC representation

        Returns:
            Geometry data (will be scaled to SI units by the calling method),
            or None when the representation holds no point, edge or face
        """
        if not representation or not representation.Items:
            return None

        item = representation.Items[0]

        if item.is_a("IfcEdge"):
            start_coord = get_coordinate(item.EdgeStart.VertexGeometry)
            end_coord = get_coordinate(item.EdgeEnd.VertexGeometry)
            if start_coord and end_coord:
                return [start_coord, end_coord]

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
                            coord = get_coordinate(
                                edge.EdgeElement.EdgeStart.VertexGeometry
                            )
                            if coord:
                                coords.append(coord)
                    return coords

        elif item.is_a("IfcVertexPoint"):
            if hasattr(item, "VertexGeometry"):
                coord = get_coordinate(item.VertexGeometry)
                if coord:
                    return coord

        return None

    def _apply_transformations(self, geometry, ifc_connection):
        """
        Apply unit scaling and transformations to geometry.

        Args:
            geometry: Raw geometry data
            ifc_connection: IFC connection entity

        Returns:
            Transformed geometry in SI units
        """
        # Apply transformation if available
        # In the file's own unit here; the scale follows
        transformation = get_item_transformation(ifc_connection)

        if transformation and geometry:
            geometry = transform_vectors(geometry, transformation)

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

        return geometry
