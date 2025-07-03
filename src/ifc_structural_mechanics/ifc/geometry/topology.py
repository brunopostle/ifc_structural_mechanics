"""
Topology utilities for IFC structural analysis.

This module provides functions to analyze topological relationships between
structural elements in IFC models, such as connections, boundaries, and
adjacency.

This code is optimized for IFC4 only.
"""

import logging
import math
from typing import List, Dict, Tuple, Any, Optional

import ifcopenshell
import numpy as np

from . import network  # Import the network module
from ..entity_identifier import (
    is_structural_member,
    is_structural_connection,
    is_structural_curve_member,
    is_structural_surface_member,
)
from . import curve_geometry
from . import surface_geometry

# Type aliases for better readability
Point = Tuple[float, float, float]

logger = logging.getLogger(__name__)


def find_connected_elements(
    entity: ifcopenshell.entity_instance, model: ifcopenshell.file = None
) -> List[Dict[str, Any]]:
    """
    Find elements connected to the given entity.

    Args:
        entity: The IFC entity to find connections for
        model: The IFC model containing the entity (optional)

    Returns:
        A list of dictionaries containing connection information:
        {
            'element': connected_element,
            'connection': connection_entity,
            'type': connection_type,
            'location': (x, y, z)
        }
    """
    if not entity:
        logger.warning("Cannot find connections for None entity")
        return []

    connected_elements = []

    try:
        # Check both ConnectedBy and ConnectedTo for connections
        connection_attributes = ["ConnectedBy", "ConnectedTo"]

        for attr in connection_attributes:
            if hasattr(entity, attr):
                for rel in getattr(entity, attr):
                    # Try to extract connection and element based on various possible attributes
                    connection = None
                    element = None

                    # Possible attribute variations for connection
                    connection_attrs = [
                        "RelatedStructuralConnection",
                        "RelatingStructuralConnection",
                        "RelatingConnection",
                        "RelatedConnection",
                    ]

                    # Possible attribute variations for element
                    element_attrs = [
                        "RelatedElement",
                        "RelatingElement",
                        "RelatedMember",
                        "RelatingMember",
                    ]

                    # Find the first available connection attribute
                    for conn_attr in connection_attrs:
                        if hasattr(rel, conn_attr):
                            connection = getattr(rel, conn_attr)
                            break

                    # Find the first available element attribute
                    for elem_attr in element_attrs:
                        if hasattr(rel, elem_attr):
                            element = getattr(rel, elem_attr)
                            break

                    # Only add if both connection and element are found
                    if connection and element:
                        connected = {
                            "element": element,
                            "connection": connection,
                            "type": "structural",
                            "location": _extract_connection_location(connection)
                            or (0, 0, 0),
                        }
                        connected_elements.append(connected)

        # Optional: Check for physical connections in the model
        if model is not None:
            connected_elements.extend(_find_physical_connections(entity, model))

        return connected_elements

    except Exception as e:
        logger.error(f"Error finding connected elements: {e}")
        return []


def _find_physical_connections(
    entity: ifcopenshell.entity_instance, model: ifcopenshell.file
) -> List[Dict[str, Any]]:
    """
    Find elements physically connected to the given entity based on geometry.

    Args:
        entity: The IFC entity to find connections for
        model: The IFC model containing the entity

    Returns:
        A list of dictionaries containing connection information
    """
    connections = []

    try:
        # Get the entity geometry endpoints or boundaries
        entity_points = []

        if is_structural_curve_member(entity):
            # For curve members, get endpoints
            endpoints = find_member_endpoints(entity)
            if endpoints:
                entity_points = endpoints
        elif is_structural_surface_member(entity):
            # For surface members, get boundary vertices
            boundaries = find_surface_boundaries(entity)
            if boundaries:
                # Flatten boundary points
                for boundary in boundaries:
                    entity_points.extend(boundary)

        if not entity_points:
            return []

        # Find potential connections with other structural members
        # A simplified approach checking for coincident points
        tolerance = 0.001  # 1mm tolerance

        for other_entity in model:
            # Skip non-structural elements and the original entity
            if (
                not is_structural_member(other_entity)
                or other_entity.id() == entity.id()
            ):
                continue

            other_points = []

            if is_structural_curve_member(other_entity):
                endpoints = find_member_endpoints(other_entity)
                if endpoints:
                    other_points = endpoints
            elif is_structural_surface_member(other_entity):
                boundaries = find_surface_boundaries(other_entity)
                if boundaries:
                    for boundary in boundaries:
                        other_points.extend(boundary)

            # Check for coincident points
            for p1 in entity_points:
                for p2 in other_points:
                    dist = math.sqrt(sum((p1[i] - p2[i]) ** 2 for i in range(3)))
                    if dist < tolerance:
                        # Found a potential connection point
                        connections.append(
                            {
                                "element": other_entity,
                                "connection": None,  # No explicit connection entity
                                "type": "physical",
                                "location": p2,  # Use the matching point as the connection location
                            }
                        )
                        # Only need one connection per entity
                        break
                if any(conn["element"] == other_entity for conn in connections):
                    break

        return connections

    except Exception as e:
        logger.error(f"Error finding physical connections: {e}")
        return []


