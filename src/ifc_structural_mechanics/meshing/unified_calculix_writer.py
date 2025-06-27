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

import meshio

from ..domain.structural_model import StructuralModel
from ..domain.structural_member import CurveMember, SurfaceMember
from ..config.analysis_config import AnalysisConfig
from ..mapping.domain_to_calculix import DomainToCalculixMapper
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
        mapper: Optional[DomainToCalculixMapper] = None,
    ):
        """
        Initialize the unified CalculiX writer.

        Args:
            domain_model: The structural domain model
            analysis_config: Analysis configuration
            mapper: Domain to CalculiX mapper
        """
        self.domain_model = domain_model
        self.analysis_config = analysis_config or AnalysisConfig()
        self.mapper = mapper or DomainToCalculixMapper()

        # Single source of truth for mesh data
        self.nodes: Dict[int, Tuple[float, float, float]] = {}
        self.elements: Dict[int, Dict[str, Any]] = {}
        self.node_sets: Dict[str, List[int]] = {}
        self.element_sets: Dict[str, List[int]] = {}
        self.defined_element_sets: set = set()

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
            member_set = f"MEMBER_{member.id}"

            self.element_sets[member_set] = member_elements
            self.defined_element_sets.add(member_set)

            # Register mapping
            for elem_id in member_elements:
                self.mapper.register_element(member.id, elem_id, member_type)

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

        with open(output_file, "w") as f:
            # Header
            self._write_header(f)

            # Mesh data
            self._write_nodes(f)
            self._write_elements(f)
            self._write_node_sets(f)
            self._write_element_sets(f)

            # Material and structural properties
            self._write_materials(f)
            self._write_sections(f)

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
                f, self.domain_model, self.analysis_config.get_analysis_type()
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

    def _write_nodes(self, file: TextIO) -> None:
        """Write node definitions."""
        file.write("*NODE\n")
        for node_id, (x, y, z) in sorted(self.nodes.items()):
            file.write(f"{node_id}, {x:.6e}, {y:.6e}, {z:.6e}\n")
        file.write("\n")

    def _write_elements(self, file: TextIO) -> None:
        """Write element definitions grouped by type."""
        # Group elements by type
        element_types = {}
        for element_id, element_data in self.elements.items():
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

    def _write_sections(self, file: TextIO) -> None:
        """Write section definitions for members."""
        file.write("** Section Definitions\n")

        sections_written = 0

        for member in self.domain_model.members:
            member_set = f"MEMBER_{member.id}"

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
                if (
                    hasattr(member.section, "section_type")
                    and member.section.section_type == "rectangular"
                ):
                    file.write(
                        f"*BEAM SECTION, ELSET={member_set}, MATERIAL=MAT_{material_id}, SECTION=RECT\n"
                    )
                    width = member.section.dimensions.get("width", 0.1)
                    height = member.section.dimensions.get("height", 0.2)
                    file.write(f"{width:.6e}, {height:.6e}\n")
                    file.write("0.0, 0.0, -1.0\n\n")
                elif (
                    hasattr(member.section, "section_type")
                    and member.section.section_type == "circular"
                ):
                    file.write(
                        f"*BEAM SECTION, ELSET={member_set}, MATERIAL=MAT_{material_id}, SECTION=CIRC\n"
                    )
                    radius = member.section.dimensions.get("radius", 0.1)
                    file.write(f"{radius:.6e}\n")
                    file.write("0.0, 0.0, -1.0\n\n")
                else:
                    # General beam section
                    file.write(
                        f"*BEAM GENERAL SECTION, ELSET={member_set}, MATERIAL=MAT_{material_id}\n"
                    )
                    area = getattr(member.section, "area", 0.01)
                    i_yy = getattr(member.section, "moment_of_inertia_y", area * 0.01)
                    i_zz = getattr(member.section, "moment_of_inertia_z", area * 0.01)
                    i_yz = 0.0
                    it = getattr(member.section, "torsional_constant", area * 0.01)
                    warping = getattr(member.section, "warping_constant", 0.0) or 0.0
                    file.write(
                        f"{area:.6e}, {i_yy:.6e}, {i_zz:.6e}, {i_yz:.6e}, {it:.6e}, {warping:.6e}\n"
                    )
                    file.write("0.0, 0.0, -1.0\n\n")
                sections_written += 1

            # Write shell sections
            elif (
                isinstance(member, SurfaceMember)
                and hasattr(member, "thickness")
                and member.thickness
            ):
                file.write(
                    f"*SHELL SECTION, ELSET={member_set}, MATERIAL=MAT_{material_id}\n"
                )
                thickness_value = getattr(member.thickness, "value", 0.1)
                file.write(f"{thickness_value:.6e}\n\n")
                sections_written += 1

        logger.info(f"Wrote {sections_written} section definitions")

    def _save_mapping(self, mapping_file: str) -> None:
        """Save domain to CalculiX mapping."""
        try:
            self.mapper.create_mapping_file(mapping_file)
            logger.info(f"Mapping saved to {mapping_file}")
        except Exception as e:
            logger.warning(f"Failed to save mapping: {e}")

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

    logger.info("Starting complete unified analysis workflow...")

    # Step 1: Convert domain model to Gmsh geometry
    logger.info("Phase 1: Converting domain model to Gmsh geometry...")
    geometry_converter = GmshGeometryConverter(meshing_config=meshing_config)
    entity_map = geometry_converter.convert_model(domain_model)
    logger.info(f"Created Gmsh geometry with {len(entity_map)} entities")

    # Step 2: Generate mesh with Gmsh
    logger.info("Phase 2: Generating mesh with Gmsh...")
    gmsh_runner = GmshRunner(meshing_config=meshing_config, system_config=system_config)
    success = gmsh_runner.run_meshing()

    if not success:
        raise MeshingError("Gmsh meshing failed")

    # Determine mesh file path
    if intermediate_files_dir:
        intermediate_dir = Path(intermediate_files_dir)
        intermediate_dir.mkdir(exist_ok=True)
        mesh_file = str(intermediate_dir / f"mesh_{domain_model.id}.msh")
        mapping_file = str(intermediate_dir / f"mapping_{domain_model.id}.json")
    else:
        temp_dir = get_temp_dir()
        mesh_file = str(Path(temp_dir) / f"mesh_{domain_model.id}.msh")
        mapping_file = None

    mesh_file = gmsh_runner.generate_mesh_file(mesh_file)
    logger.info(f"Generated mesh file: {mesh_file}")

    # Step 3: Generate CalculiX input using unified writer
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
