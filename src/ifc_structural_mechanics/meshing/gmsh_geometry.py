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
from ..domain.load import PointLoad
from ..domain.structural_member import CurveMember, SurfaceMember
from ..domain.structural_model import StructuralModel
from ..utils.error_handling import MeshingError

logger = logging.getLogger(__name__)

# Coordinate rounding precision for the shared point registry.
# 6 decimal places gives ~micron tolerance for meter-scale models.
COORD_PRECISION = 6
# Points this close are one: rounding to COORD_PRECISION moves one by up to 9e-7,
# and fragment() moves a vertex it merges.
SAME_POINT_TOLERANCE = 5e-6


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

    def _ensure_gmsh_initialized(self) -> None:
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
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Failed to initialize Gmsh: {e}", code="E-MSH-001"
                ) from e

        # A model of this name left over from an earlier run is replaced
        if "structural_model" in gmsh.model.list():
            gmsh.model.setCurrent("structural_model")
            gmsh.model.remove()
        gmsh.model.add("structural_model")

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
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Error adding Gmsh point for member {member.id}: {e}",
                    code="E-MSH-001",
                ) from e

        line_tags = []
        for i in range(len(point_tags) - 1):
            try:
                line_tag = gmsh.model.occ.addLine(point_tags[i], point_tags[i + 1])
                line_tags.append(line_tag)
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Error adding Gmsh line for member {member.id}: {e}",
                    code="E-MSH-001",
                ) from e

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
        point_tags: List[int] = []
        curve_loop_tags = [
            self._create_surface_loop(member, corners, point_tags)
            for corners in [member.geometry, *member.holes]
        ]

        # Create the surface, its outline first and then its holes
        surface_tag = None
        try:
            surface_tag = gmsh.model.occ.addPlaneSurface(curve_loop_tags)
        except MeshingError:
            raise
        except Exception as e:
            raise MeshingError(
                f"Error creating surface for member {member.id}: {e}", code="E-MSH-001"
            ) from e

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

    def _create_surface_loop(
        self, member: SurfaceMember, corners: Any, point_tags: List[int]
    ) -> int:
        """Create a closed loop through the corners of an outline or a hole.

        Args:
            member: The surface member, for messages.
            corners: The corners of the loop.
            point_tags: The tags of its points are added to this list.

        Returns:
            The tag of the curve loop.
        """
        tags = []
        for point in self._convert_surface(corners):
            try:
                tags.append(
                    self._get_or_create_point(point[0], point[1], point[2], dim=2)
                )
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Error adding Gmsh point for member {member.id}: {e}",
                    code="E-MSH-001",
                ) from e
        point_tags.extend(tags)

        line_tags = []
        for i in range(len(tags)):
            try:
                line_tags.append(
                    gmsh.model.occ.addLine(tags[i], tags[(i + 1) % len(tags)])
                )
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Error adding Gmsh line for member {member.id}: {e}",
                    code="E-MSH-001",
                ) from e
        try:
            return gmsh.model.occ.addCurveLoop(line_tags)
        except MeshingError:
            raise
        except Exception as e:
            raise MeshingError(
                f"Error creating surface for member {member.id}: {e}", code="E-MSH-001"
            ) from e

    # ------------------------------------------------------------------
    # Fragment and remap
    # ------------------------------------------------------------------

    def _fragment_all_entities(
        self,
        support_point_tags: Optional[List[int]] = None,
        surface_point_tags: Optional[List[int]] = None,
        surface_piece_tags: Optional[List[Tuple[int, int]]] = None,
    ) -> None:
        """
        Fragment geometry entities to create shared topology.

        Fragments curves against curves and surfaces against surfaces
        SEPARATELY, so beam-beam connections and slab-slab connections share
        mesh nodes, but beam-shell connections do NOT share nodes.

        This avoids CalculiX KNOT generation at beam-shell shared nodes,
        which causes ``gen3dnor`` memory overflow on large models.
        Beam-to-shell coupling is handled by ``*EQUATION`` constraints instead.

        Args:
            support_point_tags: Gmsh point tags seeded at intermediate support
                positions.  These are passed as *tools* to fragment() so that
                curves are split exactly at those positions, guaranteeing a mesh
                node for each intermediate support.
            surface_point_tags: Gmsh point tags where connections land on a
                surface member. Passed as *tools* to the surface fragment() so
                the shell mesh has a node at each of them.
            surface_piece_tags: Surfaces where a surface support covers a
                surface member (``_surface_support_pieces``), and the lines of
                line connections joining a beam to it (``_seed_line_joints``),
                passed as tools so the shell mesh follows them.
        """
        self._fragment_map = None
        curve_map = None
        surface_map = None

        support_dim_tags = [(0, pt) for pt in (support_point_tags or [])]

        # Fragment curves against curves (and against support points as tools)
        if len(self._all_curve_dim_tags) >= 2 or (
            self._all_curve_dim_tags and support_dim_tags
        ):
            try:
                out_c, map_c = gmsh.model.occ.fragment(
                    self._all_curve_dim_tags, support_dim_tags
                )
                # map_c has len(curves) + len(support_points) entries;
                # we only use the first len(curves) entries in _remap_tags_after_fragment.
                curve_map = map_c
                logger.info(
                    f"Fragment curves: {len(self._all_curve_dim_tags)} -> {len(out_c)}"
                    + (
                        f" (split at {len(support_dim_tags)} support point(s))"
                        if support_dim_tags
                        else ""
                    )
                )
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Curve fragment failed: {e}", code="E-MSH-001"
                ) from e

        # Fragment surfaces against surfaces (and against connection points
        # and the parts of them that surface supports cover)
        surface_tools = [(0, pt) for pt in (surface_point_tags or [])]
        surface_tools += list(surface_piece_tags or [])
        if len(self._all_surface_dim_tags) >= 2 or (
            self._all_surface_dim_tags and surface_tools
        ):
            try:
                out_s, map_s = gmsh.model.occ.fragment(
                    self._all_surface_dim_tags, surface_tools
                )
                surface_map = map_s
                logger.info(
                    f"Fragment surfaces: {len(self._all_surface_dim_tags)} -> {len(out_s)}"
                )
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Surface fragment failed: {e}", code="E-MSH-001"
                ) from e

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
    # Support point seeding
    # ------------------------------------------------------------------

    @staticmethod
    def _point_on_segment(
        p: np.ndarray, a: np.ndarray, b: np.ndarray, tol: float = 1e-4
    ) -> bool:
        """Return True if point *p* lies strictly inside segment [a, b].

        "Strictly inside" means not at an endpoint, so supports that coincide
        with member endpoints (already in the shared point registry) are not
        re-seeded.

        Args:
            p: Point to test.
            a: Segment start.
            b: Segment end.
            tol: Perpendicular distance tolerance in the same units as the
                 coordinates (default 0.1 mm for metre-scale models).
        """
        ab = b - a
        ab_len = float(np.linalg.norm(ab))
        if ab_len < tol:
            return False

        ap = p - a
        # Perpendicular distance from p to line ab
        perp = np.linalg.norm(np.cross(ab / ab_len, ap))
        if perp > tol:
            return False

        # Parametric position along segment
        t = float(np.dot(ap, ab) / (ab_len * ab_len))
        return tol / ab_len < t < 1.0 - tol / ab_len

    def _seed_support_points(self, domain_model: StructuralModel) -> List[int]:
        """
        Add Gmsh points at connection positions that lie strictly inside member curves.

        When a support, or a joint that another member frames into, is at an
        intermediate position on a beam (not at an endpoint), Gmsh normally
        places no mesh node there.  By seeding a point and including it as a
        *tool* in the subsequent fragment() call, the curve is split at that
        position and the mesher places a node exactly there.

        Returns:
            List of Gmsh point tags to pass as tools to fragment().
        """
        seeded: List[int] = []

        for conn in domain_model.connections:
            if not (hasattr(conn, "position") and conn.position):
                continue

            try:
                pos = np.array([float(v) for v in conn.position], dtype=float)
            except (TypeError, ValueError):
                continue

            # Skip if a curve point already exists here (endpoint of some member).
            key = self._coord_key(pos[0], pos[1], pos[2])
            if key in self._curve_point_registry:
                continue

            # Check whether pos lies strictly inside any member curve segment.
            found = False
            for member in domain_model.members:
                if not isinstance(member, CurveMember):
                    continue
                geom = member.geometry
                if not geom or len(geom) < 2:
                    continue

                for i in range(len(geom) - 1):
                    try:
                        a = np.array([float(v) for v in geom[i]], dtype=float)
                        b = np.array([float(v) for v in geom[i + 1]], dtype=float)
                    except (TypeError, ValueError):
                        continue

                    if self._point_on_segment(pos, a, b):
                        pt_tag = self._get_or_create_point(
                            pos[0], pos[1], pos[2], dim=1
                        )
                        seeded.append(pt_tag)
                        logger.info(
                            f"Seeded support point at {pos.tolist()} on "
                            f"member {member.id} segment {i}–{i+1}"
                        )
                        found = True
                        break

                if found:
                    break

            if not found:
                # Real connection not at any member endpoint or segment — warn.
                logger.debug(
                    f"Support {conn.id} at {pos.tolist()} does not lie on "
                    f"any member curve; no point seeded"
                )

        return seeded

    def _seed_load_points(self, domain_model: StructuralModel) -> List[int]:
        """Add Gmsh points where a load along a curve member starts, ends or turns,
        and where a point load acts on the span of one.

        A line load given by samples (``LineLoad.samples``) may start part
        of the way along its member and change slope at each sample. The
        shear force has a kink there, which an element cannot follow inside
        itself; with a node at each sample the nodal forces are those of a
        load that is linear over every element. A point load (one of the
        forces of a DISCRETE curve action, say) would go to the nearest node,
        which is not where it acts.

        Returns:
            List of Gmsh point tags to pass as tools to fragment().
        """
        seeded: List[int] = []
        loads = [load for group in domain_model.load_groups for load in group.loads]
        for member in domain_model.members:
            loads.extend(getattr(member, "loads", None) or [])
        for load in loads:
            if isinstance(load, PointLoad):
                seeded.extend(self._seed_point_on_curve_members(load, domain_model))
                continue
            samples = getattr(load, "samples", None)
            if not samples:
                continue
            start = np.array(load.start_position, dtype=float)
            end = np.array(load.end_position, dtype=float)
            length = float(np.linalg.norm(end - start))
            if length < 1e-9:
                continue
            for location, _ in samples:
                position = start + (end - start) * float(location) / length
                if not self._point_on_segment(position, start, end):
                    continue  # an end of the member has its point already
                if self._coord_key(*position) in self._curve_point_registry:
                    continue
                seeded.append(self._get_or_create_point(*position, dim=1))
        return seeded

    def _seed_point_on_curve_members(
        self, load: PointLoad, domain_model: StructuralModel
    ) -> List[int]:
        """A Gmsh point at a point load that acts inside a curve member, if any."""
        try:
            position = np.array([float(v) for v in load.position], dtype=float)
        except (TypeError, ValueError):
            return []
        if position.shape != (3,):
            return []
        if self._coord_key(*position) in self._curve_point_registry:
            return []
        for member in domain_model.members:
            if not isinstance(member, CurveMember):
                continue
            geometry = member.geometry
            if not geometry or len(geometry) < 2:
                continue
            for a, b in zip(geometry[:-1], geometry[1:]):
                try:
                    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
                except (TypeError, ValueError):
                    continue
                if a.shape == b.shape == (3,) and self._point_on_segment(
                    position, a, b
                ):
                    return [self._get_or_create_point(*position, dim=1)]
        return []

    @classmethod
    def _point_on_surface(
        cls,
        point: np.ndarray,
        polygon: np.ndarray,
        holes: List[np.ndarray],
        tol: float = 1e-4,
    ) -> bool:
        """Whether *point* is on a face: in its outline, not inside a hole.

        The edge of a hole is part of the face.
        """
        if not cls._point_in_planar_polygon(point, polygon, tol):
            return False
        for hole in holes:
            if not cls._point_in_planar_polygon(point, hole, tol):
                continue
            on_edge = False
            for a, b in zip(hole, np.roll(hole, -1, axis=0)):
                along = b - a
                t = float(
                    np.clip(np.dot(point - a, along) / np.dot(along, along), 0, 1)
                )
                on_edge = on_edge or np.linalg.norm(a + t * along - point) <= tol
            if not on_edge:
                return False
        return True

    @staticmethod
    def _point_in_planar_polygon(
        point: np.ndarray, polygon: np.ndarray, tol: float = 1e-4
    ) -> bool:
        """Return True if *point* lies on the planar polygon (boundary included)."""
        if len(polygon) < 3:
            return False
        # Newell normal
        nxt = np.roll(polygon, -1, axis=0)
        normal = np.array(
            [
                np.sum((polygon[:, 1] - nxt[:, 1]) * (polygon[:, 2] + nxt[:, 2])),
                np.sum((polygon[:, 2] - nxt[:, 2]) * (polygon[:, 0] + nxt[:, 0])),
                np.sum((polygon[:, 0] - nxt[:, 0]) * (polygon[:, 1] + nxt[:, 1])),
            ]
        )
        length = np.linalg.norm(normal)
        if length < 1e-12:
            return False
        normal /= length
        if abs(np.dot(point - polygon[0], normal)) > tol:
            return False
        # Project onto the two axes most perpendicular to the normal
        drop = int(np.argmax(np.abs(normal)))
        keep = [i for i in range(3) if i != drop]
        px, py = point[keep]
        poly2d = polygon[:, keep]
        inside = False
        for (x0, y0), (x1, y1) in zip(poly2d, np.roll(poly2d, -1, axis=0)):
            edge = np.array([x1 - x0, y1 - y0])
            rel = np.array([px - x0, py - y0])
            edge_len = np.linalg.norm(edge)
            if edge_len > 1e-12:
                t = np.dot(rel, edge) / edge_len**2
                if -1e-9 <= t <= 1 + 1e-9:
                    if np.linalg.norm(rel - t * edge) <= tol:
                        return True  # on the boundary
            if (y0 > py) != (y1 > py):
                if px < x0 + (py - y0) * (x1 - x0) / (y1 - y0):
                    inside = not inside
        return inside

    def _seed_crossings(
        self, domain_model: StructuralModel
    ) -> Tuple[List[int], List[int]]:
        """Add Gmsh points where a curve member meets a surface member at a point.

        A column passing through a slab, or ending on one, touches it at a
        single point. Analysis models do not always put a connection there,
        and without one neither mesh has a node at that point. Seeding it in
        both lets the input writer tie the two together there.

        A curve member lying in the plane of a surface is not a crossing; its
        nodes are located in the shell mesh by the writer.

        Returns:
            ``(curve point tags, surface point tags)`` to pass as tools to the
            two fragment() calls.
        """
        surfaces = []
        for member in domain_model.members:
            if not isinstance(member, SurfaceMember):
                continue
            try:
                polygon = np.array(
                    [
                        [float(v) for v in p]
                        for p in self._convert_surface(member.geometry)
                    ],
                    dtype=float,
                )
            except (TypeError, ValueError, KeyError, NotImplementedError):
                continue
            if polygon.ndim != 2 or polygon.shape[1] != 3 or len(polygon) < 3:
                continue
            normal = np.zeros(3)
            for i in range(len(polygon)):
                normal += np.cross(polygon[i], polygon[(i + 1) % len(polygon)])
            length = float(np.linalg.norm(normal))
            if length < 1e-12:
                continue
            surfaces.append(
                (
                    polygon,
                    normal / length,
                    polygon.min(axis=0),
                    polygon.max(axis=0),
                    [np.array(hole, dtype=float) for hole in member.holes],
                )
            )
        if not surfaces:
            return [], []

        tol = 1e-4
        curve_tags: List[int] = []
        surface_tags: List[int] = []
        for member in domain_model.members:
            if not isinstance(member, CurveMember):
                continue
            geom = member.geometry
            if not geom or len(geom) < 2:
                continue
            for i in range(len(geom) - 1):
                try:
                    a = np.array([float(v) for v in geom[i]], dtype=float)
                    b = np.array([float(v) for v in geom[i + 1]], dtype=float)
                except (TypeError, ValueError):
                    continue
                low, high = np.minimum(a, b) - tol, np.maximum(a, b) + tol
                for polygon, normal, s_low, s_high, holes in surfaces:
                    if (high < s_low).any() or (low > s_high).any():
                        continue
                    along = float(np.dot(b - a, normal))
                    if abs(along) < 1e-9 * max(float(np.linalg.norm(b - a)), 1e-12):
                        continue  # parallel to the surface, or lying in it
                    t = float(np.dot(polygon[0] - a, normal)) / along
                    reach = tol / float(np.linalg.norm(b - a))
                    if t < -reach or t > 1.0 + reach:
                        continue
                    point = a + min(max(t, 0.0), 1.0) * (b - a)
                    if not self._point_on_surface(point, polygon, holes):
                        continue
                    key = self._coord_key(point[0], point[1], point[2])
                    if key not in self._surface_point_registry:
                        surface_tags.append(
                            self._get_or_create_point(
                                point[0], point[1], point[2], dim=2
                            )
                        )
                    if key not in self._curve_point_registry and reach < t < 1 - reach:
                        curve_tags.append(
                            self._get_or_create_point(
                                point[0], point[1], point[2], dim=1
                            )
                        )
        if curve_tags or surface_tags:
            logger.info(
                f"Seeded {len(surface_tags)} point(s) on surfaces and "
                f"{len(curve_tags)} on curves where they cross"
            )
        return curve_tags, surface_tags

    def _seed_surface_connection_points(
        self, domain_model: StructuralModel
    ) -> List[int]:
        """Add Gmsh points where connections land on a surface member.

        A column meeting a slab, or a point support under one, usually falls
        inside the slab or along its edge, where the surface mesher would not
        place a node. Passing a point there as a *tool* to the surface
        fragment() makes it part of the surface topology, so the shell mesh
        gets a node exactly at the connection and the joint can share it.

        Returns:
            List of Gmsh point tags to pass as tools to the surface fragment().
        """
        polygons = []
        for member in domain_model.members:
            if not isinstance(member, SurfaceMember):
                continue
            try:
                polygon = np.array(
                    [
                        [float(v) for v in p]
                        for p in self._convert_surface(member.geometry)
                    ],
                    dtype=float,
                )
            except (TypeError, ValueError, KeyError, NotImplementedError):
                continue
            if polygon.ndim == 2 and polygon.shape[1] == 3 and len(polygon) >= 3:
                holes = [np.array(hole, dtype=float) for hole in member.holes]
                polygons.append((member.id, polygon, holes))
        if not polygons:
            return []

        seeded: List[int] = []
        for conn in domain_model.connections:
            if not (hasattr(conn, "position") and conn.position):
                continue
            surface_ids = {
                m
                for m in conn.connected_members
                if isinstance(domain_model.get_member(m), SurfaceMember)
            }
            if not surface_ids:
                continue
            try:
                pos = np.array([float(v) for v in conn.position], dtype=float)
            except (TypeError, ValueError):
                continue
            if self._coord_key(pos[0], pos[1], pos[2]) in self._surface_point_registry:
                continue  # already a corner of some surface
            for member_id, polygon, holes in polygons:
                if member_id in surface_ids and self._point_on_surface(
                    pos, polygon, holes
                ):
                    seeded.append(
                        self._get_or_create_point(pos[0], pos[1], pos[2], dim=2)
                    )
                    break
        if seeded:
            logger.info(f"Seeded {len(seeded)} connection point(s) on surfaces")
        return seeded

    def _surface_support_pieces(
        self, domain_model: StructuralModel
    ) -> List[Tuple[int, int]]:
        """The parts of surface members that surface supports cover.

        A surface support (``connection.face``) may cover a slab in part: a
        strip footing under a raft. Its outline is intersected with every
        surface member, and the pieces fragment the members, so the shell
        mesh has edges along the outline and its elements lie inside the
        support or outside it, which the spring shares of an elastic one
        need. The outline is built with points of its own and removed after,
        so nothing of it is meshed but the pieces.

        Returns:
            The (2, tag) of each piece, to pass as tools to the surface
            fragment().
        """
        faces = [
            conn.face
            for conn in domain_model.connections
            if getattr(conn, "face", None) is not None
        ]
        members = [
            tag
            for member in domain_model.members
            if isinstance(member, SurfaceMember)
            for tag in self._member_surface_tags.get(member.id, [])
        ]
        if not faces or not members:
            return []
        pieces: List[Tuple[int, int]] = []
        for face in faces:
            try:
                points = [
                    gmsh.model.occ.addPoint(*(float(v) for v in corner))
                    for corner in face
                ]
                lines = [
                    gmsh.model.occ.addLine(points[i], points[(i + 1) % len(points)])
                    for i in range(len(points))
                ]
                outline = gmsh.model.occ.addPlaneSurface(
                    [gmsh.model.occ.addCurveLoop(lines)]
                )
                for tag in members:
                    common, _ = gmsh.model.occ.intersect(
                        [(2, outline)],
                        [(2, tag)],
                        removeObject=False,
                        removeTool=False,
                    )
                    pieces += [dim_tag for dim_tag in common if dim_tag[0] == 2]
                gmsh.model.occ.remove([(2, outline)], recursive=True)
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Could not lay a surface support onto the surface members: {e}",
                    code="E-MSH-004",
                ) from e
        if pieces:
            logger.info(f"Surface supports cover {len(pieces)} piece(s) of surfaces")
        return pieces

    def _line_joints(self, domain_model: StructuralModel) -> List[tuple]:
        """The line connections joining a straight curve member to surface members.

        Returns:
            ``(beam id, plate ids, start, end, offset)`` for each, with the
            line's ends and ``offset`` the step from the beam to the line,
            across it (zero for a beam lying in the surface). Lines the curve
            member does not run along are left to the writer to report.
        """
        joints = []
        for conn in domain_model.connections:
            edge = getattr(conn, "edge", None)
            if edge is None:
                continue
            members = [domain_model.get_member(m) for m in conn.connected_members]
            beams = [m for m in members if isinstance(m, CurveMember)]
            plates = [m.id for m in members if isinstance(m, SurfaceMember)]
            if len(beams) != 1 or not plates:
                continue
            try:
                start, end = (np.array(p, dtype=float) for p in edge)
                geometry = self._convert_curve(beams[0].geometry)
            except (TypeError, ValueError, KeyError, NotImplementedError):
                continue
            if len(geometry) != 2:
                continue
            a, b = (np.array(p, dtype=float) for p in geometry)
            along, axis = end - start, b - a
            length = float(np.linalg.norm(along))
            if length < 1e-9 or float(np.linalg.norm(axis)) < 1e-9:
                continue
            along /= length
            if abs(float(along @ axis)) < (1.0 - 1e-3) * float(np.linalg.norm(axis)):
                continue
            offset = (start - a) - float((start - a) @ along) * along
            joints.append((beams[0].id, plates, start, end, offset))
        return joints

    def _seed_line_joints(
        self, domain_model: StructuralModel
    ) -> Tuple[List[int], List[Tuple[int, int]]]:
        """Mesh a line connection into the slab, node for node with its beam.

        A beam and a slab joined rigidly along a line share nodes there (or
        have a rigid link between each pair, where the beam is eccentric).
        The line becomes an edge of the slab's mesh, and the beam is split
        wherever the line, the slab or the beam has a point on it, so that
        both are cut into the same pieces. ``_conform_line_joints`` then
        gives each pair of pieces the same number of nodes.

        Called after all other seeding, so the points it mirrors are known.

        Returns:
            Point tags to pass as tools to the curve fragment(), and the
            ``(1, tag)`` lines to pass as tools to the surface fragment().
        """
        self._line_joint_pieces: List[tuple] = []
        curve_tools: List[int] = []
        surface_tools: List[Tuple[int, int]] = []
        for beam_id, plates, start, end, offset in self._line_joints(domain_model):
            along = end - start
            length = float(np.linalg.norm(along))
            along /= length
            beam_start, beam_end = start - offset, end - offset

            # Every point on the line or on the beam along it, by its distance
            # along the line. Each keeps its own coordinates: one rebuilt from a
            # rounded distance lands beside the point it came from.
            stations = {0.0: start, length: end}
            for registry, shift in (
                (self._curve_point_registry, offset),
                (self._surface_point_registry, np.zeros(3)),
            ):
                for key in registry:
                    point = np.array(key, dtype=float) + shift
                    s = float((point - start) @ along)
                    if 1e-6 < s < length - 1e-6 and self._point_on_segment(
                        point, start, end
                    ):
                        stations.setdefault(round(s, COORD_PRECISION), point)

            points = [stations[s] for s in sorted(stations)]
            surface_points = [
                self._get_or_create_point(*point, dim=2) for point in points
            ]
            for i in range(len(points) - 1):
                surface_tools.append(
                    (
                        1,
                        gmsh.model.occ.addLine(
                            surface_points[i], surface_points[i + 1]
                        ),
                    )
                )
            for point in points:
                on_beam = point - offset
                if self._point_on_segment(on_beam, beam_start, beam_end):
                    curve_tools.append(self._get_or_create_point(*on_beam, dim=1))
            size = min(
                self._member_mesh_sizes.get(m, np.inf) for m in [beam_id, *plates]
            )
            self._line_joint_pieces.append(
                (beam_id, offset, list(zip(points[:-1], points[1:])), size)
            )
        if self._line_joint_pieces:
            logger.info(
                f"Meshed {len(self._line_joint_pieces)} line connection(s) into "
                "their surface members"
            )
        return sorted(set(curve_tools)), surface_tools

    def _conform_line_joints(self) -> None:
        """Give the beam and slab pieces of each line connection the same nodes.

        Each piece of the line in the slab and the piece of the beam beside
        it are straight and of one length; meshed with the same number of
        evenly spaced nodes, their nodes (middle ones too) fall at the same
        places along them.

        Raises:
            MeshingError: If a piece of the line has no curve in the slab.
        """
        pieces = getattr(self, "_line_joint_pieces", [])
        if not pieces:
            return
        tags, firsts, seconds = [], [], []
        for _, tag in gmsh.model.getEntities(1):
            ends = gmsh.model.getBoundary([(1, tag)], oriented=False)
            if len(ends) == 2:
                tags.append(tag)
                first, second = (
                    gmsh.model.getValue(0, abs(point), []) for _, point in ends
                )
                firsts.append(first)
                seconds.append(second)
        firsts = np.array(firsts).reshape(-1, 3)
        seconds = np.array(seconds).reshape(-1, 3)

        def curves_between(a: np.ndarray, b: np.ndarray) -> List[int]:
            """The curves from a to b, by distance: fragment() moves vertices."""
            at_a = np.linalg.norm(firsts - a, axis=1) < SAME_POINT_TOLERANCE
            at_b = np.linalg.norm(seconds - b, axis=1) < SAME_POINT_TOLERANCE
            b_first = np.linalg.norm(firsts - b, axis=1) < SAME_POINT_TOLERANCE
            a_second = np.linalg.norm(seconds - a, axis=1) < SAME_POINT_TOLERANCE
            return [
                tags[i] for i in np.flatnonzero((at_a & at_b) | (b_first & a_second))
            ]

        for beam_id, offset, segments, size in pieces:
            beam_tags = set(self._member_curve_tags.get(beam_id, []))
            for a, b in segments:
                count = max(1, int(np.ceil(float(np.linalg.norm(b - a)) / size - 1e-9)))
                in_slab = [tag for tag in curves_between(a, b) if tag not in beam_tags]
                if not in_slab:
                    raise MeshingError(
                        f"The line from {a.tolist()} to {b.tolist()}, which joins "
                        f"member {beam_id} to a surface, is not in the surface's "
                        "geometry.",
                        code="E-MSH-004",
                    )
                on_beam = [
                    tag
                    for tag in curves_between(a - offset, b - offset)
                    if tag in beam_tags
                ]
                for tag in in_slab + on_beam:
                    gmsh.model.mesh.setTransfiniteCurve(tag, count + 1)

    def _create_physical_groups(self, domain_model: StructuralModel) -> None:
        """
        Create Gmsh physical groups so mesh elements inherit member ownership.

        Each member gets a unique physical group tag. When Gmsh generates the
        mesh, each element's parent geometry entity determines its physical
        group, which meshio reads as cell_data['gmsh:physical']. The writer
        uses this to map elements to domain members.

        A mesh element carries one physical group, so a geometry entity must
        be in one group only. Where members overlap, fragment() gives them the
        same entities: over the whole of both (two identical members) or over
        a part (a short beam lying inside a longer one). Entities are
        therefore grouped by the set of members they belong to, and the group
        is named with all of them ("MemberA||MemberB"), which the writer
        splits to give the elements to each. A member that overlaps another
        over a part has a group of its own for the rest.

        Stores mapping in self.physical_group_map: {phys_tag: member_id}
        (last member in an overlapping group; use physical group name to get all).
        """
        self.physical_group_map: Dict[int, str] = {}

        # (dim, tag) -> the members it belongs to, in the order of the model
        owners: Dict[Tuple[int, int], List[str]] = {}
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
            for tag in tags:
                entity_owners = owners.setdefault((dim, tag), [])
                if mid not in entity_owners:
                    entity_owners.append(mid)

        # (dim, members) -> tags
        groups: Dict[Tuple[int, Tuple[str, ...]], List[int]] = {}
        for (dim, tag), member_ids in owners.items():
            groups.setdefault((dim, tuple(member_ids)), []).append(tag)

        phys_tag = 1
        for (dim, member_ids), tags in groups.items():
            # Combine names for overlapping members so the writer can assign
            # elements to all of them from a single physical group.
            group_name = "||".join(member_ids)
            if len(member_ids) > 1:
                logger.info(
                    f"Geometry overlap detected: {list(member_ids)} share "
                    f"{len(tags)} entity tag(s) — combined into one physical group"
                )

            try:
                gmsh.model.addPhysicalGroup(dim, tags, phys_tag)
                gmsh.model.setPhysicalName(dim, phys_tag, group_name)
                for mid in member_ids:
                    self.physical_group_map[phys_tag] = mid
                phys_tag += 1
            except MeshingError:
                raise
            except Exception as e:
                raise MeshingError(
                    f"Could not create physical group for {list(member_ids)}: {e}",
                    code="E-MSH-001",
                ) from e

        logger.info(f"Created {phys_tag - 1} physical groups")

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
        existing = {tag for _, tag in gmsh.model.getEntities(0)}
        # For any point not yet assigned a size, use a reasonable default
        default_size = min(point_sizes.values()) if point_sizes else 1.0
        for tag in existing:
            point_sizes.setdefault(tag, default_size)

        # Apply sizes; fragmenting merges coincident points, so some of the
        # tags recorded before it no longer exist
        for pt, size in point_sizes.items():
            if pt in existing:
                gmsh.model.mesh.setSize([(0, pt)], size)

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

        # Phase 1.5: Seed Gmsh points at support positions that lie on beam
        # interiors so that fragment() splits the curve there and the mesher
        # places a node at the exact support location.
        support_point_tags = self._seed_support_points(domain_model)
        support_point_tags += self._seed_load_points(domain_model)
        surface_point_tags = self._seed_surface_connection_points(domain_model)
        crossing_curve_tags, crossing_surface_tags = self._seed_crossings(domain_model)
        support_point_tags += crossing_curve_tags
        surface_point_tags += crossing_surface_tags
        surface_piece_tags = self._surface_support_pieces(domain_model)
        line_curve_tags, line_surface_tags = self._seed_line_joints(domain_model)
        support_point_tags += line_curve_tags
        surface_piece_tags += line_surface_tags

        # Phase 2: Fragment for shared topology
        self._fragment_all_entities(
            support_point_tags, surface_point_tags, surface_piece_tags
        )

        # Phase 3: Single synchronize
        try:
            gmsh.model.occ.synchronize()
        except MeshingError:
            raise
        except Exception as e:
            raise MeshingError(
                f"Error synchronizing Gmsh model: {e}", code="E-MSH-001"
            ) from e

        # Phase 4: Remap tags + traceability
        self._remap_tags_after_fragment(domain_model)

        # Phase 5: Apply mesh sizes
        self._apply_all_mesh_sizes(domain_model)
        self._conform_line_joints()

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
