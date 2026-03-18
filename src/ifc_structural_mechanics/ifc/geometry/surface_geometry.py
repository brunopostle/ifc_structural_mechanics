"""
Surface geometry extraction utilities for IFC structural models.

This module provides functions to extract and process surface geometries from
IFC entities, particularly for structural surface members. It includes functions
for various IFC representation types and geometric operations on surfaces.
"""

import logging
from typing import Any, Dict, Optional

import ifcopenshell
import numpy as np

from ..entity_identifier import get_coordinate, get_transformation, transform_vectors

logger = logging.getLogger(__name__)


def extract_surface_geometry(
    entity: ifcopenshell.entity_instance,
) -> Optional[Dict[str, Any]]:
    """
    Extract surface geometry from an IFC entity.

    Args:
        entity: The IFC entity to extract surface geometry from

    Returns:
        A dictionary containing surface geometry information or None if extraction fails
    """
    if entity is None:
        logger.warning("Cannot extract surface geometry from None entity")
        return None

    try:
        # Check if entity has a representation
        if not hasattr(entity, "Representation") or not entity.Representation:
            logger.warning(f"No representation found for entity {entity.id()}")
            return None

        # Try different methods to extract the geometry

        # Method 1: Extract from Face representation (most common for structural)
        representation = get_representation(entity, "Face")
        if representation:
            geometry = extract_from_face_representation(representation, entity)
            if geometry:
                return geometry

        # Method 2: Extract from Surface representation
        representation = get_representation(entity, "Surface")
        if representation:
            geometry = extract_from_surface_representation(representation, entity)
            if geometry:
                return geometry

        # Method 3: Extract from Body representation
        representation = get_representation(entity, "Body")
        if representation:
            geometry = extract_from_body_representation(representation, entity)
            if geometry:
                return geometry

        # Method 4: Extract from general representation
        for rep in entity.Representation.Representations:
            geometry = extract_geometry_from_representation(rep, entity)
            if geometry:
                return geometry

        logger.warning(f"Could not extract surface geometry for entity {entity.id()}")
        return None

    except Exception as e:
        logger.error(f"Error extracting surface geometry from {entity.id()}: {e}")
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


def extract_plane(plane: ifcopenshell.entity_instance) -> Dict[str, Any]:
    """
    Extract plane geometry from an IfcPlane entity.

    Args:
        plane: IfcPlane entity

    Returns:
        Dictionary containing plane geometry information
    """
    # Default values
    point = (0.0, 0.0, 0.0)
    normal = (0.0, 0.0, 1.0)
    x_dir = (1.0, 0.0, 0.0)
    y_dir = (0.0, 1.0, 0.0)
    boundaries = []

    # Check if the plane has a position
    if hasattr(plane, "Position") and plane.Position:
        position = plane.Position

        # Extract location
        if hasattr(position, "Location") and position.Location:
            location = position.Location
            if hasattr(location, "Coordinates"):
                coords = tuple(location.Coordinates)
                # Ensure 3D point
                point = coords if len(coords) == 3 else (coords[0], coords[1], 0.0)

        # Extract axis (normal)
        if (
            hasattr(position, "Axis")
            and position.Axis
            and hasattr(position.Axis, "DirectionRatios")
        ):
            normal = tuple(position.Axis.DirectionRatios)

        # Extract x direction
        if (
            hasattr(position, "RefDirection")
            and position.RefDirection
            and hasattr(position.RefDirection, "DirectionRatios")
        ):
            x_dir = tuple(position.RefDirection.DirectionRatios)

        # Compute y direction (cross product)
        z = np.array(normal)
        x = np.array(x_dir)
        z_norm = z / np.linalg.norm(z)
        x_norm = x / np.linalg.norm(x)

        # Ensure x is perpendicular to z
        x_norm = x_norm - np.dot(x_norm, z_norm) * z_norm
        x_norm = x_norm / np.linalg.norm(x_norm)

        # Calculate y
        y = np.cross(z_norm, x_norm)
        # Convert y direction to a tuple
        y_dir = tuple(y)

        # Convert x direction to a tuple
        x_dir = tuple(x_norm)

    return {
        "type": "plane",
        "point": point,
        "normal": normal,
        "x_dir": x_dir,
        "y_dir": y_dir,
        "boundaries": boundaries,
    }


