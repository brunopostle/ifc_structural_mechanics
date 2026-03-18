"""
Gmsh geometry conversion module for the IFC structural analysis extension.

This module provides functionality to convert domain model geometric representations
to Gmsh geometry objects, supporting various member types and applying meshing parameters.

Supports conforming meshes via shared Gmsh topology: members that meet at
connections share Gmsh points, and `gmsh.model.occ.fragment()` is used to
produce shared topology at intersections so that the resulting mesh has
coincident nodes without post-hoc constraints.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import gmsh
import numpy as np

from ..config.meshing_config import MeshingConfig
from ..domain.structural_member import CurveMember, SurfaceMember
from ..domain.structural_model import StructuralModel

logger = logging.getLogger(__name__)

# Coordinate rounding precision for the shared point registry.
# 6 decimal places gives ~micron tolerance for meter-scale models.
COORD_PRECISION = 6


class GmshGeometryConverter:
    """
    Converts domain model geometry to Gmsh geometry objects.

    This class handles the conversion of structural members from the domain model
    to Gmsh geometry, applying appropriate meshing parameters and preserving
    geometric properties.

    When `convert_model()` is used, geometry is created with shared points at
    connection locations and `fragment()` is called to produce conforming meshes.
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

        # Separate point registries per dimension to avoid beam-shell node sharing
        # which causes CalculiX KNOT overflow (gen3dnor) on large models.
        # Key: rounded (x,y,z) -> Gmsh point tag
        self._curve_point_registry: Dict[Tuple[float, float, float], int] = {}
        self._surface_point_registry: Dict[Tuple[float, float, float], int] = {}

        # Accumulators for bulk fragment operation
        self._all_curve_dim_tags: List[Tuple[int, int]] = []
        self._all_surface_dim_tags: List[Tuple[int, int]] = []

        # Per-member tag tracking (member.id -> list of tags)
        self._member_point_tags: Dict[str, List[int]] = {}
        self._member_curve_tags: Dict[str, List[int]] = {}
        self._member_surface_tags: Dict[str, List[int]] = {}

        # Per-member mesh sizes (member.id -> element_size)
        self._member_mesh_sizes: Dict[str, float] = {}

        # Fragment results
        self._fragment_map: Optional[List] = None

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
        # when Gmsh is uninitialized --- it just prints to stderr and returns 0.
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

    # ------------------------------------------------------------------
    # Shared point registry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coord_key(x: float, y: float, z: float) -> Tuple[float, float, float]:
        """Round coordinates to a canonical key for the point registry."""
        return (
            round(float(x), COORD_PRECISION),
            round(float(y), COORD_PRECISION),
            round(float(z), COORD_PRECISION),
        )

    def _get_or_create_point(self, x: float, y: float, z: float, dim: int = 1) -> int:
        """Reuse an existing Gmsh OCC point at this location, or create a new one.

        Args:
            x, y, z: Coordinates.
            dim: Owning entity dimension (1=curve, 2=surface). Points are only
                 shared within the same dimension to avoid CalculiX KNOT
                 generation at beam-shell shared nodes.
        """
        registry = (
            self._curve_point_registry if dim == 1 else self._surface_point_registry
        )
        key = self._coord_key(x, y, z)
        if key in registry:
            return registry[key]
        tag = gmsh.model.occ.addPoint(float(x), float(y), float(z))
        registry[key] = tag
        return tag

    # ------------------------------------------------------------------
    # Internal geometry creation (no synchronize, no mesh size)
    # ------------------------------------------------------------------

    def _create_curve_geometry(
        self, member: CurveMember
    ) -> Tuple[List[int], List[int]]:
        """
        Create Gmsh OCC geometry for a curve member without synchronizing.

        Uses the shared point registry so that members meeting at the same
        location share Gmsh points.

        Returns:
            (line_tags, point_tags)
        """
        curve_points = self._convert_curve(member.geometry)

        point_tags = []
        for point in curve_points:
            try:
                pt = self._get_or_create_point(point[0], point[1], point[2], dim=1)
                point_tags.append(pt)
            except Exception as e:
                logger.warning(f"Error adding Gmsh point for member {member.id}: {e}")

        line_tags = []
        for i in range(len(point_tags) - 1):
            try:
                line_tag = gmsh.model.occ.addLine(point_tags[i], point_tags[i + 1])
                line_tags.append(line_tag)
            except Exception as e:
                logger.warning(f"Error adding Gmsh line for member {member.id}: {e}")

        # Accumulate for fragment
        for tag in line_tags:
            self._all_curve_dim_tags.append((1, tag))

        # Store per-member tags
        self._member_point_tags[member.id] = point_tags
        self._member_curve_tags[member.id] = line_tags

        # Store element type and mesh size
        element_type = self.meshing_config.get_element_type("curve_members")
        element_size = self.meshing_config.get_element_size("curve_members")
        self._member_mesh_sizes[member.id] = element_size

        # Update entity map
        self._entity_map[member.id] = {
            "type": "curve",
            "gmsh_tags": line_tags,
            "element_type": element_type,
        }

        logger.debug(
            f"Created curve geometry for {member.id}: {len(line_tags)} lines, "
            f"{len(point_tags)} points"
        )
        return line_tags, point_tags

    def _create_surface_geometry(
        self, member: SurfaceMember
    ) -> Tuple[Optional[int], List[int]]:
        """
        Create Gmsh OCC geometry for a surface member without synchronizing.

        Uses the shared point registry so that members meeting at the same
        location share Gmsh points.

        Returns:
            (surface_tag, point_tags)  -- surface_tag may be None on failure
        """
        surface_points = self._convert_surface(member.geometry)

        point_tags = []
        for point in surface_points:
            try:
                pt = self._get_or_create_point(point[0], point[1], point[2], dim=2)
                point_tags.append(pt)
            except Exception as e:
                logger.warning(f"Error adding Gmsh point for member {member.id}: {e}")

        # Create lines forming a closed loop
        line_tags = []
        for i in range(len(point_tags)):
            try:
                line_tag = gmsh.model.occ.addLine(
                    point_tags[i], point_tags[(i + 1) % len(point_tags)]
                )
                line_tags.append(line_tag)
            except Exception as e:
                logger.warning(f"Error adding Gmsh line for member {member.id}: {e}")

        # Create curve loop and surface
        surface_tag = None
        try:
            curve_loop_tag = gmsh.model.occ.addCurveLoop(line_tags)
            surface_tag = gmsh.model.occ.addPlaneSurface([curve_loop_tag])
        except Exception as e:
            logger.warning(f"Error creating surface for member {member.id}: {e}")
            return None, point_tags

        # Accumulate for fragment
        self._all_surface_dim_tags.append((2, surface_tag))

        # Store per-member tags
        self._member_point_tags[member.id] = point_tags
        self._member_surface_tags[member.id] = [surface_tag]

        # Store element type and mesh size
        element_type = self.meshing_config.get_element_type("surface_members")
        element_size = self.meshing_config.get_element_size("surface_members")
        self._member_mesh_sizes[member.id] = element_size

        # Update entity map
        self._entity_map[member.id] = {
            "type": "surface",
            "gmsh_tags": [surface_tag],
            "element_type": element_type,
        }

        logger.debug(
            f"Created surface geometry for {member.id}: surface tag {surface_tag}, "
            f"{len(point_tags)} points"
        )
        return surface_tag, point_tags

    # ------------------------------------------------------------------
    # Fragment and remap
    # ------------------------------------------------------------------

    def _fragment_all_entities(self) -> None:
        """
        Fragment geometry entities to create shared topology.

        Fragments curves against curves and surfaces against surfaces
        SEPARATELY, so beam-beam connections and slab-slab connections share
        mesh nodes, but beam-shell connections do NOT share nodes.

        This avoids CalculiX KNOT generation at beam-shell shared nodes,
        which causes ``gen3dnor`` memory overflow on large models.
        Beam-to-shell coupling is handled by ``*EQUATION`` constraints instead.
        """
        self._fragment_map = None
        curve_map = None
        surface_map = None

        # Fragment curves against curves
        if len(self._all_curve_dim_tags) >= 2:
            try:
                out_c, map_c = gmsh.model.occ.fragment(self._all_curve_dim_tags, [])
                curve_map = map_c
                logger.info(
                    f"Fragment curves: {len(self._all_curve_dim_tags)} -> {len(out_c)}"
                )
            except Exception as e:
                logger.warning(f"Curve fragment failed: {e}")

        # Fragment surfaces against surfaces
        if len(self._all_surface_dim_tags) >= 2:
            try:
                out_s, map_s = gmsh.model.occ.fragment(self._all_surface_dim_tags, [])
                surface_map = map_s
                logger.info(
                    f"Fragment surfaces: {len(self._all_surface_dim_tags)} -> {len(out_s)}"
                )
            except Exception as e:
                logger.warning(f"Surface fragment failed: {e}")

        # Build combined fragment_map aligned with the combined input list
        # (curves first, then surfaces) so _remap_tags_after_fragment works
        if curve_map is not None or surface_map is not None:
            combined = []
            for i in range(len(self._all_curve_dim_tags)):
                if curve_map is not None and i < len(curve_map):
                    combined.append(curve_map[i])
                else:
                    combined.append([self._all_curve_dim_tags[i]])
            for i in range(len(self._all_surface_dim_tags)):
                if surface_map is not None and i < len(surface_map):
                    combined.append(surface_map[i])
                else:
                    combined.append([self._all_surface_dim_tags[i]])
            self._fragment_map = combined

    def _remap_tags_after_fragment(self, domain_model: StructuralModel) -> None:
        """
        After fragment(), update entity_map and register traceability.

        Fragment may change entity tags (renumber or split). We use the
        out_map returned by fragment() to build old->new mappings.
        """
        if self._fragment_map is None:
            # No fragment was done; register tags as-is
            self._register_traceability_no_fragment(domain_model)
            return

        # Build old_dim_tag -> [new_dim_tags] mapping
        input_dim_tags = self._all_curve_dim_tags + self._all_surface_dim_tags
        old_to_new: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
        for i, old_dt in enumerate(input_dim_tags):
            if i < len(self._fragment_map):
                old_to_new[old_dt] = self._fragment_map[i]
            else:
                old_to_new[old_dt] = [old_dt]

        # Update per-member curve tags
        for member_id, old_tags in self._member_curve_tags.items():
            new_tags = []
            for old_tag in old_tags:
                old_dt = (1, old_tag)
                for new_dt in old_to_new.get(old_dt, [old_dt]):
                    if new_dt[0] == 1:
                        new_tags.append(new_dt[1])
            self._member_curve_tags[member_id] = new_tags

            # Update entity map
            if member_id in self._entity_map:
                self._entity_map[member_id]["gmsh_tags"] = new_tags

        # Update per-member surface tags
        for member_id, old_tags in self._member_surface_tags.items():
            new_tags = []
            for old_tag in old_tags:
                old_dt = (2, old_tag)
                for new_dt in old_to_new.get(old_dt, [old_dt]):
                    if new_dt[0] == 2:
                        new_tags.append(new_dt[1])
            self._member_surface_tags[member_id] = new_tags

            # Update entity map
            if member_id in self._entity_map:
                self._entity_map[member_id]["gmsh_tags"] = new_tags

        # Register traceability
        self._register_traceability(domain_model)

    def _register_traceability_no_fragment(self, domain_model: StructuralModel) -> None:
        """Register mesh entity traceability when no fragment was performed."""
        self._register_traceability(domain_model)

    def _register_traceability(self, domain_model: StructuralModel) -> None:
        """Register mesh entity IDs in domain model for all members."""
        dm = getattr(self, "domain_model", None) or domain_model
        if not dm:
            return

        for member_id, tags in self._member_curve_tags.items():
            mesh_ids = [str(tag) for tag in tags]
            dm.register_mesh_entities(member_id, mesh_ids, entity_type="member")

        for member_id, tags in self._member_surface_tags.items():
            mesh_ids = [str(tag) for tag in tags]
            dm.register_mesh_entities(member_id, mesh_ids, entity_type="member")

    # ------------------------------------------------------------------
    # Physical groups for element-to-member mapping
    # ------------------------------------------------------------------

    def _create_physical_groups(self, domain_model: StructuralModel) -> None:
        """
        Create Gmsh physical groups so mesh elements inherit member ownership.

        Each member gets a unique physical group tag. When Gmsh generates the
        mesh, each element's parent geometry entity determines its physical
        group, which meshio reads as cell_data['gmsh:physical']. The writer
        uses this to map elements to domain members.

        Stores mapping in self.physical_group_map: {phys_tag: member_id}
        """
        self.physical_group_map: Dict[int, str] = {}
        phys_tag = 1

        for member in domain_model.members:
            mid = member.id
            if isinstance(member, CurveMember):
                tags = self._member_curve_tags.get(mid, [])
                dim = 1
            elif isinstance(member, SurfaceMember):
                tags = self._member_surface_tags.get(mid, [])
                dim = 2
            else:
                continue

            if not tags:
                continue

            try:
                gmsh.model.addPhysicalGroup(dim, tags, phys_tag)
                gmsh.model.setPhysicalName(dim, phys_tag, mid)
                self.physical_group_map[phys_tag] = mid
                phys_tag += 1
            except Exception as e:
                logger.debug(f"Could not create physical group for {mid}: {e}")

        logger.info(f"Created {len(self.physical_group_map)} physical groups")

    # ------------------------------------------------------------------
    # Mesh size application
    # ------------------------------------------------------------------

    def _apply_all_mesh_sizes(self, domain_model: StructuralModel) -> None:
        """
        Apply mesh sizes to all member points after synchronize.

        For shared points (used by multiple members), use the minimum size.
        """
        # Build point -> min mesh size mapping
        point_sizes: Dict[int, float] = {}

        for member in domain_model.members:
            size = self._member_mesh_sizes.get(member.id)
            if size is None:
                continue
            pts = self._member_point_tags.get(member.id, [])
            for pt in pts:
                if pt in point_sizes:
                    point_sizes[pt] = min(point_sizes[pt], size)
                else:
                    point_sizes[pt] = size

        # Also collect points from post-fragment entities that may have new tags
        # Get all points in the model after synchronize
        try:
            all_points = gmsh.model.getEntities(0)
            # For any point not yet assigned a size, use a reasonable default
            default_size = min(point_sizes.values()) if point_sizes else 1.0
            for dim, tag in all_points:
                if tag not in point_sizes:
                    point_sizes[tag] = default_size
        except Exception:
            pass

        # Apply sizes
        for pt, size in point_sizes.items():
            try:
                gmsh.model.mesh.setSize([(0, pt)], size)
            except Exception as e:
                logger.debug(f"Could not set mesh size for point {pt}: {e}")

    # ------------------------------------------------------------------
    # Main entry point: convert_model with shared topology
    # ------------------------------------------------------------------

    def convert_model(self, domain_model: StructuralModel) -> Dict[str, Any]:
        """
        Convert an entire domain model to Gmsh geometry with conforming topology.

        Uses shared points and fragment() to produce a mesh where connected
        members share nodes automatically.

        Args:
            domain_model (StructuralModel): The structural model to convert.

        Returns:
            Dict[str, Any]: A mapping of member IDs to their Gmsh geometric entities.
        """
        # Ensure Gmsh is initialized
        self._ensure_gmsh_initialized()

        # Clear state
        self._entity_map = {}
        self._curve_point_registry = {}
        self._surface_point_registry = {}
        self._all_curve_dim_tags = []
        self._all_surface_dim_tags = []
        self._member_point_tags = {}
        self._member_curve_tags = {}
        self._member_surface_tags = {}
        self._member_mesh_sizes = {}
        self._fragment_map = None

        # Phase 1: Create all geometry with shared points (no synchronize)
        for member in domain_model.members:
            if isinstance(member, CurveMember):
                self._create_curve_geometry(member)
            elif isinstance(member, SurfaceMember):
                self._create_surface_geometry(member)

        # Phase 2: Fragment for shared topology
        self._fragment_all_entities()

        # Phase 3: Single synchronize
        try:
            gmsh.model.occ.synchronize()
        except Exception as e:
            logger.warning(f"Error synchronizing Gmsh model: {e}")

        # Phase 4: Remap tags + traceability
        self._remap_tags_after_fragment(domain_model)

        # Phase 5: Apply mesh sizes
        self._apply_all_mesh_sizes(domain_model)

        # Phase 6: Create physical groups for element-to-member mapping
        self._create_physical_groups(domain_model)

        shared_curve_pts = len(self._curve_point_registry)
        shared_surface_pts = len(self._surface_point_registry)
        logger.info(
            f"Converted model with {len(self._entity_map)} members, "
            f"{shared_curve_pts} shared curve points, "
            f"{shared_surface_pts} shared surface points"
        )
        return self._entity_map

    # ------------------------------------------------------------------
    # Public standalone API (for individual member conversion and tests)
    # ------------------------------------------------------------------

    def convert_curve_member(self, member: CurveMember) -> List[int]:
        """
        Convert a curve member to Gmsh geometry (standalone, with synchronize).

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
        if hasattr(self, "domain_model") and self.domain_model:
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
        Convert a surface member to Gmsh geometry (standalone, with synchronize).

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
        if hasattr(self, "domain_model") and self.domain_model:
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
        logger.warning(
            "Mapping file generation deprecated - traceability is in domain model"
        )

    def load_mapping(self, file_path: str) -> None:
        """Load mapping (deprecated - traceability is now in domain model)."""
        logger.warning(
            "Mapping file loading deprecated - traceability is in domain model"
        )

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
