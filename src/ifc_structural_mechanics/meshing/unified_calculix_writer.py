"""
Unified CalculiX Input Writer - THE REAL SOLUTION

This module replaces both MeshConverter and CalculixInputGenerator with a single,
unified tool that writes CalculiX input files. No more dual systems, no fallbacks,
no conflicts.

PRINCIPLE: All geometry → Gmsh → Unified Writer → CalculiX input file

This eliminates the architectural problem at its source by having only ONE system
responsible for writing elements to CalculiX input files.
"""

import logging
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Set, TextIO, Tuple

import meshio
import numpy as np

# Import boundary condition and load handling
from ..analysis.boundary_condition_handling import (
    write_analysis_steps,
    write_boundary_conditions,
    write_equation,
)
from ..config.analysis_config import AnalysisConfig
from ..converters.section_profiles import (
    RECTANGLE_SHEAR_COEFFICIENT,
    TORSION_MATCHED_SECTIONS,
    equivalent_rectangle,
    equivalent_shear_moduli,
    get_native_section,
    rectangle_shear_moduli,
    uses_user_element,
)
from ..domain.structural_member import CurveMember, SurfaceMember
from ..domain.structural_model import StructuralModel
from ..utils.error_handling import (
    AnalysisError,
    MeshingError,
    StructuralAnalysisError,
)
from ..utils.messages import guids_of, record_warning
from ..utils.temp_dir import create_temp_subdir, get_temp_dir
from .mesh_mapper import BEAM_ELEMENT_TYPES, SHELL_ELEMENT_TYPES, MeshMapper

# Configure logging
logger = logging.getLogger(__name__)


