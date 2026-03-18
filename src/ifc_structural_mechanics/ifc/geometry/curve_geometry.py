"""
Curve geometry extraction from IFC entities for structural analysis.

This module provides functions to extract geometric information from IFC curve
entities (lines, polylines, etc.) and convert them to a consistent internal
representation.
"""

import logging
from typing import Optional, Tuple

import ifcopenshell
import numpy as np

from ..entity_identifier import get_coordinate, get_transformation, transform_vectors

logger = logging.getLogger(__name__)


def extract_curve_geometry(entity: ifcopenshell.entity_instance) -> Optional[Tuple]:
    """
    Extract geometric representation of curve member from IFC entity.

    Args:
        entity: IFC entity representing a curve member (beam, column, etc.)

    Returns:
        Geometry representation as ((x1, y1, z1), (x2, y2, z2)) or None if extraction fails
    """
    if entity is None:
        logger.warning("Cannot extract geometry from None entity")
        return None

    try:
        # Try different methods to extract the geometry

        # Method 1: Extract from Edge representation (most common for structural)
        representation = get_representation(entity, "Edge")
        if representation:
            geometry = extract_from_edge_representation(representation)
            if geometry:
                # Apply transformation if needed
                if hasattr(entity, "ObjectPlacement") and entity.ObjectPlacement:
                    transformation = get_transformation(entity.ObjectPlacement)
                    if transformation:
                        geometry = transform_vectors(geometry, transformation)
                return geometry

        # Method 2: Extract from Axis representation
        representation = get_representation(entity, "Axis")
        if representation:
            geometry = extract_from_axis_representation(representation)
            if geometry:
                # Apply transformation if needed
                if hasattr(entity, "ObjectPlacement") and entity.ObjectPlacement:
                    transformation = get_transformation(entity.ObjectPlacement)
                    if transformation:
                        geometry = transform_vectors(geometry, transformation)
                return geometry

        # Method 3: Extract from Body representation
        representation = get_representation(entity, "Body")
        if representation:
            geometry = extract_from_body_representation(representation)
            if geometry:
                # Apply transformation if needed
                if hasattr(entity, "ObjectPlacement") and entity.ObjectPlacement:
                    transformation = get_transformation(entity.ObjectPlacement)
                    if transformation:
                        geometry = transform_vectors(geometry, transformation)
                return geometry

        # Method 4: Extract from general representation
        if hasattr(entity, "Representation") and entity.Representation:
            for rep in entity.Representation.Representations:
                geometry = extract_geometry_from_representation(rep)
                if geometry:
                    # Apply transformation if needed
                    if hasattr(entity, "ObjectPlacement") and entity.ObjectPlacement:
                        transformation = get_transformation(entity.ObjectPlacement)
                        if transformation:
                            geometry = transform_vectors(geometry, transformation)
                    return geometry

        # Method 5: Fallback - try to get endpoints from connected connections
        from ..entity_identifier import find_member_endpoints

        endpoints = find_member_endpoints(entity)
        if endpoints and len(endpoints) >= 2:
            return (endpoints[0], endpoints[1])

        logger.warning(f"Could not extract geometry for entity {entity.id()}")
        return None

    except Exception as e:
        logger.error(f"Error extracting curve geometry: {e}")
        return None


def get_representation(
    entity: ifcopenshell.entity_instance, rep_type: str
) -> Optional[ifcopenshell.entity_instance]:
    """
    Get representation of specific type from an entity.

    Args:
        entity: IFC entity
        rep_type: Representation type to find

    Returns:
        Representation instance or None if not found
    """
    if not hasattr(entity, "Representation") or not entity.Representation:
        return None

    # First try with "Reference" identifier (common for structural)
    for representation in entity.Representation.Representations:
        if (
            hasattr(representation, "RepresentationIdentifier")
            and representation.RepresentationIdentifier == "Reference"
            and hasattr(representation, "RepresentationType")
            and representation.RepresentationType == rep_type
        ):
            return representation

    # Then try with just the rep_type
    for representation in entity.Representation.Representations:
        if (
            hasattr(representation, "RepresentationType")
            and representation.RepresentationType == rep_type
        ):
            return representation

    return None