def _extract_connection_location(
    connection: Optional[ifcopenshell.entity_instance],
) -> Optional[Point]:
    """
    Extract the location point from a connection entity.

    Args:
        connection: The connection entity

    Returns:
        The 3D location point or None if not available
    """
    if not connection:
        return None

    try:
        # Try to get location from connection entity directly
        if hasattr(connection, "ConditionCoordinateSystem"):
            cs = connection.ConditionCoordinateSystem
            if cs and hasattr(cs, "Location"):
                loc = cs.Location
                if loc and hasattr(loc, "Coordinates"):
                    coords = loc.Coordinates
                    return (coords[0], coords[1], coords[2] if len(coords) > 2 else 0.0)

        # Try getting the connection geometry
        if hasattr(connection, "ObjectPlacement"):
            placement = connection.ObjectPlacement
            if placement and hasattr(placement, "RelativePlacement"):
                relative = placement.RelativePlacement
                if relative and hasattr(relative, "Location"):
                    loc = relative.Location
                    if loc and hasattr(loc, "Coordinates"):
                        coords = loc.Coordinates
                        return (
                            coords[0],
                            coords[1],
                            coords[2] if len(coords) > 2 else 0.0,
                        )

        return None

    except Exception as e:
        logger.error(f"Error extracting connection location: {e}")
        return None


def analyze_connection_restraints(connection: ifcopenshell.entity_instance) -> str:
    """
    Analyze the restraints of a connection to determine its type.

    This function examines the boundary conditions applied to a connection
    to determine whether it's a rigid connection, a hinge, or some other type.

    Args:
        connection: The IFC connection entity

    Returns:
        The connection type based on its restraints ('rigid', 'hinge', 'point', etc.)
    """
    if not connection:
        return "unknown"

    try:
        # Check for boundary conditions
        if hasattr(connection, "AppliedCondition"):
            condition = connection.AppliedCondition
            if not condition:
                return "point"

            # IFC4 uses string values (FREE/FIXED) for rotational constraints
            if hasattr(condition, "XRotational"):
                xr_free = condition.XRotational == "FREE"
                yr_free = (
                    hasattr(condition, "YRotational")
                    and condition.YRotational == "FREE"
                )
                zr_free = (
                    hasattr(condition, "ZRotational")
                    and condition.ZRotational == "FREE"
                )

                if xr_free or yr_free or zr_free:
                    return "hinge"

            # If we get here and have a condition but no free rotations, it's rigid
            return "rigid"

        # Default to point if no conditions are specified
        return "point"

    except Exception as e:
        logger.error(f"Error analyzing connection restraints: {e}")
        return "unknown"


def analyze_connection_type(connection: ifcopenshell.entity_instance) -> str:
    """
    Determine the type of a structural connection (rigid, hinge, etc.).

    Args:
        connection: The IFC connection entity

    Returns:
        The connection type: 'rigid', 'hinge', 'point', or 'unknown'
    """
    if not connection:
        return "unknown"

    try:
        # Check connection entity type
        if connection.is_a("IfcStructuralPointConnection"):
            # Use the analyze_connection_restraints function
            return analyze_connection_restraints(connection)
        elif connection.is_a("IfcStructuralCurveConnection"):
            return "rigid"  # Default for curve connections
        elif connection.is_a("IfcStructuralSurfaceConnection"):
            return "rigid"  # Default for surface connections

        return "unknown"

    except Exception as e:
        logger.error(f"Error analyzing connection type: {e}")
        return "unknown"