class UnifiedCalculixWriter:
    """
    THE UNIFIED SOLUTION: Single tool for writing CalculiX input files.

    This replaces both MeshConverter and CalculixInputGenerator, eliminating
    the dual element writing problem by design.

    Workflow: Domain Model → Gmsh → UnifiedCalculixWriter → CalculiX Input File
    """

    # Element type mapping from Gmsh to CalculiX
    ELEMENT_TYPE_MAPPING = {
        # Line elements (beams, trusses)
        "line": "B31",
        "line2": "B31",
        # Reduced integration (expanded to C3D20R) is the beam element the
        # CalculiX manual recommends; B32 gives the same answers within 1 %.
        "line3": "B32R",
        # Triangle elements (shells)
        "triangle": "S3",
        "triangle3": "S3",
        "triangle6": "S6",
        # Quadrilateral elements (shells)
        "quad": "S4",
        "quad4": "S4",
        "quad8": "S8",
        "quad9": "S9",
        # Tetrahedral elements (solids)
        "tetra": "C3D4",
        "tetra10": "C3D10",
        # Hexahedral elements (solids)
        "hexahedron": "C3D8",
        "hexahedron20": "C3D20",
        "hexahedron27": "C3D27",
    }

    def __init__(
        self,
        domain_model: StructuralModel,
        analysis_config: Optional[AnalysisConfig] = None,
    ):
        """
        Initialize the unified CalculiX writer.

        Args:
            domain_model: The structural domain model
            analysis_config: Analysis configuration
        """
        self.domain_model = domain_model
        self.analysis_config = analysis_config or AnalysisConfig()

        # Single source of truth for mesh data
        self.nodes: Dict[int, Tuple[float, float, float]] = {}
        self.elements: Dict[int, Dict[str, Any]] = {}
        self.node_sets: Dict[str, List[int]] = {}
        self.element_sets: Dict[str, List[int]] = {}
        self.defined_element_sets: set = set()

        # Short ID mapping for CalculiX (20-char limit for set names)
        self.short_id_map: Dict[str, str] = {}
        self.short_id_counter = 0

        # U1 user-element tracking: members whose elements use TYPE=U1
        # (non-standard cross-sections: I, T, L, C, arbitrary)
        self._u1_members: set = set()  # member IDs that need U1 elements
        # Members analysed with an equivalent rectangle instead:
        # Curve members whose section had to be oriented without an IFC Axis
        self._members_without_axis: set = set()
        # member ID -> (a, b, factor), see equivalent_rectangle()
        self._equivalent_sections: Dict[str, Tuple[float, float, float]] = {}
        # Element set names (MEMBER_*) that contain only U1 elements.
        # Used by boundary_condition_handling to skip *DLOAD for these sets
        # (U1 elements don't support *DLOAD; facial-load processing crashes).
        self._u1_element_sets: set = set()
        self._equation_nodes: set = set()
        self._translation_ties: List[Tuple[int, int]] = []
        # Mass of the U1 elements lumped at their nodes (node_id -> kg)
        self._u1_node_masses: Dict[int, float] = {}

        # Working directory
        self.work_dir = create_temp_subdir(prefix="unified_calculix_")

        # Validation
        self._validate_domain_model()

    def _validate_domain_model(self) -> None:
        """Validate the domain model."""
        if not self.domain_model:
            raise AnalysisError("Domain model is missing", code="E-GEN-001")
        if not self.domain_model.members:
            raise AnalysisError("Domain model has no members", code="E-GEN-001")

        logger.info(
            f"Validated domain model with {len(self.domain_model.members)} members"
        )

    def _get_short_id(self, full_id: str) -> str:
        """
        Generate a short ID for CalculiX set names (20-char limit).

        CalculiX has a 20-character limit for set names. This method creates
        short, unique IDs (e.g., M1, M2, ...) mapped to full IFC GUIDs.

        Args:
            full_id: Full IFC GUID or entity ID

        Returns:
            Short ID suitable for CalculiX (max 20 chars)
        """
        if full_id not in self.short_id_map:
            self.short_id_counter += 1
            self.short_id_map[full_id] = f"M{self.short_id_counter}"
        return self.short_id_map[full_id]

    def _get_beam_normal(self, member: CurveMember) -> Tuple[float, float, float]:
        """Return the cross-section "1" direction for a beam member.

        CalculiX's ``*BEAM SECTION`` second data line is the direction of the
        section's local 1 axis. The first section dimension (RECT ``a``, BOX
        ``a``) is measured along it, and for ``SECTION=GENERAL`` the first
        inertia (``I11``) resists loads acting along it.

        IFC defines the member's local z by ``IfcStructuralCurveMember.Axis``
        and maps the profile's Y dimension (depth) onto it. So the direction
        written here is the IFC local z, paired with depth-first dimensions and
        ``I11 = Iy``. ``local_axis`` is ``(xAxis, yAxis, zAxis)`` with xAxis
        along the member.

        Args:
            member: CurveMember with local_axis from IFC transformation

        Returns:
            Tuple[float, float, float]: Direction of the section 1 axis.
        """
        if hasattr(member, "local_axis") and member.local_axis is not None:
            if (
                isinstance(member.local_axis, (tuple, list))
                and len(member.local_axis) == 3
            ):
                z_axis = member.local_axis[2]
                if isinstance(z_axis, (tuple, list, np.ndarray)) and len(z_axis) == 3:
                    return tuple(float(v) for v in z_axis)
            logger.warning(f"Unexpected local_axis format: {member.local_axis}")

        # No orientation in the file: reported once by _write_sections
        self._members_without_axis.add(member.id)

        curve_geometry = member.geometry
        if isinstance(curve_geometry, (tuple, list)) and len(curve_geometry) >= 2:
            start_point = np.array(curve_geometry[0], dtype=float)
            end_point = np.array(curve_geometry[-1], dtype=float)
        else:
            raise AnalysisError(
                f"Member {member.id} has no end points to place its section by.",
                code="E-SEC-005",
            )
        return self._default_section_direction(end_point - start_point)

    @staticmethod
    def _default_section_direction(axis) -> Tuple[float, float, float]:
        """Return the section 1 direction of a member the file gives no axes for.

        The depth of the section is put as near vertical as the member
        allows: global Z less its part along the member. A vertical member
        gets global X.

        Args:
            axis: Direction of the member (any length).

        Returns:
            Tuple[float, float, float]: Unit vector across the member.
        """
        axis = np.array(axis, dtype=float)
        length = np.linalg.norm(axis)
        if length < 1e-10:
            raise AnalysisError(
                "A member of no length has no section direction.", code="E-SEC-005"
            )
        axis = axis / length
        for candidate in (np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0])):
            direction = candidate - np.dot(candidate, axis) * axis
            size = np.linalg.norm(direction)
            if size > 1e-6:
                direction = direction / size
                break
        return (float(direction[0]), float(direction[1]), float(direction[2]))

    @staticmethod
    def _section_has_a_direction(section) -> bool:
        """Whether turning a section about its member changes the analysis.

        It does not for a circle or a round tube, nor for a square or a
        square tube, whose bending stiffness is the same about every axis.
        """
        kind = getattr(section, "section_type", None)
        if kind in ("circular", "hollow_circular"):
            return False
        if kind in ("rectangular", "hollow_rectangular"):
            iy = getattr(section, "moment_of_inertia_y", None)
            iz = getattr(section, "moment_of_inertia_z", None)
            if iy and iz:
                return not math.isclose(iy, iz, rel_tol=1e-6)
        return True

    def write_calculix_input_from_mesh(
        self,
        mesh_file: str,
        output_file: str,
    ) -> str:
        """
        THE MAIN METHOD: Write CalculiX input file from Gmsh mesh.

        This is the single entry point that replaces both mesh conversion
        and input generation. No dual systems, no conflicts.

        Args:
            mesh_file: Path to Gmsh mesh file (.msh)
            output_file: Path for output CalculiX input file (.inp)

        Returns:
            str: Path to generated CalculiX input file

        Raises:
            AnalysisError: If writing fails
        """
        try:
            logger.info(f"Writing unified CalculiX input from mesh: {mesh_file}")

            # Step 1: Read and process mesh
            mesh = meshio.read(mesh_file)
            self._process_mesh(mesh)

            # Step 2: Map elements to domain members
            self._map_elements_to_members()

            # Step 2b: Identify non-standard-section members and retype to U1
            self._identify_and_retype_u1_members()

            # Step 2c: Resolve remaining overlapping-geometry element ownership
            self._resolve_overlapping_element_sets()
            self._check_members_reach_their_connections()
            self._check_user_elements_join_their_own_kind()
            self._check_user_elements_have_no_modes()

            # Step 2c2: Give members hinged along an edge their own edge nodes
            self._release_hinged_edges()

            # Step 2c3: Make rigid connections rigid by sharing one node
            self._merge_rigid_connection_nodes()

            # Step 2c4: Hinge released member ends about the released axes only
            self._build_release_hinges()

            # Step 2c5: Tie beams lying in a slab or wall to it along their length
            self._build_line_bearings()

            # Step 2c5b: Report curve members joined by nothing but the mesh
            self._report_joints_made_by_the_mesh()

            # Step 2c6: Hold a plane truss or frame that can leave its plane
            self._hold_plane_structure()

            # Step 2c7: Hold members that nothing stops spinning about their axis
            self._hold_spinning_members()

            # Step 2c8: Fix an arm to supports that hold skew rotations, those
            # of step 2c7 among them
            self._build_support_arms()

            # Step 2c9: Spread point forces on beam nodes over a rigid section
            self._knot_point_loaded_nodes()

            # Step 2c10: Springs of elastic supports
            self._build_support_springs()

            # Step 2c11: Hold the whole thickness of shells where an equation
            # acts on them
            self._knot_shell_nodes_on_equations()

            # Step 2d: Register node→member memberships for result export
            self._register_node_memberships()

            # Step 3: Write complete CalculiX input file
            self._write_calculix_input_file(output_file)

            logger.info(f"Successfully wrote unified CalculiX input: {output_file}")
            return output_file

        except StructuralAnalysisError:
            raise
        except Exception as e:
            raise AnalysisError(
                f"Failed to write CalculiX input: {type(e).__name__}: {e}",
                code="E-SLV-006",
            ) from e

    def _process_mesh(self, mesh: meshio.Mesh) -> None:
        """
        Process Gmsh mesh data into internal structures.

        This is the ONLY place where elements are created from mesh data.
        Also extracts physical group data for element-to-member mapping.
        """
        logger.info("Processing mesh data...")

        # Clear any existing data
        self.nodes.clear()
        self.elements.clear()
        self.element_sets.clear()
        self._element_physical_group = {}  # element_id -> physical_group_tag

        # Process nodes
        for i, (x, y, z) in enumerate(mesh.points):
            node_id = i + 1  # CalculiX uses 1-based indexing
            self.nodes[node_id] = (float(x), float(y), float(z))

        # Extract physical group name mapping: tag -> name (member_id or
        # "MemberA||MemberB" for exact-overlap groups).
        # meshio field_data format: {name: [tag, dim]}
        self._physical_group_names = {}  # tag -> name
        if hasattr(mesh, "field_data") and mesh.field_data:
            for name, (tag, dim) in mesh.field_data.items():
                self._physical_group_names[int(tag)] = name
            logger.info(
                f"Found {len(self._physical_group_names)} physical groups in mesh"
            )

        # Extract physical group tags per cell block
        # meshio cell_data format: {'gmsh:physical': [array_for_block0, array_for_block1, ...]}
        phys_data = None
        if hasattr(mesh, "cell_data") and mesh.cell_data:
            phys_data = mesh.cell_data.get("gmsh:physical")

        # Process elements
        element_id = 1
        element_type_counts = {}
        block_idx = 0

        # Extract cell blocks in version-agnostic way
        cell_blocks = self._extract_cell_blocks(mesh)

        for block_name, block_cells in cell_blocks:
            calculix_type = self.ELEMENT_TYPE_MAPPING.get(block_name)

            # Get physical group tags for this block (if available)
            block_phys_tags = None
            if phys_data is not None and block_idx < len(phys_data):
                block_phys_tags = phys_data[block_idx]
            block_idx += 1

            if not calculix_type:
                # Skip non-structural element types (vertex, edge, etc.) silently
                # These are geometric entities from Gmsh, not FEA elements
                if block_name not in ["vertex", "edge", "point"]:
                    logger.warning(f"Unknown element type: {block_name}")
                continue

            # Create element set for this block type
            set_name = f"ELSET_{block_name.upper()}"
            if set_name not in self.element_sets:
                self.element_sets[set_name] = []
                self.defined_element_sets.add(set_name)

            # Process each element in the block
            for cell_idx, cell in enumerate(block_cells):
                # Convert to 1-based indexing for CalculiX
                node_indices = [int(idx) + 1 for idx in cell]
                if block_name == "line3":
                    # Gmsh lists the two end nodes and then the middle one;
                    # CalculiX wants them in order along the element.
                    node_indices = [node_indices[0], node_indices[2], node_indices[1]]

                # Store element data
                self.elements[element_id] = {
                    "type": calculix_type,
                    "nodes": node_indices,
                    "block_name": block_name,
                }

                # Store physical group tag for this element
                if block_phys_tags is not None and cell_idx < len(block_phys_tags):
                    ptag = int(block_phys_tags[cell_idx])
                    if ptag > 0:
                        self._element_physical_group[element_id] = ptag

                # Add to element set
                self.element_sets[set_name].append(element_id)

                # Count elements by type
                element_type_counts[calculix_type] = (
                    element_type_counts.get(calculix_type, 0) + 1
                )

                element_id += 1

        # Log processing results
        logger.info(
            f"Processed {len(self.nodes)} nodes and {len(self.elements)} elements"
        )
        for elem_type, count in element_type_counts.items():
            logger.info(f"  {elem_type}: {count} elements")
        if self._element_physical_group:
            logger.info(
                f"  {len(self._element_physical_group)} elements have physical group tags"
            )

    def _extract_cell_blocks(self, mesh: "meshio.Mesh") -> List:
        """Extract cell blocks from mesh in version-agnostic way."""
        try:
            if hasattr(mesh.cells, "items"):
                return list(mesh.cells.items())
            if hasattr(mesh.cells[0], "type"):
                return [(cell_block.type, cell_block.data) for cell_block in mesh.cells]
            return list(mesh.cells)
        except MeshingError:
            raise
        except Exception as e:
            raise MeshingError(
                f"The mesh has no readable cell blocks: {e}", code="E-MSH-001"
            ) from e

    def _map_elements_to_members(self) -> None:
        """Map mesh elements to domain model members via MeshMapper."""
        mapper = MeshMapper(
            elements=self.elements,
            nodes=self.nodes,
            domain_model=self.domain_model,
            element_physical_group=self._element_physical_group,
            physical_group_names=self._physical_group_names,
            get_short_id=self._get_short_id,
        )
        mapper.map()
        self.element_sets = mapper.element_sets
        self.defined_element_sets = mapper.defined_element_sets
        # The elements lying in each member's geometry, whoever is analysed
        # there: where members overlap, element_sets keeps each element for
        # one of them, and the others still end and are joined where the
        # file says.
        self._geometry_element_sets = {
            name: list(elems) for name, elems in self.element_sets.items()
        }

    @staticmethod
    def _needs_user_element(member) -> bool:
        """Return True when a CurveMember's section requires a U1 element.

        Queries the section_profiles registry — B31 native types (RECT, CIRC,
        PIPE, BOX) use standard B31 elements; all others (I, L, T, C, …) use
        U1 with SECTION=GENERAL.  Unknown types default to U1 (safe fallback).
        """
        if not isinstance(member, CurveMember):
            return False
        section = getattr(member, "section", None)
        if section is None:
            return False
        stype = getattr(section, "section_type", None)
        return uses_user_element(stype)

    def _use_user_elements(self) -> bool:
        """Whether sections other than solid rectangles take U1 elements.

        Only when asked for. Stock CalculiX crashes when a U1 element shares
        a model with any other beam or shell element, and on a build where it
        does not, a U1 beam passes no moment to a native beam at a shared
        node. The default is the equivalent rectangle.
        """
        return self.analysis_config.get_open_sections() == "user_element"

    def _assign_equivalent_sections(self) -> None:
        """Give every open-section member a rectangle of the same stiffness.

        The member keeps its native beam elements. Its section is written as a
        rectangle with a material of its own (``_write_materials``), scaled so
        that EA, both EI and the weight per length are those of the real
        section, and orthotropic so that its shear stiffness in each
        direction is too. The stresses CalculiX computes in that rectangle mean
        nothing, so the model records which members they are and the results
        export leaves their stress out.
        """
        for member in self.domain_model.members:
            if not self._needs_user_element(member):
                continue
            if not self.element_sets.get(f"MEMBER_{self._get_short_id(member.id)}"):
                continue
            section = member.section
            try:
                self._equivalent_sections[member.id] = equivalent_rectangle(
                    float(getattr(section, "area", None) or 0.0),
                    float(getattr(section, "moment_of_inertia_y", None) or 0.0),
                    float(getattr(section, "moment_of_inertia_z", None) or 0.0),
                )
            except ValueError as error:
                raise MeshingError(
                    f"Member {member.id}: section "
                    f"{getattr(section, 'name', None)!r} cannot be analysed, {error}",
                    code="E-SEC-004",
                )
        if not self._equivalent_sections:
            return
        self.domain_model.equivalent_section_members = set(self._equivalent_sections)
        members = {member.id: member for member in self.domain_model.members}
        matched = sum(
            1
            for member_id in self._equivalent_sections
            if self._matched_torsion_constant(members[member_id]) is not None
        )
        unmatched = len(self._equivalent_sections) - matched
        message = (
            f"{len(self._equivalent_sections)} member(s) whose section is not a "
            "solid rectangle are analysed as rectangles of the same axial and "
            "bending stiffness and weight, and no stress is reported for them."
        )
        if matched:
            message += (
                f" {matched} with a closed or round section have its torsional "
                "stiffness, and a shear stiffness up to twice too high."
            )
        if unmatched:
            message += (
                f" {unmatched} with an open section have its shear stiffness, "
                "and a torsional stiffness tens of times too high: do not rely "
                "on results where they carry torsion."
            )
        self._warn_user(
            "W-SEC-002", message, ifc_guids=self._ifc_guids(self._equivalent_sections)
        )

    def _rectangle_moduli(self, member) -> Optional[Tuple[float, float]]:
        """Shear moduli of a solid rectangular member's own material, if any.

        CalculiX's rectangle shears with its whole area and is up to 18.5 %
        too stiff in torsion, so the member gets an orthotropic material with
        5/6 of the shear modulus along its depth and the one across its width
        set for torsion (``rectangle_shear_moduli``). None for any other
        member.
        """
        section = getattr(member, "section", None)
        if not isinstance(member, CurveMember) or section is None:
            return None
        if get_native_section(getattr(section, "section_type", None)) is None:
            return None
        material = member.material
        dimensions = getattr(section, "dimensions", None) or {}
        constant = getattr(section, "torsional_constant", None)
        if not material or not constant:
            return None
        try:
            return rectangle_shear_moduli(
                float(dimensions["height"]),
                float(dimensions["width"]),
                self._shear_modulus(material),
                float(constant),
            )
        except (KeyError, ValueError) as error:
            raise MeshingError(
                f"Member {member.id}: section {getattr(section, 'name', None)!r} "
                f"cannot be analysed, {error}",
                code="E-SEC-004",
            ) from error

    @staticmethod
    def _shear_modulus(material) -> float:
        """Shear modulus of an isotropic material."""
        return material.elastic_modulus / (2.0 * (1.0 + material.poisson_ratio))

    def _rectangle_material_name(self, member) -> str:
        """Name of the material of a torsion-corrected rectangular member."""
        return f"MAT_RT_{self._get_short_id(member.id)}"

    def _note_torsion_corrected_rectangles(self) -> None:
        """Say once what the shear moduli of solid rectangles cost."""
        across_width = 0.0
        along_depth = 0.0
        corrected = []
        for member in self.domain_model.members:
            if not self.element_sets.get(f"MEMBER_{self._get_short_id(member.id)}"):
                continue
            moduli = self._rectangle_moduli(member)
            if moduli is None:
                continue
            corrected.append(member.id)
            timoshenko = RECTANGLE_SHEAR_COEFFICIENT * self._shear_modulus(
                member.material
            )
            along_depth = max(along_depth, moduli[0] / timoshenko - 1.0)
            across_width = max(across_width, abs(moduli[1] / timoshenko - 1.0))
        count = len(corrected)
        if count:
            message = (
                f"{count} member(s) with a solid rectangular section are given "
                "their torsional stiffness by changing the shear stiffness "
                f"across their width, which is off by up to "
                f"{100 * across_width:.0f} %"
            )
            if along_depth >= 0.005:
                message += (
                    ", and for sections more than twice as deep as wide the "
                    "shear stiffness along their depth, which is too high by "
                    f"up to {100 * along_depth:.0f} %"
                )
            self._warn_user(
                "W-SEC-001",
                message + ". Bending is not affected.",
                ifc_guids=self._ifc_guids(corrected),
            )

    def _identify_and_retype_u1_members(self) -> None:
        """Mark non-standard-section beam members and retype their elements to U1.

        Called after element-to-member mapping so element ownership is known.
        Modifies self.elements in-place and populates self._u1_members and
        self._u1_element_sets.

        A member sharing mesh elements with a U1 member (via the overlapping-
        geometry fallback in MeshMapper) may still list those now-U1 elements
        in its own element_sets entry. Since those elements are only ever
        written under the U1 member's SECTION=GENERAL card (_write_elements()
        skips U1-typed elements entirely, deferring them to _write_sections()),
        leaving them in a native member's set produces a *BEAM SECTION whose
        ELSET references an element that is never actually defined in the
        file. Strip retyped elements from every non-U1 member's set once all
        retyping is complete.
        """
        self._note_torsion_corrected_rectangles()
        if not self._use_user_elements():
            self._assign_equivalent_sections()
            return

        for member in self.domain_model.members:
            if not self._needs_user_element(member):
                continue
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"
            elem_ids = self.element_sets.get(member_set, [])
            if not elem_ids:
                continue
            self._u1_members.add(member.id)
            self._u1_element_sets.add(member_set)
            for elem_id in elem_ids:
                if elem_id in self.elements:
                    self.elements[elem_id]["type"] = "U1"
            self._split_quadratic_u1_elements(member, member_set)
            elem_ids = self.element_sets[member_set]
            logger.info(
                f"Member {member.id}: {len(elem_ids)} elements retyped to U1 "
                f"(section_type={getattr(member.section, 'section_type', 'unknown')})"
            )

        for member in self.domain_model.members:
            if member.id in self._u1_members:
                continue
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"
            elem_ids = self.element_sets.get(member_set)
            if not elem_ids:
                continue
            filtered = [
                eid
                for eid in elem_ids
                if self.elements.get(eid, {}).get("type") != "U1"
            ]
            if len(filtered) != len(elem_ids):
                logger.info(
                    f"Member {member.id}: {len(elem_ids) - len(filtered)} shared "
                    f"element(s) retyped to U1 by an overlapping member, "
                    f"removed from native element set"
                )
                self.element_sets[member_set] = filtered

    def _split_quadratic_u1_elements(self, member, member_set: str) -> None:
        """Turn each three-node U1 element of a member into two two-node ones.

        U1 is a two-node element, but a second-order mesh gives every line
        element a middle node. Splitting at that node keeps every mesh node in
        use, so a support or point load that lands on a middle node still acts
        on the member. The first half keeps the element ID; the second half
        gets a new one, placed right after it in the member's set.
        """
        next_id = max(self.elements.keys(), default=0) + 1
        split_set: List[int] = []
        second_halves: Dict[int, int] = {}
        for elem_id in self.element_sets[member_set]:
            split_set.append(elem_id)
            elem = self.elements.get(elem_id)
            if elem is None or elem["type"] != "U1" or len(elem["nodes"]) != 3:
                continue
            start, middle, end = elem["nodes"]
            elem["nodes"] = [start, middle]
            self.elements[next_id] = {**elem, "nodes": [middle, end]}
            split_set.append(next_id)
            second_halves[elem_id] = next_id
            next_id += 1
        if second_halves:
            self.element_sets[member_set] = split_set
            # The end node is in the second half only: a member that lists
            # the first half without it has no node at its end
            geometry_sets = getattr(self, "_geometry_element_sets", {})
            for name, elems in geometry_sets.items():
                geometry_sets[name] = [
                    e
                    for elem_id in elems
                    for e in (elem_id, second_halves.get(elem_id))
                    if e is not None
                ]
            self.domain_model.register_analysis_elements(
                member.id, list(second_halves.values()), entity_type="member"
            )

    def _resolve_overlapping_element_sets(self) -> None:
        """Ensure every mesh element belongs to exactly one member's set.

        MeshMapper's shared-element-assignment fallback (used when two
        members have overlapping IFC geometry) can list the same element in
        more than one member's element_sets entry. Exactly one member may
        claim an element in the output file — CalculiX cannot have two
        *BEAM SECTION/*SHELL SECTION cards cover the same element, and every
        downstream consumer of element_sets (raw *ELSET cards, orientation
        grouping, nodal thickness, node-membership registration) reads the
        same dict, so resolving ownership once here — rather than patching
        each consumer separately — keeps them all consistent.

        The first member encountered in domain_model.members order keeps a
        shared element; later members lose it (but keep whatever elements
        they don't share with an earlier member). Type-based ownership
        (native vs. U1) is already resolved by _identify_and_retype_u1_members()
        before this runs, so this pass only needs to break ties between
        members of the same kind (e.g. two overlapping shells).
        """
        already_claimed: set = set()
        overlapping: List[str] = []
        for member in self.domain_model.members:
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"
            elem_ids = self.element_sets.get(member_set)
            if not elem_ids:
                continue
            remaining = [eid for eid in elem_ids if eid not in already_claimed]
            if len(remaining) != len(elem_ids):
                logger.info(
                    f"Member {member.id}: {len(elem_ids) - len(remaining)} "
                    f"element(s) already claimed by an earlier-processed "
                    f"overlapping member — excluded from this member's set"
                )
                overlapping.append(member.id)
                self.element_sets[member_set] = remaining
            already_claimed.update(remaining)
        if overlapping:
            self._warn_user(
                "W-MSH-001",
                f"{len(overlapping)} member(s) overlap another member. Where "
                "two overlap, the mesh has one layer of elements and it is "
                "analysed with the material and thickness or section of the "
                "member that comes first in the file, not with both. The first "
                f"are {', '.join(overlapping[:5])}.",
                ifc_guids=self._ifc_guids(overlapping),
            )

    def _check_members_reach_their_connections(self) -> None:
        """Stop when the mesh has no node for a curve member at a connection.

        Every joint and support is made at the node a member has at its
        connection: its end, or the point of its span nearest to it. A member
        with no node there would be left out of the joint without a word,
        and the structure analysed would be another one.

        Raises:
            MeshingError: If a curve member has no node at one of its
                connections.
        """
        missing: List[str] = []
        concerned: List[str] = []
        for conn in self.domain_model.connections:
            for member_id in conn.connected_members:
                if self._get_member_endpoints(member_id) is None:
                    continue
                if not self._find_connection_nodes_at_location(conn, [member_id]):
                    missing.append(f"{member_id} at {conn.id}")
                    concerned += [member_id, conn.id]
        if missing:
            raise MeshingError(
                f"The mesh has no node for {len(missing)} member end(s) at "
                "their connection, so they cannot be joined as the model "
                f"says. The first are {', '.join(missing[:5])}.",
                code="E-JNT-001",
                ifc_guids=self._ifc_guids(concerned),
            )

    def _check_user_elements_have_no_modes(self) -> None:
        """Stop a modal analysis of U1 members: CalculiX gives them no mass.

        Their weight is put on their nodes as forces for a load case
        (``_u1_node_masses``), which a modal analysis cannot use.

        Raises:
            AnalysisError: If the analysis is modal and a member is of U1
                elements.
        """
        if not self._u1_members or self.analysis_config.get_analysis_type() != (
            "modal"
        ):
            return
        members = sorted(self._u1_members)
        raise AnalysisError(
            f"{len(members)} member(s) are CalculiX user elements "
            f"(--open-sections user-element), the first {members[0]}, and "
            "CalculiX gives them no mass, so a modal analysis cannot be made "
            "of them. Analyse the model with equivalent sections instead.",
            code="E-SEC-006",
            ifc_guids=guids_of(self.domain_model, members),
        )

    def _check_user_elements_join_their_own_kind(self) -> None:
        """Stop when a U1 member is joined to a beam or shell of another type.

        CalculiX expands native beams and shells into solids and joins them at
        a knot; the rotations of a U1 node are not part of it, so a U1 element
        and a native one sharing a node pass no moment (``aiz.14``: the second
        half of a propped cantilever made of U1 deflected as a cantilever with
        a pinned link). A U1 member at a connection is not merged with the
        others either (``_merge_rigid_connection_nodes``) and is tied to them
        in translation only. Either way the joint is a pin. Stock CalculiX
        stops in gen3delem on such a model; a build that gets past it would
        analyse another structure. A joint that releases every rotation of
        one of the two members is a pin in the file too, and is left alone.

        Raises:
            AnalysisError: If a U1 member meets a member of native elements at
                a shared node or a connection that does not release it.
        """
        if not self._u1_members:
            return
        owners: Dict[int, set] = {}
        for member in self.domain_model.members:
            member_set = f"MEMBER_{self._get_short_id(member.id)}"
            for elem_id in self.element_sets.get(member_set, []):
                elem = self.elements.get(elem_id)
                if elem is None:
                    continue
                for node in elem["nodes"]:
                    owners.setdefault(node, set()).add(member.id)

        pairs: set = set()
        for members in owners.values():
            for user in members & self._u1_members:
                pairs.update((user, other) for other in members - self._u1_members)
        pinned: set = set()
        for conn in self.domain_model.connections:
            if getattr(conn, "edge", None) is not None:
                continue
            members = set(conn.connected_members)
            released = getattr(conn, "released_dofs_by_member", None) or {}
            for user in members & self._u1_members:
                for other in members - self._u1_members:
                    if conn.entity_type == "hinge" or any(
                        {4, 5, 6}.issubset(released.get(m) or ()) for m in (user, other)
                    ):
                        pinned.add((user, other))
                    elif conn.entity_type in ("point", "rigid"):
                        pairs.add((user, other))
        wrong = sorted(pairs - pinned)
        if wrong:
            first = ", ".join(f"{user} with {other}" for user, other in wrong[:5])
            raise AnalysisError(
                f"{len(wrong)} joint(s) join a member of user elements (U1, "
                "--open-sections user-element) to a member of native beam or "
                "shell elements. CalculiX passes no moment between the two, "
                "so each would be a pin, and stock CalculiX stops on such a "
                f"model. The first are {first}. Analyse the model without "
                "user elements: every section is then an equivalent rectangle "
                "on native elements.",
                code="E-JNT-003",
            )

    def _register_node_memberships(self) -> None:
        """Record the final elements and mesh nodes of every member in the model.

        Results are attributed to members through these. CalculiX expands beam
        and shell elements into solids and reports on the solids' nodes, which
        are numbered by the solver; the expanded element keeps the number of
        the element it came from, so the exporter goes from a member to its
        elements and from those to the nodes in the result file. The mesh nodes
        registered here serve elements the result file does not list (U1).
        """
        for member in self.domain_model.members:
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"
            elem_ids = [
                e for e in self.element_sets.get(member_set, []) if e in self.elements
            ]
            node_ids = []
            for elem_id in elem_ids:
                node_ids.extend(self.elements[elem_id]["nodes"])
            if elem_ids:
                self.domain_model.set_analysis_elements(member.id, elem_ids)
            if node_ids:
                self.domain_model.register_node_memberships(node_ids, member.id)
            if isinstance(member, SurfaceMember):
                for elem_id in elem_ids:
                    element = self.elements[elem_id]
                    if element["type"] not in SHELL_ELEMENT_TYPES:
                        continue
                    nodes = tuple(int(n) for n in element["nodes"])
                    self.domain_model.shell_elements[elem_id] = (member.id, nodes)
                    for node in nodes:
                        self.domain_model.shell_node_positions[node] = tuple(
                            float(v) for v in self.nodes[node]
                        )

    def _write_calculix_input_file(self, output_file: str) -> None:
        """
        Write the complete CalculiX input file.

        This is the ONLY place where CalculiX input is written.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

        # Collect boundary condition (node, DOF) pairs before writing connections
        # to avoid MPC/SPC conflicts
        bc_node_dofs = self._collect_boundary_condition_dofs()
        self._prepare_temperature_loads()

        with open(output_file, "w") as f:
            # Header
            self._write_header(f)

            # Pre-analysis stability check
            for warning in self._detect_mechanism_risk():
                self._warn_user("W-SUP-003", warning)
                f.write(f"** *** STABILITY WARNING: {warning}\n")
                f.write("**\n")

            # Mesh data
            self._write_nodes(f)
            self._write_nodal_thickness(f)  # Must come after nodes, before elements
            # *USER ELEMENT must appear before any *ELEMENT TYPE=U1 cards
            if self._u1_members:
                self._write_user_element_definition(f)
            self._write_elements(f)
            self._write_node_sets(f)
            self._write_element_sets(f)

            # Material and structural properties
            self._write_materials(f)
            self._write_sections(f)
            self._write_rigid_links(f)
            self._write_support_springs(f)
            self._write_knot_drilling(f)

            # Connections (kinematic couplings, MPCs)
            # Pass boundary condition DOFs to avoid conflicts
            self._write_connections(f, bc_node_dofs)

            # Boundary conditions and loads
            dependent = write_boundary_conditions(
                f,
                self.domain_model,
                self.node_sets,
                self.element_sets,
                self._structure_nodes(),
                rotation_arms=getattr(self, "_support_arms", None),
                springs=getattr(self, "_support_springs", None),
                member_nodes=self._support_member_nodes(),
                translation_ties=self._translation_ties,
            )
            self._record_support_node_elements()
            # What an equation of a skew support already decides is not
            # restrained a second time
            plane_holds = [
                hold for hold in self._plane_hold_dofs() if hold not in dependent
            ]
            if plane_holds:
                f.write("** Plane structure held in its plane\n")
                f.write("*BOUNDARY\n")
                for node, dof in plane_holds:
                    f.write(f"{node}, {dof}, {dof}\n")
                f.write("\n")
            plane_equations = getattr(self, "_plane_equations", [])
            if plane_equations:
                f.write("** Plane structure held across its plane\n")
                for terms in plane_equations:
                    self._write_equation(f, terms)
                f.write("\n")
            holds = self._torsion_hold_dofs()
            if holds:
                f.write("** Members held against spinning about their own axis\n")
                f.write("*BOUNDARY\n")
                for node, dof in holds:
                    f.write(f"{node}, {dof}, {dof}\n")
                f.write("\n")
            spin_arms = getattr(self, "_spin_arm_equations", [])
            if spin_arms:
                f.write("** Members held against spinning, by arms across the plane\n")
                for terms in spin_arms:
                    self._write_equation(f, terms)
                f.write("\n")

            temperatures = self._temperature_fields()
            if temperatures:
                f.write("** Temperatures are changes from zero\n")
                f.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\n")
                for node in sorted(self.nodes):
                    f.write(f"{node}, 0.\n")
                f.write("\n")

            # Analysis steps
            write_analysis_steps(
                f,
                self.domain_model,
                self.analysis_config.get_analysis_type(),
                self.short_id_map,
                self._load_element_sets(),
                self._structure_nodes(),
                gravity=self.analysis_config.get_gravity(),
                gravity_direction=self.analysis_config.get_gravity_direction(),
                u1_node_masses=self._u1_node_masses,
                u1_element_sets=self._u1_element_sets,
                elements_data=dict(self.elements),
                temperatures=temperatures,
                num_modes=self.analysis_config.get_num_modes(),
            )

    def _temperature_loads(self) -> List[Tuple[Any, Any]]:
        """Every temperature load of the model with its load group."""
        return [
            (group, load)
            for group in getattr(self.domain_model, "load_groups", None) or []
            for load in getattr(group, "temperature_loads", None) or []
        ]

    def _prepare_temperature_loads(self) -> None:
        """Check the temperature loads, and turn the elements of members with a
        temperature difference to run the way the member does.

        CalculiX takes a gradient along the element's own axes: across a beam
        along its tangent (first node to last) times the section's 1 axis,
        and across a shell along the normal its node order gives (measured;
        each turns over with the element). Nodes are shared, so the elements
        of a member have to agree.

        Raises:
            AnalysisError: E-LOD-008 for a temperature load that cannot be
                applied (see the message registry).
        """
        loads = self._temperature_loads()
        if not loads:
            return
        sets = self._load_element_sets()
        for _, load in loads:
            member = self.domain_model.get_member(load.member_id)
            guids = guids_of(self.domain_model, [load.id, load.member_id])

            def refuse(reason: str) -> None:
                raise AnalysisError(
                    f"Temperature load {load.id} on member {load.member_id} "
                    f"cannot be applied: {reason}",
                    code="E-LOD-008",
                    ifc_guids=guids,
                )

            if member is None:
                refuse("the member is not in the model.")
            material = getattr(member, "material", None)
            if not getattr(material, "thermal_expansion_coefficient", None):
                refuse(
                    f"its material '{getattr(material, 'name', None)}' has no "
                    "thermal expansion coefficient "
                    "(Pset_MaterialMechanical.ThermalExpansionCoefficient)."
                )
            if member.id in self._u1_members:
                refuse(
                    "it is made of CalculiX user elements (U1), which take no "
                    "temperature."
                )
            elements = [
                e
                for e in sets.get(f"MEMBER_{self._get_short_id(member.id)}", [])
                if e in self.elements
            ]
            if isinstance(member, CurveMember):
                if not (load.delta_t_y or load.delta_t_z):
                    continue
                axes = getattr(member, "local_axis", None)
                if axes is None:
                    refuse(
                        "it has a temperature difference across the member, "
                        "and the member has no local axes (Axis) to say which "
                        "way."
                    )
                depths = member.section.get_depths()
                for delta, depth, axis in zip(
                    (load.delta_t_y, load.delta_t_z), depths, "yz"
                ):
                    if delta and not (depth and depth > 0):
                        refuse(
                            f"it has a temperature difference across local "
                            f"{axis}, and the depth of the section "
                            f"({member.section.section_type}) along it is not "
                            "known."
                        )
                geometry = np.array(member.geometry, dtype=float)
                self._orient_elements(elements, geometry[-1] - geometry[0])
            else:
                if not load.delta_t_z:
                    continue
                normal = getattr(member, "normal", None)
                if normal is None:
                    refuse(
                        "it has a temperature difference across the thickness, "
                        "and the member's face has no plane to give its normal."
                    )
                self._orient_elements(elements, np.array(normal, dtype=float))

    def _element_direction(self, element_id: int) -> np.ndarray:
        """A beam's tangent (first node to last) or a shell's normal."""
        element = self.elements[element_id]
        points = [np.array(self.nodes[n], dtype=float) for n in element["nodes"]]
        if element["type"] in SHELL_ELEMENT_TYPES:
            return np.cross(points[1] - points[0], points[2] - points[0])
        # B31 (start, end), B32R (start, middle, end)
        return points[-1] - points[0]

    def _orient_elements(self, element_ids: List[int], direction: np.ndarray) -> None:
        """Reverse the node order of the elements that run against ``direction``."""
        for element_id in element_ids:
            if float(np.dot(self._element_direction(element_id), direction)) >= 0:
                continue
            element = self.elements[element_id]
            nodes = list(element["nodes"])
            if element["type"] in SHELL_ELEMENT_TYPES:
                corners = 3 if len(nodes) in (3, 6) else 4
                head, middles = nodes[:corners], nodes[corners:]
                head = [head[0], *reversed(head[1:])]
                middles = list(reversed(middles))
                nodes = head + middles
            else:
                # B31 (start, end) or B32R (start, middle, end)
                nodes = list(reversed(nodes))
            element["nodes"] = nodes

    def _temperature_fields(self) -> Dict[Optional[str], Dict[int, Tuple[float, ...]]]:
        """The *TEMPERATURE values each load group gives the nodes.

        Returns:
            ``{group id: {node: (T, gradient, gradient)}}``: the change of
            temperature, then for a beam the gradients (K/m) along the
            element's tangent times its section's 1 axis and along that 1
            axis, for a shell the gradient along its normal and zero. Every
            node of a member whose material expands is in every group,
            zero where the group does not heat it. A node shared by members
            with different values takes their mean, with one warning.

            Has to run after the sections are written: the beams' section
            axes are those recorded then.
        """
        loads = self._temperature_loads()
        if not loads:
            return {}
        sets = self._load_element_sets()
        frames = getattr(self.domain_model, "beam_section_frames", {})

        # Members whose material expands, by node
        expanding: Dict[int, set] = {}
        for member in self.domain_model.members:
            material = getattr(member, "material", None)
            if not getattr(material, "thermal_expansion_coefficient", None):
                continue
            for element_id in sets.get(f"MEMBER_{self._get_short_id(member.id)}", []):
                if element_id in self.elements:
                    for node in self.elements[element_id]["nodes"]:
                        expanding.setdefault(node, set()).add(member.id)

        fields: Dict[Optional[str], Dict[int, Tuple[float, ...]]] = {}
        shared_nodes: set = set()
        shared_members: set = set()
        for group in {id(g): g for g, _ in loads}.values():
            # The loads of one member in a group add up; at a node its
            # elements agree, being turned the same way
            member_values: Dict[str, Dict[int, np.ndarray]] = {}
            for load in group.temperature_loads:
                member = self.domain_model.get_member(load.member_id)
                at_nodes: Dict[int, List[np.ndarray]] = {}
                for element_id, element_values in self._element_temperatures(
                    member, load, sets, frames
                ):
                    for node in self.elements[element_id]["nodes"]:
                        at_nodes.setdefault(node, []).append(element_values)
                values = member_values.setdefault(member.id, {})
                for node, node_values in at_nodes.items():
                    values[node] = values.get(node, np.zeros(3)) + np.mean(
                        node_values, axis=0
                    )
            field: Dict[int, Tuple[float, ...]] = {}
            for node, members in expanding.items():
                values = [
                    member_values.get(member_id, {}).get(node, np.zeros(3))
                    for member_id in sorted(members)
                ]
                mean = np.mean(values, axis=0)
                if any(not np.allclose(v, mean, atol=1e-9) for v in values):
                    shared_nodes.add(node)
                    shared_members.update(members)
                field[node] = tuple(float(v) for v in mean)
            fields[group.id] = field

        if shared_nodes:
            members = sorted(shared_members)
            self._warn_user(
                "W-LOD-010",
                f"{len(shared_nodes)} node(s) are shared by members with "
                "different temperature changes and take the mean of their "
                f"values; members concerned: {', '.join(members[:5])}"
                + (f" and {len(members) - 5} more" if len(members) > 5 else "")
                + ".",
                ifc_guids=guids_of(self.domain_model, members),
            )
        return fields

    def _element_temperatures(self, member, load, sets, frames):
        """(element, (T, field 3, field 4)) for the elements of a heated member."""
        constant = load.delta_t_constant
        elements = [
            e
            for e in sets.get(f"MEMBER_{self._get_short_id(member.id)}", [])
            if e in self.elements
        ]
        if isinstance(member, SurfaceMember):
            thickness = float(getattr(member.thickness, "value", 0.0) or 0.0)
            gradient = load.delta_t_z / thickness if load.delta_t_z else 0.0
            for element_id in elements:
                yield element_id, np.array([constant, gradient, 0.0])
            return
        gradient = np.zeros(3)
        if load.delta_t_y or load.delta_t_z:
            axes = np.array(member.local_axis, dtype=float)
            depth_y, depth_z = member.section.get_depths()
            if load.delta_t_y:
                gradient += load.delta_t_y / depth_y * axes[1]
            if load.delta_t_z:
                gradient += load.delta_t_z / depth_z * axes[2]
        for element_id in elements:
            if not gradient.any():
                yield element_id, np.array([constant, 0.0, 0.0])
                continue
            tangent = self._element_direction(element_id)
            tangent = tangent / np.linalg.norm(tangent)
            normal = np.array(frames[element_id][1], dtype=float)
            yield element_id, np.array(
                [
                    constant,
                    float(gradient @ np.cross(tangent, normal)),
                    float(gradient @ normal),
                ]
            )

    def _load_element_sets(self) -> Dict[str, List[int]]:
        """Element sets for applying loads, by outline where members overlap.

        A surface member lying inside another one (a landing drawn on top of
        the floor slab it is part of) shares its geometry with it once the
        surfaces are fragmented, and each element can belong to one member
        only. One of the two ends up with fewer elements than its outline
        covers, or none. Stiffness and weight are right like that, counted
        once, but an area load belongs to the whole outline of its member.

        A curve member lying inside another one (a short beam along a longer
        one) is the same: its loads go on the elements in its geometry
        (``_geometry_element_sets``), whoever they belong to. Its loads were
        once left out with a warning.

        Returns:
            ``self.element_sets``, with the entry of every surface member
            whose elements do not cover its outline replaced by the shell
            elements lying within the outline, and that of every curve member
            by the elements in its geometry.
        """
        sets = dict(self.element_sets)
        geometry_sets = getattr(self, "_geometry_element_sets", {})
        shells = None
        for member in self.domain_model.members:
            if isinstance(member, CurveMember):
                member_set = f"MEMBER_{self._get_short_id(member.id)}"
                in_geometry = [
                    e for e in geometry_sets.get(member_set, []) if e in self.elements
                ]
                if in_geometry and set(in_geometry) != set(sets.get(member_set, [])):
                    sets[member_set] = in_geometry
                continue
            if not isinstance(member, SurfaceMember):
                continue
            geometry = member.geometry
            if isinstance(geometry, dict):
                geometry = (geometry.get("boundaries") or [None])[0]
            try:
                outline = np.array(geometry, dtype=float).reshape(-1, 3)
            except (TypeError, ValueError):
                continue
            if len(outline) < 3:
                continue
            member_set = f"MEMBER_{self._get_short_id(member.id)}"
            own = [e for e in sets.get(member_set, []) if e in self.elements]
            holes = [np.array(hole, dtype=float) for hole in member.holes]
            outline_area = self._polygon_area(outline) - sum(
                self._polygon_area(hole) for hole in holes
            )
            meshed_area = sum(
                self._polygon_area(
                    np.array([self.nodes[n] for n in self.elements[e]["nodes"][:3]])
                )
                for e in own
            )
            if abs(meshed_area - outline_area) <= 1e-6 * outline_area:
                continue
            if shells is None:
                shells = [
                    (
                        elem_id,
                        np.mean([self.nodes[n] for n in elem["nodes"][:3]], axis=0),
                    )
                    for elem_id, elem in self.elements.items()
                    if elem.get("type") in SHELL_ELEMENT_TYPES
                ]
            inside = [
                elem_id
                for elem_id, centroid in shells
                if self._point_in_outline(centroid, outline)
                and not any(self._point_in_outline(centroid, hole) for hole in holes)
            ]
            if inside:
                sets[member_set] = inside
                logger.info(
                    f"Member {member.id}: {len(own)} elements of its own cover "
                    f"{meshed_area:.3g} of {outline_area:.3g}; its loads go to "
                    f"the {len(inside)} shell elements within its outline"
                )
        return sets

    @staticmethod
    def _polygon_area(corners: np.ndarray) -> float:
        """Area of a planar polygon given by its corners in order."""
        normal = np.zeros(3)
        for i in range(len(corners)):
            normal += np.cross(corners[i], corners[(i + 1) % len(corners)])
        return float(np.linalg.norm(normal)) / 2.0

    def _point_in_outline(self, point: np.ndarray, outline: np.ndarray) -> bool:
        """Whether ``point`` lies in the plane and inside a planar polygon."""
        normal = np.zeros(3)
        for i in range(len(outline)):
            normal += np.cross(outline[i], outline[(i + 1) % len(outline)])
        length = float(np.linalg.norm(normal))
        if length < 1e-12:
            return False
        normal /= length
        if abs(float(np.dot(point - outline[0], normal))) > self._COINCIDENT_TOL:
            return False
        # Ray casting in the two axes that best span the plane
        keep = [i for i in range(3) if i != int(np.argmax(np.abs(normal)))]
        px, py = point[keep]
        corners = outline[:, keep]
        inside = False
        for i in range(len(corners)):
            (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % len(corners)]
            if (y0 > py) != (y1 > py) and px < x0 + (py - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
        return inside

    def _write_header(self, file: TextIO) -> None:
        """Write header section."""
        file.write("** CalculiX Input File - Unified Writer\n")
        file.write("** Generated by UnifiedCalculixWriter (single source of truth)\n")
        file.write(f"** Model ID: {self.domain_model.id}\n")
        if self.domain_model.name:
            file.write(f"** Model Name: {self.domain_model.name}\n")
        if self.domain_model.description:
            file.write(f"** Description: {self.domain_model.description}\n")
        file.write(f"** Analysis Type: {self.analysis_config.get_analysis_type()}\n")
        file.write("**\n\n")

    def _write_nodal_thickness(self, file: TextIO) -> None:
        """
        Write nodal thickness definitions for shell elements.

        CalculiX requires *NODAL THICKNESS to be defined after *NODE
        and before *ELEMENT for shell elements.
        """
        # Collect all shell members and their nodes with thickness
        nodal_thickness_map = {}  # node_id -> thickness

        for member in self.domain_model.members:
            if (
                isinstance(member, SurfaceMember)
                and hasattr(member, "thickness")
                and member.thickness
            ):
                thickness_value = getattr(member.thickness, "value", None)
                if thickness_value is None or thickness_value <= 0:
                    continue

                # Find element set for this member
                member_set = f"MEMBER_{self._get_short_id(member.id)}"
                if member_set in self.element_sets:
                    # Get all nodes in this member's shell elements only
                    for elem_id in self.element_sets[member_set]:
                        if elem_id in self.elements:
                            elem_type = self.elements[elem_id]["type"]
                            # Only add thickness for shell elements (S3, S4, S6, S8, etc.)
                            if elem_type.startswith("S"):
                                for node_id in self.elements[elem_id]["nodes"]:
                                    # Use maximum thickness if node belongs to multiple members
                                    if node_id in nodal_thickness_map:
                                        nodal_thickness_map[node_id] = max(
                                            nodal_thickness_map[node_id],
                                            thickness_value,
                                        )
                                    else:
                                        nodal_thickness_map[node_id] = thickness_value

        # Write nodal thickness if we have any shell elements
        if nodal_thickness_map:
            file.write("**\n")
            file.write("** Nodal Thickness for Shell Elements\n")
            file.write("*NODAL THICKNESS\n")
            for node_id in sorted(nodal_thickness_map.keys()):
                file.write(f"{node_id}, {nodal_thickness_map[node_id]:.6e}\n")
            file.write("\n")
            logger.debug(f"Wrote nodal thickness for {len(nodal_thickness_map)} nodes")

    def _write_nodes(self, file: TextIO) -> None:
        """Write node definitions."""
        file.write("*NODE\n")
        for node_id, (x, y, z) in sorted(self.nodes.items()):
            file.write(f"{node_id}, {x:.6e}, {y:.6e}, {z:.6e}\n")
        file.write("\n")

    def _write_elements(self, file: TextIO) -> None:
        """Write element definitions grouped by type, only for elements assigned to members."""
        # Collect element IDs that are assigned to members
        assigned_element_ids = set()
        for member in self.domain_model.members:
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"
            if member_set in self.element_sets:
                assigned_element_ids.update(self.element_sets[member_set])

        # Group assigned elements by type
        element_types = {}
        for element_id in assigned_element_ids:
            if element_id in self.elements:
                element_data = self.elements[element_id]
                element_type = element_data["type"]
                if element_type not in element_types:
                    element_types[element_type] = []
                element_types[element_type].append((element_id, element_data["nodes"]))

        # Write each element type
        for element_type, elements in element_types.items():
            # U1 elements are written individually (with per-element ELSET + MATRIX)
            # inside _write_sections() — skip them here to avoid a premature block
            if element_type == "U1":
                continue
            set_name = f"ELSET_{element_type}"
            file.write(f"*ELEMENT, TYPE={element_type}, ELSET={set_name}\n")

            for element_id, nodes in elements:
                nodes_str = ", ".join(map(str, nodes))
                file.write(f"{element_id}, {nodes_str}\n")

            file.write("\n")

            logger.info(f"Wrote {len(elements)} elements of type {element_type}")

    def _write_node_sets(self, file: TextIO) -> None:
        """Write node set definitions."""
        for set_name, node_ids in self.node_sets.items():
            if node_ids:
                file.write(f"*NSET, NSET={set_name}\n")
                for i in range(0, len(node_ids), 8):
                    line_nodes = node_ids[i : i + 8]
                    file.write(", ".join(map(str, line_nodes)) + "\n")
                file.write("\n")

    def _write_element_sets(self, file: TextIO) -> None:
        """Write element set definitions."""
        written_sets = set()
        # Set names are short; a comment gives the member's own id, by which
        # results.json knows it (the plot command reads it)
        member_of = {
            f"MEMBER_{short}": full_id for full_id, short in self.short_id_map.items()
        }

        for set_name, element_ids in self.element_sets.items():
            if element_ids and set_name not in written_sets:
                if set_name in member_of:
                    file.write(f"** Member {member_of[set_name]}\n")
                file.write(f"*ELSET, ELSET={set_name}\n")
                for i in range(0, len(element_ids), 8):
                    line_elements = element_ids[i : i + 8]
                    file.write(", ".join(map(str, line_elements)) + "\n")
                file.write("\n")
                written_sets.add(set_name)

        # Write EALL set (all elements) and BEAM_B31 set (native beam elements
        # of either order, for SF output; the name predates B32R)
        all_element_ids = sorted(self.elements.keys())
        b31_element_ids = sorted(
            eid for eid, ed in self.elements.items() if ed["type"] in BEAM_ELEMENT_TYPES
        )
        if all_element_ids:
            file.write("*ELSET, ELSET=EALL\n")
            for i in range(0, len(all_element_ids), 8):
                line_elements = all_element_ids[i : i + 8]
                file.write(", ".join(map(str, line_elements)) + "\n")
            file.write("\n")
        # Always register BEAM_B31 in element_sets when U1 members exist so that
        # _find_beam_elset() in boundary_condition_handling knows not to fall back to
        # ELSET_LINE* (which would include U1 elements that don't support SF output).
        if self._u1_members:
            self.element_sets["BEAM_B31"] = b31_element_ids
        if b31_element_ids:
            file.write("*ELSET, ELSET=BEAM_B31\n")
            for i in range(0, len(b31_element_ids), 8):
                line_elements = b31_element_ids[i : i + 8]
                file.write(", ".join(map(str, line_elements)) + "\n")
            file.write("\n")

        logger.info(f"Wrote {len(written_sets)} element sets")

    # Poisson's ratio of the materials of beams. Beam theory has no use for
    # it: bending and axial stiffness are E alone and the shear moduli are
    # given. In CalculiX's expanded solids it makes the cross-section contract
    # and swell as the member bends, and wherever a knot holds the section
    # rigid (a clamped end, a joint of members at an angle, an arm) that is
    # stopped and the member is stiffer than it is. Measured on a 3 m
    # cantilever with nu = 0.2: 1.2, 0.75 and 0.5 % stiff at a 0.5, 0.25 and
    # 0.1 m mesh with it, 0.29 % at all three without (aiz.91); a beam with a
    # knot at every node, nu = 0.3, 24 % stiff with it and right without.
    _BEAM_POISSON = "0."

    def _write_materials(self, file: TextIO) -> None:
        """Write material definitions."""
        materials = {}
        for member in self.domain_model.members:
            if member.material and member.material.id not in materials:
                materials[member.material.id] = member.material

        for material_id, material in materials.items():
            file.write(f"*MATERIAL, NAME=MAT_{material_id}\n")
            file.write("*ELASTIC\n")
            file.write(
                f"{material.elastic_modulus:.6e}, {material.poisson_ratio:.6e}\n"
            )

            if hasattr(material, "density") and material.density:
                file.write("*DENSITY\n")
                file.write(f"{material.density:.6e}\n")
            self._write_expansion(file, material)
            file.write("\n")

        # One material per equivalent rectangle, scaled to the real section
        for member in self.domain_model.members:
            if member.id not in self._equivalent_sections or not member.material:
                continue
            depth, width, factor = self._equivalent_sections[member.id]
            material = member.material
            modulus = material.elastic_modulus * factor
            poisson = material.poisson_ratio
            # Shear moduli of the planes holding the member axis (1) and the
            # section's depth (2) or width (3): the section's shear stiffness
            # in each direction, or for closed and solid sections its
            # torsional stiffness (see equivalent_shear_moduli)
            shear = material.elastic_modulus / (2.0 * (1.0 + poisson))
            isotropic = modulus / (2.0 * (1.0 + poisson))
            shear_areas = [
                float(getattr(member.section, name, None) or 0.0)
                for name in ("shear_area_y", "shear_area_z")
            ]
            if min(shear_areas) > 0:
                moduli = equivalent_shear_moduli(
                    depth,
                    width,
                    shear,
                    shear_areas[0],
                    shear_areas[1],
                    self._matched_torsion_constant(member),
                )[:2]
            else:
                moduli = (isotropic, isotropic)
            file.write(f"*MATERIAL, NAME={self._equivalent_material_name(member)}\n")
            file.write("*ELASTIC, TYPE=ENGINEERING CONSTANTS\n")
            file.write(
                f"{modulus:.6e}, {modulus:.6e}, {modulus:.6e},"
                f" {self._BEAM_POISSON}, {self._BEAM_POISSON}, {self._BEAM_POISSON},"
                f" {moduli[0]:.6e}, {moduli[1]:.6e},\n"
            )
            file.write(f"{isotropic:.6e}\n")
            if getattr(material, "density", None):
                file.write("*DENSITY\n")
                file.write(f"{material.density * factor:.6e}\n")
            self._write_expansion(file, material, along_member=True)
            file.write("\n")

        # One material per solid rectangle, with the shear modulus across its
        # width lowered so that it twists as it should
        for member in self.domain_model.members:
            if not self.element_sets.get(f"MEMBER_{self._get_short_id(member.id)}"):
                continue
            moduli = self._rectangle_moduli(member)
            if moduli is None:
                continue
            material = member.material
            modulus = material.elastic_modulus
            file.write(f"*MATERIAL, NAME={self._rectangle_material_name(member)}\n")
            file.write("*ELASTIC, TYPE=ENGINEERING CONSTANTS\n")
            file.write(
                f"{modulus:.6e}, {modulus:.6e}, {modulus:.6e},"
                f" {self._BEAM_POISSON}, {self._BEAM_POISSON}, {self._BEAM_POISSON},"
                f" {moduli[0]:.6e}, {moduli[1]:.6e},\n"
            )
            file.write(f"{moduli[0]:.6e}\n")
            if getattr(material, "density", None):
                file.write("*DENSITY\n")
                file.write(f"{material.density:.6e}\n")
            self._write_expansion(file, material, along_member=True)
            file.write("\n")

    def _write_expansion(self, file: TextIO, material, along_member=False) -> None:
        """Thermal expansion of a material, in a model with temperature loads.

        The materials of beams, which have their 1 axis along the member,
        expand along it only. Beam theory knows no other expansion, and in
        CalculiX's expanded solids the section swelling in its own plane is
        held wherever a knot holds the section: a free cantilever under a
        gradient had E alpha dT of stress at its clamped root, and 0.1 % too
        much deflection (measured). An equivalent rectangle has the real
        section's EA and EI, so EA alpha dT and EI alpha dT / h are the real
        member's.
        """
        coefficient = getattr(material, "thermal_expansion_coefficient", None)
        if not coefficient or not self._temperature_loads():
            return
        if along_member:
            file.write("*EXPANSION, ZERO=0., TYPE=ORTHO\n")
            file.write(f"{coefficient:.6e}, 0., 0.\n")
        else:
            file.write("*EXPANSION, ZERO=0.\n")
            file.write(f"{coefficient:.6e}\n")

    @staticmethod
    def _matched_torsion_constant(member) -> Optional[float]:
        """Torsion constant to give a member's equivalent rectangle, if any."""
        section = member.section
        section_type = (getattr(section, "section_type", None) or "").lower()
        if section_type not in TORSION_MATCHED_SECTIONS:
            return None
        constant = getattr(section, "torsional_constant", None)
        return float(constant) if constant and float(constant) > 0 else None

    def _equivalent_material_name(self, member) -> str:
        """Name of the scaled material of a member's equivalent rectangle."""
        return f"MAT_EQ_{self._get_short_id(member.id)}"

    def _write_list_in_chunks(
        self, file: TextIO, items: List[int], chunk_size: int = 16
    ) -> None:
        """Write a list of integers in chunks with proper formatting."""
        for i in range(0, len(items), chunk_size):
            chunk = items[i : i + chunk_size]
            file.write(", ".join(str(x) for x in chunk))
            if i + chunk_size < len(items):
                file.write(",\n")
            else:
                file.write("\n")

    def _compute_beam_axis(
        self,
        elem_ids: Optional[List[int]] = None,
        member: Optional[CurveMember] = None,
    ) -> Tuple[float, float, float]:
        """Compute the unit beam axis, preferring mesh element node coords.

        Falls back to the member's own geometry endpoints when element/node
        data isn't available (or doesn't resolve), and finally to global Z.
        """
        if elem_ids:
            for eid in elem_ids:
                elem = self.elements.get(eid)
                if not elem:
                    continue
                nodes = elem.get("nodes")
                if not nodes or len(nodes) < 2:
                    continue
                n1 = self.nodes.get(nodes[0])
                n2 = self.nodes.get(nodes[1])
                if n1 is None or n2 is None:
                    continue
                axis = np.array(n2, dtype=float) - np.array(n1, dtype=float)
                length = np.linalg.norm(axis)
                if length > 1e-12:
                    return tuple(axis / length)

        if member is not None:
            geometry = getattr(member, "geometry", None)
            if isinstance(geometry, (list, tuple)) and len(geometry) >= 2:
                start = np.array(geometry[0], dtype=float)
                end = np.array(geometry[-1], dtype=float)
                axis = end - start
                length = np.linalg.norm(axis)
                if length > 1e-12:
                    return tuple(axis / length)

        return (0.0, 0.0, 1.0)

    def _orthogonal_beam_normal(
        self,
        raw_normal: Tuple[float, float, float],
        beam_axis: Tuple[float, float, float],
    ) -> Tuple[float, float, float]:
        """Return raw_normal orthogonalised against beam_axis, unit length.

        Subtracts the component of raw_normal parallel to beam_axis.  If the
        result is (near) zero — i.e. raw_normal was parallel to the axis —
        falls back to the first canonical perpendicular (global Y, X, or Z)
        that isn't degenerate.  This is the single source of truth used by
        both the native B31 (*BEAM SECTION) and U1 (SECTION=GENERAL) writers
        so neither can emit a degenerate local system.
        """
        axis = np.array(beam_axis, dtype=float)
        axis_len = np.linalg.norm(axis)
        axis = axis / axis_len if axis_len > 1e-12 else np.array([0.0, 0.0, 1.0])

        raw = np.array(raw_normal, dtype=float)
        n = raw - np.dot(raw, axis) * axis
        n_len = float(np.linalg.norm(n))
        if n_len < 1e-10:
            for cand in (
                np.array([0.0, 1.0, 0.0]),
                np.array([1.0, 0.0, 0.0]),
                np.array([0.0, 0.0, 1.0]),
            ):
                n = cand - np.dot(cand, axis) * axis
                n_len = float(np.linalg.norm(n))
                if n_len > 1e-10:
                    break
        n = n / n_len
        return (float(n[0]), float(n[1]), float(n[2]))

    def _write_beam_section_for_set(
        self,
        file: TextIO,
        member: CurveMember,
        elset_name: str,
        material_id: str,
        beam_normal: tuple,
        elem_ids: Optional[List[int]] = None,
    ) -> None:
        """Write a *BEAM SECTION definition for a B31 element set.

        Looks up the section type in the section_profiles registry.  Native
        types (RECT, CIRC, PIPE, BOX) are written with their exact CCX keyword
        and dimension data line. Any other type reaching this path is one
        that ``_assign_equivalent_sections`` gave an equivalent rectangle.

        ``beam_normal`` is orthogonalised against the beam axis before being
        written (safety net — mirrors the U1/GENERAL path) so a normal that
        is parallel/near-parallel to the beam axis can never reach CalculiX.
        """
        beam_axis = self._compute_beam_axis(elem_ids, member)
        beam_normal = self._orthogonal_beam_normal(beam_normal, beam_axis)
        # Section forces are recovered in these axes after the analysis
        for elem_id in elem_ids or []:
            self.domain_model.beam_section_frames[elem_id] = (
                tuple(float(v) for v in beam_axis),
                tuple(float(v) for v in beam_normal),
            )

        stype = getattr(getattr(member, "section", None), "section_type", None)
        native = get_native_section(stype)

        if native is not None:
            dims = getattr(member.section, "dimensions", {})
            data_line = native.format_data_line(dims)
            if self._rectangle_moduli(member) is None:
                material_and_axes = f"MAT_{material_id}"
            else:
                # Its own orthotropic material: 1 along the member, 2 along
                # the section's depth.
                orientation = f"OR_{elset_name}"
                file.write(f"*ORIENTATION, NAME={orientation}, SYSTEM=RECTANGULAR\n")
                file.write(
                    ", ".join(f"{v:.6e}" for v in (*beam_axis, *beam_normal)) + "\n"
                )
                material_and_axes = (
                    f"{self._rectangle_material_name(member)},"
                    f" ORIENTATION={orientation}"
                )
            file.write(
                f"*BEAM SECTION, ELSET={elset_name},"
                f" MATERIAL={material_and_axes}, SECTION={native.ccx_keyword}\n"
            )
            file.write(f"{data_line}\n")
            file.write(
                f"{beam_normal[0]:.6e}, {beam_normal[1]:.6e},"
                f" {beam_normal[2]:.6e}\n\n"
            )
        else:
            # A section CalculiX has no shape for: the rectangle of the same
            # stiffness, depth first as for RECT, with its own scaled material.
            if member.id not in self._equivalent_sections:
                raise MeshingError(
                    f"Member {member.id}: section_type={stype!r} has neither a "
                    "CalculiX shape nor an equivalent rectangle",
                    code="E-SEC-004",
                )
            depth, width, _ = self._equivalent_sections[member.id]
            # The scaled material is orthotropic: its 1 axis runs along the
            # member and its 2 axis along the section's depth.
            orientation = f"OR_{elset_name}"
            file.write(f"*ORIENTATION, NAME={orientation}, SYSTEM=RECTANGULAR\n")
            file.write(", ".join(f"{v:.6e}" for v in (*beam_axis, *beam_normal)) + "\n")
            file.write(
                f"*BEAM SECTION, ELSET={elset_name},"
                f" MATERIAL={self._equivalent_material_name(member)},"
                f" SECTION=RECT, ORIENTATION={orientation}\n"
            )
            file.write(f"{depth:.6e}, {width:.6e}\n")
            file.write(
                f"{beam_normal[0]:.6e}, {beam_normal[1]:.6e},"
                f" {beam_normal[2]:.6e}\n\n"
            )

    def _compute_element_normal(self, element_id: int) -> Tuple[float, float, float]:
        """
        Compute normal vector for a specific beam element based on its node positions.

        Args:
            element_id: Element ID to compute normal for

        Returns:
            Normal vector perpendicular to the element axis
        """
        if element_id not in self.elements:
            logger.warning(f"Element {element_id} not found in mesh")
            return (0.0, 1.0, 0.0)

        element = self.elements[element_id]
        connectivity = element.get("nodes", [])

        if len(connectivity) < 2:
            logger.warning(f"Element {element_id} has insufficient nodes")
            return (0.0, 1.0, 0.0)

        # Get node coordinates
        node1_id = connectivity[0]
        node2_id = connectivity[1]

        if node1_id not in self.nodes or node2_id not in self.nodes:
            logger.warning(f"Node coordinates not found for element {element_id}")
            return (0.0, 1.0, 0.0)

        node1 = np.array(self.nodes[node1_id])
        node2 = np.array(self.nodes[node2_id])

        if np.linalg.norm(node2 - node1) < 1e-10:
            return (0.0, 1.0, 0.0)
        return self._default_section_direction(node2 - node1)

    def _write_user_element_definition(self, file: TextIO) -> None:
        """Write the *USER ELEMENT type declaration (written once per model).

        U1 is a built-in 2-node 3D Timoshenko beam element.  The correct
        keyword parameters are INTEGRATIONPOINTS and MAXDOF (not INTEGRATION
        or VARIABLES).  No data line follows this keyword.

        INTEGRATIONPOINTS=2: resultsmech_u1.f iterates jj=1..nope (nope=2) and
        writes to stx/eme/eei arrays indexed by jj.  These arrays have size mi(1)
        in the second dimension where mi(1) is the max integration points across
        all elements.  With INTEGRATIONPOINTS=0 → mi(1)=0 → out-of-bounds write
        → segfault.  Setting INTEGRATIONPOINTS=2 gives mi(1)≥2.
        """
        file.write("** User element: 2-node 3D Timoshenko beam (6 DOF/node)\n")
        file.write("*USER ELEMENT, NODES=2, TYPE=U1, INTEGRATIONPOINTS=2, MAXDOF=6\n\n")

    def _write_beam_section_general(
        self, file: TextIO, member: "CurveMember", elem_ids: List[int]
    ) -> None:
        """Write *ELEMENT TYPE=U1 and *BEAM SECTION SECTION=GENERAL for a member.

        U1 is CalculiX's built-in Timoshenko beam element.  All elements for
        the member share one ELSET so that a single *BEAM SECTION card covers
        them.  Section properties are taken directly from the domain model.

        Side-effects:
            Adds the mass of the elements to ``self._u1_node_masses``.

        Raises:
            AnalysisError: If the member has no section or material, or its
                section has no area or no second moment of area: without
                them its elements would not be written and the structure
                would be analysed without the member.
        """
        section = member.section
        material = member.material
        if section is None or material is None:
            raise AnalysisError(
                f"Member {member.id} cannot be analysed with user elements: "
                "it has no section or no material.",
                code="E-SEC-004",
            )

        A = getattr(section, "area", None)
        xi11 = getattr(section, "moment_of_inertia_y", None)
        xi22 = getattr(section, "moment_of_inertia_z", None)
        shear_area = getattr(section, "shear_area_y", None)

        if not all([A, xi11, xi22]):
            raise AnalysisError(
                f"Member {member.id} cannot be analysed with user elements: "
                f"its section has A={A}, Iy={xi11}, Iz={xi22}, and needs all "
                "three.",
                code="E-SEC-004",
            )

        # Shear correction factor k_s (dimensionless)
        k_s = float(shear_area) / float(A) if shear_area else 0.833

        short_id = self._get_short_id(member.id)
        elset = f"U1_{short_id}"
        material_id = material.id

        # Write all elements for this member as a single block
        file.write(f"*ELEMENT, TYPE=U1, ELSET={elset}\n")
        for elem_id in elem_ids:
            elem = self.elements.get(elem_id)
            if elem is None:
                continue
            node1_id, node2_id = elem["nodes"][0], elem["nodes"][1]
            file.write(f"{elem_id}, {node1_id}, {node2_id}\n")
        file.write("\n")

        # *BEAM SECTION, SECTION=GENERAL
        # Data line 1: A, xi11, xi12(=0), xi22, k_s
        # Data line 2: beam normal direction (e2 — must be perpendicular to beam axis)
        # Orthogonalised against the beam axis (common failure: vertical columns
        # whose xAxis == zAxis == (0,0,1) make the raw IFC normal parallel to
        # the axis) via the same helper used by the native B31 path.
        beam_normal_raw = self._get_beam_normal(member)
        beam_axis = self._compute_beam_axis(elem_ids, member)
        beam_normal = self._orthogonal_beam_normal(beam_normal_raw, beam_axis)

        file.write(
            f"*BEAM SECTION, SECTION=GENERAL, ELSET={elset},"
            f" MATERIAL=MAT_{material_id}\n"
        )
        file.write(
            f"{float(A):.6e}, {float(xi11):.6e}, 0.0,"
            f" {float(xi22):.6e}, {k_s:.6e}\n"
        )
        file.write(
            f"{beam_normal[0]:.6e}, {beam_normal[1]:.6e}," f" {beam_normal[2]:.6e}\n\n"
        )

        # CalculiX misreports the forces at the nodes of U1 elements: the
        # results parser works them out from the element's stiffness, with
        # the values the solver read
        def written(value: float) -> float:
            return float(f"{float(value):.6e}")

        density = getattr(material, "density", None)
        mass_per_length = float(density) * float(A) if density and A else 0.0
        properties = {
            "direction": tuple(written(v) for v in beam_normal),
            "modulus": written(material.elastic_modulus),
            "poisson": written(material.poisson_ratio),
            "area": written(A),
            "inertia_11": written(xi11),
            "inertia_22": written(xi22),
            "shear_factor": written(k_s),
            "mass_per_length": mass_per_length,
        }
        for elem_id in elem_ids:
            elem = self.elements.get(elem_id)
            if elem is None:
                continue
            ends = (elem["nodes"][0], elem["nodes"][1])
            self.domain_model.user_elements[int(elem_id)] = {
                "nodes": ends,
                "positions": tuple(
                    tuple(written(c) for c in self.nodes[node]) for node in ends
                ),
                **properties,
            }
            # Section forces are worked out from the stiffness in these axes
            self.domain_model.beam_section_frames[elem_id] = (
                tuple(float(v) for v in beam_axis),
                tuple(float(v) for v in beam_normal),
            )

        # Mass of the U1 elements at their nodes, for their self-weight
        if mass_per_length:
            for elem_id in elem_ids:
                elem = self.elements.get(elem_id)
                if elem is None:
                    continue
                node1_id, node2_id = elem["nodes"][0], elem["nodes"][1]
                n1 = np.array(self.nodes[node1_id], dtype=float)
                n2 = np.array(self.nodes[node2_id], dtype=float)
                L = float(np.linalg.norm(n2 - n1))
                for node_id in (node1_id, node2_id):
                    self._u1_node_masses[node_id] = (
                        self._u1_node_masses.get(node_id, 0.0)
                        + mass_per_length * L / 2.0
                    )

    def _write_sections(self, file: TextIO) -> None:
        """Write section definitions for members.

        By the time this runs, self.element_sets has already been resolved so
        that each element belongs to exactly one member's set (see
        _resolve_overlapping_element_sets() and _identify_and_retype_u1_members()),
        so no further deduplication is needed here.
        """
        file.write("** Section Definitions\n")

        sections_written = 0
        without_elements: List[str] = []

        # Split beam element sets by orientation
        beam_orientation_groups = self._split_beam_sets_by_orientation()

        for member in self.domain_model.members:
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"

            # Check if member has elements
            if member_set not in self.element_sets or not self.element_sets[member_set]:
                without_elements.append(member.id)
                continue

            member_elems = self.element_sets[member_set]
            material_id = member.material.id if member.material else "DEFAULT"

            # Write beam sections
            if (
                isinstance(member, CurveMember)
                and hasattr(member, "section")
                and member.section
            ):
                # Non-standard section → U1 built-in Timoshenko + SECTION=GENERAL
                if member.id in self._u1_members:
                    self._write_beam_section_general(file, member, member_elems)
                    sections_written += 1
                    continue

                # Standard section (RECT/CIRC/PIPE/BOX) → *BEAM SECTION
                if member_set in beam_orientation_groups:
                    orientation_groups = beam_orientation_groups[member_set]

                    # Write a section for each orientation group
                    for ori_idx, (normal_key, element_ids) in enumerate(
                        orientation_groups.items()
                    ):
                        # Create sub-element-set for this orientation
                        subset_name = f"{member_set}_ORI{ori_idx+1}"

                        # Write the element set definition
                        file.write(f"*ELSET, ELSET={subset_name}\n")
                        self._write_list_in_chunks(file, element_ids, chunk_size=16)
                        file.write("\n")

                        # Use computed normal from grouping
                        beam_normal = normal_key

                        # Write beam section for this subset
                        self._write_beam_section_for_set(
                            file,
                            member,
                            subset_name,
                            material_id,
                            beam_normal,
                            elem_ids=element_ids,
                        )
                        sections_written += 1
                else:
                    # No orientation groups (shouldn't happen, but fallback to single section)
                    beam_normal = self._get_beam_normal(member)
                    self._write_beam_section_for_set(
                        file,
                        member,
                        member_set,
                        material_id,
                        beam_normal,
                        elem_ids=member_elems,
                    )
                    sections_written += 1

            # Write shell sections
            elif (
                isinstance(member, SurfaceMember)
                and hasattr(member, "thickness")
                and member.thickness
            ):
                thickness_value = getattr(member.thickness, "value", 0.1)
                # Note: Nodal thickness is written separately before elements
                file.write(
                    f"*SHELL SECTION, ELSET={member_set}, MATERIAL=MAT_{material_id}\n"
                )
                file.write(f"{thickness_value:.6e}\n\n")
                sections_written += 1

        logger.info(f"Wrote {sections_written} section definitions")

        if without_elements:
            self._warn_user(
                "W-MSH-002",
                f"{len(without_elements)} member(s) have no finite elements and "
                "take no part in the analysis: their geometry is covered by a "
                "member they overlap, whose stiffness is used there. The first "
                f"are {', '.join(without_elements[:5])}.",
                ifc_guids=self._ifc_guids(without_elements),
            )
        listed = sorted(
            member.id
            for member in self.domain_model.members
            if member.id in self._members_without_axis
            and self._section_has_a_direction(getattr(member, "section", None))
        )
        if listed:
            self._warn_user(
                "W-SEC-003",
                f"{len(listed)} curve member(s) have no usable Axis in the IFC "
                "file, so the orientation of their section about the member "
                "is a guess: its depth as near vertical as the member allows, "
                "and along global X for a vertical member. Strong and weak "
                f"axis may be interchanged. The first are {', '.join(listed[:5])}.",
                ifc_guids=self._ifc_guids(listed),
            )

    def _collect_boundary_condition_dofs(self) -> set:
        """
        Collect all (node, DOF) pairs that have boundary conditions (SPCs).

        This prevents MPC/SPC conflicts where a node DOF is constrained by
        both an MPC (from connections) and an SPC (from boundary conditions).

        Replicates the logic from write_boundary_conditions() to determine
        which nodes will have SPCs applied.

        Returns:
            Set of (node_id, dof) tuples that have boundary conditions
        """
        bc_node_dofs = set()
        # Every direction with a share in what a support holds: a skew
        # support holds a combination of them (see _write_line_bearings)
        self._supported_node_dofs: set = set()
        node_coords = self._structure_nodes()
        member_nodes = self._support_member_nodes()
        arms = getattr(self, "_support_arms", {})

        from ..analysis.boundary_condition_handling import (
            find_connection_support_nodes,
            get_constrained_dofs,
            support_equations,
            support_restraint,
        )

        # What each support node is held in, for a plane hold across a
        # skew plane
        held: Dict[int, List[np.ndarray]] = {}
        for conn in self.domain_model.connections:
            # Find nodes at this connection's position
            if hasattr(conn, "position") and conn.position:
                bc_nodes = find_connection_support_nodes(
                    conn, node_coords, member_nodes
                )
                dofs = get_constrained_dofs(conn)
                restraint = support_restraint(conn)

                for node in bc_nodes:
                    if restraint is not None and len(restraint[0]):
                        held.setdefault(node, []).append(restraint[0])
                    for dof in dofs:
                        bc_node_dofs.add((node, dof))
                    # A skew direction is an equation, and its first term
                    # is taken as much as a restrained DOF is
                    tip, _, drilling = arms.get(conn.id, {}).get(
                        node, (None, None, None)
                    )
                    for terms in support_equations(conn, node, tip, drilling):
                        bc_node_dofs.add(terms[0][:2])
                        self._supported_node_dofs.update(
                            (n, dof) for n, dof, _ in terms
                        )
        self._supported_node_dofs.update(bc_node_dofs)

        bc_node_dofs.update(self._torsion_hold_dofs())
        bc_node_dofs.update(self._plane_hold_dofs())
        self._plane_equations = self._plane_hold_equations(bc_node_dofs, held)

        logger.info(f"Collected {len(bc_node_dofs)} boundary condition DOFs")
        if logger.isEnabledFor(logging.DEBUG):
            # Log first 20 for debugging
            sample = sorted(list(bc_node_dofs))[:20]
            logger.debug(f"Sample boundary condition DOFs: {sample}")
        return bc_node_dofs

    def _record_support_node_elements(self) -> None:
        """Note the elements at every support node, for the reaction moments.

        CalculiX gives the force on each node of the solids it expands beams
        and shells into. Those at a support node, taken about it, are the
        moment the support takes there, and the results parser finds them
        through the elements that have the node: every one of them, links
        and arms included, since the forces between the elements at a node
        only cancel when all are added.

        ``domain_model.support_node_elements`` gets ``{node: (position,
        {element: positions of the element's other nodes})}``.
        """
        supports = getattr(self.domain_model, "support_nodes", None) or {}
        wanted = {node for record in supports.values() for node in record["nodes"]}
        recorded: Dict[int, tuple] = {
            node: (tuple(float(c) for c in self.nodes[node]), {})
            for node in wanted
            if node in self.nodes
        }
        connectivity = [(e, elem["nodes"]) for e, elem in self.elements.items()]
        connectivity += [
            (e, [a, b])
            for e, a, b in list(getattr(self, "_rigid_links", []))
            + list(getattr(self, "_knot_links", []))
        ]
        for elem_id, elem_nodes in connectivity:
            for node in elem_nodes:
                if node in recorded:
                    recorded[node][1][int(elem_id)] = [
                        tuple(float(c) for c in self.nodes[other])
                        for other in elem_nodes
                        if other != node
                    ]
        self.domain_model.support_node_elements = recorded

    def _structure_nodes(self) -> Dict[int, Tuple[float, float, float]]:
        """The nodes of the members: not the tips of hinge and support arms.

        Supports and loads are placed on the node nearest to them, which must
        not be one of those.
        """
        helpers = getattr(self, "_helper_nodes", set())
        return {n: xyz for n, xyz in self.nodes.items() if n not in helpers}

    def _support_member_nodes(self) -> Dict[str, set]:
        """The nodes of the members each support holds, by support id.

        Beam and shell meshes keep nodes of their own at one point, and a
        support takes only those of its members (``aiz.97``,
        ``find_connection_support_nodes``). Members are found by the elements
        in their geometry, so one overlapped by another still has its nodes.
        """
        geometry_sets = getattr(self, "_geometry_element_sets", {})
        nodes_of: Dict[str, set] = {}
        result: Dict[str, set] = {}
        for conn in self.domain_model.connections:
            if not conn.has_stiffness_properties():
                continue
            held: set = set()
            for member_id in conn.connected_members:
                if member_id not in nodes_of:
                    member_set = f"MEMBER_{self._get_short_id(member_id)}"
                    elems = geometry_sets.get(member_set) or self.element_sets.get(
                        member_set, []
                    )
                    nodes_of[member_id] = {
                        n
                        for elem_id in elems
                        if elem_id in self.elements
                        for n in self.elements[elem_id]["nodes"]
                    }
                held |= nodes_of[member_id]
            if held:
                result[conn.id] = held
        return result

    # Largest gap between two nodes that are treated as the same point.
    _COINCIDENT_TOL = 1e-3

    def _warn_user(
        self,
        code: str,
        message: str,
        domain_id: Optional[str] = None,
        ifc_guids: Iterable[str] = (),
    ) -> None:
        """Log a warning and record it on the model for ``result["warnings"]``.

        ``code`` is one of ``utils.messages.KINDS``.
        """
        record_warning(
            self.domain_model,
            code,
            message,
            domain_id=domain_id,
            ifc_guids=ifc_guids,
        )

    def _ifc_guids(self, ids: Iterable[str]) -> List[str]:
        """The IFC GlobalIds of the members and connections with these ids."""
        return guids_of(self.domain_model, ids)

    # Longest rigid end zone that is bridged with a stiff link element.
    _MAX_RIGID_LINK = 2.0
    # Stiff link properties: a 0.5 m square at 100 x the modulus of steel is
    # about a thousand times stiffer in bending than a typical member, which
    # is rigid for practical purposes without wrecking the conditioning.
    _RIGID_LINK_SIDE = 0.5
    _RIGID_LINK_MODULUS = 2.1e13

    def _merge_rigid_connection_nodes(self) -> None:
        """Make every rigid connection able to transfer moment.

        CalculiX expands beam and shell elements into solids, so their nodes
        have no rotational degrees of freedom of their own. ``*EQUATION`` on
        DOF 4-6 between two such nodes is accepted and silently does nothing,
        and rigid bodies or beam MPCs on them are rejected. The only way to
        pass moment between two members is a shared node, where CalculiX
        builds a knot (a rigid body over the expanded nodes).

        For each connection, the joint node is the member node nearest the
        connection position. Every other member without an end release is
        then joined to it:

        * a coincident node is merged into the joint node (beams and shells
          are meshed with separate nodes);
        * a node that stops short of the joint, as analysis models with rigid
          end zones produce (a column ending at the beam soffit, a beam ending
          at the column face), is bridged by a stiff B31 link element recorded
          in ``self._rigid_links``.

        Members with an end release keep their own node and are tied by
        translation equations in ``_write_point_connection``.

        A line connection joining a curve and a surface member with no
        release about the line (``_line_joints``) is made the same way at
        every node along it: the beam and slab nodes are merged, or joined
        by a link where the beam is eccentric. An arm or an equation cannot
        do it: an equation reaches only the slab's middle surface, and the
        slab's normals stay free to turn against its shear stiffness alone
        (a slab clamped that way to a beam held against twisting came out
        40 % too flexible in its own share). The slab is a knot along the
        line, which holds its thickness there and stiffens it a little: 3 %
        of a cantilevered slab's own deflection at a 0.25 m mesh, nu = 0.3.
        """
        parent: Dict[int, int] = {}
        links: List[Tuple[int, int]] = []
        far: List[Tuple[str, str, float]] = []

        def find(node: int) -> int:
            while node in parent:
                node = parent[node]
            return node

        for conn in self.domain_model.connections:
            real_members = list(conn.connected_members)
            if len(real_members) < 2 or conn.entity_type not in ("point", "rigid"):
                continue
            if getattr(conn, "edge", None) is not None:
                continue  # joined along the line (_build_line_joints)
            released = getattr(conn, "released_dofs_by_member", None) or {}
            rigid_members = [
                m
                for m in real_members
                if not released.get(m) and m not in self._u1_members
            ]
            if len(rigid_members) < 2:
                continue

            pairs = self._find_connection_nodes_at_location(conn, rigid_members)
            if len(pairs) < 2:
                continue
            positions = {n: np.array(self.nodes[n], dtype=float) for _, n in pairs}
            try:
                conn_pos = np.array([float(v) for v in conn.position[:3]])
            except (TypeError, ValueError, AttributeError):
                conn_pos = positions[pairs[0][1]]
            joint_node = min(
                (n for _, n in pairs),
                key=lambda n: float(np.linalg.norm(positions[n] - conn_pos)),
            )
            for member_id, node in pairs:
                if node == joint_node:
                    continue
                gap = float(np.linalg.norm(positions[node] - positions[joint_node]))
                if gap <= self._COINCIDENT_TOL:
                    root_a, root_b = find(joint_node), find(node)
                    if root_a != root_b:
                        parent[max(root_a, root_b)] = min(root_a, root_b)
                elif gap <= self._MAX_RIGID_LINK:
                    links.append((node, joint_node))
                else:
                    far.append((conn.id, member_id, gap))
        self._warn_far_member_ends(
            far, "they are tied in translation only and carry no moment there"
        )

        # Members joined rigidly along a line connection of the file
        for joint in self._line_joints():
            if not joint["rigid"]:
                continue
            for node, shell_node in joint["pairs"]:
                gap = float(
                    np.linalg.norm(
                        np.array(self.nodes[node]) - np.array(self.nodes[shell_node])
                    )
                )
                if gap <= self._COINCIDENT_TOL:
                    root_a, root_b = find(node), find(shell_node)
                    if root_a != root_b:
                        parent[max(root_a, root_b)] = min(root_a, root_b)
                else:
                    links.append((node, shell_node))

        if parent:
            for elem in self.elements.values():
                elem["nodes"] = [find(n) for n in elem["nodes"]]
            for name, node_ids in self.node_sets.items():
                self.node_sets[name] = sorted({find(n) for n in node_ids})
            for node in parent:
                del self.nodes[node]
            # Node lookups cached before the merge are now stale
            self._member_node_cache = {}
            logger.info(f"Merged {len(parent)} coincident nodes at rigid connections")

        unique_links = sorted(
            {tuple(sorted((find(a), find(b)))) for a, b in links if find(a) != find(b)}
        )
        next_id = max(self.elements.keys(), default=0) + 1
        self._rigid_links = [
            (next_id + i, a, b) for i, (a, b) in enumerate(unique_links)
        ]
        if self._rigid_links:
            logger.info(f"Added {len(self._rigid_links)} rigid link elements")

    def _release_hinged_edges(self) -> None:
        """Hinge surface members that are released along a shared edge.

        Surfaces that meet along an edge are meshed with shared nodes, which
        makes the joint rigid. A member whose connection to the edge releases
        the rotation about it (a slab simply resting on a wall) gets its own
        copy of the edge nodes instead. ``_write_edge_hinges`` then ties each
        copy to the original in translation only, and a row of such ties along
        a line is a hinge about that line.

        At least one member keeps the original nodes; if every member is
        released, the first one does.
        """
        from ..analysis.boundary_condition_handling import (
            find_nodes_on_segment,
            released_rotation_axes,
            share_in_span,
        )

        self._edge_hinge_pairs: List[Tuple[int, int]] = []
        copies: Dict[Tuple[str, int], int] = {}
        next_node = max(self.nodes.keys(), default=0) + 1

        for conn in self.domain_model.connections:
            edge = getattr(conn, "edge", None)
            # Surfaces only: a curve member's joint along the line is made
            # by _build_line_joints, node for node
            members = [
                m
                for m in conn.connected_members
                if isinstance(self.domain_model.get_member(m), SurfaceMember)
            ]
            if edge is None or len(edge) != 2 or len(members) < 2:
                continue

            direction = np.array(edge[1], dtype=float) - np.array(edge[0])
            if float(np.linalg.norm(direction)) < 1e-9:
                continue

            hinged = []
            for member_id in members:
                if not isinstance(
                    self.domain_model.get_member(member_id), SurfaceMember
                ):
                    continue
                # Released about the edge, whichever way the edge runs
                released = released_rotation_axes(conn, member_id)
                if share_in_span(released, direction) > 1.0 - 1e-6:
                    hinged.append(member_id)
            if len(hinged) == len(members):
                hinged = hinged[1:]
            if not hinged:
                continue

            edge_nodes = set(find_nodes_on_segment(edge[0], edge[1], dict(self.nodes)))
            for member_id in hinged:
                member_set = f"MEMBER_{self._get_short_id(member_id)}"
                for elem_id in self.element_sets.get(member_set, []):
                    elem = self.elements.get(elem_id)
                    if elem is None:
                        continue
                    for i, node in enumerate(elem["nodes"]):
                        if node not in edge_nodes:
                            continue
                        key = (member_id, node)
                        if key not in copies:
                            copies[key] = next_node
                            self.nodes[next_node] = self.nodes[node]
                            self._edge_hinge_pairs.append((next_node, node))
                            next_node += 1
                        elem["nodes"][i] = copies[key]

        if copies:
            self._member_node_cache = {}
            logger.info(f"Hinged {len(copies)} edge nodes of released surface members")

    def _write_edge_hinges(self, file: TextIO, constrained_node_dofs: set) -> None:
        """Tie the edge nodes of hinged surface members to the edge in translation."""
        pairs = getattr(self, "_edge_hinge_pairs", [])
        if not pairs:
            return
        file.write("** Hinged edges between surface members\n")
        for copy, original in pairs:
            for dof in (1, 2, 3):
                if (copy, dof) in constrained_node_dofs:
                    continue
                file.write("*EQUATION\n2\n")
                file.write(f"{copy},{dof},1.0,{original},{dof},-1.0\n")
                constrained_node_dofs.add((copy, dof))
                self._note_equation_nodes((copy, original))
                self._note_translation_tie(copy, original)
        file.write("**\n")

    # Length of the stiff arms that carry a partial end release.
    _HINGE_ARM = 0.25

    def _build_release_hinges(self) -> None:
        """Prepare the hinge of every member end that has a rotational release.

        CalculiX beam nodes have no rotational degrees of freedom to tie or
        leave free, so a hinge is built from translations alone:

        * The released member end gets its own node, tied to the joint in
          DOF 1-3. That is a ball joint: all three rotations free.
        * A rotation that is *not* released is then taken away again with a
          pair of stiff arms, one fixed to the member end and one to the
          joint, running side by side along a released axis. Tying the arm
          tips together in the directions across the arm stops the two sides
          rotating relative to each other about those directions, while
          rotation about the arm itself stays free.

        A member end that stops short of the joint (an eccentric connection)
        is hinged where it ends: a rigid link carries the joint out to that
        point first, so the reaction acts on the joint with its lever arm.

        The equations are stored in ``self._release_hinges`` and written by
        ``_write_point_connection``. U1 members are left to the old ball
        joint, since link elements cannot be mixed with them on stock CalculiX.
        """
        self._release_hinges: Dict[str, Dict[str, List[List[tuple]]]] = {}
        helpers: set = set()
        links = list(getattr(self, "_rigid_links", []))
        next_node = max(self.nodes.keys(), default=0) + 1
        next_elem = (
            max(
                [max(self.elements.keys(), default=0)]
                + [elem_id for elem_id, _, _ in links]
            )
            + 1
        )

        def add_node(position) -> int:
            nonlocal next_node
            self.nodes[next_node] = tuple(float(v) for v in position)
            next_node += 1
            return next_node - 1

        def add_link(node_a: int, node_b: int) -> None:
            nonlocal next_elem
            links.append((next_elem, node_a, node_b))
            next_elem += 1

        def end_node(conn, member_id: str) -> Optional[int]:
            pairs = self._find_connection_nodes_at_location(conn, [member_id])
            return pairs[0][1] if pairs else None

        far: List[Tuple[str, str, float]] = []
        for conn in self.domain_model.connections:
            members = list(conn.connected_members)
            if len(members) < 2 or getattr(conn, "edge", None) is not None:
                continue
            if conn.entity_type == "hinge":
                released = {m: [4, 5, 6] for m in members}
            elif conn.entity_type in ("point", "rigid"):
                released = getattr(conn, "released_dofs_by_member", None) or {}
            else:
                continue
            if not any(released.values()):
                continue
            if any(m in self._u1_members for m in members):
                continue

            nodes = {m: end_node(conn, m) for m in members}
            held = [m for m in members if not released.get(m) and nodes[m] is not None]
            anchor_member = (
                held[0]
                if held
                else next((m for m in members if nodes[m] is not None), None)
            )
            if anchor_member is None:
                continue
            joint = nodes[anchor_member]
            joint_pos = np.array(self.nodes[joint], dtype=float)

            for member_id in members:
                dofs = released.get(member_id)
                node = nodes[member_id]
                if not dofs or member_id == anchor_member or node is None:
                    continue

                if node == joint:
                    # Meshed with a node shared with the joint: split it off
                    node = add_node(joint_pos)
                    member_set = f"MEMBER_{self._get_short_id(member_id)}"
                    for elem_id in self.element_sets.get(member_set, []):
                        elem = self.elements.get(elem_id)
                        if elem is not None:
                            elem["nodes"] = [
                                node if n == joint else n for n in elem["nodes"]
                            ]
                position = np.array(self.nodes[node], dtype=float)
                gap = float(np.linalg.norm(position - joint_pos))
                anchor = joint
                if self._COINCIDENT_TOL < gap <= self._MAX_RIGID_LINK:
                    anchor = add_node(position)
                    add_link(joint, anchor)
                elif gap > self._MAX_RIGID_LINK:
                    far.append((conn.id, member_id, gap))

                equations = [
                    [(node, dof, 1.0), (anchor, dof, -1.0)] for dof in (1, 2, 3)
                ]

                free = sorted({d - 4 for d in dofs if d in (4, 5, 6)})
                if 0 < len(free) < 3:
                    axes = (getattr(conn, "release_axes_by_member", None) or {}).get(
                        member_id
                    )
                    axes = np.array(
                        axes if axes is not None else np.eye(3), dtype=float
                    )
                    fixed = [i for i in range(3) if i not in free]
                    # One released axis: arm along it, tips tied in both
                    # directions across it. Two released axes: arm along one,
                    # tips tied along the other, which stops rotation about
                    # the third (fixed) axis only.
                    arm = axes[free[0]]
                    across = (
                        [axes[i] for i in fixed] if len(free) == 1 else [axes[free[1]]]
                    )
                    tip = position + self._HINGE_ARM * arm
                    member_tip, joint_tip = add_node(tip), add_node(tip)
                    helpers.update((member_tip, joint_tip))
                    add_link(node, member_tip)
                    add_link(anchor, joint_tip)
                    used: set = set()
                    for direction in across:
                        order = sorted(
                            range(3),
                            key=lambda i: (i in used, -abs(direction[i])),
                        )
                        used.add(order[0])
                        terms = [
                            (tip_node, i + 1, sign * float(direction[i]))
                            for tip_node, sign in ((member_tip, 1.0), (joint_tip, -1.0))
                            for i in order
                            if abs(direction[i]) > 1e-9
                        ]
                        equations.append(terms)

                self._release_hinges.setdefault(conn.id, {})[member_id] = equations

        self._warn_far_member_ends(
            far, "they are tied to it in translation with no lever arm"
        )
        if self._release_hinges:
            self._rigid_links = links
            self._helper_nodes = getattr(self, "_helper_nodes", set()) | helpers
            self._member_node_cache = {}
            logger.info(
                f"Built release hinges at {len(self._release_hinges)} connections"
            )

    def _warn_far_member_ends(
        self, far: List[Tuple[str, str, float]], consequence: str
    ) -> None:
        """One W-JNT-006 for the member ends too far from their connection.

        Args:
            far: (connection id, member id, distance in metres) of each.
            consequence: What is done instead, said of the members.
        """
        if not far:
            return
        first = ", ".join(f"{m} at {c} ({gap:.2f} m)" for c, m, gap in far[:5])
        self._warn_user(
            "W-JNT-006",
            f"{len(far)} member end(s) lie further than {self._MAX_RIGID_LINK} "
            f"m from their connection, too far for a rigid link; {consequence}. "
            f"The first are {first}.",
            ifc_guids=self._ifc_guids(
                list(dict.fromkeys([c for c, _, _ in far] + [m for _, m, _ in far]))
            ),
        )

    def _build_support_arms(self) -> None:
        """Fix a stiff arm to every node of a support that holds skew rotations.

        A rotation about an axis that is not a global one cannot be given to
        ``*BOUNDARY``, and the nodes of beams and shells have no rotations
        for an equation to act on. An arm along an axis the support leaves
        free turns the rotations it holds into translations of its tip, which
        ``write_boundary_conditions`` ties down (``rotation_arm``).

        A node of shells alone has no rotation about their normal, and that
        one is held too (``_drilling_axis``), which can leave nothing for an
        arm to do.

        Stored in ``self._support_arms`` as
        ``{support id: {node: (tip node, tip position, shell normal)}}``, the
        first two None where no arm is needed. Nothing is built in a model
        with U1 members, where link elements cannot be used on stock
        CalculiX; ``write_boundary_conditions`` then stops the analysis.
        """
        from ..analysis.boundary_condition_handling import (
            find_connection_support_nodes,
            rotation_arm,
            support_restraint,
        )

        self._support_arms: Dict[str, Dict[int, tuple]] = {}
        if self._u1_members:
            return
        elements_at: Dict[int, List[int]] = {}
        for elem_id, elem in self.elements.items():
            for node in elem["nodes"]:
                elements_at.setdefault(node, []).append(elem_id)
        member_nodes = self._support_member_nodes()
        links = list(getattr(self, "_rigid_links", []))
        helpers = set(getattr(self, "_helper_nodes", set()))
        next_node = max(self.nodes.keys(), default=0) + 1
        next_elem = (
            max(
                [max(self.elements.keys(), default=0)]
                + [elem_id for elem_id, _, _ in links]
            )
            + 1
        )
        for conn in self.domain_model.connections:
            restraint = support_restraint(conn)
            if restraint is None or rotation_arm(restraint[1]) is None:
                continue
            nodes = find_connection_support_nodes(
                conn, self._structure_nodes(), member_nodes
            )
            linked = {n for _, a, b in links for n in (a, b)}
            for node in nodes:
                drilling = (
                    None
                    if node in linked
                    else self._drilling_axis(elements_at.get(node, []))
                )
                arm = rotation_arm(restraint[1], drilling)
                arms = self._support_arms.setdefault(conn.id, {})
                if arm is None:
                    arms[node] = (None, None, drilling)
                    continue
                tip = tuple(
                    float(v)
                    for v in np.array(self.nodes[node]) + self._HINGE_ARM * arm[0]
                )
                self.nodes[next_node] = tip
                helpers.add(next_node)
                self._helper_nodes = helpers
                links.append((next_elem, node, next_node))
                arms[node] = (next_node, tip, drilling)
                next_node += 1
                next_elem += 1
        if len(links) > len(getattr(self, "_rigid_links", [])):
            self._rigid_links = links
            self._member_node_cache = {}
            logger.info(f"Built arms at {len(self._support_arms)} skew supports")

    # A knot link carries nothing; it is short and thin so that its
    # expanded nodes stay next to the node it is hung on.
    _KNOT_LINK = 0.01
    # The cosine above which CalculiX gives shells at a node one normal
    # (``gen3dnor.f``, about half a degree)
    _SHELL_SAME_NORMAL = 0.999962

    def _knot_point_loaded_nodes(self) -> None:
        """Make a knot of every beam node a point force is applied to.

        CalculiX applies a force on a beam node that is not a knot to the
        four corner nodes of the expanded cross-section, a quarter each
        (``gen3dforc.f``), where a uniform push on the face of a 20-node
        brick has -1/12 at the corners and 1/3 at the middles of its sides.
        The corners are dented, and more so the shorter the elements are: a
        3 m column under 10 kN at its top shortened 2.7 % more than PL/EA at
        a 0.25 m mesh and 6.6 % at 0.1 m (``aiz.76``), and an I section as
        its equivalent rectangle under a load at midspan sagged 1.2 % more
        than Timoshenko's beam at a 0.25 m mesh and 3.1 % at 0.05 m. At a
        knot the cross-section is rigid and the force is spread as the
        elements need: the column comes out at PL/EA to 0.03 % and the I
        section to 3e-6 at any mesh.

        A rigid cross-section once stiffened a member in bending over the
        elements beside it (3 % at midspan of a 4 m span at a 0.5 m mesh),
        by stopping the Poisson contraction of the section; beams have no
        Poisson's ratio now (``_BEAM_POISSON``, aiz.91), and knots anywhere
        cost nothing.

        CalculiX makes a knot where beams of different directions meet, so
        a short link at right angles to the member is hung on the node, its
        other end free. It carries no force. Support nodes are left alone
        (the force there goes into the support), and so are nodes a link
        already makes a knot of. Nothing in a model with U1 members, where
        link elements cannot be used on stock CalculiX.
        """
        from ..analysis.boundary_condition_handling import (
            find_closest_node,
            find_connection_support_nodes,
        )
        from ..domain.load import PointLoad

        self._knot_links: List[Tuple[int, int, int]] = []
        if self._u1_members or self.analysis_config.get_analysis_type() == "modal":
            # A modal analysis applies no load
            return
        loads = [
            load
            for group in self.domain_model.load_groups
            for load in group.loads
            if isinstance(load, PointLoad)
        ] + [
            load
            for member in self.domain_model.members
            for load in getattr(member, "loads", [])
            if isinstance(load, PointLoad)
        ]
        if not loads:
            return
        structure = self._structure_nodes()
        elements_at: Dict[int, List[dict]] = {}
        for elem in self.elements.values():
            for node in elem["nodes"]:
                elements_at.setdefault(node, []).append(elem)
        beam_axis: Dict[int, np.ndarray] = {}
        for node, elems in elements_at.items():
            if any(e["type"] not in BEAM_ELEMENT_TYPES for e in elems):
                continue
            nodes = elems[0]["nodes"]
            beam_axis[node] = np.array(self.nodes[nodes[-1]]) - np.array(
                self.nodes[nodes[0]]
            )
        skip = {n for _, a, b in getattr(self, "_rigid_links", []) for n in (a, b)}
        member_nodes = self._support_member_nodes()
        for conn in self.domain_model.connections:
            if conn.has_stiffness_properties():
                skip.update(
                    find_connection_support_nodes(conn, structure, member_nodes)
                )

        helpers = set(getattr(self, "_helper_nodes", set()))
        next_node = max(self.nodes.keys(), default=0) + 1
        next_elem = (
            max(
                [max(self.elements.keys(), default=0)]
                + [elem_id for elem_id, _, _ in getattr(self, "_rigid_links", [])]
            )
            + 1
        )
        for load in loads:
            position = getattr(load, "position", None)
            if position is None or not len(position):
                continue
            node = find_closest_node(position, structure)
            if node is None or node in skip or node not in beam_axis:
                continue
            skip.add(node)
            across = self._orthogonal_beam_normal(
                (0.0, 0.0, 1.0), tuple(beam_axis[node])
            )
            self.nodes[next_node] = tuple(
                float(v)
                for v in np.array(self.nodes[node]) + self._KNOT_LINK * np.array(across)
            )
            helpers.add(next_node)
            self._knot_links.append((next_elem, node, next_node))
            next_node += 1
            next_elem += 1
        self._helper_nodes = helpers

    def _knot_shell_nodes_on_equations(self) -> None:
        """Make a knot of every node of shells an equation acts on in their plane.

        CalculiX expands a shell node into three through the thickness. A
        ``*BOUNDARY`` holds the mean of the outer two and the middle one
        (``gen3dboun.f``), an equation the mean of the outer two only
        (``gen3dmpc.f``, where the line for the middle one is commented
        out), so the middle of the section is free to slide. ``slab_01``
        pushed in its plane between two edges, their hold along the edge
        written as an equation, came out 1.9, 3.0 and 4.8 % more flexible than
        with ``*BOUNDARY`` at a 0.5, 0.25 and 0.125 m mesh (``aiz.103``). Sheared
        in their plane at 0.25, 0.125 and 0.0625 m, a hinge between two slabs was
        4.4, 7.8 and 8.9 % too flexible and a slab tied or hinged to beams along
        its edges 9, 15 and 19 %; line springs in its plane, at 0.5, 0.25 and
        0.125 m, 3.6, 6.4 and 9.1 % (``aiz.104``). At a knot the section is rigid
        and the equation holds all of it: each is then within 1e-3 of its
        reference at every mesh.

        A short link hung on the node makes it a knot, as for point loads
        (``_knot_point_loaded_nodes``). Nodes on a beam, a link or an arm
        are knots already. Nothing in a model with U1 members, where link
        elements cannot be used on stock CalculiX.

        **The link lies in the shells' plane and its tip is tied against
        turning about their normal** (``_knot_drilling``). The points of a
        section are in line along the normal, so nothing else stops a knot
        turning about it: the solver's value for that rotation is noise, and
        it broke equilibrium once the knot turned about anything else (the
        hinge above had reactions of 17 kN at an imbalance of 20 kN of a 20
        kN load at 0.0625 m, with the links along the normal). The tie touches
        the section at no point, so it holds nothing of the structure. Only
        where the shells lie in one plane: where a wall meets a slab the
        section's points are not in line, the knot needs no tie, and a tie holds
        the structure against the ground (``building_01``'s moments were out by
        5e-4 of the total, its forces balancing).

        A spring across the shells acts on the mean of the top and bottom
        where it matters, so it does not make a knot of its node.
        """
        from ..analysis.boundary_condition_handling import (
            find_connection_support_nodes,
            support_equations,
        )

        self._knot_drilling: List[List[Tuple[int, int, float]]] = []
        if self._u1_members:
            return
        if not hasattr(self, "_knot_links"):
            self._knot_links = []
        arms = getattr(self, "_support_arms", {})
        structure = self._structure_nodes()
        member_nodes = self._support_member_nodes()
        on_equations: set = set()
        for conn in self.domain_model.connections:
            if not conn.has_stiffness_properties():
                continue
            for node in find_connection_support_nodes(conn, structure, member_nodes):
                tip, _, drilling = arms.get(conn.id, {}).get(node, (None, None, None))
                for terms in support_equations(conn, node, tip, drilling):
                    if len(terms) > 1:
                        on_equations.update(n for n, _, _ in terms)
        for pair in getattr(self, "_edge_hinge_pairs", []):
            on_equations.update(pair)
        for node, terms in getattr(self, "_line_bearings", []):
            on_equations.add(node)
            on_equations.update(n for n, weight in terms if abs(weight) > 1e-9)

        elements_at: Dict[int, List[int]] = {}
        for elem_id, elem in self.elements.items():
            for node in elem["nodes"]:
                elements_at.setdefault(node, []).append(elem_id)

        def shell_axes(elements: List[int]) -> Tuple[np.ndarray, np.ndarray]:
            """The normal of the first element, and a direction in its plane."""
            corners = [
                np.array(self.nodes[n], dtype=float)
                for n in self.elements[elements[0]]["nodes"][:3]
            ]
            along = corners[1] - corners[0]
            normal = np.cross(along, corners[2] - corners[0])
            return normal / np.linalg.norm(normal), along / np.linalg.norm(along)

        for springs in getattr(self, "_support_springs", {}).values():
            for spring in springs:
                elems = elements_at.get(spring["node"], [])
                if (
                    spring["kind"] == "translation"
                    and elems
                    and all(
                        self.elements[e]["type"] in SHELL_ELEMENT_TYPES for e in elems
                    )
                    and abs(float(np.dot(shell_axes(elems)[0], spring["direction"])))
                    < 1.0 - 1e-6
                ):
                    on_equations.add(spring["node"])
        if not on_equations:
            return

        linked = {
            n
            for _, a, b in list(getattr(self, "_rigid_links", [])) + self._knot_links
            for n in (a, b)
        }
        helpers = set(getattr(self, "_helper_nodes", set()))
        next_node = max(self.nodes.keys(), default=0) + 1
        next_elem = (
            max(
                [max(self.elements.keys(), default=0)]
                + [e for e, _, _ in getattr(self, "_rigid_links", [])]
                + [e for e, _, _ in self._knot_links]
                + [e for e, _, _ in getattr(self, "_spring_elements", [])]
            )
            + 1
        )
        knotted = 0
        for node in sorted(on_equations):
            elems = elements_at.get(node, [])
            if (
                node in linked
                or not elems
                or any(
                    self.elements[e]["type"] not in SHELL_ELEMENT_TYPES for e in elems
                )
            ):
                continue
            normal, along = shell_axes(elems)
            self.nodes[next_node] = tuple(
                float(v) for v in np.array(self.nodes[node]) + self._KNOT_LINK * along
            )
            helpers.add(next_node)
            self._knot_links.append((next_elem, node, next_node))
            if all(
                abs(float(np.dot(normal, shell_axes([e])[0]))) > self._SHELL_SAME_NORMAL
                for e in elems
            ):
                across = np.cross(normal, along)
                terms = [
                    i for i in np.argsort(-np.abs(across)) if abs(across[i]) > 1e-12
                ]
                self._knot_drilling.append(
                    [(next_node, int(i) + 1, float(across[i])) for i in terms]
                    + [(node, int(i) + 1, -float(across[i])) for i in terms]
                )
            next_node += 1
            next_elem += 1
            knotted += 1
        self._helper_nodes = helpers
        if knotted:
            logger.info(f"Made knots of {knotted} shell nodes on equations")

    def _write_knot_drilling(self, file: TextIO) -> None:
        """Tie the links of shell knots against turning about the shells' normal."""
        ties = getattr(self, "_knot_drilling", [])
        if not ties:
            return
        file.write("** Knots of shell nodes held against turning about the normal\n")
        for terms in ties:
            self._write_equation(file, terms)
        file.write("**\n")

    def _build_support_springs(self) -> None:
        """Put a spring on every node of an elastic support.

        Each spring is a ``SPRING1`` on a node of its own, whose first
        translation an equation makes what the spring resists: the node's
        translation along the spring for a translational one, and for a
        rotational one the rotation of a stiff arm fixed to the node (the
        movement of its tip across it, over its length). CalculiX ignores a
        ``SPRING1`` on the rotation of a beam or shell node, and a spring on
        the tip of an arm would hold the node's translation as well
        (measured). The spring's own node is printed in every step, and its
        displacement times the stiffness is the reaction: the solver's force
        at a node is wrong when a tie leans on it, as the line bearings do.

        A node of shells alone has no rotation about their normal. A spring
        about it would hold nothing and is left out, with a warning; the arm
        of one about an axis in their plane lies in it too, and its tip is
        held against turning about the normal relative to the node.

        Stored in ``self._support_springs`` as ``{support id: [spring]}``,
        each a dict with ``kind`` (translation or rotation), ``node``,
        ``spring_node``, ``position``, ``direction`` (the direction or the
        axis, global) and ``stiffness`` (N/m or N*m/rad); a rotational one
        also has ``across``, the direction its arm's tip moves in, and
        ``arm_length``.

        Raises:
            AnalysisError: If a support has no node, its elements do not cover
                it, or it has a rotational spring that cannot be built: in a
                model with U1 members, or about an axis neither in the plane
                of the shells at a node of theirs alone nor across it.
        """
        from ..analysis.boundary_condition_handling import (
            find_connection_support_nodes,
            spring_node_shares,
            support_springs,
        )

        self._support_springs: Dict[str, List[Dict[str, Any]]] = {}
        self._spring_elements: List[Tuple[int, int, float]] = []
        self._spring_equations: List[List[Tuple[int, int, float]]] = []
        elastic = [
            (conn, *support_springs(conn)) for conn in self.domain_model.connections
        ]
        elastic = [item for item in elastic if item[1] or item[2]]
        if not elastic:
            return
        elements_at: Dict[int, List[int]] = {}
        for elem_id, elem in self.elements.items():
            for node in elem["nodes"]:
                elements_at.setdefault(node, []).append(elem_id)
        links = list(getattr(self, "_rigid_links", []))
        linked = {
            n
            for _, a, b in links + list(getattr(self, "_knot_links", []))
            for n in (a, b)
        }
        helpers = set(getattr(self, "_helper_nodes", set()))
        next_node = max(self.nodes.keys(), default=0) + 1
        next_elem = (
            max(
                [max(self.elements.keys(), default=0)]
                + [e for e, _, _ in links]
                + [e for e, _, _ in getattr(self, "_knot_links", [])]
            )
            + 1
        )
        structure = self._structure_nodes()
        member_nodes = self._support_member_nodes()
        drilling_left_out: List[str] = []

        def new_node(position) -> int:
            nonlocal next_node
            node = next_node
            self.nodes[node] = tuple(float(v) for v in position)
            helpers.add(node)
            next_node += 1
            return node

        for conn, translations, rotations in elastic:
            if rotations and self._u1_members:
                raise AnalysisError(
                    f"Support {conn.id} cannot be applied: it has a rotational "
                    "spring, which takes a stiff arm, and arms cannot be used "
                    "in a model with user elements.",
                    code="E-SUP-008",
                )
            nodes = find_connection_support_nodes(conn, structure, member_nodes)
            if not nodes:
                raise AnalysisError(
                    f"Support {conn.id} cannot be applied: the mesh has no node "
                    "on it. Check that it lies on a member.",
                    code="E-SUP-002",
                )
            shares = spring_node_shares(conn, nodes, self.elements, self.nodes)
            springs = self._support_springs.setdefault(conn.id, [])
            for node, share in sorted(shares.items()):
                if share <= 0.0:
                    continue
                here = np.array(self.nodes[node], dtype=float)
                for direction, stiffness in translations:
                    spring_node = new_node(here)
                    self._spring_equations.append(
                        [(spring_node, 1, 1.0)]
                        + [
                            (node, i + 1, -float(direction[i]))
                            for i in range(3)
                            if abs(direction[i]) > 1e-12
                        ]
                    )
                    self._spring_elements.append(
                        (next_elem, spring_node, stiffness * share)
                    )
                    next_elem += 1
                    springs.append(
                        {
                            "kind": "translation",
                            "node": node,
                            "spring_node": spring_node,
                            "position": tuple(float(v) for v in here),
                            "direction": [float(v) for v in direction],
                            "stiffness": stiffness * share,
                        }
                    )
                for axis, stiffness in rotations:
                    drilling = (
                        None
                        if node in linked
                        else self._drilling_axis(elements_at.get(node, []))
                    )
                    if drilling is not None:
                        along = abs(float(np.dot(axis, drilling)))
                        if along > 1.0 - 1e-6:
                            drilling_left_out.append(str(conn.id))
                            continue
                        if along > 1e-6:
                            raise AnalysisError(
                                f"Support {conn.id} cannot be applied: it has a "
                                "rotational spring about an axis that is neither "
                                "in the plane of the shells at node "
                                f"{node} nor across it.",
                                code="E-SUP-008",
                            )
                        arm = np.cross(axis, drilling)
                    else:
                        arm = np.array(
                            self._orthogonal_beam_normal(
                                (0.0, 0.0, 1.0), tuple(float(v) for v in axis)
                            ),
                            dtype=float,
                        )
                    arm = arm / np.linalg.norm(arm)
                    tip = new_node(here + self._HINGE_ARM * arm)
                    links.append((next_elem, node, tip))
                    linked.update((node, tip))
                    next_elem += 1
                    # The tip moves across the arm by the rotation times its
                    # length
                    across = np.cross(axis, arm)
                    spring_node = new_node(here)
                    self._spring_equations.append(
                        [(spring_node, 1, 1.0)]
                        + [
                            term
                            for i in range(3)
                            if abs(across[i]) > 1e-12
                            for term in (
                                (tip, i + 1, -float(across[i]) / self._HINGE_ARM),
                                (node, i + 1, float(across[i]) / self._HINGE_ARM),
                            )
                        ]
                    )
                    if drilling is not None:
                        # Turning about the normal swings the tip along this
                        turn = np.cross(drilling, arm)
                        pivot = int(np.argmax(np.abs(turn)))
                        order = [pivot] + [i for i in range(3) if i != pivot]
                        self._spring_equations.append(
                            [
                                (tip, i + 1, float(turn[i]))
                                for i in order
                                if abs(turn[i]) > 1e-12
                            ]
                            + [
                                (node, i + 1, -float(turn[i]))
                                for i in range(3)
                                if abs(turn[i]) > 1e-12
                            ]
                        )
                    self._spring_elements.append(
                        (next_elem, spring_node, stiffness * share)
                    )
                    next_elem += 1
                    springs.append(
                        {
                            "kind": "rotation",
                            "node": node,
                            "spring_node": spring_node,
                            "position": tuple(float(v) for v in here),
                            "direction": [float(v) for v in axis],
                            "stiffness": stiffness * share,
                            "across": [float(v) for v in across],
                            "arm_length": self._HINGE_ARM,
                        }
                    )
        self._helper_nodes = helpers
        if len(links) > len(getattr(self, "_rigid_links", [])):
            self._rigid_links = links
        self._member_node_cache = {}
        if drilling_left_out:
            names = sorted(set(drilling_left_out))
            self._warn_user(
                "W-SUP-006",
                f"{len(names)} elastic support(s) have a rotational spring about "
                "the normal of the shells they hold, which have no rotation "
                "about it: it holds nothing and is left out: "
                + ", ".join(names[:5])
                + (", ..." if len(names) > 5 else ""),
                ifc_guids=self._ifc_guids(names),
            )
        logger.info(
            f"Built {len(self._spring_elements)} springs at "
            f"{len(self._support_springs)} elastic supports"
        )

    def _write_support_springs(self, file: TextIO) -> None:
        """Write the springs of elastic supports (``_build_support_springs``).

        Each has an element set and a ``*SPRING`` card of its own, since each
        node's stiffness is its share of the support's. The spring nodes are
        held in their other two translations, which nothing else resists,
        and gathered in ``SPRING_NODES``, which every step prints.
        """
        elements = getattr(self, "_spring_elements", [])
        if not elements:
            return
        file.write("** Elastic supports: a spring on a node of its own each\n")
        for elem_id, node, stiffness in elements:
            elset = f"SPRING_{elem_id}"
            file.write(f"*ELEMENT, TYPE=SPRING1, ELSET={elset}\n{elem_id}, {node}\n")
            file.write(f"*SPRING, ELSET={elset}\n1\n{stiffness:.9e}\n")
        file.write("** What each spring resists\n")
        for terms in self._spring_equations:
            self._write_equation(file, terms)
        nodes = sorted(node for _, node, _ in elements)
        file.write("*BOUNDARY\n")
        for node in nodes:
            file.write(f"{node}, 2, 3\n")
        file.write("*NSET, NSET=SPRING_NODES\n")
        for i in range(0, len(nodes), 8):
            file.write(", ".join(map(str, nodes[i : i + 8])) + "\n")
        file.write("\n")
        self.node_sets["SPRING_NODES"] = nodes

    def _drilling_axis(self, element_ids: List[int]) -> Optional[np.ndarray]:
        """The normal of the shells at a node, if it is a node of shells alone.

        None for a node with a beam on it, or where shells meet at an angle:
        every rotation is resisted there.
        """
        normal = None
        for elem_id in element_ids:
            elem = self.elements[elem_id]
            if not str(elem.get("type", "")).startswith("S"):
                return None
            corners = [np.array(self.nodes[n], dtype=float) for n in elem["nodes"][:3]]
            cross = np.cross(corners[1] - corners[0], corners[2] - corners[0])
            size = float(np.linalg.norm(cross))
            if size < 1e-18:
                continue
            cross = cross / size
            if normal is None:
                normal = cross
            elif abs(float(normal @ cross)) < 1.0 - 1e-6:
                return None
        return normal

    @staticmethod
    def _shell_shape_values(n_nodes: int, bary: np.ndarray) -> Optional[List[float]]:
        """Shape function values of a 3- or 6-node triangle at barycentric ``bary``."""
        l1, l2, l3 = (float(v) for v in bary)
        if n_nodes == 3:
            return [l1, l2, l3]
        if n_nodes == 6:
            return [
                l1 * (2.0 * l1 - 1.0),
                l2 * (2.0 * l2 - 1.0),
                l3 * (2.0 * l3 - 1.0),
                4.0 * l1 * l2,
                4.0 * l2 * l3,
                4.0 * l3 * l1,
            ]
        return None

    def _build_line_bearings(self) -> None:
        """Tie curve members that lie in a surface member to it along their length.

        Beam and shell meshes have separate nodes and are joined only at
        connections. Analysis models commonly connect a slab at its corners
        alone and leave the beams under its edges, or a column cast into a
        wall, unconnected in between; read literally the slab then spans from
        corner to corner and the beams carry nothing.

        A curve member with two or more nodes in the mesh of one surface
        member is taken to lie in it; with one, to meet it at a point (a
        column ending on a slab or passing through it; the geometry stage
        seeds a node there in both meshes). Each of its nodes that the shell
        mesh does not already share is made to follow the shell there: its
        translations are interpolated from the nodes of the triangle it falls
        in, with that element's shape functions. Rotations are not tied, so
        a line is a hinge line and a point is a pin: the surface bears on the
        member and neither twists the other.

        A line connection of the file that joins the two (an
        ``IfcStructuralCurveConnection``) is honoured the same way, without
        the warning and whatever ``strict_connections`` says. A point where a
        connection of the file already joins them is left to that connection.

        Nodes on a rigid link are left alone, for the reason given in
        ``_write_point_connection``. With ``strict_connections`` set in the
        analysis configuration nothing is tied, and the warning says how many
        members were left unconnected. The result is stored in
        ``self._line_bearings`` as ``(node, [(shell_node, weight), ...])``.
        """
        self._line_bearings: List[Tuple[int, List[Tuple[int, float]]]] = []
        tol = self._COINCIDENT_TOL

        surfaces = []
        for member in self.domain_model.members:
            if not isinstance(member, SurfaceMember):
                continue
            member_set = f"MEMBER_{self._get_short_id(member.id)}"
            triangles = [
                self.elements[e]["nodes"]
                for e in self.element_sets.get(member_set, [])
                if e in self.elements
                and self.elements[e].get("type") in SHELL_ELEMENT_TYPES
                and len(self.elements[e]["nodes"]) in (3, 6)
            ]
            if not triangles:
                continue
            corners = np.array(
                [[self.nodes[n] for n in tri[:3]] for tri in triangles], dtype=float
            )
            flat = corners.reshape(-1, 3)
            surfaces.append(
                (
                    triangles,
                    corners,
                    flat.min(axis=0) - tol,
                    flat.max(axis=0) + tol,
                    {n for tri in triangles for n in tri},
                    member.id,
                )
            )

        # What the file itself connects: a line connection joining a curve
        # member and a surface member, and the points where two members share
        # a connection.
        explicit_lines = set()
        shared_points: Dict[Tuple[str, str], List[np.ndarray]] = {}
        for conn in self.domain_model.connections:
            ids = [m for m in conn.connected_members or []]
            position = None
            if getattr(conn, "position", None):
                try:
                    position = np.array([float(v) for v in conn.position[:3]])
                except (TypeError, ValueError):
                    position = None
            for a in ids:
                for b in ids:
                    if a == b:
                        continue
                    if getattr(conn, "edge", None):
                        explicit_lines.add((a, b))
                    if position is not None:
                        shared_points.setdefault((a, b), []).append(position)

        def locate(point: np.ndarray, corners: np.ndarray):
            """Index and barycentric coordinates of the triangle holding ``point``."""
            a = corners[:, 0]
            v0 = corners[:, 1] - a
            v1 = corners[:, 2] - a
            v2 = point - a
            normal = np.cross(v0, v1)
            area2 = np.linalg.norm(normal, axis=1)
            ok = area2 > 1e-18
            safe = np.where(ok, area2, 1.0)
            distance = np.abs(np.einsum("ij,ij->i", v2, normal)) / safe
            d00 = np.einsum("ij,ij->i", v0, v0)
            d01 = np.einsum("ij,ij->i", v0, v1)
            d11 = np.einsum("ij,ij->i", v1, v1)
            d20 = np.einsum("ij,ij->i", v2, v0)
            d21 = np.einsum("ij,ij->i", v2, v1)
            denom = np.where(ok, d00 * d11 - d01 * d01, 1.0)
            l2 = (d11 * d20 - d01 * d21) / denom
            l3 = (d00 * d21 - d01 * d20) / denom
            l1 = 1.0 - l2 - l3
            # Slack of tol along the shortest side, as a barycentric fraction
            slack = tol / np.sqrt(np.minimum(d00, d11).clip(min=1e-18))
            worst = np.minimum(np.minimum(l1, l2), l3)
            inside = ok & (distance <= tol) & (worst >= -slack)
            if not inside.any():
                return None
            best = int(np.argmax(np.where(inside, worst, -np.inf)))
            return best, np.array([l1[best], l2[best], l3[best]])

        linked_nodes = set()
        for _, node_a, node_b in getattr(self, "_rigid_links", []):
            linked_nodes.update((node_a, node_b))
        all_shell_nodes = set()
        for surface in surfaces:
            all_shell_nodes |= surface[4]

        joined = self._build_line_joints()

        strict = self.analysis_config.get_strict_connections()
        lying, meeting = set(), set()
        for member in self.domain_model.members:
            if not isinstance(member, CurveMember):
                continue
            member_set = f"MEMBER_{self._get_short_id(member.id)}"
            node_ids = sorted(
                {
                    n
                    for e in self.element_sets.get(member_set, [])
                    if e in self.elements
                    for n in self.elements[e]["nodes"]
                }
            )
            if len(node_ids) < 2:
                continue
            points = {n: np.array(self.nodes[n], dtype=float) for n in node_ids}
            lo = np.min(list(points.values()), axis=0)
            hi = np.max(list(points.values()), axis=0)

            # (node, terms, implied by geometry alone, along a line, surface)
            member_ties: List[Tuple[int, List[Tuple[int, float]], bool, bool, str]] = []
            for triangles, corners, s_lo, s_hi, shell_nodes, surface_id in surfaces:
                if (hi < s_lo).any() or (lo > s_hi).any():
                    continue
                if (member.id, surface_id) in explicit_lines:
                    continue  # a line connection of the file (_build_line_joints)
                found = 0
                ties = []
                for node, point in points.items():
                    if node in shell_nodes:
                        found += 1
                        continue
                    if (point < s_lo).any() or (point > s_hi).any():
                        continue
                    hit = locate(point, corners)
                    if hit is None:
                        continue
                    found += 1
                    weights = self._shell_shape_values(len(triangles[hit[0]]), hit[1])
                    terms = [
                        (shell_node, weight)
                        for shell_node, weight in zip(triangles[hit[0]], weights)
                        if abs(weight) > 1e-9
                    ]
                    ties.append((node, terms))
                along_a_line = found >= 2
                for node, terms in ties:
                    if not along_a_line and any(
                        float(np.linalg.norm(points[node] - p)) <= tol
                        for p in shared_points.get((member.id, surface_id), ())
                    ):
                        continue  # a connection of the file joins them here
                    member_ties.append((node, terms, True, along_a_line, surface_id))

            seen = set()
            tied_to = set(joined.get(member.id, ()))
            for node, terms, implied, along_a_line, surface_id in member_ties:
                if node in seen or node in linked_nodes or node in all_shell_nodes:
                    continue
                seen.add(node)
                if implied:
                    (lying if along_a_line else meeting).add(member.id)
                    if strict:
                        continue
                self._line_bearings.append((node, terms))
                if along_a_line:
                    tied_to.add(surface_id)
            member.tied_to_surface_members = sorted(tied_to)

        # A node shared by two members is tied once
        unique = {}
        for node, terms in self._line_bearings:
            unique.setdefault(node, terms)
        self._line_bearings = sorted(unique.items())

        # A member that both lies in one surface and meets another is reported
        # for the line only
        meeting -= lying
        if lying:
            found = (
                f"{len(lying)} curve member(s) lie in a surface member that "
                "the model does not connect to them along their length. "
            )
            if strict:
                self._warn_user(
                    "W-JNT-004",
                    found + "Strict connections were requested, so they are left "
                    "unconnected there; a slab connected only at its corners spans "
                    "between them.",
                    ifc_guids=self._ifc_guids(sorted(lying)),
                )
            else:
                self._warn_user(
                    "W-JNT-001",
                    found + "They are tied to it in translation along the line (a "
                    "hinge line), as a slab bearing on its beams. Their section "
                    "forces are what is left to them with the surface taking its "
                    "share; where force passes between the two at a point (the "
                    "end of a wall, a column in a wall) they change abruptly "
                    "from one cross-section to the next and their largest values "
                    "depend on the mesh size. Use strict connections to analyse "
                    "only the connections in the file.",
                    ifc_guids=self._ifc_guids(sorted(lying)),
                )
        if meeting:
            found = (
                f"{len(meeting)} curve member(s) meet a surface member at a point "
                "where the model has no connection. "
            )
            if strict:
                self._warn_user(
                    "W-JNT-005",
                    found + "Strict connections were requested, so they are left "
                    "unconnected there.",
                    ifc_guids=self._ifc_guids(sorted(meeting)),
                )
            else:
                self._warn_user(
                    "W-JNT-003",
                    found + "They are tied to it in translation there, as a "
                    "column bearing on or passing through a slab. Use strict "
                    "connections to analyse only the connections in the file.",
                    ifc_guids=self._ifc_guids(sorted(meeting)),
                )

    def _line_joints(self) -> List[dict]:
        """The curve and surface members the line connections of the file join.

        An ``IfcStructuralCurveConnection`` joining a beam and a slab holds
        them together along its whole length. The geometry stage meshes the
        line into the slab and the beam with the same nodes along it
        (``GmshGeometry._seed_line_joints``), so each beam node on the line
        has a node of the slab at its foot: the same point where the beam
        lies in the slab, the point the eccentricity leads to where it does
        not (a downstand beam; ``IfcRelConnectsWithEccentricity`` is drawn
        as geometry, as at points).

        Returns:
            One entry per curve and surface member joined: ``conn``,
            ``beam`` and ``plate`` (member ids), ``rigid`` (neither is
            released about the line) and ``pairs``, ``[(beam node, slab
            node), ...]``. A pair is one node where the two are merged.

        Raises:
            AnalysisError: For a line connection joining two curve members, a
                curve member that does not run along its line or lies too far
                from it, or a mesh with no slab node at a beam node's foot.
        """
        from ..analysis.boundary_condition_handling import released_rotation_axes

        tol = self._COINCIDENT_TOL
        joints: List[dict] = []
        kinds = {m.id: m for m in self.domain_model.members}

        def released_about(conn, member_id: str, direction: np.ndarray) -> bool:
            axes = released_rotation_axes(conn, member_id)
            return bool(len(axes)) and float(np.abs(axes @ direction).max()) > 0.5

        def member_nodes(member_id: str) -> List[int]:
            member_set = f"MEMBER_{self._get_short_id(member_id)}"
            return sorted(
                {
                    n
                    for e in self.element_sets.get(member_set, [])
                    if e in self.elements
                    for n in self.elements[e]["nodes"]
                }
            )

        for conn in self.domain_model.connections:
            edge = getattr(conn, "edge", None)
            members = list(conn.connected_members or [])
            if edge is None or len(members) < 2:
                continue
            beams = [m for m in members if isinstance(kinds.get(m), CurveMember)]
            plates = [m for m in members if isinstance(kinds.get(m), SurfaceMember)]
            if len(beams) > 1:
                raise AnalysisError(
                    f"Line connection {conn.id} joins curve members "
                    f"{', '.join(beams)}. Curve members can only be joined along "
                    "a line to a surface member; join them at points instead.",
                    code="E-JNT-002",
                )
            if not beams or not plates:
                continue
            start = np.array(edge[0], dtype=float)
            along = np.array(edge[1], dtype=float) - start
            length = float(np.linalg.norm(along))
            if length < 1e-9:
                continue
            along /= length
            beam_id = beams[0]
            endpoints = self._get_member_endpoints(beam_id)
            if endpoints is not None:
                axis = endpoints[1] - endpoints[0]
                if abs(float(axis @ along)) < (1.0 - 1e-3) * float(
                    np.linalg.norm(axis)
                ):
                    raise AnalysisError(
                        f"Line connection {conn.id} joins curve member {beam_id}, "
                        "which does not run along the line.",
                        code="E-JNT-002",
                    )
            on_line = []
            for node in member_nodes(beam_id):
                point = np.array(self.nodes[node], dtype=float)
                s = float((point - start) @ along)
                if s < -tol or s > length + tol:
                    continue
                foot = start + s * along
                gap = float(np.linalg.norm(foot - point))
                if gap > self._MAX_RIGID_LINK:
                    raise AnalysisError(
                        f"Line connection {conn.id}: curve member {beam_id} lies "
                        f"{gap:.2f} m from the line, too far for a rigid link.",
                        code="E-JNT-002",
                    )
                on_line.append((node, foot))
            if len(on_line) < 2:
                raise AnalysisError(
                    f"Line connection {conn.id}: curve member {beam_id} has "
                    f"{len(on_line)} node(s) along the line, so it cannot be "
                    "joined there.",
                    code="E-JNT-002",
                )

            for plate_id in plates:
                shell = member_nodes(plate_id)
                coords = np.array([self.nodes[n] for n in shell], dtype=float)
                pairs = []
                for node, foot in on_line:
                    if node in shell:
                        pairs.append((node, node))
                        continue
                    distance = np.linalg.norm(coords - foot, axis=1)
                    nearest = int(np.argmin(distance))
                    if distance[nearest] > tol:
                        raise AnalysisError(
                            f"Line connection {conn.id}: the mesh of surface "
                            f"member {plate_id} has no node at "
                            f"({foot[0]:.3f}, {foot[1]:.3f}, {foot[2]:.3f}), "
                            f"the foot of a node of {beam_id}. Is the line in "
                            "the surface?",
                            code="E-JNT-002",
                        )
                    pairs.append((node, shell[nearest]))
                joints.append(
                    {
                        "conn": conn,
                        "beam": beam_id,
                        "plate": plate_id,
                        "rigid": not (
                            released_about(conn, beam_id, along)
                            or released_about(conn, plate_id, along)
                        ),
                        "pairs": pairs,
                    }
                )
        return joints

    def _build_line_joints(self) -> Dict[str, set]:
        """Hinge curve and surface members along the line connections of the file.

        Rigid joints are made by ``_merge_rigid_connection_nodes``: the beam
        and slab nodes on the line become one, or a rigid link joins them,
        and CalculiX makes a knot of each. Where either member is released
        about the line, each beam node is tied to the slab node at its foot
        in translation: a row of ball joints, which is a hinge about the
        line. An eccentric beam is carried to the slab by a rigid link
        first, so the hinge is where the line is.

        Returns:
            ``{curve member id: {surface member id, ...}}`` for every pair the
            file joins along a line, rigidly or not.
        """
        joined: Dict[str, set] = {}
        links = list(getattr(self, "_rigid_links", []))
        helpers = set(getattr(self, "_helper_nodes", set()))
        next_node = max(self.nodes.keys(), default=0) + 1
        next_elem = (
            max(
                [max(self.elements.keys(), default=0)]
                + [elem_id for elem_id, _, _ in links]
            )
            + 1
        )
        for joint in self._line_joints():
            joined.setdefault(joint["beam"], set()).add(joint["plate"])
            if joint["rigid"]:
                continue
            for node, shell_node in joint["pairs"]:
                if node == shell_node:
                    continue
                gap = float(
                    np.linalg.norm(
                        np.array(self.nodes[node]) - np.array(self.nodes[shell_node])
                    )
                )
                anchor = node
                if gap > self._COINCIDENT_TOL:
                    anchor = next_node
                    self.nodes[anchor] = self.nodes[shell_node]
                    helpers.add(anchor)
                    links.append((next_elem, node, anchor))
                    next_node += 1
                    next_elem += 1
                self._line_bearings.append((anchor, [(shell_node, 1.0)]))
        if len(links) > len(getattr(self, "_rigid_links", [])):
            self._rigid_links = links
            self._member_node_cache = {}
        self._helper_nodes = helpers
        return joined

    @staticmethod
    def _write_equation(file: TextIO, terms: List[Tuple[int, int, float]]) -> None:
        """Write one ``*EQUATION``; CalculiX takes at most four terms per line."""
        write_equation(file, terms)

    def _note_equation_nodes(self, nodes) -> None:
        """Remember the nodes of an equation just written (see line bearings)."""
        self._equation_nodes.update(nodes)

    def _note_translation_tie(self, node: int, other: int) -> None:
        """Remember that an equation ties two nodes at one point together.

        Those ties are what ``write_boundary_conditions`` follows to find the
        nodes whose force arrives at a support. Tips of arms are not at the
        point they serve, and the arm's elements carry their force.
        """
        helpers = getattr(self, "_helper_nodes", set())
        if node not in helpers and other not in helpers:
            self._translation_ties.append((node, other))

    def _write_line_bearings(
        self, file: TextIO, constrained_node_dofs: set, bc_node_dofs: set
    ) -> None:
        """Write the ties prepared by ``_build_line_bearings``.

        Written after every other equation, and only for nodes that none of
        them mentions, so a tied node never ends up depending on itself.

        A tie that would lean on a restrained shell node is left out. CalculiX
        reports the force such a tie carries at the tied node, not at the
        support, so it would go missing from the reactions; and next to a
        support the member needs no help.
        """
        bearings = getattr(self, "_line_bearings", [])
        if not bearings:
            return
        used = getattr(self, "_equation_nodes", set())
        supported = bc_node_dofs | getattr(self, "_supported_node_dofs", set())
        file.write("** Curve members bearing on the surface member they lie in\n")
        for node, terms in bearings:
            if node in used:
                continue
            for dof in (1, 2, 3):
                if (node, dof) in constrained_node_dofs:
                    continue
                if any((n, dof) in supported for n, _ in terms):
                    continue
                self._write_equation(
                    file,
                    [(node, dof, 1.0)] + [(n, dof, -weight) for n, weight in terms],
                )
                constrained_node_dofs.add((node, dof))
        file.write("**\n")

    def _curve_members_joined_by_the_mesh(self) -> Dict[Tuple[str, str], int]:
        """Curve members that share a node where no connection joins them.

        Curves that touch are meshed with one node at that point (a beam
        ending on the span of another, two that cross), and a shared node is
        a rigid joint. Where a connection of the file joins the two, it says
        how; where none does, the joint is the mesh's alone.

        Returns:
            ``{(member id, member id): node}``, each pair once with its ids
            in order, and the first node the two share.
        """
        joined_by_the_file = set()
        for conn in self.domain_model.connections:
            attached = list(conn.connected_members or [])
            joined_by_the_file.update((a, b) for a in attached for b in attached)

        members_at: Dict[int, List[str]] = {}
        for member in self.domain_model.members:
            if not isinstance(member, CurveMember):
                continue
            member_set = f"MEMBER_{self._get_short_id(member.id)}"
            nodes = {
                node
                for element in self.element_sets.get(member_set, [])
                if element in self.elements
                for node in self.elements[element]["nodes"]
            }
            for node in nodes:
                members_at.setdefault(node, []).append(member.id)

        pairs: Dict[Tuple[str, str], int] = {}
        for node in sorted(members_at):
            sharing = sorted(members_at[node])
            for i, a in enumerate(sharing):
                for b in sharing[i + 1 :]:
                    if (a, b) not in joined_by_the_file:
                        pairs.setdefault((a, b), node)
        return pairs

    def _curve_members_on_surfaces(self) -> Set[str]:
        """Curve members the mesh ties to a surface member.

        By a node they share (a line joint merged into the slab) or a line
        bearing at one of their nodes (``_build_line_bearings``: a beam lying
        in a slab, a column meeting one). Connections of the file between a
        curve and a surface member are not looked for here.
        """
        shell_nodes = {
            node
            for element in self.elements.values()
            if element.get("type") in SHELL_ELEMENT_TYPES
            for node in element["nodes"]
        }
        tied = shell_nodes | {node for node, _ in getattr(self, "_line_bearings", [])}
        found = set()
        for member in self.domain_model.members:
            if not isinstance(member, CurveMember):
                continue
            member_set = f"MEMBER_{self._get_short_id(member.id)}"
            if any(
                node in tied
                for element in self.element_sets.get(member_set, [])
                if element in self.elements
                for node in self.elements[element]["nodes"]
            ):
                found.add(member.id)
        return found

    def _mesh_joints(self) -> List[Tuple[str, str, np.ndarray]]:
        """``_curve_members_joined_by_the_mesh`` with where each joint is."""
        return [
            (a, b, np.array(self.nodes[node], dtype=float))
            for (a, b), node in self._curve_members_joined_by_the_mesh().items()
        ]

    def _report_joints_made_by_the_mesh(self) -> None:
        """Say where curve members are joined with no connection in the file."""
        pairs = self._curve_members_joined_by_the_mesh()
        if not pairs:
            return
        # Name the member that ends there, which is the one to look at
        named: List[str] = []
        for (a, b), node in pairs.items():
            point = np.array(self.nodes[node], dtype=float)
            ending = []
            for member_id in (a, b):
                endpoints = self._get_member_endpoints(member_id)
                if endpoints is not None and any(
                    float(np.linalg.norm(point - end)) <= self._COINCIDENT_TOL
                    for end in endpoints
                ):
                    ending.append(member_id)
            for member_id in ending or [a, b]:
                if member_id not in named:
                    named.append(member_id)
        self._warn_user(
            "W-JNT-002",
            f"Curve members touch at {len(pairs)} place(s) where the model has no "
            "connection between them (a member ending on the span of another, "
            "or two that cross). They are meshed with one node there, which "
            "joins them rigidly, with strict connections as well: "
            f"{', '.join(named[:5])}{' ...' if len(named) > 5 else ''}",
            ifc_guids=self._ifc_guids(named),
        )

    def _hold_spinning_members(self) -> None:
        """Hold in torsion the members nothing stops spinning about their axis.

        A beam on two pinned supports, each restraining the three translations
        and no rotation, is free to turn about its own axis. That is how a
        simply supported beam is usually described, and it is a mechanism:
        the solver returns an arbitrary rotation, which shows up in the
        displacements of the section's faces (a 0.3 m beam came out with more
        than twice its deflection).

        A member counts as held when a support restrains rotation about its
        axis, or when it joins a member that is not in line with it without a
        torsional release: turning it would bend that one. So does one that
        shares a mesh node with such a member where no connection joins them
        (``_curve_members_joined_by_the_mesh``; the secondary beams of
        ``building_02`` end on the spans of its girders, were reported as
        free to spin, and are not). A member in line
        with it holds nothing by itself. The two turn together, so members
        joined end to end in a straight line are one run, held when any of
        them is (two members on ball supports once each counted as held by
        the other: 13 mm of deflection for 7.6, and nothing said).

        A run that is not held gets that rotation restrained at one of its
        supports, at an end of the run if it has one there, and the user is
        told. Along a global axis that is a ``*BOUNDARY`` on the rotation.
        Along any other (a rafter, a brace) the support is given the rotation
        to hold (``torsion_hold_axes``), and holds it as a skew support does,
        with a stiff arm (``_build_support_arms``). A run with no support of
        its own is only reported; so is a skew one whose supports are line
        supports, or in a model with U1 members, where arms cannot be used.
        """
        from ..analysis.boundary_condition_handling import (
            released_rotation_axes,
            share_in_span,
            support_resistance,
        )

        self._torsion_holds: List[Tuple[Any, str, int]] = []
        self._spin_arm_equations: List[List[Tuple[int, int, float]]] = []
        for conn in self.domain_model.connections:
            conn.torsion_hold_axes = []
        # In a plane structure held in its plane, a member's rotations about
        # the two axes of the plane are both zero, so both can be held where
        # it spins: about an axis that is not a global one too. Preferably at
        # an end where it is pinned, where no bending moment is disturbed.
        # (Held at a node inside a member in bending, they stiffened it by
        # 3 %: CalculiX's restraint of a beam node's rotation is approximate.)
        plane = getattr(self, "_plane_normal", None)
        if plane is not None:
            from ..analysis.plane_structure import global_axis, spinning_members

            axis = global_axis(plane)
            for conn, member_id in spinning_members(
                self.domain_model, plane, self._mesh_joints()
            ):
                if axis is None:
                    self._build_spin_arms(conn, member_id, plane)
                    continue
                for dof in (4 + i for i in range(3) if i != axis):
                    self._torsion_holds.append((conn, member_id, dof))
            return

        directions: Dict[str, np.ndarray] = {}
        for member in self.domain_model.members:
            if not isinstance(member, CurveMember) or member.id in self._u1_members:
                continue
            endpoints = self._get_member_endpoints(member.id)
            if endpoints is None:
                continue
            axis = endpoints[1] - endpoints[0]
            length = float(np.linalg.norm(axis))
            if length < 1e-12:
                continue
            directions[member.id] = axis / length

        def turns_with(conn, member_id: str, axis=None) -> bool:
            """Whether the member passes rotation about ``axis`` on there.

            ``axis`` is the member's own by default: its torsion.
            """
            if conn.entity_type == "hinge" and len(conn.connected_members) > 1:
                return False
            if axis is None:
                axis = directions[member_id]
            released = released_rotation_axes(conn, member_id)
            # An axis counts when it has a share in rotation about the member
            return not (len(released) and np.abs(released @ axis).max() > 0.5)

        # The run each member belongs to, and the runs something holds
        run_of = {member_id: member_id for member_id in directions}

        def run(member_id: str) -> str:
            while run_of[member_id] != member_id:
                member_id = run_of[member_id]
            return member_id

        connections_of: Dict[str, list] = {member_id: [] for member_id in directions}
        restrained = set()
        for conn in self.domain_model.connections:
            attached = list(conn.connected_members or [])
            restraint = support_resistance(conn)
            for member_id in attached:
                if member_id not in directions:
                    continue
                connections_of[member_id].append(conn)
                if not turns_with(conn, member_id):
                    continue
                direction = directions[member_id]
                if (
                    restraint is not None
                    and share_in_span(restraint[1], direction) > 0.5
                ):
                    restrained.add(member_id)
                for other in attached:
                    if other == member_id:
                        continue
                    in_line = (
                        other in directions
                        and abs(float(directions[other] @ direction)) > 1.0 - 1e-6
                    )
                    if not in_line:
                        # A surface it is joined to along a line holds it
                        # unless the surface is hinged about that line
                        if getattr(conn, "edge", None) is None or turns_with(
                            conn, other, direction
                        ):
                            restrained.add(member_id)
                    elif turns_with(conn, other):
                        run_of[run(other)] = run(member_id)

        # Members the mesh joins where the file has no connection share a
        # node, which passes torsion on as a rigid joint of the file does
        for a, b in self._curve_members_joined_by_the_mesh():
            if a not in directions or b not in directions:
                continue
            if abs(float(directions[a] @ directions[b])) > 1.0 - 1e-6:
                run_of[run(a)] = run(b)
            else:
                restrained.update((a, b))

        grouped: Dict[str, List[str]] = {}
        for member_id in directions:
            if connections_of[member_id]:
                grouped.setdefault(run(member_id), []).append(member_id)
        runs = list(grouped.values())

        def supports_of(members: List[str]) -> list:
            """Where a run can be held: ``(members there, support, member)``.

            A support that holds nothing but members of the run, an end of
            the run before a joint inside it.
            """
            supports = []
            for member_id in members:
                for conn in connections_of[member_id]:
                    restraint = support_resistance(conn)
                    if restraint is None or not (
                        len(restraint[0]) or len(restraint[1])
                    ):
                        continue
                    attached = list(conn.connected_members or [])
                    if set(attached) <= set(members):
                        supports.append((len(attached), conn, member_id))
            axis = np.abs(directions[members[0]])
            aligned = [i for i in range(3) if axis[i] > 1.0 - 1e-6]
            if not aligned:
                # An arm at every node of a line support would be many holds
                supports = [
                    found
                    for found in supports
                    if getattr(found[1], "edge", None) is None and not self._u1_members
                ]
            return supports

        held: List[str] = []
        loose: List[str] = []
        held_runs: List[int] = []

        def hold(index: int) -> None:
            members = runs[index]
            supports = supports_of(members)
            if not supports:
                loose.extend(members)
                return
            _, conn, member_id = min(supports, key=lambda found: found[0])
            axis = np.abs(directions[members[0]])
            aligned = [i for i in range(3) if axis[i] > 1.0 - 1e-6]
            if aligned and getattr(conn, "edge", None) is not None:
                # At one node of the line, not every node along it
                self._torsion_holds.append((conn, member_id, 4 + aligned[0]))
            else:
                conn.torsion_hold_axes.append(
                    [float(v) for v in directions[members[0]]]
                )
            held.extend(members)
            held_runs.append(index)

        for index, members in enumerate(runs):
            if not restrained.intersection(members):
                hold(index)

        # A member across may give way itself: count what is still free with
        # every member and joint a rigid body (aiz.79)
        from ..analysis.spinning import free_runs

        checked = [i for i, members in enumerate(runs) if restrained & set(members)]
        if checked:
            free = free_runs(
                self.domain_model,
                directions,
                runs,
                held=held_runs,
                grounded=self._curve_members_on_surfaces(),
                mesh_joints=self._mesh_joints(),
                preferred={i for i in checked if supports_of(runs[i])},
            )
            for index in free:
                if index in checked:
                    hold(index)

        if held:
            self._warn_user(
                "W-SUP-001",
                f"{len(held)} member(s) are free to spin about their own axis: no "
                "support or joint restrains that rotation. Each, or the straight "
                "run of members it is part of, is held in torsion at one of its "
                "supports so that the results are "
                f"defined: {', '.join(held[:5])}{' ...' if len(held) > 5 else ''}",
                ifc_guids=self._ifc_guids(held),
            )
        if loose:
            self._warn_user(
                "W-SUP-004",
                f"{len(loose)} member(s) are free to spin about their own axis and "
                "could not be held automatically; their displacements include "
                f"an arbitrary rotation: {', '.join(loose[:5])}"
                f"{' ...' if len(loose) > 5 else ''}",
                ifc_guids=self._ifc_guids(loose),
            )

    def _build_spin_arms(self, conn, member_id: str, normal: np.ndarray) -> None:
        """Hold a member's rotations about the axes of a skew plane at a joint.

        What ``*BOUNDARY`` on two rotations does in a plane parallel to two
        global axes: a stiff arm across the plane on each of the member's
        nodes there, its tip tied to the node in both directions of the
        plane. The tip of an arm along the normal moves by ``rotation x
        normal``, so that stops the rotations about the axes in the plane and
        leaves the one about the normal, the structure's own, free.

        Stored in ``self._spin_arm_equations``, written with the members
        held against spinning.
        """
        from ..analysis.boundary_condition_handling import _reduce, _terms
        from ..analysis.plane_structure import in_plane_axes

        links = list(getattr(self, "_rigid_links", []))
        helpers = set(getattr(self, "_helper_nodes", set()))
        next_node = max(self.nodes.keys(), default=0) + 1
        next_elem = (
            max(
                [max(self.elements.keys(), default=0)]
                + [elem_id for elem_id, _, _ in links]
            )
            + 1
        )
        rows, pivots = _reduce(in_plane_axes(normal))
        for _, node in self._find_connection_nodes_at_location(conn, [member_id]):
            tip = tuple(
                float(v)
                for v in np.array(self.nodes[node], dtype=float)
                + self._HINGE_ARM * np.array(normal, dtype=float)
            )
            self.nodes[next_node] = tip
            helpers.add(next_node)
            links.append((next_elem, node, next_node))
            for row, pivot in zip(rows, pivots):
                self._spin_arm_equations.append(
                    _terms(next_node, row, pivot) + _terms(node, -row, pivot)
                )
            next_node += 1
            next_elem += 1
        self._rigid_links = links
        self._helper_nodes = helpers
        self._member_node_cache = {}

    def _hold_plane_structure(self) -> None:
        """Hold a plane truss or frame that nothing keeps in its plane.

        A structure drawn and loaded in one plane is often supported as its
        textbook picture is: in the plane only, with pinned joints. In three
        dimensions that is a mechanism. The solver still answers, with the
        right member forces and displacements that include whatever the
        mechanism does (a truss supported in X and Z only came out with 19
        times its deflection).

        When the model is a plane structure (``plane_normal()``) and can move
        out of its plane without straining (``out_of_plane_freedoms()``),
        every node is held across the plane, and the user is told. Members
        that could still spin about their own axis are then held by
        ``_hold_spinning_members``. Nothing in the plane changes: a plane
        structure loaded in its plane has no reason to leave it. Linear static
        analysis only; holding a model in its plane would take the buckling
        modes out of it.
        """
        from ..analysis.plane_structure import (
            AXIS_NAMES,
            describe_plane,
            global_axis,
            out_of_plane_freedoms,
            plane_normal,
        )

        self._plane_normal: Optional[np.ndarray] = None
        if self.analysis_config.get_analysis_type() != "linear_static":
            return
        if self._u1_members:
            return
        gravity = (
            self.analysis_config.get_gravity_direction()
            if self.analysis_config.get_gravity()
            else None
        )
        normal = plane_normal(self.domain_model, gravity)
        if normal is None:
            return
        freedoms = out_of_plane_freedoms(self.domain_model, normal, self._mesh_joints())
        if not freedoms:
            return
        self._plane_normal = normal
        axis = global_axis(normal)
        held = f"along {AXIS_NAMES[axis]}" if axis is not None else "across the plane"
        self._warn_user(
            "W-SUP-002",
            f"The model is a plane structure: every member lies in a plane "
            f"{describe_plane(normal)} and every load acts in it. Nothing "
            f"holds it there ({freedoms} movement(s) out of the plane are "
            "unrestrained), so it is analysed as a plane frame: every node is "
            f"held {held}, and members free to spin about their own axis are "
            "held against it. Forces and displacements in the plane are not "
            "affected.",
        )

    def _plane_hold_dofs(self) -> List[Tuple[int, int]]:
        """The ``(node, dof)`` restraints decided by ``_hold_plane_structure``,
        in a plane parallel to two global axes (``_plane_hold_equations`` in
        any other)."""
        from ..analysis.plane_structure import global_axis

        normal = getattr(self, "_plane_normal", None)
        if normal is None or global_axis(normal) is None:
            return []
        return [(node, global_axis(normal) + 1) for node in self._plane_held_nodes()]

    def _plane_held_nodes(self) -> List[int]:
        """The nodes of the elements and links, which a plane hold holds."""
        nodes: set = set()
        for element in self.elements.values():
            nodes.update(element["nodes"])
        for _, node_a, node_b in getattr(self, "_rigid_links", []):
            nodes.update((node_a, node_b))
        return sorted(nodes)

    def _plane_hold_equations(
        self, bc_node_dofs: set, held: Dict[int, List[np.ndarray]]
    ) -> List[List[Tuple[int, int, float]]]:
        """The equations that hold every node across a skew plane.

        Each node's translation along the normal is zero: an equation between
        its three translations, with the one the normal has most of
        dependent, unless a restraint or another support's equation has it
        already. What a support restrains is put in (it is zero, or the
        dependent term of the support's equation is replaced by the others),
        so that no equation depends on another's dependent term, and a node
        whose support holds it across the plane already is left out. Arm and
        hinge tips are left out too: their own arms carry them with the
        nodes they are fixed to.

        Args:
            bc_node_dofs: The ``(node, dof)`` pairs restrained or dependent
                so far; the dependent term of each equation is added.
            held: The translations each support node is held in, as the
                reduced rows of ``support_restraint``, from every support at
                the node.
        """
        from ..analysis.boundary_condition_handling import _reduce, share_in_span
        from ..analysis.plane_structure import global_axis

        normal = getattr(self, "_plane_normal", None)
        if normal is None or global_axis(normal) is not None:
            return []
        normal = np.array(normal, dtype=float)
        helpers = getattr(self, "_helper_nodes", set())
        equations = []
        for node in self._plane_held_nodes():
            if node in helpers:
                continue
            row = normal.copy()
            rows = held.get(node, [])
            if rows:
                stacked = np.vstack(rows)
                if share_in_span(stacked, normal) > 1.0 - 1e-9:
                    continue
                for support_row, pivot in zip(*_reduce(stacked)):
                    row = row - row[pivot] * support_row
            row[np.abs(row) < 1e-12] = 0.0
            free = [
                i
                for i in range(3)
                if row[i] != 0.0 and (node, i + 1) not in bc_node_dofs
            ]
            if not free:
                continue
            pivot = max(free, key=lambda i: abs(row[i]))
            order = [pivot] + [i for i in range(3) if i != pivot and row[i] != 0.0]
            terms = [(node, i + 1, float(row[i] / row[pivot])) for i in order]
            equations.append(terms)
            bc_node_dofs.add((node, pivot + 1))
        return equations

    def _torsion_hold_dofs(self) -> List[Tuple[int, int]]:
        """The ``(node, dof)`` restraints decided by ``_hold_spinning_members``."""
        holds = []
        for conn, member_id, dof in getattr(self, "_torsion_holds", []):
            for _, node in self._find_connection_nodes_at_location(conn, [member_id]):
                holds.append((node, dof))
        return holds

    def _rigid_link_groups(self) -> Dict[int, int]:
        """Map each node on a rigid link to a label shared by all nodes linked to it."""
        groups: Dict[int, int] = {}
        for _, node_a, node_b in getattr(self, "_rigid_links", []):
            label = min(groups.get(node_a, node_a), groups.get(node_b, node_b))
            for node, old_label in list(groups.items()):
                if old_label in (groups.get(node_a), groups.get(node_b)):
                    groups[node] = label
            groups[node_a] = groups[node_b] = label
        return groups

    def _write_rigid_links(self, file: TextIO) -> None:
        """Write the stiff B31 elements: links, arms and knot links.

        They are kept out of ``self.elements`` and ``EALL`` so they carry no
        self-weight and belong to no member.
        """
        links = [
            (elem_id, a, b, self._RIGID_LINK_SIDE, "RIGID_LINK")
            for elem_id, a, b in getattr(self, "_rigid_links", [])
        ] + [
            (elem_id, a, b, self._KNOT_LINK, "KNOT_LINK")
            for elem_id, a, b in getattr(self, "_knot_links", [])
        ]
        if not links:
            return
        file.write("** Rigid links bridging member ends to their joints\n")
        # Links weigh nothing. Saying so keeps CalculiX from warning, in
        # every step with self-weight, that the material has no density
        file.write("*MATERIAL, NAME=MAT_RIGID_LINK\n*DENSITY\n0.\n*ELASTIC\n")
        file.write(f"{self._RIGID_LINK_MODULUS:.6e}, 0.3\n\n")
        for elem_id, node_a, node_b, side, name in links:
            axis = np.array(self.nodes[node_b]) - np.array(self.nodes[node_a])
            normal = self._orthogonal_beam_normal((0.0, 0.0, 1.0), tuple(axis))
            elset = f"{name}_{elem_id}"
            file.write(f"*ELEMENT, TYPE=B31, ELSET={elset}\n")
            file.write(f"{elem_id}, {node_a}, {node_b}\n")
            file.write(
                f"*BEAM SECTION, ELSET={elset}, MATERIAL=MAT_RIGID_LINK,"
                " SECTION=RECT\n"
            )
            file.write(f"{side:.6e}, {side:.6e}\n")
            file.write(f"{normal[0]:.6e}, {normal[1]:.6e}, {normal[2]:.6e}\n")
        file.write("\n")

    def _write_connections(self, file: TextIO, bc_node_dofs: set) -> None:
        """
        Write structural connections as CalculiX constraints.

        Connections between members are implemented as:
        - Point connections: *KINEMATIC coupling (rigid connection)
        - Hinge connections: Boundary conditions (handled elsewhere)
        - Spring connections: *SPRING elements (future)

        Uses hierarchical constraint approach to avoid conflicts when nodes
        are shared between multiple connections or have boundary conditions.

        Args:
            file: Output file handle
            bc_node_dofs: Set of (node_id, dof) tuples that have boundary conditions
        """
        self._equation_nodes: set = set()
        self._translation_ties: List[Tuple[int, int]] = []
        if not self.domain_model.connections:
            logger.debug("No connections to write")
            self._write_line_bearings(file, set(bc_node_dofs), bc_node_dofs)
            return

        file.write("**\n")
        file.write("** ========================================\n")
        file.write("** STRUCTURAL CONNECTIONS\n")
        file.write("** ========================================\n")
        file.write("**\n\n")

        connections_written = 0

        # Track which (node, DOF) pairs are already constrained as dependent
        # to avoid CalculiX errors:
        # - "DOF detected on dependent side of two different MPC's"
        # - "DOF detected on dependent side of a MPC and a SPC"
        constrained_node_dofs = set(bc_node_dofs)  # Start with boundary condition DOFs

        self._write_edge_hinges(file, constrained_node_dofs)

        for conn in self.domain_model.connections:
            # A connection holding one member is a support, not a joint
            real_members = list(conn.connected_members)
            if len(real_members) < 2:
                logger.debug(
                    f"Skipping connection {conn.id} - only {len(real_members)} real members (boundary condition)"
                )
                continue
            if getattr(conn, "edge", None) is not None:
                # Joined along the line: surfaces by their shared edge nodes
                # (_release_hinged_edges), a curve member and a surface by
                # _build_line_joints
                continue

            # Get connection type
            if conn.entity_type in ("point", "rigid"):
                released = getattr(conn, "released_dofs_by_member", {})
                self._write_point_connection(
                    file,
                    conn,
                    real_members,
                    constrained_node_dofs,
                    released_dofs_by_member=released,
                )
                connections_written += 1
            elif conn.entity_type == "hinge":
                # Legacy hinge: release all rotation DOFs for all real members.
                released = {mid: [4, 5, 6] for mid in real_members}
                self._write_point_connection(
                    file,
                    conn,
                    real_members,
                    constrained_node_dofs,
                    released_dofs_by_member=released,
                )
                connections_written += 1
            else:
                # A spring joint between members, or a type of a model built
                # by hand: leaving it out would analyse members apart
                raise AnalysisError(
                    f"Connection {conn.id} joins {len(real_members)} members "
                    f"as a '{conn.entity_type}' connection, which cannot be "
                    "modelled; the members would be analysed apart.",
                    code="E-JNT-004",
                    ifc_guids=self._ifc_guids([conn.id, *real_members]),
                )

        self._write_line_bearings(file, constrained_node_dofs, bc_node_dofs)
        self._warn_partial_releases()

        logger.info(f"Wrote {connections_written} structural connections")

    def _warn_partial_releases(self) -> None:
        """One W-JNT-007 for partial releases analysed as full pins.

        A member released about some rotations at a joint has the others
        taken away again by a release hinge (``_build_release_hinges``),
        except a U1 member, which has none: it is tied in translation only
        and released about all three.
        """
        hinges = getattr(self, "_release_hinges", None)
        hinges = hinges if isinstance(hinges, dict) else {}
        partial: List[Tuple[str, str]] = []
        for conn in self.domain_model.connections:
            if len(conn.connected_members) < 2 or conn.entity_type == "hinge":
                continue
            if getattr(conn, "edge", None) is not None:
                continue
            released = getattr(conn, "released_dofs_by_member", None) or {}
            for member_id, dofs in released.items():
                if member_id in hinges.get(conn.id, {}):
                    continue
                if dofs and not {4, 5, 6}.issubset(set(dofs)):
                    partial.append((conn.id, member_id))
        if not partial:
            return
        self._warn_user(
            "W-JNT-007",
            f"{len(partial)} member end(s) are released about some rotations "
            "only, which cannot be represented there; they are analysed as "
            "pins, released about all three. The first are "
            f"{', '.join(f'{m} at {c}' for c, m in partial[:5])}.",
            ifc_guids=self._ifc_guids(
                list(dict.fromkeys([c for c, _ in partial] + [m for _, m in partial]))
            ),
        )

    def _write_point_connection(
        self,
        file: TextIO,
        conn,
        member_ids: List[str],
        constrained_node_dofs: set,
        released_dofs_by_member: Optional[dict] = None,
    ) -> None:
        """
        Write a point connection using CalculiX *EQUATION constraints.

        Couples translations (DOF 1-3) only, which makes a pin. Members that
        are rigidly connected share a single node before this is called (see
        ``_merge_rigid_connection_nodes``) and need no equations.

        Args:
            file: Output file handle
            conn: Connection object
            member_ids: List of member IDs
            constrained_node_dofs: Set of (node_id, dof) tuples already constrained
            released_dofs_by_member: Dict mapping member IFC GlobalId → list of
                released CalculiX DOF numbers (4, 5, 6).  None or {} = rigid.
        """
        # Find (member_id, node_id) pairs at the connection point
        connection_pairs = self._find_connection_nodes_at_location(conn, member_ids)

        if len(connection_pairs) < 2:
            if len(connection_pairs) == 1:
                _, sole_node = connection_pairs[0]
                logger.debug(
                    f"Connection {conn.id}: single shared node {sole_node}, no equations needed"
                )
            else:
                raise MeshingError(
                    f"The mesh has no node of members {', '.join(member_ids)} "
                    f"at connection {conn.id}, so it joins nothing.",
                    code="E-JNT-001",
                    ifc_guids=self._ifc_guids([conn.id, *member_ids]),
                )
            return

        released = released_dofs_by_member or {}
        any_released = any(released.values())
        conn_type = "PARTIAL_HINGE" if any_released else "RIGID"
        file.write(f"** {conn_type} Connection: {conn.id}\n")
        file.write(
            f"** Connects {len(member_ids)} members at {len(connection_pairs)} nodes\n"
        )

        # Members whose release hinge was prepared by _build_release_hinges
        hinges = getattr(self, "_release_hinges", None)
        hinges = hinges.get(conn.id, {}) if isinstance(hinges, dict) else {}
        for equations in hinges.values():
            for terms in equations:
                node, dof, _ = terms[0]
                if (node, dof) in constrained_node_dofs:
                    continue
                self._write_equation(file, terms)
                constrained_node_dofs.add((node, dof))
                self._note_equation_nodes(n for n, _, _ in terms)
                if len(terms) == 2 and terms[0][1] == terms[1][1] and dof <= 3:
                    self._note_translation_tie(node, terms[1][0])
        connection_pairs = [
            (m, n)
            for m, n in self._find_connection_nodes_at_location(
                conn, [m for m in member_ids if m not in hinges]
            )
        ]
        if not connection_pairs:
            file.write("**\n")
            return

        _, ref_node = connection_pairs[0]

        equations_written = 0
        equations_skipped = 0

        def _write_eq(node, dof, ref):
            nonlocal equations_written, equations_skipped
            if (node, dof) in constrained_node_dofs:
                logger.debug(
                    f"Connection {conn.id}: Skipping node {node} DOF {dof} (already constrained)"
                )
                equations_skipped += 1
                return
            file.write("*EQUATION\n2\n")
            file.write(f"{node},{dof},1.0,{ref},{dof},-1.0\n")
            constrained_node_dofs.add((node, dof))
            self._note_equation_nodes((node, ref))
            self._note_translation_tie(node, ref)
            equations_written += 1

        # Translations (DOF 1-3): couple all nodes to ref_node, except a node
        # that a rigid link already joins to it. The two ends of a link are
        # apart, so tying their translations as well would stop the joint
        # rotating and clamp whatever is attached to it.
        linked = self._rigid_link_groups()
        for dof in [1, 2, 3]:
            for _, node in connection_pairs[1:]:
                if node in linked and linked[node] == linked.get(ref_node):
                    continue
                _write_eq(node, dof, ref_node)

        # Rotations are not coupled here. CalculiX ignores *EQUATION on DOF 4-6
        # of beam and shell nodes, so a member reaching this point through a
        # separate node is pinned. Members meant to be rigid already share one
        # node (_merge_rigid_connection_nodes); what is left are members with
        # an end release, and a partial release with no hinge is reported by
        # _warn_partial_releases.

        if equations_skipped > 0:
            logger.info(
                f"Connection {conn.id}: Wrote {equations_written} equations, skipped {equations_skipped} (shared nodes)"
            )

        file.write("**\n")

    def _get_member_endpoints(self, member_id: str):
        """
        Return (start, end) numpy arrays for a curve member's geometry endpoints.

        Returns None if the member has no usable geometry (surface members,
        missing geometry, etc.).  Results are cached per member_id.
        """
        if not hasattr(self, "_member_endpoint_cache"):
            self._member_endpoint_cache = {}

        if member_id not in self._member_endpoint_cache:
            member = self.domain_model.get_member(member_id)
            endpoints = None
            if (
                member is not None
                and not isinstance(member, SurfaceMember)
                and hasattr(member, "geometry")
                and member.geometry
            ):
                geom = member.geometry
                if isinstance(geom, (list, tuple)) and len(geom) >= 2:
                    try:
                        start = np.array([float(v) for v in geom[0]])
                        end = np.array([float(v) for v in geom[-1]])
                        if start.shape == (3,) and end.shape == (3,):
                            endpoints = (start, end)
                    except (TypeError, ValueError):
                        pass
            self._member_endpoint_cache[member_id] = endpoints

        return self._member_endpoint_cache[member_id]

    def _find_connection_nodes_at_location(
        self, conn, member_ids: List[str]
    ) -> List[Tuple[str, int]]:
        """
        Find the nearest mesh node to the connection position for each member.

        Uses member geometry (from the domain model) to pinpoint the point of
        each curve member closest to the connection: an end, or a point along
        its span.  A mesh node is expected there, so a tight 10 mm tolerance
        is used.  Falls back to a loose 0.5 m proximity search when geometry
        is unavailable (e.g. surface members).

        Args:
            conn: Connection with .position attribute [x,y,z]
            member_ids: List of member IDs to search

        Returns:
            List of (member_id, node_id) pairs — one per member that has an
            element set.  The member_id is the domain member identifier and is
            used to look up per-member end-release DOFs.
        """
        conn_pos = None
        if hasattr(conn, "position") and conn.position:
            pos = conn.position
            if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                conn_pos = np.array([float(pos[0]), float(pos[1]), float(pos[2])])

        if conn_pos is None:
            raise MeshingError(
                f"Connection {conn.id} has no position, so the nodes it joins "
                "cannot be found.",
                code="E-SUP-003",
            )

        # Build member node sets lazily (cached for repeated lookups)
        if not hasattr(self, "_member_node_cache"):
            self._member_node_cache = {}

        # Tight tolerance for matching a mesh node at a known geometry endpoint.
        # Gmsh places nodes exactly at geometry points, so 10 mm is very generous.
        _TIGHT_TOL = 1e-2
        # Fallback when no geometry is available.
        _LOOSE_TOL = 0.5

        seen_nodes: set = set()
        connection_pairs: list = []  # List[Tuple[str, int]]
        for member_id in member_ids:
            short_id = self._get_short_id(member_id)
            member_set = f"MEMBER_{short_id}"
            # A member overlapped by another has no elements of its own
            # there, and is found by those in its geometry
            member_elements = getattr(self, "_geometry_element_sets", {}).get(
                member_set
            ) or self.element_sets.get(member_set)
            if not member_elements:
                continue

            # Get or build node set for this member
            if member_set not in self._member_node_cache:
                node_set = set()
                for elem_id in member_elements:
                    if elem_id in self.elements:
                        node_set.update(self.elements[elem_id]["nodes"])
                self._member_node_cache[member_set] = node_set
            node_set = self._member_node_cache[member_set]

            # Choose search target and tolerance.
            # When we know the member endpoints (curve members), target the
            # endpoint nearest to the connection position with a tight tolerance.
            # This avoids false matches for closely-spaced but unconnected members.
            endpoints = self._get_member_endpoints(member_id)
            if endpoints is not None:
                # The point of the member nearest the connection: one of its
                # ends, or a point along it when another member frames into
                # its span (the mesh is seeded with a node there).
                start, end = endpoints
                axis = end - start
                length_sq = float(np.dot(axis, axis))
                t = (
                    float(np.dot(conn_pos - start, axis)) / length_sq
                    if length_sq > 1e-18
                    else 0.0
                )
                # With no node along the span (the connection was not on the
                # member, only near its end), fall back to the nearest end.
                targets = [
                    start + min(max(t, 0.0), 1.0) * axis,
                    min(endpoints, key=lambda ep: float(np.linalg.norm(ep - conn_pos))),
                ]
                tolerance = _TIGHT_TOL
            else:
                targets = [conn_pos]
                tolerance = _LOOSE_TOL

            # Find nearest node to the target within tolerance
            best_node = None
            for target_pos in targets:
                best_dist = tolerance
                for node_id in node_set:
                    if node_id in self.nodes:
                        npos = self.nodes[node_id]
                        dist = float(
                            np.sqrt(
                                (npos[0] - target_pos[0]) ** 2
                                + (npos[1] - target_pos[1]) ** 2
                                + (npos[2] - target_pos[2]) ** 2
                            )
                        )
                        if dist < best_dist:
                            best_dist = dist
                            best_node = node_id
                if best_node is not None:
                    break

            if best_node is not None and best_node not in seen_nodes:
                seen_nodes.add(best_node)
                connection_pairs.append((member_id, best_node))

        if connection_pairs:
            logger.debug(
                f"Connection {conn.id}: Found {len(connection_pairs)} nodes at location"
            )

        return connection_pairs

    def _detect_mechanism_risk(self) -> List[str]:
        """Return warning strings when the model may be a kinematic mechanism under lateral loads.

        The heuristic flags models where:
        (1) every support fixes only translational DOFs (1-3, no rotational restraint), AND
        (2) no moment-resisting member connection exists (all connections are hinges), AND
        (3) at least one lateral (non-gravity) load is present.

        Under these conditions CalculiX will often report a zero-pivot singularity or
        converge to unrealistically large displacements.
        """
        from ifc_structural_mechanics.analysis.boundary_condition_handling import (
            support_resistance,
        )

        model = self.domain_model

        # --- 1. Any support with rotational fixity (DOF 4-6)? ---
        for conn in model.connections:
            real = list(conn.connected_members)
            if len(real) >= 2:
                continue  # member-to-member connection
            restraint = support_resistance(conn)
            if restraint is not None and len(restraint[1]):
                return (
                    []
                )  # rotationally restrained support found → not a pure mechanism

        # --- 2. Any moment-resisting connection between members? ---
        for conn in model.connections:
            real = list(conn.connected_members)
            if len(real) < 2:
                continue  # support
            if conn.entity_type == "hinge":
                continue  # explicit hinge releases all rotations
            if conn.entity_type in ("point", "rigid"):
                released = getattr(conn, "released_dofs_by_member", {}) or {}
                for mid in real:
                    if not {4, 5, 6}.issubset(set(released.get(mid, []))):
                        return []  # this member retains at least one rotation DOF

        # --- 3. Any lateral (non-gravity) load? ---
        for load_group in model.load_groups:
            for load in load_group.loads:
                try:
                    vec = load.get_force_vector()
                    if len(vec) >= 2 and (
                        abs(float(vec[0])) > 1e-3 or abs(float(vec[1])) > 1e-3
                    ):
                        return [
                            "Possible mechanism: no support holds a rotation, "
                            "every joint between members is a pin, and the model "
                            "has sideways loads. The structure may be free to "
                            "sway: CalculiX may report a zero pivot or very large "
                            "displacements. Check the rotations of the supports' "
                            "IfcBoundaryNodeCondition and the releases at the "
                            "joints."
                        ]
                except (AttributeError, TypeError, ValueError):
                    continue  # a load with no vector says nothing here

        return []

    def _split_beam_sets_by_orientation(self) -> Dict[str, Dict[tuple, List[int]]]:
        """
        Split beam element sets by element orientation.

        Returns a mapping of member_set -> {normal_vector: [element_ids]}
        """
        orientation_groups = {}

        for member in self.domain_model.members:
            if not isinstance(member, CurveMember):
                continue

            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"

            if member_set not in self.element_sets or not self.element_sets[member_set]:
                continue

            # Group elements by section direction. The IFC orientation wins;
            # the purely geometric default is only for members without one.
            has_ifc_axis = getattr(member, "local_axis", None) is not None
            section_direction = self._get_beam_normal(member) if has_ifc_axis else None
            if not has_ifc_axis:
                self._members_without_axis.add(member.id)
            groups = {}
            for elem_id in self.element_sets[member_set]:
                if section_direction is not None:
                    normal = self._orthogonal_beam_normal(
                        section_direction, self._compute_beam_axis([elem_id], member)
                    )
                else:
                    normal = self._compute_element_normal(elem_id)
                # Round to avoid floating point comparison issues
                normal_key = tuple(round(x, 6) for x in normal)

                if normal_key not in groups:
                    groups[normal_key] = []
                groups[normal_key].append(elem_id)

            orientation_groups[member_set] = groups

        return orientation_groups

    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics."""
        element_types = {}
        for elem_data in self.elements.values():
            elem_type = elem_data["type"]
            element_types[elem_type] = element_types.get(elem_type, 0) + 1

        return {
            "nodes": len(self.nodes),
            "elements": len(self.elements),
            "element_sets": len(self.element_sets),
            "node_sets": len(self.node_sets),
            "element_types": element_types,
        }


# Main workflow function - replaces all the complex coordination
def generate_calculix_input(
    domain_model: StructuralModel,
    mesh_file: str,
    output_file: str,
    analysis_config: Optional[AnalysisConfig] = None,
) -> str:
    """
    THE SIMPLE SOLUTION: Generate CalculiX input from domain model and mesh.

    This single function replaces the entire complex workflow with a simple,
    unified approach that eliminates dual element writing by design.

    Args:
        domain_model: Structural domain model
        mesh_file: Gmsh mesh file (.msh)
        output_file: Output CalculiX input file (.inp)
        analysis_config: Analysis configuration

    Returns:
        str: Path to generated CalculiX input file
    """
    writer = UnifiedCalculixWriter(
        domain_model=domain_model,
        analysis_config=analysis_config,
    )

    result = writer.write_calculix_input_from_mesh(
        mesh_file=mesh_file,
        output_file=output_file,
    )

    # Log statistics
    stats = writer.get_statistics()
    logger.info(f"Generation complete: {stats}")

    return result


# Complete workflow from domain model to CalculiX input
def run_complete_analysis_workflow(
    domain_model: StructuralModel,
    output_inp_file: str,
    analysis_config: Optional[AnalysisConfig] = None,
    meshing_config=None,
    system_config=None,
    intermediate_files_dir: Optional[str] = None,
) -> str:
    """
    Complete workflow: Domain Model → Gmsh → Unified Writer → CalculiX Input.

    This is the ONE TRUE WORKFLOW that replaces all the complex coordination.

    Args:
        domain_model: Structural domain model
        output_inp_file: Final CalculiX input file path
        analysis_config: Analysis configuration
        meshing_config: Meshing configuration
        system_config: System configuration
        intermediate_files_dir: Directory for intermediate files

    Returns:
        str: Path to generated CalculiX input file
    """
    from pathlib import Path

    import gmsh

    from .gmsh_geometry import GmshGeometryConverter
    from .gmsh_runner import GmshRunner

    logger.info("Starting complete unified analysis workflow...")

    # Explicitly manage Gmsh lifecycle for the entire workflow.
    # This prevents premature finalization between geometry conversion
    # and mesh generation phases.
    we_initialized_gmsh = not gmsh.isInitialized()
    if we_initialized_gmsh:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)

    try:
        # Step 1: Convert domain model to Gmsh geometry
        logger.info("Phase 1: Converting domain model to Gmsh geometry...")
        geometry_converter = GmshGeometryConverter(
            meshing_config=meshing_config, domain_model=domain_model
        )
        entity_map = geometry_converter.convert_model(domain_model)
        logger.info(f"Created Gmsh geometry with {len(entity_map)} entities")

        # Prevent the converter from finalizing Gmsh in __del__ —
        # we manage the lifecycle here.
        geometry_converter._we_initialized_gmsh = False

        # Step 2: Generate mesh with Gmsh
        logger.info("Phase 2: Generating mesh with Gmsh...")
        gmsh_runner = GmshRunner(
            meshing_config=meshing_config, system_config=system_config
        )
        success = gmsh_runner.run_meshing()

        if not success:
            raise MeshingError("Gmsh meshing failed", code="E-MSH-001")

        # Determine mesh file path
        if intermediate_files_dir:
            intermediate_dir = Path(intermediate_files_dir)
            intermediate_dir.mkdir(exist_ok=True)
            mesh_file = str(intermediate_dir / f"mesh_{domain_model.id}.msh")
        else:
            temp_dir = get_temp_dir()
            mesh_file = str(Path(temp_dir) / f"mesh_{domain_model.id}.msh")

        mesh_file = gmsh_runner.generate_mesh_file(mesh_file)
        logger.info(f"Generated mesh file: {mesh_file}")

        # Prevent the runner from finalizing Gmsh in __del__
        gmsh_runner._we_initialized_gmsh = False

    finally:
        # Finalize Gmsh after all meshing operations are complete
        if we_initialized_gmsh and gmsh.isInitialized():
            try:
                gmsh.finalize()
            except Exception:
                pass

    # Step 3: Generate CalculiX input using unified writer (no Gmsh needed)
    logger.info("Phase 3: Generating CalculiX input with unified writer...")
    result = generate_calculix_input(
        domain_model=domain_model,
        mesh_file=mesh_file,
        output_file=output_inp_file,
        analysis_config=analysis_config,
    )

    logger.info(f"Complete workflow finished successfully: {result}")
    return result