def extract_from_edge_representation(
    representation: ifcopenshell.entity_instance,
) -> Optional[Tuple]:
    """
    Extract geometry from an Edge representation.

    Args:
        representation: IFC edge representation

    Returns:
        Tuple of start and end points
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        item = representation.Items[0]

        if item.is_a("IfcEdge"):
            # Direct edge representation
            if (
                hasattr(item, "EdgeStart")
                and item.EdgeStart
                and hasattr(item, "EdgeEnd")
                and item.EdgeEnd
            ):
                start = get_coordinate(item.EdgeStart.VertexGeometry)
                end = get_coordinate(item.EdgeEnd.VertexGeometry)
                if start and end:
                    return (start, end)

        elif item.is_a("IfcPolyline"):
            # Polyline representation
            if hasattr(item, "Points") and len(item.Points) >= 2:
                start = get_coordinate(item.Points[0])
                end = get_coordinate(item.Points[-1])  # Use last point for end
                if start and end:
                    return (start, end)

        elif item.is_a("IfcTrimmedCurve"):
            # Trimmed curve representation (like a partial circle)
            if hasattr(item, "BasisCurve") and item.BasisCurve.is_a("IfcLine"):
                base_line = item.BasisCurve
                origin = get_coordinate(base_line.Pnt)
                direction = np.array(base_line.Dir.DirectionRatios)

                # Get trim parameters
                params = []
                if hasattr(item, "Trim1") and item.Trim1:
                    for param in item.Trim1:
                        if hasattr(param, "wrappedValue"):
                            params.append(param.wrappedValue)
                if hasattr(item, "Trim2") and item.Trim2:
                    for param in item.Trim2:
                        if hasattr(param, "wrappedValue"):
                            params.append(param.wrappedValue)

                # Calculate endpoints using parameters
                if len(params) >= 2:
                    start = np.array(origin) + params[0] * direction
                    end = np.array(origin) + params[1] * direction
                    return (start.tolist(), end.tolist())

        # Try other items if the first one failed
        for item in representation.Items:
            if item.is_a("IfcEdge"):
                if (
                    hasattr(item, "EdgeStart")
                    and item.EdgeStart
                    and hasattr(item, "EdgeEnd")
                    and item.EdgeEnd
                ):
                    start = get_coordinate(item.EdgeStart.VertexGeometry)
                    end = get_coordinate(item.EdgeEnd.VertexGeometry)
                    if start and end:
                        return (start, end)

    except Exception as e:
        logger.warning(f"Error extracting from edge representation: {e}")

    return None


def extract_from_axis_representation(
    representation: ifcopenshell.entity_instance,
) -> Optional[Tuple]:
    """
    Extract geometry from an Axis representation.

    Args:
        representation: IFC axis representation

    Returns:
        Tuple of start and end points
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        for item in representation.Items:
            if item.is_a("IfcPolyline"):
                # Polyline representation
                if hasattr(item, "Points") and len(item.Points) >= 2:
                    start = get_coordinate(item.Points[0])
                    end = get_coordinate(item.Points[-1])  # Use last point for end
                    if start and end:
                        return (start, end)

            elif item.is_a("IfcLine"):
                # Line representation
                origin = get_coordinate(item.Pnt)
                direction = np.array(item.Dir.DirectionRatios)
                magnitude = getattr(item, "Magnitude", 1.0)
                end = (np.array(origin) + direction * magnitude).tolist()
                return (origin, end)

    except Exception as e:
        logger.warning(f"Error extracting from axis representation: {e}")

    return None