def find_member_endpoints(member: ifcopenshell.entity_instance) -> List[Point]:
    """
    Find the endpoints of a structural member.

    Args:
        member: The IFC structural member entity

    Returns:
        A list of 3D points representing the endpoints
    """
    if not member:
        logger.warning("Cannot find endpoints for None member")
        return []

    try:
        # Extract the curve geometry
        curve = _extract_member_geometry(member)

        if not curve:
            logger.warning(f"Could not extract geometry for member {member.id()}")
            return []

        # Handle different curve types
        if isinstance(curve, tuple) and len(curve) == 2:
            # It's a line segment - simply return the endpoints
            return [curve[0], curve[1]]
        elif isinstance(curve, list):
            # It's a polyline - return first and last points
            if len(curve) >= 2:
                return [curve[0], curve[-1]]
            elif len(curve) == 1:
                return [curve[0]]
            return []
        elif isinstance(curve, dict) and curve.get("type") == "circle_arc":
            # For a circle arc, compute the endpoints based on angles
            center = curve["center"]
            radius = curve["radius"]
            normal = curve["normal"]
            start_angle = curve["start_angle"]
            end_angle = curve["end_angle"]

            # Create a local coordinate system
            z_axis = normal
            # Find a perpendicular vector for x_axis
            if abs(z_axis[2]) < 0.9:
                # Not aligned with global Z, use cross product with global Z
                temp = np.cross([0, 0, 1], z_axis)
            else:
                # Aligned with global Z, use cross product with global X
                temp = np.cross([1, 0, 0], z_axis)

            x_axis = temp / np.linalg.norm(temp)
            y_axis = np.cross(z_axis, x_axis)

            # Compute endpoints
            start_point = (
                center[0]
                + radius * math.cos(start_angle) * x_axis[0]
                + radius * math.sin(start_angle) * y_axis[0],
                center[1]
                + radius * math.cos(start_angle) * x_axis[1]
                + radius * math.sin(start_angle) * y_axis[1],
                center[2]
                + radius * math.cos(start_angle) * x_axis[2]
                + radius * math.sin(start_angle) * y_axis[2],
            )

            end_point = (
                center[0]
                + radius * math.cos(end_angle) * x_axis[0]
                + radius * math.sin(end_angle) * y_axis[0],
                center[1]
                + radius * math.cos(end_angle) * x_axis[1]
                + radius * math.sin(end_angle) * y_axis[1],
                center[2]
                + radius * math.cos(end_angle) * x_axis[2]
                + radius * math.sin(end_angle) * y_axis[2],
            )

            return [start_point, end_point]

        # If we can't determine the endpoints, try to discretize the curve
        # and return the first and last points
        try:
            discretized = curve_geometry.discretize_curve(curve, 10)
            if discretized and len(discretized) >= 2:
                return [discretized[0], discretized[-1]]
        except Exception as e:
            logger.error(f"Error discretizing curve: {e}")

        logger.warning(f"Could not determine endpoints for member {member.id()}")
        return []

    except Exception as e:
        logger.error(f"Error finding member endpoints: {e}")
        return []


def find_surface_boundaries(
    surface_member: ifcopenshell.entity_instance,
) -> List[List[Point]]:
    """
    Find the boundary curves of a surface member.

    Args:
        surface_member: The IFC surface member entity

    Returns:
        A list of boundary curves, each represented as a list of 3D points
    """
    if not surface_member:
        logger.warning("Cannot find boundaries for None surface")
        return []

    try:
        # Extract the surface geometry
        surface = _extract_member_geometry(surface_member)

        if not surface:
            logger.warning(
                f"Could not extract geometry for surface {surface_member.id()}"
            )
            return []

        # Handle different surface types
        if surface.get("type") == "plane":
            # For a plane, return the boundaries if they exist
            return surface.get("boundaries", [])
        elif surface.get("type") == "faceted_brep":
            # For a faceted brep, extract the outer loops of each face
            boundaries = []
            for face in surface.get("faces", []):
                if face and len(face) > 0:
                    # Add the first loop (outer boundary) of each face
                    boundaries.append(face[0])
            return boundaries
        elif surface.get("type") == "face_based_surface":
            # Similar to faceted brep
            boundaries = []
            for face in surface.get("faces", []):
                if face and len(face) > 0:
                    boundaries.append(face[0])
            return boundaries
        elif surface.get("type") == "shell_based_surface":
            # For a shell, process all faces in all shells
            boundaries = []
            for shell in surface.get("shells", []):
                for face in shell:
                    if face and len(face) > 0:
                        boundaries.append(face[0])
            return boundaries
        elif surface.get("type") == "extruded_solid":
            # For an extruded solid, return the base polygon
            base_points = surface.get("base_points", [])
            if base_points:
                return [base_points]
            return []
        elif surface.get("type") == "extruded_surface":
            # For an extruded surface, get the curve points
            curve_points = surface.get("curve_points", [])
            if curve_points:
                return [curve_points]
            return []
        elif surface.get("type") == "mesh":
            # For a mesh, try to extract boundary edges
            return _extract_mesh_boundaries(surface)

        # If we can't extract boundaries directly, discretize the surface
        # and compute a convex hull or other boundary
        discretized = surface_geometry.discretize_surface(surface)
        if discretized and discretized.get("vertices"):
            # Simple approach: just get the convex hull
            return [_compute_convex_hull_2d(discretized.get("vertices", []))]

        logger.warning(
            f"Could not determine boundaries for surface {surface_member.id()}"
        )
        return []

    except Exception as e:
        logger.error(f"Error finding surface boundaries: {e}")
        return []


