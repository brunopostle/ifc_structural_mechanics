"""
Updated CalculiX Input File Generation Module

This module provides enhanced functionality to generate CalculiX input files (.inp) from
the domain model, mesh data, and analysis configuration.
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Any, TextIO

import numpy as np

from ..domain.structural_model import StructuralModel
from ..domain.structural_member import CurveMember, SurfaceMember
from ..domain.load import (
    PointLoad,
    LineLoad,
    AreaLoad,
)
from ..config.analysis_config import AnalysisConfig
from ..utils.error_handling import AnalysisError

# Import the enhanced boundary condition and load handling
from ..analysis.boundary_condition_handling import (
    write_boundary_conditions,
    write_loads,
    write_analysis_steps,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CalculixInputGenerator:
    """
    Generates CalculiX input files from the structural model and mesh data.
    """

    def __init__(
        self,
        domain_model: StructuralModel,
        analysis_config: Optional[AnalysisConfig] = None,
        mesh_file: Optional[str] = None,
    ):
        """
        Initialize the CalculiX input generator.

        Args:
            domain_model (StructuralModel): The structural domain model to analyze.
            analysis_config (Optional[AnalysisConfig]): Analysis configuration to use.
            mesh_file (Optional[str]): Path to the mesh file to use.
        """
        self.domain_model = domain_model
        self.analysis_config = analysis_config or AnalysisConfig()
        self.mesh_file = mesh_file

        # Initialize data containers
        self.node_sets: Dict[str, List[int]] = {}
        self.element_sets: Dict[str, List[int]] = {}
        self.nodes: Dict[int, Tuple[float, float, float]] = {}
        self.elements: Dict[int, Dict[str, Any]] = {}

        # Validate and prepare the model
        self._validate_domain_model()
        self._generate_nodes_and_elements()

    def _validate_domain_model(self) -> None:
        """
        Validate the domain model, raising an error if invalid.
        """
        if not self.domain_model:
            raise AnalysisError("Domain model is missing")

        if not self.domain_model.members:
            logger.warning("Domain model has no members")
            raise AnalysisError("Domain model has no members")

        logger.info(
            f"Validating domain model with {len(self.domain_model.members)} members"
        )
        for member in self.domain_model.members:
            logger.debug(f"Member {member.id}: Type={type(member).__name__}")

    def _generate_nodes_and_elements(self) -> None:
        """
        Generate nodes and elements from the domain model.
        """
        if self.nodes or self.elements:
            return  # Skip if already generated

        logger.info("Generating nodes and elements from domain model")
        node_id = 1
        element_id = 1

        for member in self.domain_model.members:
            # Determine node and element generation strategy based on member type
            if hasattr(member, "geometry"):
                # Extract points from geometry
                points = []

                # Case 1: Tuple of start and end points (common for curve members)
                if isinstance(member.geometry, tuple) and len(member.geometry) == 2:
                    # For curve members with start and end point geometry
                    start_point = member.geometry[0]
                    end_point = member.geometry[1]

                    if all(
                        isinstance(p, (tuple, list)) and len(p) == 3
                        for p in (start_point, end_point)
                    ):
                        points = [start_point, end_point]

                # Case 2: Dict with boundaries (common for surface members)
                elif (
                    isinstance(member.geometry, dict)
                    and "boundaries" in member.geometry
                ):
                    boundaries = member.geometry.get("boundaries", [])
                    # Flatten the list of points
                    for boundary in boundaries:
                        points.extend(boundary)

                # Case 3: List of points (alternative format)
                elif isinstance(member.geometry, list) and all(
                    isinstance(p, (tuple, list)) and len(p) == 3
                    for p in member.geometry
                ):
                    points = member.geometry

                # Generate nodes from points
                member_node_ids = []
                for point in points:
                    if len(point) == 3:
                        # Create or reuse existing node
                        existing_node = next(
                            (
                                node_id
                                for node_id, coords in self.nodes.items()
                                if np.allclose(coords, point)
                            ),
                            None,
                        )

                        if existing_node is None:
                            # Create new node
                            self.nodes[node_id] = tuple(point)
                            member_node_ids.append(node_id)
                            node_id += 1
                        else:
                            member_node_ids.append(existing_node)

                # Generate elements
                if member_node_ids:
                    # Determine element type based on member type
                    if isinstance(member, CurveMember):
                        element_type = "B31"  # Beam element
                    elif isinstance(member, SurfaceMember):
                        element_type = "S4"  # Shell element
                    else:
                        element_type = "C3D4"  # Default to tetrahedral

                    # Create elements by connecting consecutive nodes
                    if (
                        len(member_node_ids) >= 2
                    ):  # Need at least 2 nodes for an element
                        for i in range(len(member_node_ids) - 1):
                            # Create element connecting two consecutive nodes
                            self.elements[element_id] = {
                                "type": element_type,
                                "nodes": [member_node_ids[i], member_node_ids[i + 1]],
                            }

                            # Create element set for this member
                            member_element_set = f"MEMBER_{member.id}_ELEMENTS"
                            if member_element_set not in self.element_sets:
                                self.element_sets[member_element_set] = []
                            self.element_sets[member_element_set].append(element_id)

                            # Also add to a set with just the member ID for section assignment
                            member_set = f"MEMBER_{member.id}"
                            if member_set not in self.element_sets:
                                self.element_sets[member_set] = []
                            self.element_sets[member_set].append(element_id)

                            element_id += 1

        # Log generation results
        logger.info(f"Generated {len(self.nodes)} nodes")
        logger.info(f"Generated {len(self.elements)} elements")
        logger.info(f"Node sets: {list(self.node_sets.keys())}")
        logger.info(f"Element sets: {list(self.element_sets.keys())}")

    def generate_input_file(self, output_path: str) -> str:
        """
        Generate a complete CalculiX input file.

        Args:
            output_path (str): Path where the input file will be written.

        Returns:
            str: Path to the generated input file.
        """
        try:
            # Ensure the output directory exists
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

            with open(output_path, "w") as f:
                self._write_header(f)
                self._write_nodes(f)
                self._write_elements(f)
                self._write_node_sets(f)
                self._write_element_sets(f)
                self._write_materials(f)
                self._write_sections(f)

                # Write boundary conditions (these can be outside the step)
                write_boundary_conditions(
                    f,
                    self.domain_model,
                    self.node_sets,
                    self.element_sets,
                    dict(self.nodes),
                )

                # REMOVED: Don't call write_loads here since loads need to be
                # defined inside the step section
                # write_loads(
                #     f,
                #     self.domain_model,
                #     self.node_sets,
                #     self.element_sets,
                #     dict(self.nodes),
                # )

                # Write analysis steps with appropriate analysis type
                # The write_analysis_steps function will now handle writing the loads
                # inside the step section
                write_analysis_steps(
                    f, self.domain_model, self.analysis_config.get_analysis_type()
                )

            logger.info(f"Generated CalculiX input file: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error generating input file: {e}")
            raise AnalysisError(f"Failed to generate input file: {str(e)}")

    def _write_header(self, file: TextIO) -> None:
        """Write the header section of the input file."""
        file.write(
            "** CalculiX Input File generated by IFC Structural Mechanics Analysis\n"
        )
        file.write("** Model ID: " + str(self.domain_model.id) + "\n")
        if self.domain_model.name:
            file.write("** Model Name: " + self.domain_model.name + "\n")
        if self.domain_model.description:
            file.write("** Description: " + self.domain_model.description + "\n")
        file.write(
            "** Analysis Type: " + self.analysis_config.get_analysis_type() + "\n"
        )
        file.write("**\n\n")

    def _write_nodes(self, file: TextIO) -> None:
        """Write node definitions to the input file."""
        file.write("*NODE\n")

        # Write actual nodes if available
        if self.nodes:
            for node_id, (x, y, z) in sorted(self.nodes.items()):
                file.write(f"{node_id}, {x:.6e}, {y:.6e}, {z:.6e}\n")
        else:
            logger.warning("No nodes found for input file")
            file.write("** WARNING: No nodes generated\n")

        file.write("\n")

    def _write_elements(self, file: TextIO) -> None:
        """Write element definitions to the input file."""
        # Group elements by type
        element_types = {}
        for element_id, element_data in self.elements.items():
            element_type = element_data["type"]
            if element_type not in element_types:
                element_types[element_type] = []
            element_types[element_type].append((element_id, element_data["nodes"]))

        # Write elements for each type
        for element_type, elements in element_types.items():
            file.write(f"*ELEMENT, TYPE={element_type}\n")
            for element_id, nodes in elements:
                node_str = ", ".join(map(str, nodes))
                file.write(f"{element_id}, {node_str}\n")
            file.write("\n")

        # Warn if no elements
        if not element_types:
            logger.warning("No elements found for input file")
            file.write("** WARNING: No elements generated\n")
            file.write("\n")

    def _write_node_sets(self, file: TextIO) -> None:
        """Write node sets to the input file."""
        for set_name, node_ids in self.node_sets.items():
            if node_ids:
                file.write(f"*NSET, NSET={set_name}\n")
                # Write with at most 8 nodes per line
                for i in range(0, len(node_ids), 8):
                    line_nodes = node_ids[i : i + 8]
                    line = ", ".join(map(str, line_nodes))
                    file.write(f"{line}\n")
                file.write("\n")

    def _write_element_sets(self, file: TextIO) -> None:
        """Write element sets to the input file."""
        for set_name, element_ids in self.element_sets.items():
            if element_ids:
                file.write(f"*ELSET, ELSET={set_name}\n")
                # Write with at most 8 elements per line
                for i in range(0, len(element_ids), 8):
                    line_elements = element_ids[i : i + 8]
                    line = ", ".join(map(str, line_elements))
                    file.write(f"{line}\n")
                file.write("\n")

    def _write_materials(self, file: TextIO) -> None:
        """
        Write material definitions to the input file.

        Materials are defined based on the material properties in the domain model.

        Args:
            file (TextIO): The file object to write to.
        """
        # Collect unique materials from members
        materials = {}
        for member in self.domain_model.members:
            if member.material and member.material.id not in materials:
                materials[member.material.id] = member.material

        # Write each material
        for material_id, material in materials.items():
            file.write(f"*MATERIAL, NAME=MAT_{material_id}\n")

            # Write elastic properties
            file.write("*ELASTIC\n")
            file.write(
                f"{material.elastic_modulus:.6e}, {material.poisson_ratio:.6e}\n"
            )

            # Write density if available
            if hasattr(material, "density") and material.density is not None:
                file.write("*DENSITY\n")
                file.write(f"{material.density:.6e}\n")

            file.write("\n")

    def _write_sections(self, file: TextIO) -> None:
        """
        Write section definitions to the input file.

        Sections define the geometry of structural members and are associated
        with element sets.

        Args:
            file (TextIO): The file object to write to.
        """
        # Process curve members (beam sections)
        beam_sections = {}
        for member in self.domain_model.members:
            if (
                isinstance(member, CurveMember)
                and hasattr(member, "section")
                and member.section
            ):
                set_name = f"MEMBER_{member.id}"
                if set_name not in self.element_sets:
                    # Create an element set for this member if it doesn't exist
                    self.element_sets[set_name] = []
                beam_sections[set_name] = (member.section, member.material)

        # Write beam section definitions
        for set_name, (section, material) in beam_sections.items():
            if (
                hasattr(section, "section_type")
                and section.section_type == "rectangular"
            ):
                file.write(
                    f"*BEAM SECTION, ELSET={set_name}, MATERIAL=MAT_{material.id}, SECTION=RECT\n"
                )
                width = section.dimensions.get("width", 0.1)
                height = section.dimensions.get("height", 0.2)
                file.write(f"{width:.6e}, {height:.6e}\n")
                # Direction cosines defining the local beam n1 direction (default: 0,0,-1)
                file.write("0.0, 0.0, -1.0\n\n")
            elif (
                hasattr(section, "section_type") and section.section_type == "circular"
            ):
                file.write(
                    f"*BEAM SECTION, ELSET={set_name}, MATERIAL=MAT_{material.id}, SECTION=CIRC\n"
                )
                radius = section.dimensions.get("radius", 0.1)
                file.write(f"{radius:.6e}\n")
                # Direction cosines defining the local beam n1 direction (default: 0,0,-1)
                file.write("0.0, 0.0, -1.0\n\n")
            else:
                # For other section types or if section_type isn't available, use a general section
                file.write(
                    f"*BEAM GENERAL SECTION, ELSET={set_name}, MATERIAL=MAT_{material.id}\n"
                )
                # Area, Iyy, Izz, Iyz, It, Warping constant
                area = getattr(section, "area", 0.01)
                i_yy = getattr(section, "moment_of_inertia_y", area * 0.01)
                i_zz = getattr(section, "moment_of_inertia_z", area * 0.01)
                i_yz = 0.0  # Assumed for most sections
                it = getattr(section, "torsional_constant", area * 0.01)
                warping = getattr(section, "warping_constant", 0.0) or 0.0
                file.write(
                    f"{area:.6e}, {i_yy:.6e}, {i_zz:.6e}, {i_yz:.6e}, {it:.6e}, {warping:.6e}\n"
                )
                # Direction cosines defining the local beam n1 direction (default: 0,0,-1)
                file.write("0.0, 0.0, -1.0\n\n")

        # Process surface members (shell thicknesses)
        shell_thicknesses = {}
        for member in self.domain_model.members:
            if (
                isinstance(member, SurfaceMember)
                and hasattr(member, "thickness")
                and member.thickness
            ):
                set_name = f"MEMBER_{member.id}"
                if set_name not in self.element_sets:
                    # Create an element set for this member if it doesn't exist
                    self.element_sets[set_name] = []
                shell_thicknesses[set_name] = (member.thickness, member.material)

        # Write shell section definitions
        for set_name, (thickness, material) in shell_thicknesses.items():
            file.write(
                f"*SHELL SECTION, ELSET={set_name}, MATERIAL=MAT_{material.id}\n"
            )
            thickness_value = getattr(thickness, "value", 0.1)
            file.write(f"{thickness_value:.6e}\n\n")
