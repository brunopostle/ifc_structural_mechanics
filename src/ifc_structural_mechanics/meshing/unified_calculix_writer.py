"""
Unified CalculiX Input Writer - THE REAL SOLUTION

This module replaces both MeshConverter and CalculixInputGenerator with a single,
unified tool that writes CalculiX input files. No more dual systems, no fallbacks,
no conflicts.

PRINCIPLE: All geometry → Gmsh → Unified Writer → CalculiX input file

This eliminates the architectural problem at its source by having only ONE system
responsible for writing elements to CalculiX input files.
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Any, TextIO

import numpy as np
import meshio

from ..domain.structural_model import StructuralModel
from ..domain.structural_member import CurveMember, SurfaceMember
from ..config.analysis_config import AnalysisConfig
from ..utils.error_handling import AnalysisError, MeshingError
from ..utils.temp_dir import get_temp_dir, create_temp_subdir

# Import boundary condition and load handling
from ..analysis.boundary_condition_handling import (
    write_boundary_conditions,
    write_analysis_steps,
)

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
        "line3": "B32",
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

        # Working directory
        self.work_dir = create_temp_subdir(prefix="unified_calculix_")

        # Validation
        self._validate_domain_model()

    def _validate_domain_model(self) -> None:
        """Validate the domain model."""
        if not self.domain_model:
            raise AnalysisError("Domain model is missing")
        if not self.domain_model.members:
            raise AnalysisError("Domain model has no members")

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
        """
        Get beam normal vector from member's local axis.

        CalculiX requires a normal vector for beam elements that is perpendicular
        to the beam axis. This method uses the local_axis extracted from IFC.

        The local_axis from IFC is a tuple of (xAxis, yAxis, zAxis) where:
        - xAxis: Local X direction
        - yAxis: Local Y direction (used as beam normal in CalculiX)
        - zAxis: Beam axis direction

        Args:
            member: CurveMember with local_axis from IFC transformation

        Returns:
            Tuple[float, float, float]: Normal vector (nx, ny, nz)
        """
        # Use local axis from IFC if available
        if hasattr(member, 'local_axis') and member.local_axis is not None:
            # local_axis is (xAxis, yAxis, zAxis) - try xAxis for beam normal
            if isinstance(member.local_axis, (tuple, list)) and len(member.local_axis) == 3:
                x_axis = member.local_axis[0]  # Get xAxis
                logger.info(f"Using x-axis from IFC local coordinate system: {x_axis}")
                return tuple(x_axis)
            else:
                logger.warning(f"Unexpected local_axis format: {member.local_axis}")
                # Try to use it directly if it's already a 3-element vector
                if isinstance(member.local_axis, (tuple, list)) and len(member.local_axis) == 3:
                    return tuple(member.local_axis)

        # Fallback: compute from geometry if no local axis
        logger.warning(f"Member {member.id} has no local_axis, computing from geometry")

        curve_geometry = member.geometry

        # Extract start and end points
        if isinstance(curve_geometry, tuple) and len(curve_geometry) == 2:
            start_point = np.array(curve_geometry[0], dtype=float)
            end_point = np.array(curve_geometry[1], dtype=float)
        elif isinstance(curve_geometry, list) and len(curve_geometry) >= 2:
            start_point = np.array(curve_geometry[0], dtype=float)
            end_point = np.array(curve_geometry[-1], dtype=float)
        else:
            logger.warning("Unable to extract beam geometry points, using default normal")
            return (0.0, 1.0, 0.0)

        # Compute beam axis direction
        beam_axis = end_point - start_point
        beam_length = np.linalg.norm(beam_axis)

        if beam_length < 1e-10:
            logger.warning("Beam has zero length, using default normal")
            return (0.0, 1.0, 0.0)

        # Normalize beam axis
        beam_axis_normalized = beam_axis / beam_length

        # Find a perpendicular vector
        candidate_vectors = [
            np.array([0.0, 1.0, 0.0]),  # Global Y
            np.array([0.0, 0.0, 1.0]),  # Global Z
            np.array([1.0, 0.0, 0.0]),  # Global X
        ]

        for candidate in candidate_vectors:
            normal = np.cross(beam_axis_normalized, candidate)
            normal_length = np.linalg.norm(normal)

            if normal_length > 1e-6:
                normal_normalized = normal / normal_length
                return (float(normal_normalized[0]), float(normal_normalized[1]), float(normal_normalized[2]))

        logger.warning("Could not compute perpendicular normal, using default")
        return (0.0, 1.0, 0.0)

    def write_calculix_input_from_mesh(
        self,
        mesh_file: str,
        output_file: str,
        mapping_file: Optional[str] = None,
    ) -> str:
        """
        THE MAIN METHOD: Write CalculiX input file from Gmsh mesh.

        This is the single entry point that replaces both mesh conversion
        and input generation. No dual systems, no conflicts.

        Args:
            mesh_file: Path to Gmsh mesh file (.msh)
            output_file: Path for output CalculiX input file (.inp)
            mapping_file: Optional path for mapping information

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

            # Step 3: Write complete CalculiX input file
            self._write_calculix_input_file(output_file)

            # Step 4: Save mapping if requested
            if mapping_file:
                self._save_mapping(mapping_file)

            logger.info(f"Successfully wrote unified CalculiX input: {output_file}")
            return output_file

        except Exception as e:
            logger.error(f"Error writing unified CalculiX input: {e}")
            raise AnalysisError(f"Failed to write CalculiX input: {str(e)}")

    def _process_mesh(self, mesh: meshio.Mesh) -> None:
        """
        Process Gmsh mesh data into internal structures.

        This is the ONLY place where elements are created from mesh data.
        """
        logger.info("Processing mesh data...")

        # Clear any existing data
        self.nodes.clear()
        self.elements.clear()
        self.element_sets.clear()

        # Process nodes
        for i, (x, y, z) in enumerate(mesh.points):
            node_id = i + 1  # CalculiX uses 1-based indexing
            self.nodes[node_id] = (float(x), float(y), float(z))

        # Process elements
        element_id = 1
        element_type_counts = {}

        # Extract cell blocks in version-agnostic way
        cell_blocks = self._extract_cell_blocks(mesh)

        for block_name, block_cells in cell_blocks:
            calculix_type = self.ELEMENT_TYPE_MAPPING.get(block_name)

            if not calculix_type:
                # Skip non-structural element types (vertex, edge, etc.) silently
                # These are geometric entities from Gmsh, not FEA elements
                if block_name not in ['vertex', 'edge', 'point']:
                    logger.warning(f"Unknown element type: {block_name}")
                continue

            # Create element set for this block type
            set_name = f"ELSET_{block_name.upper()}"
            self.element_sets[set_name] = []
            self.defined_element_sets.add(set_name)

            # Process each element in the block
            for cell in block_cells:
                # Convert to 1-based indexing for CalculiX
                node_indices = [idx + 1 for idx in cell]

                # Store element data
                self.elements[element_id] = {
                    "type": calculix_type,
                    "nodes": node_indices,
                    "block_name": block_name,
                }

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

    def _extract_cell_blocks(self, mesh):
        """Extract cell blocks from mesh in version-agnostic way."""
        try:
            if hasattr(mesh.cells, "items"):
                return list(mesh.cells.items())
            if hasattr(mesh.cells[0], "type"):
                return [(cell_block.type, cell_block.data) for cell_block in mesh.cells]
            return list(mesh.cells)
        except Exception as e:
            logger.warning(f"Could not extract cell blocks: {e}")
            return []

    def _map_elements_to_members(self) -> None:
        """
        Map mesh elements to domain model members.

        This creates member-specific element sets for material and section assignment.
        """
        logger.info("Mapping elements to domain members...")

        # Separate elements by type
        surface_elements = []
        curve_elements = []

        for elem_id, elem_data in self.elements.items():
            elem_type = elem_data["type"]
            if elem_type in ["S3", "S4", "S6", "S8", "S9"]:  # Shell elements
                surface_elements.append(elem_id)
            elif elem_type in ["B31", "B32"]:  # Beam elements
                curve_elements.append(elem_id)

        # Get members by type
        surface_members = [
            m for m in self.domain_model.members if m.entity_type == "surface"
        ]
        curve_members = [
            m for m in self.domain_model.members if m.entity_type == "curve"
        ]

        # Distribute surface elements among surface members
        self._distribute_elements_to_members(
            surface_elements, surface_members, "surface"
        )

        # Distribute curve elements among curve members
        self._distribute_elements_to_members(curve_elements, curve_members, "curve")

    def _distribute_elements_to_members(
        self, elements: List[int], members: List, member_type: str
    ):
        """Distribute elements among members of the same type."""
        if not elements or not members:
            logger.warning(f"No {member_type} elements or members to distribute")
            return

        elements_per_member = len(elements) // len(members)
        remainder = len(elements) % len(members)

        start_idx = 0
        for i, member in enumerate(members):
            # Calculate elements for this member
            num_elements = elements_per_member + (1 if i < remainder else 0)
            end_idx = start_idx + num_elements

            # Assign elements to member
            member_elements = elements[start_idx:end_idx]
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"

            self.element_sets[member_set] = member_elements
            self.defined_element_sets.add(member_set)

            # Register analysis elements in domain model for traceability
            self.domain_model.register_analysis_elements(
                member.id, member_elements, entity_type="member"
            )

            logger.info(
                f"Assigned {len(member_elements)} {member_type} elements to member {member.id}"
            )
            start_idx = end_idx

    def _write_calculix_input_file(self, output_file: str) -> None:
        """
        Write the complete CalculiX input file.

        This is the ONLY place where CalculiX input is written.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

        # Collect boundary condition (node, DOF) pairs before writing connections
        # to avoid MPC/SPC conflicts
        bc_node_dofs = self._collect_boundary_condition_dofs()

        with open(output_file, "w") as f:
            # Header
            self._write_header(f)

            # Mesh data
            self._write_nodes(f)
            self._write_nodal_thickness(f)  # Must come after nodes, before elements
            self._write_elements(f)
            self._write_node_sets(f)
            self._write_element_sets(f)

            # Material and structural properties
            self._write_materials(f)
            self._write_sections(f)

            # Connections (kinematic couplings, MPCs)
            # Pass boundary condition DOFs to avoid conflicts
            self._write_connections(f, bc_node_dofs)

            # Boundary conditions and loads
            write_boundary_conditions(
                f,
                self.domain_model,
                self.node_sets,
                self.element_sets,
                dict(self.nodes),
            )

            # Analysis steps
            write_analysis_steps(
                f, self.domain_model, self.analysis_config.get_analysis_type(),
                self.short_id_map, self.element_sets, dict(self.nodes),
                gravity=self.analysis_config.get_gravity(),
                gravity_direction=self.analysis_config.get_gravity_direction(),
            )

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
            if isinstance(member, SurfaceMember) and hasattr(member, "thickness") and member.thickness:
                thickness_value = getattr(member.thickness, "value", None)
                if thickness_value is None or thickness_value <= 0:
                    continue

                # Find element set for this member
                member_set = f"MEMBER_{self._get_short_id(member.id)}"
                if member_set in self.element_sets:
                    # Get all nodes in this member's shell elements only
                    for elem_id in self.element_sets[member_set]:
                        if elem_id in self.elements:
                            elem_type = self.elements[elem_id]['type']
                            # Only add thickness for shell elements (S3, S4, S6, S8, etc.)
                            if elem_type.startswith('S'):
                                for node_id in self.elements[elem_id]['nodes']:
                                    # Use maximum thickness if node belongs to multiple members
                                    if node_id in nodal_thickness_map:
                                        nodal_thickness_map[node_id] = max(
                                            nodal_thickness_map[node_id], thickness_value
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

        for set_name, element_ids in self.element_sets.items():
            if element_ids and set_name not in written_sets:
                file.write(f"*ELSET, ELSET={set_name}\n")
                for i in range(0, len(element_ids), 8):
                    line_elements = element_ids[i : i + 8]
                    file.write(", ".join(map(str, line_elements)) + "\n")
                file.write("\n")
                written_sets.add(set_name)

        # Write EALL set containing all elements (needed for gravity DLOAD)
        all_element_ids = sorted(self.elements.keys())
        if all_element_ids:
            file.write("*ELSET, ELSET=EALL\n")
            for i in range(0, len(all_element_ids), 8):
                line_elements = all_element_ids[i : i + 8]
                file.write(", ".join(map(str, line_elements)) + "\n")
            file.write("\n")

        logger.info(f"Wrote {len(written_sets)} element sets")

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
            file.write("\n")

    def _write_list_in_chunks(self, file: TextIO, items: List[int], chunk_size: int = 16) -> None:
        """Write a list of integers in chunks with proper formatting."""
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i+chunk_size]
            file.write(", ".join(str(x) for x in chunk))
            if i + chunk_size < len(items):
                file.write(",\n")
            else:
                file.write("\n")

    def _write_beam_section_for_set(
        self, file: TextIO, member: CurveMember, elset_name: str, material_id: str, beam_normal: tuple
    ) -> None:
        """Write a beam section definition for a given element set."""
        if (
            hasattr(member.section, "section_type")
            and member.section.section_type == "rectangular"
        ):
            file.write(
                f"*BEAM SECTION, ELSET={elset_name}, MATERIAL=MAT_{material_id}, SECTION=RECT\n"
            )
            width = member.section.dimensions.get("width", 0.1)
            height = member.section.dimensions.get("height", 0.2)
            file.write(f"{width:.6e}, {height:.6e}\n")
            file.write(f"{beam_normal[0]:.6e}, {beam_normal[1]:.6e}, {beam_normal[2]:.6e}\n\n")

        elif (
            hasattr(member.section, "section_type")
            and member.section.section_type == "circular"
        ):
            file.write(
                f"*BEAM SECTION, ELSET={elset_name}, MATERIAL=MAT_{material_id}, SECTION=CIRC\n"
            )
            radius = member.section.dimensions.get("radius", 0.1)
            file.write(f"{radius:.6e}\n")
            file.write(f"{beam_normal[0]:.6e}, {beam_normal[1]:.6e}, {beam_normal[2]:.6e}\n\n")

        else:
            # Non-standard section (I-beam, etc.): CalculiX B31 only supports
            # RECT, CIRC, PIPE, BOX — not GENERAL. Use equivalent RECT that
            # preserves area and strong-axis moment of inertia:
            #   w*h = A, w*h³/12 = Iy → h = sqrt(12*Iy/A), w = A/h
            area = getattr(member.section, "area", 0.01)
            i_yy = getattr(member.section, "moment_of_inertia_y", area * 0.01)

            if area > 0 and i_yy > 0:
                height = (12.0 * i_yy / area) ** 0.5
                width = area / height
            else:
                height = area ** 0.5 if area > 0 else 0.1
                width = height

            file.write(
                f"*BEAM SECTION, ELSET={elset_name}, MATERIAL=MAT_{material_id}, SECTION=RECT\n"
            )
            file.write(f"{width:.6e}, {height:.6e}\n")
            file.write(f"{beam_normal[0]:.6e}, {beam_normal[1]:.6e}, {beam_normal[2]:.6e}\n\n")

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
        connectivity = element.get('nodes', [])

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

        # Compute element axis
        element_axis = node2 - node1
        element_length = np.linalg.norm(element_axis)

        if element_length < 1e-10:
            return (0.0, 1.0, 0.0)

        element_axis_normalized = element_axis / element_length

        # Find perpendicular vector
        candidates = [
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
            np.array([1.0, 0.0, 0.0]),
        ]

        for candidate in candidates:
            normal = np.cross(element_axis_normalized, candidate)
            normal_length = np.linalg.norm(normal)

            if normal_length > 1e-6:
                normal_normalized = normal / normal_length
                return (float(normal_normalized[0]), float(normal_normalized[1]), float(normal_normalized[2]))

        return (0.0, 1.0, 0.0)

    def _write_sections(self, file: TextIO) -> None:
        """Write section definitions for members."""
        file.write("** Section Definitions\n")

        sections_written = 0

        # Split beam element sets by orientation
        beam_orientation_groups = self._split_beam_sets_by_orientation()

        for member in self.domain_model.members:
            short_id = self._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"

            # Check if member has elements
            if member_set not in self.element_sets or not self.element_sets[member_set]:
                logger.warning(f"No elements for member {member.id}, skipping section")
                continue

            material_id = member.material.id if member.material else "DEFAULT"

            # Write beam sections
            if (
                isinstance(member, CurveMember)
                and hasattr(member, "section")
                and member.section
            ):
                # Get orientation groups for this member
                if member_set in beam_orientation_groups:
                    orientation_groups = beam_orientation_groups[member_set]

                    # Write a section for each orientation group
                    for ori_idx, (normal_key, element_ids) in enumerate(orientation_groups.items()):
                        # Create sub-element-set for this orientation
                        subset_name = f"{member_set}_ORI{ori_idx+1}"

                        # Write the element set definition
                        file.write(f"*ELSET, ELSET={subset_name}\n")
                        self._write_list_in_chunks(file, element_ids, chunk_size=16)
                        file.write("\n")

                        # Use computed normal from grouping
                        beam_normal = normal_key

                        # Write beam section for this subset
                        self._write_beam_section_for_set(file, member, subset_name, material_id, beam_normal)
                        sections_written += 1
                else:
                    # No orientation groups (shouldn't happen, but fallback to single section)
                    beam_normal = self._get_beam_normal(member)
                    self._write_beam_section_for_set(file, member, member_set, material_id, beam_normal)
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
        node_coords = dict(self.nodes)

        from ..analysis.boundary_condition_handling import find_nodes_at_position

        for conn in self.domain_model.connections:
            # Determine BC type
            bc_type = getattr(conn, "connection_type", getattr(conn, "entity_type", "point"))

            # Skip non-support connections (same logic as write_boundary_conditions)
            has_stiffness = (
                hasattr(conn, "has_stiffness_properties")
                and conn.has_stiffness_properties()
            )
            if bc_type == "point" and not has_stiffness:
                continue

            # Find nodes at this connection's position
            if hasattr(conn, "position") and conn.position:
                bc_nodes = find_nodes_at_position(
                    conn.position, node_coords, tolerance=0.1
                )

                if not bc_nodes:
                    continue

                if bc_type == "rigid" or bc_type == "fixed":
                    # Fixed: constrain all 6 DOF (1-6)
                    for node in bc_nodes:
                        for dof in [1, 2, 3, 4, 5, 6]:
                            bc_node_dofs.add((node, dof))

                elif bc_type == "hinge":
                    # Pinned: constrain translations (1-3), but not rotations
                    for node in bc_nodes:
                        for dof in [1, 2, 3]:
                            bc_node_dofs.add((node, dof))

                elif bc_type == "point" and has_stiffness:
                    # Point with stiffness: check behavior
                    if (hasattr(conn, "is_rigid_behavior")
                            and conn.is_rigid_behavior()):
                        for node in bc_nodes:
                            for dof in [1, 2, 3, 4, 5, 6]:
                                bc_node_dofs.add((node, dof))
                    else:
                        for node in bc_nodes:
                            for dof in [1, 2, 3]:
                                bc_node_dofs.add((node, dof))

        logger.info(f"Collected {len(bc_node_dofs)} boundary condition DOFs")
        if logger.isEnabledFor(logging.DEBUG):
            # Log first 20 for debugging
            sample = sorted(list(bc_node_dofs))[:20]
            logger.debug(f"Sample boundary condition DOFs: {sample}")
        return bc_node_dofs

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
        if not self.domain_model.connections:
            logger.debug("No connections to write")
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

        for conn in self.domain_model.connections:
            # Skip connections with dummy members (boundary conditions)
            real_members = [m for m in conn.connected_members if not m.startswith('dummy_member_')]
            if len(real_members) < 2:
                logger.debug(f"Skipping connection {conn.id} - only {len(real_members)} real members (boundary condition)")
                continue

            # Get connection type
            if conn.entity_type == "point":
                self._write_point_connection(file, conn, real_members, constrained_node_dofs)
                connections_written += 1
            elif conn.entity_type == "rigid":
                self._write_rigid_connection(file, conn, real_members, constrained_node_dofs)
                connections_written += 1
            elif conn.entity_type == "hinge":
                # Hinges with multiple members could be modeled differently
                # For now, treat as point connection with note
                if len(real_members) >= 2:
                    logger.debug(f"Hinge connection {conn.id} with {len(real_members)} members - treating as pinned joint")
                    self._write_point_connection(file, conn, real_members, constrained_node_dofs, is_hinge=True)
                    connections_written += 1
            elif conn.entity_type == "spring":
                logger.warning(f"Spring connections not yet implemented: {conn.id}")
            else:
                logger.warning(f"Unknown connection type '{conn.entity_type}' for {conn.id}")

        logger.info(f"Wrote {connections_written} structural connections")

    def _write_point_connection(self, file: TextIO, conn, member_ids: List[str],
                                 constrained_node_dofs: set, is_hinge: bool = False) -> None:
        """
        Write a point connection using CalculiX *EQUATION constraints.

        A point connection ties all member nodes at the connection point together.

        Args:
            file: Output file handle
            conn: Connection object
            member_ids: List of member IDs
            constrained_node_dofs: Set of (node_id, dof) tuples already constrained
            is_hinge: If True, only constrain translations, not rotations
        """
        # Find nodes at this connection point for each member
        connection_nodes = self._find_connection_nodes(conn, member_ids)

        if len(connection_nodes) < 2:
            logger.warning(f"Connection {conn.id}: Found only {len(connection_nodes)} nodes, need at least 2")
            return

        conn_type = "HINGE" if is_hinge else "POINT"
        file.write(f"** {conn_type} Connection: {conn.id}\n")
        file.write(f"** Connects {len(member_ids)} members at {len(connection_nodes)} nodes\n")

        # Check if all connected elements support rotational DOFs
        has_rotational_dofs = self._check_rotational_dofs_at_nodes(connection_nodes)

        # Use first node as reference, constrain all others to it
        ref_node = connection_nodes[0]

        # For each DOF, create equation: node_i.dof = ref_node.dof
        # Equation format: *EQUATION
        #                  2
        #                  node1, dof1, coef1, node2, dof2, coef2

        dofs = [1, 2, 3]  # X, Y, Z translations (always constrained)

        # Only constrain rotations if all elements support them AND it's not a hinge
        if not is_hinge and has_rotational_dofs:
            dofs.extend([4, 5, 6])  # Add rotations for rigid connection
        elif not is_hinge and not has_rotational_dofs:
            logger.debug(f"Connection {conn.id}: Skipping rotational constraints (shell elements present)")

        equations_written = 0
        equations_skipped = 0

        for dof in dofs:
            for node in connection_nodes[1:]:
                # Check if this (node, DOF) is already constrained
                if (node, dof) in constrained_node_dofs:
                    logger.debug(f"Connection {conn.id}: Skipping node {node} DOF {dof} (already constrained)")
                    equations_skipped += 1
                    continue

                # Write the equation
                file.write(f"*EQUATION\n")
                file.write(f"2\n")
                file.write(f"{node},{dof},1.0,{ref_node},{dof},-1.0\n")

                # Mark this (node, DOF) as constrained
                constrained_node_dofs.add((node, dof))
                equations_written += 1

        if equations_skipped > 0:
            logger.info(f"Connection {conn.id}: Wrote {equations_written} equations, skipped {equations_skipped} (shared nodes)")

        file.write("**\n")

    def _write_rigid_connection(self, file: TextIO, conn, member_ids: List[str], constrained_node_dofs: set) -> None:
        """Write a rigid connection (same as point connection for now)."""
        self._write_point_connection(file, conn, member_ids, constrained_node_dofs, is_hinge=False)

    def _find_connection_nodes(self, conn, member_ids: List[str]) -> List[int]:
        """
        Find mesh nodes shared by connected members.

        Strategy:
        1. Get all nodes from elements of each connected member
        2. Find nodes that are spatially coincident (within tolerance)
        3. Return nodes at the connection point
        """
        # Collect all nodes from all connected members
        member_nodes = {}  # member_id -> set of node_ids

        for member_id in member_ids:
            # Get element set for this member
            short_id = self._get_short_id(member_id)
            member_set = f"MEMBER_{short_id}"

            if member_set not in self.element_sets:
                logger.warning(f"Connection {conn.id}: Member {member_id} has no element set {member_set}")
                continue

            # Get all nodes from this member's elements
            nodes = set()
            for elem_id in self.element_sets[member_set]:
                if elem_id in self.elements:
                    elem_nodes = self.elements[elem_id]['nodes']
                    nodes.update(elem_nodes)

            member_nodes[member_id] = nodes

        if len(member_nodes) < 2:
            logger.warning(f"Connection {conn.id}: Could not find nodes for enough members ({len(member_nodes)} < 2)")
            return []

        # Find coincident nodes: nodes that appear in multiple members
        # or are spatially close to nodes from other members
        tolerance = 1e-3  # Spatial tolerance

        connection_node_ids = []
        all_nodes = set().union(*member_nodes.values())

        # Group nodes by spatial proximity
        node_groups = []  # List of lists of coincident node IDs
        processed = set()

        for node_id in all_nodes:
            if node_id in processed:
                continue

            # Start a new group with this node
            group = [node_id]
            processed.add(node_id)
            node_pos = self.nodes[node_id]

            # Find all other unprocessed nodes within tolerance
            for other_id in all_nodes:
                if other_id in processed:
                    continue

                other_pos = self.nodes[other_id]
                dist = np.sqrt(sum((node_pos[i] - other_pos[i])**2 for i in range(3)))

                if dist < tolerance:
                    group.append(other_id)
                    processed.add(other_id)

            if len(group) > 1 or self._node_connects_multiple_members(group[0], member_nodes):
                node_groups.append(group)

        # Find the largest group (most likely the connection point)
        if node_groups:
            largest_group = max(node_groups, key=len)
            connection_node_ids = largest_group
            logger.debug(f"Connection {conn.id}: Found {len(connection_node_ids)} coincident nodes")
        else:
            logger.warning(f"Connection {conn.id}: No coincident nodes found")

        return connection_node_ids

    def _node_connects_multiple_members(self, node_id: int, member_nodes: Dict[str, set]) -> bool:
        """Check if a node belongs to elements from multiple members."""
        count = sum(1 for nodes in member_nodes.values() if node_id in nodes)
        return count >= 2

    def _check_rotational_dofs_at_nodes(self, node_ids: List[int]) -> bool:
        """
        Check if all elements connected to these nodes support rotational DOFs.

        Returns:
            True if all elements support rotations (beam elements), False otherwise
        """
        # Element types that support rotational DOFs in CalculiX
        rotational_types = {'B31', 'B32', 'B33'}  # Beam elements

        for node_id in node_ids:
            # Find all elements using this node
            for elem_id, elem_data in self.elements.items():
                if node_id in elem_data['nodes']:
                    elem_type = elem_data['type']
                    if elem_type not in rotational_types:
                        # Found an element that doesn't support rotations (e.g., shell)
                        logger.debug(f"Node {node_id} has element {elem_id} of type {elem_type} (no rotational DOFs)")
                        return False

        return True

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

            # Group elements by their computed normal
            groups = {}
            for elem_id in self.element_sets[member_set]:
                normal = self._compute_element_normal(elem_id)
                # Round to avoid floating point comparison issues
                normal_key = tuple(round(x, 6) for x in normal)

                if normal_key not in groups:
                    groups[normal_key] = []
                groups[normal_key].append(elem_id)

            orientation_groups[member_set] = groups

        return orientation_groups

    def _save_mapping(self, mapping_file: str) -> None:
        """Save domain to CalculiX mapping (deprecated - now in domain model)."""
        logger.warning("Mapping file generation deprecated - traceability is in domain model")

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
    mapping_file: Optional[str] = None,
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
        mapping_file: Optional mapping file

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
        mapping_file=mapping_file,
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
    from .gmsh_geometry import GmshGeometryConverter
    from .gmsh_runner import GmshRunner
    from pathlib import Path
    import gmsh

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
        geometry_converter = GmshGeometryConverter(meshing_config=meshing_config)
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
            raise MeshingError("Gmsh meshing failed")

        # Determine mesh file path
        if intermediate_files_dir:
            intermediate_dir = Path(intermediate_files_dir)
            intermediate_dir.mkdir(exist_ok=True)
            mesh_file = str(intermediate_dir / f"mesh_{domain_model.id}.msh")
            mapping_file = str(
                intermediate_dir / f"mapping_{domain_model.id}.json"
            )
        else:
            temp_dir = get_temp_dir()
            mesh_file = str(Path(temp_dir) / f"mesh_{domain_model.id}.msh")
            mapping_file = None

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
        mapping_file=mapping_file,
    )

    logger.info(f"Complete workflow finished successfully: {result}")
    return result