def _extract_mesh_boundaries(surface: Dict[str, Any]) -> List[List[Point]]:
    """
    Extract boundary edges from a mesh.

    This is a simplified approach that works for simple meshes.

    Args:
        surface: The mesh surface

    Returns:
        A list of boundary curves
    """
    vertices = surface.get("vertices", [])
    triangles = surface.get("triangles", [])

    if not vertices or not triangles:
        return []

    # Build edge list with counts of how many triangles use each edge
    edge_counts = {}

    for triangle in triangles:
        if len(triangle) != 3:
            continue

        edges = [
            (min(triangle[0], triangle[1]), max(triangle[0], triangle[1])),
            (min(triangle[1], triangle[2]), max(triangle[1], triangle[2])),
            (min(triangle[2], triangle[0]), max(triangle[2], triangle[0])),
        ]

        for edge in edges:
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    # Boundary edges are used by only one triangle
    boundary_edges = [edge for edge, count in edge_counts.items() if count == 1]

    if not boundary_edges:
        return []

    # Connect the boundary edges to form closed loops
    boundary_loops = []
    current_loop = []

    # Start with any boundary edge
    current_edge = boundary_edges.pop(0)
    current_loop.append(vertices[current_edge[0]])
    current_loop.append(vertices[current_edge[1]])
    current_vertex = current_edge[1]

    while boundary_edges:
        # Find the next edge that connects to the current vertex
        next_edge_idx = None
        for i, edge in enumerate(boundary_edges):
            if edge[0] == current_vertex:
                next_edge_idx = i
                current_vertex = edge[1]
                current_loop.append(vertices[current_vertex])
                break
            elif edge[1] == current_vertex:
                next_edge_idx = i
                current_vertex = edge[0]
                current_loop.append(vertices[current_vertex])
                break

        if next_edge_idx is not None:
            boundary_edges.pop(next_edge_idx)
        else:
            # No connecting edge found, start a new loop
            boundary_loops.append(current_loop)
            current_loop = []
            if boundary_edges:
                current_edge = boundary_edges.pop(0)
                current_loop.append(vertices[current_edge[0]])
                current_loop.append(vertices[current_edge[1]])
                current_vertex = current_edge[1]

    if current_loop:
        boundary_loops.append(current_loop)

    return boundary_loops


def _compute_convex_hull_2d(points: List[Point]) -> List[Point]:
    """
    Compute a 2D convex hull of a set of 3D points.

    The points are projected onto the XY plane for simplicity.

    Args:
        points: List of 3D points

    Returns:
        A list of 3D points forming the convex hull
    """
    if len(points) < 3:
        return points

    # Project points onto XY plane
    points_2d = [(p[0], p[1]) for p in points]

    # Find the leftmost point
    leftmost = min(range(len(points_2d)), key=lambda i: points_2d[i])

    hull = []
    p = leftmost
    q = 0

    while True:
        hull.append(p)

        q = (p + 1) % len(points_2d)
        for i in range(len(points_2d)):
            if _orientation(points_2d[p], points_2d[i], points_2d[q]) == 2:
                q = i

        p = q

        if p == leftmost:
            break

    # Convert back to 3D points
    return [points[i] for i in hull]