def extract_face_surface(
    face_surface: ifcopenshell.entity_instance,
) -> Optional[Dict[str, Any]]:
    """
    Extract geometry from an IfcFaceSurface entity.

    Args:
        face_surface: IFC face surface entity

    Returns:
        Dictionary containing surface geometry information
    """
    if (
        not face_surface
        or not hasattr(face_surface, "is_a")
        or not face_surface.is_a("IfcFaceSurface")
    ):
        return None

    # Check for FaceSurface attribute
    if not hasattr(face_surface, "FaceSurface"):
        return None

    face_surface_entity = face_surface.FaceSurface

    # Verify it's a plane
    if not (
        hasattr(face_surface_entity, "is_a") and face_surface_entity.is_a("IfcPlane")
    ):
        return None

    # Call extract_plane to get plane geometry
    return extract_plane(face_surface_entity)


def extract_from_face_representation(
    representation: ifcopenshell.entity_instance, entity: ifcopenshell.entity_instance
) -> Optional[Dict[str, Any]]:
    """
    Extract geometry from a Face representation.

    Args:
        representation: IFC face representation
        entity: Original IFC entity (for placement)

    Returns:
        Dictionary containing surface geometry information
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        item = representation.Items[0]

        if item.is_a("IfcFaceSurface") or item.is_a("IfcFace"):
            # Extract boundaries
            boundaries = []
            if hasattr(item, "Bounds"):
                for bound in item.Bounds:
                    if (
                        hasattr(bound, "Bound")
                        and bound.Bound
                        and bound.Bound.is_a("IfcPolyLoop")
                        and hasattr(bound.Bound, "Polygon")
                    ):
                        points = [get_coordinate(p) for p in bound.Bound.Polygon]
                        if all(points):
                            boundaries.append(points)

            # Try to get orientation from FaceSurface
            if item.is_a("IfcFaceSurface") and hasattr(item, "FaceSurface"):
                face_surface = item.FaceSurface
                if face_surface.is_a("IfcPlane"):
                    plane_geom = extract_plane(face_surface)
                    plane_geom["boundaries"] = boundaries
                    return plane_geom

            # Default plane if no explicit surface is found
            return {
                "type": "plane",
                "normal": [0, 0, 1],
                "point": [0, 0, 0],
                "x_dir": [1, 0, 0],
                "y_dir": [0, 1, 0],
                "boundaries": boundaries,
            }

    except Exception as e:
        logger.warning(f"Error extracting from face representation: {e}")

    return None


def extract_from_surface_representation(
    representation: ifcopenshell.entity_instance, entity: ifcopenshell.entity_instance
) -> Optional[Dict[str, Any]]:
    """
    Extract geometry from a Surface representation.

    Args:
        representation: IFC surface representation
        entity: Original IFC entity (for placement)

    Returns:
        Dictionary containing surface geometry information
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        for item in representation.Items:
            if item.is_a("IfcFaceSurface"):
                return extract_from_face_representation(representation, entity)
    except Exception as e:
        logger.warning(f"Error extracting from surface representation: {e}")

    return None


