"""
Gmsh geometry conversion module for the IFC structural analysis extension.

This module provides functionality to convert domain model geometric representations
to Gmsh geometry objects, supporting various member types and applying meshing parameters.
"""

from typing import Any, Dict, List, Optional
import gmsh
import numpy as np
import logging
from ..config.meshing_config import MeshingConfig
from ..domain.structural_model import StructuralModel
from ..domain.structural_member import CurveMember, SurfaceMember

logger = logging.getLogger(__name__)


class GmshGeometryConverter:
    """
    Converts domain model geometry to Gmsh geometry objects.

    This class handles the conversion of structural members from the domain model
    to Gmsh geometry, applying appropriate meshing parameters and preserving
    geometric properties.
    """

    def __init__(
        self,
        meshing_config: Optional[MeshingConfig] = None,
        domain_model: Optional[StructuralModel] = None,
    ):
        """
        Initialize the Gmsh geometry converter.

        Args:
            meshing_config (Optional[MeshingConfig]): Meshing configuration to use.
                If not provided, a default configuration will be created.
            domain_model (Optional[StructuralModel]): Domain model for registering
                mesh entity traceability. If not provided, traceability won't be registered.
        """
        # Track if we initialized Gmsh ourselves
        self._we_initialized_gmsh = False

        # Flag to track if we've checked Gmsh initialization
        self._gmsh_checked = False

        # Use provided config or create default
        self.meshing_config = meshing_config or MeshingConfig()

        # Store domain model reference for traceability
        self.domain_model = domain_model

        # Maintain backward compatibility with _entity_map for existing tests
        self._entity_map = {}

    def _ensure_gmsh_initialized(self):
        """
        Ensure Gmsh is initialized before performing operations.

        This prevents "Gmsh has not been initialized" errors by checking and
        initializing Gmsh only when needed.
        """
        # Skip if we've already checked initialization
        if self._gmsh_checked:
            return

        # Set flag to avoid repeated checks
        self._gmsh_checked = True

        # Use gmsh.isInitialized() for a reliable check.
        # Note: gmsh.option.getNumber() does NOT raise a Python exception
        # when Gmsh is uninitialized — it just prints to stderr and returns 0.
        if not gmsh.isInitialized():
            try:
                gmsh.initialize()
                self._we_initialized_gmsh = True

                # Reduce terminal output
                gmsh.option.setNumber("General.Terminal", 0)
            except Exception as e:
                logger.warning(f"Failed to initialize Gmsh: {e}")

        # Now try to set up the model
        try:
            # Try to add a new model
            try:
                gmsh.model.add("structural_model")
            except Exception as e:
                logger.debug(f"Could not add model: {e}")
                # If model already exists, remove it first
                try:
                    gmsh.model.remove()
                    gmsh.model.add("structural_model")
                except Exception as e:
                    logger.debug(f"Could not remove/add model: {e}")
                    # If that still fails, just continue
                    pass
        except Exception as e:
            logger.warning(f"Failed to set up Gmsh model: {e}")

    def convert_model(self, domain_model: StructuralModel) -> Dict[str, Any]:
        """
        Convert an entire domain model to Gmsh geometry.

        Args:
            domain_model (StructuralModel): The structural model to convert.

        Returns:
            Dict[str, Any]: A mapping of member IDs to their Gmsh geometric entities.
        """
        # Ensure Gmsh is initialized
        self._ensure_gmsh_initialized()

        # Clear the entity map for backward compatibility
        self._entity_map = {}

        # Convert members based on their type
        for member in domain_model.members:
            if isinstance(member, CurveMember):
                self.convert_curve_member(member)
            elif isinstance(member, SurfaceMember):
                self.convert_surface_member(member)

        # Return the domain to Gmsh mapping from the mapper
        # But also maintain backward compatibility with _entity_map
        return self._entity_map

    def convert_curve_member(self, member: CurveMember) -> List[int]:
        """
        Convert a curve member to Gmsh geometry.

        Args:
            member (CurveMember): The curve member to convert.

        Returns:
            List[int]: List of Gmsh entity tags created for this member.
        """
        # Ensure Gmsh is initialized
        self._ensure_gmsh_initialized()

        # Get element type and size for curve members
        element_type = self.meshing_config.get_element_type("curve_members")
        element_size = self.meshing_config.get_element_size("curve_members")

        # Convert curve geometry
        curve_points = self._convert_curve(member.geometry)

        # Create line from points
        line_tags = []
        point_tags = []

        # First create all points
        for point in curve_points:
            try:
                point_tag = gmsh.model.occ.addPoint(point[0], point[1], point[2])
                point_tags.append(point_tag)
            except Exception as e:
                logger.warning(f"Error adding Gmsh point: {e}")

        # Then create lines between consecutive points
        for i in range(len(point_tags) - 1):
            try:
                line_tag = gmsh.model.occ.addLine(point_tags[i], point_tags[i + 1])
                line_tags.append(line_tag)
            except Exception as e:
                logger.warning(f"Error adding Gmsh line: {e}")

        # Synchronize before applying mesh parameters
        try:
            gmsh.model.occ.synchronize()
        except Exception as e:
            logger.warning(f"Error synchronizing Gmsh model: {e}")

        # Apply mesh size to the points (instead of lines)
        for point_tag in point_tags:
            try:
                gmsh.model.mesh.setSize([(0, point_tag)], element_size)
            except Exception as e:
                logger.warning(f"Error setting mesh size: {e}")

        # Register mesh entities in domain model for traceability
        if hasattr(self, 'domain_model') and self.domain_model:
            # Convert tags to strings for consistent ID format
            mesh_ids = [str(tag) for tag in line_tags]
            self.domain_model.register_mesh_entities(
                member.id, mesh_ids, entity_type="member"
            )

        # Maintain backward compatibility with _entity_map
        self._entity_map[member.id] = {
            "type": "curve",
            "gmsh_tags": line_tags,
            "element_type": element_type,
        }

        logger.info(
            f"Converted curve member {member.id} to Gmsh geometry with {len(line_tags)} line segments"
        )
        return line_tags

    def convert_surface_member(self, member: SurfaceMember) -> List[int]:
        """
        Convert a surface member to Gmsh geometry.

        Args:
            member (SurfaceMember): The surface member to convert.

        Returns:
            List[int]: List of Gmsh entity tags created for this member.
        """
        # Ensure Gmsh is initialized
        self._ensure_gmsh_initialized()

        # Get element type and size for surface members
        element_type = self.meshing_config.get_element_type("surface_members")
        element_size = self.meshing_config.get_element_size("surface_members")

        # Convert surface geometry
        surface_points = self._convert_surface(member.geometry)

        # Create points
        point_tags = []
        for point in surface_points:
            try:
                point_tag = gmsh.model.occ.addPoint(point[0], point[1], point[2])
                point_tags.append(point_tag)
            except Exception as e:
                logger.warning(f"Error adding Gmsh point: {e}")

        # Create lines to form a closed loop
        line_tags = []
        for i in range(len(point_tags)):
            try:
                line_tag = gmsh.model.occ.addLine(
                    point_tags[i], point_tags[(i + 1) % len(point_tags)]
                )
                line_tags.append(line_tag)
            except Exception as e:
                logger.warning(f"Error adding Gmsh line: {e}")

        # Create a curve loop
        curve_loop_tag = None
        surface_tag = None
        try:
            curve_loop_tag = gmsh.model.occ.addCurveLoop(line_tags)

            # Create the surface using the curve loop
            surface_tag = gmsh.model.occ.addPlaneSurface([curve_loop_tag])
        except Exception as e:
            logger.warning(f"Error creating surface: {e}")
            # Return early if we couldn't create the surface
            if not surface_tag:
                return []

        # Synchronize before applying mesh parameters
        try:
            gmsh.model.occ.synchronize()
        except Exception as e:
            logger.warning(f"Error synchronizing Gmsh model: {e}")

        # Apply mesh size to points
        for point_tag in point_tags:
            try:
                gmsh.model.mesh.setSize([(0, point_tag)], element_size)
            except Exception as e:
                logger.warning(f"Error setting mesh size: {e}")

        # Register mesh entities in domain model for traceability
        if hasattr(self, 'domain_model') and self.domain_model:
            # Convert tag to string for consistent ID format
            mesh_ids = [str(surface_tag)]
            self.domain_model.register_mesh_entities(
                member.id, mesh_ids, entity_type="member"
            )

        # Maintain backward compatibility with _entity_map
        self._entity_map[member.id] = {
            "type": "surface",
            "gmsh_tags": [surface_tag] if surface_tag else [],
            "element_type": element_type,
        }

        logger.info(
            f"Converted surface member {member.id} to Gmsh geometry with surface tag {surface_tag}"
        )
        return [surface_tag] if surface_tag else []

    def apply_mesh_size(
        self, gmsh_entity: int, size: float, dimension: int = 1
    ) -> None:
        """
        Apply mesh size to a Gmsh geometric entity.

        Args:
            gmsh_entity (int): Gmsh entity tag to apply mesh size to.
            size (float): Desired mesh element size.
            dimension (int, optional): Dimension of the entity. Defaults to 1 (curve).
        """
        # Ensure Gmsh is initialized
        self._ensure_gmsh_initialized()

        # Apply mesh size using the simpler setSize method instead of fields
        try:
            gmsh.model.mesh.setSize([(dimension, gmsh_entity)], size)
        except Exception as e:
            logger.warning(f"Error applying mesh size: {e}")

    def _convert_point(self, point: Any) -> np.ndarray:
        """
        Convert a point representation to a numpy array.

        This is a placeholder method that should be overridden or extended
        to handle different point representations from the domain model.

        Args:
            point (Any): Point representation from the domain model.

        Returns:
            np.ndarray: 3D point coordinates.

        Raises:
            NotImplementedError: If point conversion is not implemented.
        """
        # Basic implementation - assumes point is already a list or numpy array of 3 coordinates
        if isinstance(point, (list, np.ndarray)) and len(point) == 3:
            return np.array(point)

        raise NotImplementedError(
            f"Point conversion not implemented for type {type(point)}"
        )

    def _convert_curve(self, curve: Any) -> List[np.ndarray]:
        """
        Convert a curve representation to a list of points.

        This method handles different curve representations from the domain model,
        including tuples of points, lists of points, and other formats.

        Args:
            curve (Any): Curve representation from the domain model.

        Returns:
            List[np.ndarray]: List of 3D point coordinates representing the curve.

        Raises:
            NotImplementedError: If curve conversion is not implemented for this type.
        """
        # Check if the list is empty
        if isinstance(curve, list) and len(curve) == 0:
            raise NotImplementedError("Cannot convert empty curve points")

        # Case 1: Handle tuple of two points (start, end)
        if (
            isinstance(curve, tuple)
            and len(curve) == 2
            and all(isinstance(p, (list, tuple, np.ndarray)) for p in curve)
        ):
            return [np.array(curve[0], dtype=float), np.array(curve[1], dtype=float)]

        # Case 2: Handle list of points
        if isinstance(curve, list):
            # Check if it's a list of points
            if all(
                isinstance(p, (list, tuple, np.ndarray)) and len(p) == 3 for p in curve
            ):
                return [np.array(p, dtype=float) for p in curve]

        # Case 3: Handle dictionary format with "boundaries"
        if isinstance(curve, dict) and "boundaries" in curve:
            boundaries = curve.get("boundaries", [])
            if boundaries and isinstance(boundaries[0], list):
                return [np.array(p, dtype=float) for p in boundaries[0]]

        # Case 4: Extract from geometry in the IFC format
        if isinstance(curve, dict) and "type" in curve:
            if curve["type"] == "line":
                if "start" in curve and "end" in curve:
                    return [
                        np.array(curve["start"], dtype=float),
                        np.array(curve["end"], dtype=float),
                    ]

        # Log the unsupported curve format for debugging
        logger.error(f"Unsupported curve format: {type(curve)}, content: {curve}")

        # If we get here, the format is not recognized
        raise NotImplementedError(f"Cannot convert curve points: {curve}")

    def _convert_surface(self, surface: Any) -> List[np.ndarray]:
        """
        Convert a surface representation to a list of points forming the boundary.

        This method handles different surface representations from the domain model,
        including dictionaries with boundaries and lists of points.

        Args:
            surface (Any): Surface representation from the domain model.

        Returns:
            List[np.ndarray]: List of 3D point coordinates representing the surface boundary.

        Raises:
            NotImplementedError: If surface conversion is not implemented for this type.
        """
        # Check if the list is empty
        if isinstance(surface, list) and len(surface) == 0:
            raise NotImplementedError("Cannot convert empty surface points")

        # Case 1: Dictionary with boundaries key
        if isinstance(surface, dict) and "boundaries" in surface:
            boundaries = surface["boundaries"]
            if boundaries and isinstance(boundaries, list):
                if boundaries[0] and isinstance(boundaries[0], list):
                    # Extract the first boundary loop for simple surfaces
                    boundary = boundaries[0]
                    return [np.array(p, dtype=float) for p in boundary]

        # Case 2: Dictionary with specific geometry format
        if isinstance(surface, dict) and "type" in surface:
            if surface["type"] == "plane":
                # Extract boundary points if available
                if "boundaries" in surface and surface["boundaries"]:
                    boundary = surface["boundaries"][0]
                    return [np.array(p, dtype=float) for p in boundary]
                # Create a default rectangular boundary based on normal and point
                elif "normal" in surface and "point" in surface:
                    normal = np.array(surface["normal"], dtype=float)
                    point = np.array(surface["point"], dtype=float)
                    # Create a rectangle in plane defined by normal and point
                    return self._create_rectangle_in_plane(point, normal)

        # Case 3: List of boundary points
        if isinstance(surface, list):
            if len(surface) >= 3:  # Need at least 3 points for a surface
                if all(
                    isinstance(p, (list, tuple, np.ndarray)) and len(p) == 3
                    for p in surface
                ):
                    return [np.array(p, dtype=float) for p in surface]

        # If we get here, the format is not recognized
        raise NotImplementedError(f"Cannot convert surface points: {surface}")

    def _create_rectangle_in_plane(
        self, point: np.ndarray, normal: np.ndarray, size: float = 10.0
    ) -> List[np.ndarray]:
        """
        Create a rectangular boundary in a plane defined by a point and normal.

        Args:
            point: A point on the plane
            normal: Normal vector to the plane
            size: Size of the rectangle (default 10.0)

        Returns:
            List of 3D points forming a rectangle in the plane
        """
        # Normalize the normal vector
        normal = normal / np.linalg.norm(normal)

        # Find two perpendicular vectors in the plane
        if abs(normal[2]) < 0.9:  # Not aligned with Z axis
            v1 = np.cross(np.array([0, 0, 1]), normal)
        else:  # Aligned with Z axis, use X axis
            v1 = np.cross(np.array([1, 0, 0]), normal)

        v1 = v1 / np.linalg.norm(v1)
        v2 = np.cross(normal, v1)

        # Create four corners of the rectangle
        half_size = size / 2
        corners = [
            point - half_size * v1 - half_size * v2,
            point + half_size * v1 - half_size * v2,
            point + half_size * v1 + half_size * v2,
            point - half_size * v1 + half_size * v2,
        ]

        return corners

    def save_mapping(self, file_path: str) -> None:
        """Save mapping (deprecated - traceability is now in domain model)."""
        logger.warning("Mapping file generation deprecated - traceability is in domain model")

    def load_mapping(self, file_path: str) -> None:
        """Load mapping (deprecated - traceability is now in domain model)."""
        logger.warning("Mapping file loading deprecated - traceability is in domain model")

    def __del__(self):
        """
        Cleanup Gmsh resources when the converter is deleted.
        """
        # Only finalize Gmsh if we were the ones who initialized it
        if hasattr(self, "_we_initialized_gmsh") and self._we_initialized_gmsh:
            try:
                gmsh.finalize()
            except Exception:
                # Ignore any errors during finalization
                pass