def extract_from_body_representation(
    representation: ifcopenshell.entity_instance,
) -> Optional[Tuple]:
    """
    Extract geometry from a Body representation.

    Args:
        representation: IFC body representation

    Returns:
        Tuple of start and end points
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        for item in representation.Items:
            if item.is_a("IfcExtrudedAreaSolid"):
                # Common representation for beams and columns
                if (
                    hasattr(item, "Position")
                    and item.Position
                    and hasattr(item, "ExtrudedDirection")
                    and item.ExtrudedDirection
                    and hasattr(item, "Depth")
                ):
                    # Get start position
                    start = get_coordinate(item.Position.Location)

                    # Get direction and depth
                    direction = np.array(item.ExtrudedDirection.DirectionRatios)
                    normalized_dir = direction / np.linalg.norm(direction)
                    depth = item.Depth

                    # Calculate end point
                    end = (np.array(start) + normalized_dir * depth).tolist()

                    return (start, end)

    except Exception as e:
        logger.warning(f"Error extracting from body representation: {e}")

    return None


def extract_geometry_from_representation(
    representation: ifcopenshell.entity_instance,
) -> Optional[Tuple]:
    """
    Generic function to extract curve geometry from any representation.

    Args:
        representation: IFC representation

    Returns:
        Tuple of start and end points if found, None otherwise
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        # Try different extraction methods
        for item in representation.Items:
            # Handle mapped representations
            if item.is_a("IfcMappedItem"):
                if (
                    hasattr(item, "MappingSource")
                    and item.MappingSource
                    and hasattr(item.MappingSource, "MappedRepresentation")
                ):
                    # Recursively process the mapped representation
                    geometry = extract_geometry_from_representation(
                        item.MappingSource.MappedRepresentation
                    )
                    if geometry:
                        # Apply mapping transform if needed
                        if hasattr(item, "MappingTarget") and item.MappingTarget:
                            # Handle mapping transformation (simplified)
                            # This would need to be expanded for complex mappings
                            pass
                        return geometry

            # Try to extract edge geometry
            elif (
                item.is_a("IfcEdge") or item.is_a("IfcPolyline") or item.is_a("IfcLine")
            ):
                if item.is_a("IfcEdge"):
                    if (
                        hasattr(item, "EdgeStart")
                        and item.EdgeStart
                        and hasattr(item, "EdgeEnd")
                        and item.EdgeEnd
                    ):
                        start = get_coordinate(item.EdgeStart.VertexGeometry)
                        end = get_coordinate(item.EdgeEnd.VertexGeometry)
                        if start and end:
                            return (start, end)

                elif item.is_a("IfcPolyline"):
                    if hasattr(item, "Points") and len(item.Points) >= 2:
                        start = get_coordinate(item.Points[0])
                        end = get_coordinate(item.Points[-1])
                        if start and end:
                            return (start, end)

                elif item.is_a("IfcLine"):
                    origin = get_coordinate(item.Pnt)
                    direction = np.array(item.Dir.DirectionRatios)
                    magnitude = getattr(item, "Magnitude", 1.0)
                    end = (np.array(origin) + direction * magnitude).tolist()
                    return (origin, end)

            # Extract from solid
            elif item.is_a("IfcExtrudedAreaSolid"):
                if (
                    hasattr(item, "Position")
                    and item.Position
                    and hasattr(item, "ExtrudedDirection")
                    and item.ExtrudedDirection
                    and hasattr(item, "Depth")
                ):
                    # Get start position
                    start = get_coordinate(item.Position.Location)

                    # Get direction and depth
                    direction = np.array(item.ExtrudedDirection.DirectionRatios)
                    normalized_dir = direction / np.linalg.norm(direction)
                    depth = item.Depth

                    # Calculate end point
                    end = (np.array(start) + normalized_dir * depth).tolist()

                    return (start, end)

    except Exception as e:
        logger.warning(f"Error extracting geometry from representation: {e}")

    return None