def extract_from_body_representation(
    representation: ifcopenshell.entity_instance, entity: ifcopenshell.entity_instance
) -> Optional[Dict[str, Any]]:
    """
    Extract surface geometry from a Body representation.

    Args:
        representation: IFC body representation
        entity: Original IFC entity (for placement)

    Returns:
        Dictionary containing surface geometry information
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        for item in representation.Items:
            # Extract from extruded area solid (common for walls, slabs)
            if item.is_a("IfcExtrudedAreaSolid"):
                if (
                    hasattr(item, "SweptArea")
                    and item.SweptArea
                    and hasattr(item, "Position")
                    and item.Position
                    and hasattr(item, "ExtrudedDirection")
                    and item.ExtrudedDirection
                ):
                    # Get profile information
                    profile = item.SweptArea
                    boundaries = []

                    if profile.is_a("IfcRectangleProfileDef"):
                        # Create rectangular boundary
                        width = profile.XDim
                        height = profile.YDim

                        # Create simple rectangle
                        points = [
                            [-width / 2, -height / 2, 0],
                            [width / 2, -height / 2, 0],
                            [width / 2, height / 2, 0],
                            [-width / 2, height / 2, 0],
                        ]
                        boundaries.append(points)

                    elif profile.is_a("IfcArbitraryClosedProfileDef") and hasattr(
                        profile, "OuterCurve"
                    ):
                        # Extract points from the profile curve
                        curve = profile.OuterCurve
                        if curve.is_a("IfcPolyline") and hasattr(curve, "Points"):
                            points = [get_coordinate(p) for p in curve.Points]
                            for i in range(len(points)):
                                if len(points[i]) == 2:  # Add z-coordinate if needed
                                    points[i].append(0.0)
                            boundaries.append(points)

                    # Get position and orientation
                    position = item.Position
                    origin = get_coordinate(position.Location)

                    # Get extrusion direction (normal)
                    normal = list(item.ExtrudedDirection.DirectionRatios)

                    # Get x and y directions
                    x_dir = [1, 0, 0]  # Default
                    y_dir = [0, 1, 0]  # Default

                    if hasattr(position, "RefDirection") and position.RefDirection:
                        x_dir = list(position.RefDirection.DirectionRatios)

                    if hasattr(position, "Axis") and position.Axis:
                        z_aux = list(position.Axis.DirectionRatios)
                        z = np.array(z_aux)
                        x = np.array(x_dir)
                        z_norm = z / np.linalg.norm(z)
                        x_norm = x / np.linalg.norm(x)

                        # Ensure x is perpendicular to z
                        x_norm = x_norm - np.dot(x_norm, z_norm) * z_norm
                        x_norm = x_norm / np.linalg.norm(x_norm)

                        # Calculate y
                        y = np.cross(z_norm, x_norm)
                        y_dir = y.tolist()

                        # Update x_dir to be properly orthogonal
                        x_dir = x_norm.tolist()

                    else:
                        # Calculate x and y based on normal
                        z = np.array(normal)
                        z_norm = z / np.linalg.norm(z)

                        # Find a perpendicular vector for x_dir
                        if abs(z_norm[2]) < 0.9:  # Not nearly parallel to global Z
                            aux = np.array([0, 0, 1])
                        else:
                            aux = np.array([1, 0, 0])

                        x = np.cross(aux, z_norm)
                        x_norm = x / np.linalg.norm(x)

                        # Calculate y direction
                        y = np.cross(z_norm, x_norm)
                        y_dir = y.tolist()
                        x_dir = x_norm.tolist()

                    # Apply position transformation to boundary points
                    transform = get_transformation(position)
                    if transform:
                        boundaries = transform_vectors(boundaries, transform)

                    # Apply object placement if available
                    if hasattr(entity, "ObjectPlacement") and entity.ObjectPlacement:
                        transformation = get_transformation(entity.ObjectPlacement)
                        if transformation:
                            # Transform boundary points
                            boundaries = transform_vectors(boundaries, transformation)

                            # Transform normal and directions (without translation)
                            origin = transform_vectors([origin], transformation)[0]
                            normal = transform_vectors(
                                [normal], transformation, include_translation=False
                            )[0]
                            x_dir = transform_vectors(
                                [x_dir], transformation, include_translation=False
                            )[0]
                            y_dir = transform_vectors(
                                [y_dir], transformation, include_translation=False
                            )[0]

                    return {
                        "type": "plane",
                        "normal": normal,
                        "point": origin,
                        "x_dir": x_dir,
                        "y_dir": y_dir,
                        "boundaries": boundaries,
                    }

            # Extract from faceted brep
            elif item.is_a("IfcFacetedBrep"):
                if hasattr(item, "Outer") and hasattr(item.Outer, "CfsFaces"):
                    # Get the first face with its bounds
                    boundaries = []
                    normal = [0, 0, 1]  # Default normal

                    for face in item.Outer.CfsFaces:
                        if hasattr(face, "Bounds"):
                            for bound in face.Bounds:
                                if (
                                    hasattr(bound, "Bound")
                                    and bound.Bound
                                    and bound.Bound.is_a("IfcPolyLoop")
                                ):
                                    points = [
                                        get_coordinate(p) for p in bound.Bound.Polygon
                                    ]
                                    if all(points):
                                        boundaries.append(points)

                            # Only process the first face for now
                            if boundaries:
                                # Calculate approximate normal from first face
                                if len(boundaries[0]) >= 3:
                                    p1 = np.array(boundaries[0][0])
                                    p2 = np.array(boundaries[0][1])
                                    p3 = np.array(boundaries[0][2])

                                    v1 = p2 - p1
                                    v2 = p3 - p1

                                    # Calculate normal using cross product
                                    n = np.cross(v1, v2)
                                    if np.linalg.norm(n) > 0:
                                        normal = (n / np.linalg.norm(n)).tolist()

                                break

                    if boundaries:
                        # Calculate origin as first point of first boundary
                        origin = boundaries[0][0]

                        # Calculate x and y directions based on normal
                        z = np.array(normal)
                        z_norm = z / np.linalg.norm(z)

                        # Find a perpendicular vector for x_dir
                        if abs(z_norm[2]) < 0.9:  # Not nearly parallel to global Z
                            aux = np.array([0, 0, 1])
                        else:
                            aux = np.array([1, 0, 0])

                        x = np.cross(aux, z_norm)
                        x_norm = x / np.linalg.norm(x)

                        # Calculate y direction
                        y = np.cross(z_norm, x_norm)
                        y_dir = y.tolist()
                        x_dir = x_norm.tolist()

                        # Apply object placement if available
                        if (
                            hasattr(entity, "ObjectPlacement")
                            and entity.ObjectPlacement
                        ):
                            transformation = get_transformation(entity.ObjectPlacement)
                            if transformation:
                                # Transform boundary points
                                boundaries = transform_vectors(
                                    boundaries, transformation
                                )

                                # Transform normal and directions (without translation)
                                origin = transform_vectors(origin, transformation)
                                normal = transform_vectors(
                                    [normal], transformation, include_translation=False
                                )[0]
                                x_dir = transform_vectors(
                                    [x_dir], transformation, include_translation=False
                                )[0]
                                y_dir = transform_vectors(
                                    [y_dir], transformation, include_translation=False
                                )[0]

                        return {
                            "type": "plane",
                            "normal": normal,
                            "point": origin,
                            "x_dir": x_dir,
                            "y_dir": y_dir,
                            "boundaries": boundaries,
                        }

    except Exception as e:
        logger.warning(f"Error extracting from body representation: {e}")

    return None


def extract_geometry_from_representation(
    representation: ifcopenshell.entity_instance, entity: ifcopenshell.entity_instance
) -> Optional[Dict[str, Any]]:
    """
    Generic function to extract surface geometry from any representation.

    Args:
        representation: IFC representation
        entity: Original IFC entity (for placement)

    Returns:
        Dictionary containing surface geometry information or None if extraction fails
    """
    if not hasattr(representation, "Items") or not representation.Items:
        return None

    try:
        # Try various extraction methods

        # Handle mapped items first
        for item in representation.Items:
            if item.is_a("IfcMappedItem"):
                if (
                    hasattr(item, "MappingSource")
                    and item.MappingSource
                    and hasattr(item.MappingSource, "MappedRepresentation")
                ):
                    # Recursively process the mapped representation
                    geometry = extract_geometry_from_representation(
                        item.MappingSource.MappedRepresentation, entity
                    )
                    if geometry:
                        # Apply mapping transform if needed
                        if hasattr(item, "MappingTarget") and item.MappingTarget:
                            # Handle the mapping transformation (simplified)
                            # This would need to be expanded for complex mappings
                            pass
                        return geometry

        # Process face based entities
        for item in representation.Items:
            if item.is_a("IfcFace") or item.is_a("IfcFaceSurface"):
                # Handle face-based representations
                item_rep = ifcopenshell.entity_instance()
                item_rep.Items = [item]
                return extract_from_face_representation(item_rep, entity)

            elif item.is_a("IfcFacetedBrep"):
                # Handle brep representations
                item_rep = ifcopenshell.entity_instance()
                item_rep.Items = [item]
                return extract_from_body_representation(item_rep, entity)

            elif item.is_a("IfcExtrudedAreaSolid"):
                # Handle extruded solids
                item_rep = ifcopenshell.entity_instance()
                item_rep.Items = [item]
                return extract_from_body_representation(item_rep, entity)

        # If no direct extraction methods worked, try a generic approach
        if representation.Items:
            # Try to extract from the first item that looks promising
            for item in representation.Items:
                if (
                    item.is_a("IfcExtrudedAreaSolid")
                    or item.is_a("IfcFacetedBrep")
                    or item.is_a("IfcFace")
                    or item.is_a("IfcFaceSurface")
                ):
                    # Create a new representation with just this item
                    item_rep = ifcopenshell.entity_instance()
                    item_rep.Items = [item]

                    # Try different extraction methods
                    result = extract_from_face_representation(item_rep, entity)
                    if result:
                        return result

                    result = extract_from_body_representation(item_rep, entity)
                    if result:
                        return result

        # If nothing worked but we have the thickness, we can create a default surface
        if hasattr(entity, "Thickness") and entity.Thickness:
            # Create a default horizontal plane with the correct thickness
            return {
                "type": "plane",
                "normal": [0, 0, 1],
                "point": [0, 0, 0],
                "x_dir": [1, 0, 0],
                "y_dir": [0, 1, 0],
                "boundaries": [[[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]]],
                "thickness": entity.Thickness,
            }

    except Exception as e:
        logger.warning(f"Error extracting geometry from representation: {e}")

    return None