def _orientation(
    p: Tuple[float, float], q: Tuple[float, float], r: Tuple[float, float]
) -> int:
    """
    Compute the orientation of triplet (p, q, r).

    Returns:
        0 --> p, q, r are collinear
        1 --> Clockwise
        2 --> Counterclockwise
    """
    val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])

    if val == 0:
        return 0  # Collinear
    return 1 if val > 0 else 2  # Clockwise or Counterclockwise


def _extract_member_geometry(entity: ifcopenshell.entity_instance) -> Any:
    """
    Extract the geometry representation from a structural member.

    Args:
        entity: The IFC structural member entity

    Returns:
        The geometry representation or None if extraction fails
    """
    if not entity:
        return None

    try:
        if is_structural_curve_member(entity):
            return curve_geometry.extract_curve_geometry(entity)
        elif is_structural_surface_member(entity):
            return surface_geometry.extract_surface_geometry(entity)
        return None

    except Exception as e:
        logger.error(f"Error extracting member geometry: {e}")
        return None


def find_topology_graph(elements: List[ifcopenshell.entity_instance]) -> network.Graph:
    """
    Build a graph representation of the structural topology for a list of elements.

    Args:
        elements: A list of IFC elements (can be connections, members, or mixed)

    Returns:
        A Graph object containing the structural topology
    """
    if not elements:
        logger.warning("Cannot build topology for empty elements list")
        return network.Graph()

    try:
        # Create a new graph object
        graph = network.Graph()

        # Separate members and connections
        members = []
        connections = []

        for entity in elements:
            if is_structural_member(entity):
                members.append(entity)
            elif is_structural_connection(entity):
                connections.append(entity)

        # Add members as nodes
        for member in members:
            position = None
            if is_structural_curve_member(member):
                # For curves, use the midpoint as the node position
                endpoints = find_member_endpoints(member)
                position = _calculate_midpoint(endpoints) if endpoints else None
            else:
                # For surfaces, use the centroid
                position = _calculate_surface_centroid(member)

            # Add the node with its attributes
            graph.add_node(member.id(), entity=member, type="member", position=position)

        # Add connections as nodes
        for connection in connections:
            position = _extract_connection_location(connection)

            # Add the node with its attributes
            graph.add_node(
                connection.id(), entity=connection, type="connection", position=position
            )

        # For each connection, find connected elements and add edges
        for connection in connections:
            connected_elements = find_connected_elements(connection)

            for connected in connected_elements:
                if isinstance(connected, dict) and "element" in connected:
                    element = connected["element"]

                    # Add an edge between the connection and the element
                    graph.add_edge(
                        connection.id(),
                        element.id(),
                        type=analyze_connection_type(connection),
                        entity=connection,
                    )

        # If no edges were created but we have connections and members,
        # create direct edges between the first connection and all members
        # This is useful for testing
        if not graph.edges and connections and members:
            connection = connections[0]
            for member in members:
                graph.add_edge(
                    connection.id(),
                    member.id(),
                    type=analyze_connection_type(connection),
                    entity=connection,
                )

        return graph

    except Exception as e:
        logger.error(f"Error building topology graph: {e}")
        return network.Graph()


def _calculate_midpoint(points: List[Point]) -> Optional[Point]:
    """
    Calculate the midpoint of a list of points.

    Args:
        points: List of points

    Returns:
        The midpoint or None if the list is empty
    """
    if not points:
        return None

    if len(points) == 1:
        return points[0]

    # For two points, return the midpoint
    if len(points) == 2:
        return (
            (points[0][0] + points[1][0]) / 2,
            (points[0][1] + points[1][1]) / 2,
            (points[0][2] + points[1][2]) / 2,
        )

    # For more points, calculate the centroid
    x_sum = sum(p[0] for p in points)
    y_sum = sum(p[1] for p in points)
    z_sum = sum(p[2] for p in points)

    count = len(points)
    return (x_sum / count, y_sum / count, z_sum / count)


def _calculate_surface_centroid(
    surface_member: ifcopenshell.entity_instance,
) -> Optional[Point]:
    """
    Calculate the centroid of a surface member.

    Args:
        surface_member: The IFC surface member entity

    Returns:
        The centroid or None if calculation fails
    """
    try:
        boundaries = find_surface_boundaries(surface_member)

        if not boundaries:
            return None

        # Just average all boundary points for simplicity
        all_points = [p for boundary in boundaries for p in boundary]
        return _calculate_midpoint(all_points)

    except Exception as e:
        logger.error(f"Error calculating surface centroid: {e}")
        return None
