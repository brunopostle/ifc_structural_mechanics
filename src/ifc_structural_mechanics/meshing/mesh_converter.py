"""
Mesh conversion module for the IFC structural analysis extension.

This module provides functionality to convert Gmsh mesh files to CalculiX input format,
mapping domain model properties to mesh elements.
"""

import os
import logging
from typing import List, Optional, Union, Tuple

import meshio
import numpy as np

from ..domain.structural_model import StructuralModel
from ..mapping.domain_to_calculix import DomainToCalculixMapper
from ..utils.error_handling import MeshingError
from ..utils.temp_dir import get_temp_dir, create_temp_subdir

# Set up logger
logger = logging.getLogger(__name__)


class MeshConverter:
    """
    Converts mesh files to CalculiX input format.

    This class handles the conversion of mesh files produced by Gmsh to the
    input format required by CalculiX, mapping domain model properties to
    mesh elements as needed.
    """

    # Element type mapping from Gmsh to CalculiX
    # Based on common element types used in structural analysis
    ELEMENT_TYPE_MAPPING = {
        # Line elements (beams, trusses)
        "line": "B31",  # 2-node beam element
        "line2": "B31",  # 2-node beam element
        "line3": "B32",  # 3-node beam element
        # Triangle elements (shells)
        "triangle": "S3",  # 3-node shell element
        "triangle3": "S3",  # 3-node shell element
        "triangle6": "S6",  # 6-node shell element
        # Quadrilateral elements (shells)
        "quad": "S4",  # 4-node shell element
        "quad4": "S4",  # 4-node shell element
        "quad8": "S8",  # 8-node shell element
        "quad9": "S9",  # 9-node shell element
        # Tetrahedral elements (solids)
        "tetra": "C3D4",  # 4-node tetrahedral element
        "tetra10": "C3D10",  # 10-node tetrahedral element
        # Hexahedral elements (solids)
        "hexahedron": "C3D8",  # 8-node hexahedral element
        "hexahedron20": "C3D20",  # 20-node hexahedral element
        "hexahedron27": "C3D27",  # 27-node hexahedral element
    }

    def __init__(
        self,
        domain_model: Optional[StructuralModel] = None,
        mapper: Optional[DomainToCalculixMapper] = None,
    ):
        """
        Initialize the mesh converter.

        Args:
            domain_model (Optional[StructuralModel]): The domain model to use for property mapping.
            mapper (Optional[DomainToCalculixMapper]): A pre-existing mapper to use for
                tracking mappings between domain model and CalculiX entities.
        """
        self.domain_model = domain_model

        # Use provided mapper or create a new one
        self.mapper = mapper or DomainToCalculixMapper()

        # Track sets of nodes and elements for different entity types
        self.node_sets = {}
        self.element_sets = {}

        # For backward compatibility with existing tests
        # This maps mesh elements to domain model members
        self.element_to_member_map = {}

        # Create a dedicated working directory for this converter
        self.work_dir = create_temp_subdir(prefix="mesh_converter_")

    def convert_mesh(
        self,
        mesh_file: Optional[Union[str, None]] = None,
        output_file: str = "",
        format: str = "inp",
        mapping_file: Optional[str] = None,
        mesh: Optional[meshio.Mesh] = None,
    ) -> str:
        """
        Convert a mesh file to CalculiX input format.

        Args:
            mesh_file (Optional[Union[str, None]]): Path to the input mesh file.
            output_file (str): Path to the output file.
            format (str): Format of the output file. Default is "inp" for CalculiX.
            mapping_file (Optional[str]): Path where the mapping information should be saved.
            mesh (Optional[meshio.Mesh]): Pre-created mesh object (used in testing/direct conversion)

        Returns:
            str: Path to the converted mesh file.

        Raises:
            MeshingError: If an error occurs during mesh conversion.
        """
        try:
            # Read the mesh file using meshio if not provided directly
            if mesh is None:
                if mesh_file is None:
                    raise ValueError("Either mesh_file or mesh must be provided")
                mesh = meshio.read(mesh_file)

            # If output_file is not specified, create a temporary one in our working directory
            if not output_file:
                output_file = os.path.join(self.work_dir, f"converted_mesh.{format}")

            if format.lower() == "inp":
                # Write directly to CalculiX .inp format
                result_file = self._write_inp_file(mesh, output_file)

                # Save mapping information if requested
                if mapping_file:
                    try:
                        self.mapper.create_mapping_file(mapping_file)
                        logger.info(f"Mapping information saved to {mapping_file}")
                    except Exception as e:
                        logger.warning(f"Failed to save mapping information: {str(e)}")

                return result_file
            else:
                # Use meshio to convert to the requested format
                meshio.write(output_file, mesh, file_format=format)
                return output_file

        except Exception as e:
            raise MeshingError(f"Error converting mesh file: {str(e)}")

    def _write_inp_file(self, mesh: meshio.Mesh, output_file: str) -> str:
        """
        Write a CalculiX .inp file from the mesh data.

        Args:
            mesh (meshio.Mesh): The mesh data.
            output_file (str): Path to the output .inp file.

        Returns:
            str: Path to the written .inp file.

        Raises:
            MeshingError: If an error occurs during file writing.
        """
        try:
            # Ensure the output directory exists
            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

            with open(output_file, "w") as f:
                # Write header
                f.write(
                    "** CalculiX Input File generated by IFC Structural Mechanics Analysis\n"
                )
                f.write("** Mesh converted from Gmsh\n")
                f.write("**\n\n")

                # Write nodes
                self._write_nodes(mesh, f)

                # Write elements
                self._write_elements(mesh, f)

                # Write node sets
                self._write_node_sets(f)

                # Write element sets
                self._write_element_sets(f)

                # If domain model is available, write additional sections
                if self.domain_model:
                    # Write materials
                    self._write_materials(f)

                    # Write element properties (sections, thicknesses)
                    self._write_element_properties(f)

                    # Write boundary conditions
                    self._write_boundary_conditions(f)

                return output_file

        except Exception as e:
            raise MeshingError(f"Error writing CalculiX input file: {str(e)}")

    def _write_nodes(self, mesh: meshio.Mesh, file) -> None:
        """
        Write node definitions to the CalculiX input file.

        Args:
            mesh (meshio.Mesh): The mesh data.
            file: The file object to write to.
        """
        # Write node section header
        file.write("*NODE\n")

        # Write each node: ID, X, Y, Z
        for i, (x, y, z) in enumerate(mesh.points):
            # CalculiX node IDs start from 1
            node_id = i + 1
            file.write(f"{node_id}, {x:.6e}, {y:.6e}, {z:.6e}\n")

            # Register this node in the mapper if domain model is available
            if self.domain_model:
                # In a real implementation, we would look up the corresponding domain entity
                # For now, we just register with a placeholder domain ID
                domain_id = f"node_{node_id}"
                self.mapper.register_node(domain_id, node_id)

        file.write("\n")

    def _write_elements(self, mesh: meshio.Mesh, file) -> None:
        """
        Write element definitions to the CalculiX input file with improved mapping.

        Args:
            mesh (meshio.Mesh): The mesh data.
            file: The file object to write to.
        """
        # Process each element block in the mesh
        element_id = 1  # Element IDs start from 1

        # Prepare to track the element types
        element_sets_by_type = {}

        # Process cells with different methods based on meshio version
        def _get_cell_blocks(mesh):
            # Try different methods to extract cell data
            try:
                # Newer meshio versions (dictionary-like)
                if hasattr(mesh.cells, "items"):
                    return list(mesh.cells.items())

                # List of CellBlock objects
                if hasattr(mesh.cells[0], "type"):
                    return [
                        (cell_block.type, cell_block.data) for cell_block in mesh.cells
                    ]

                # Fallback to old tuple-based approach
                return list(mesh.cells)
            except Exception as e:
                logger.warning(f"Could not extract cell blocks: {e}")
                return []

        # First pass: identify elements types and prepare element sets
        for block_name, block_cells in _get_cell_blocks(mesh):
            # Map Gmsh element type to CalculiX
            calculix_type = self.ELEMENT_TYPE_MAPPING.get(block_name)

            if calculix_type:
                set_name = f"ELSET_{block_name.upper()}"
                if set_name not in element_sets_by_type:
                    element_sets_by_type[set_name] = {
                        "type": calculix_type,
                        "elements": [],
                    }

                # Store the element IDs for this type
                start_id = element_id
                end_id = start_id + len(block_cells) - 1
                element_sets_by_type[set_name]["elements"].extend(
                    range(start_id, end_id + 1)
                )
                element_id = end_id + 1

        # Reset element_id for the second pass
        element_id = 1

        # Second pass: write element definitions by type
        for block_name, block_cells in _get_cell_blocks(mesh):
            calculix_type = self.ELEMENT_TYPE_MAPPING.get(block_name)

            if calculix_type:
                set_name = f"ELSET_{block_name.upper()}"

                # Write element section header with explicit TYPE and ELSET
                file.write(f"*ELEMENT, TYPE={calculix_type}, ELSET={set_name}\n")

                # Add to element sets tracking
                if set_name not in self.element_sets:
                    self.element_sets[set_name] = []

                # Write each element
                for cell in block_cells:
                    # Add 1 to node indices (CalculiX uses 1-based indexing)
                    node_indices = [idx + 1 for idx in cell]

                    # Write element line
                    nodes_str = ", ".join(map(str, node_indices))
                    file.write(f"{element_id}, {nodes_str}\n")

                    # Add to element set
                    self.element_sets[set_name].append(element_id)

                    # Map element to domain entity
                    if self.domain_model:
                        # Try to map using physical coordinates
                        cell_nodes = [mesh.points[idx] for idx in cell]
                        domain_entity_id = self._map_element_to_member_by_coordinates(
                            element_id, calculix_type, cell_nodes
                        )

                        # Fallback to mapping by element type
                        if not domain_entity_id:
                            domain_entity_id = self._map_element_to_member(
                                element_id, block_name, cell
                            )

                        # Register the mapping if found
                        if domain_entity_id:
                            self.mapper.register_element(
                                domain_entity_id,
                                element_id,
                                self._get_specific_type(block_name),
                            )

                            # Create member-specific element set
                            member_set = f"MEMBER_{domain_entity_id}"
                            if member_set not in self.element_sets:
                                self.element_sets[member_set] = []
                            self.element_sets[member_set].append(element_id)

                    element_id += 1

                file.write("\n")

    def _get_specific_type(self, block_name: str) -> Optional[str]:
        """
        Determine the specific element type based on Gmsh block name.
        """
        if block_name.startswith(("line", "edge")):
            return "beam"
        elif block_name.startswith(("triangle", "quad", "polygon")):
            return "shell"
        elif block_name.startswith(("tetra", "hexa")):
            return "solid"
        return None

    def _map_element_to_member_by_coordinates(
        self, element_id: int, element_type: str, nodes: List[np.ndarray]
    ) -> Optional[str]:
        """
        Map a mesh element to a domain model member by checking coordinates.

        This method tries to identify corresponding domain member based on spatial
        overlap between elements and member geometries.

        Args:
            element_id (int): The element's ID
            element_type (str): The CalculiX element type
            nodes (List[np.ndarray]): The node coordinates of the element

        Returns:
            Optional[str]: The domain entity ID if found
        """
        # Only attempt mapping if a domain model exists
        if not self.domain_model or not self.domain_model.members:
            return None

        # Calculate element center
        if not nodes:
            return None

        element_center = np.mean(nodes, axis=0)

        # Determine if this is a curve (beam) or surface (shell) element
        is_beam = element_type in ["B31", "B32"]
        is_shell = element_type in ["S3", "S4", "S6", "S8", "S9"]

        for member in self.domain_model.members:
            # Match element type to member type
            if is_beam and member.entity_type == "curve":
                # Check if element is part of this curve
                if hasattr(member, "geometry"):
                    geometry = member.geometry

                    # Handle different geometry formats
                    curve_points = []
                    if isinstance(geometry, tuple) and len(geometry) == 2:
                        curve_points = [geometry[0], geometry[1]]
                    elif isinstance(geometry, list) and all(
                        isinstance(p, (list, tuple)) for p in geometry
                    ):
                        curve_points = geometry
                    elif isinstance(geometry, dict) and "boundaries" in geometry:
                        if geometry["boundaries"] and isinstance(
                            geometry["boundaries"][0], list
                        ):
                            curve_points = geometry["boundaries"][0]

                    # If we have valid curve points, check proximity
                    if curve_points:
                        # For a beam element, check if it's near any segment of the curve
                        for i in range(len(curve_points) - 1):
                            line_start = np.array(curve_points[i])
                            line_end = np.array(curve_points[i + 1])

                            # Check distance from element center to line segment
                            if (
                                self._point_to_line_distance(
                                    element_center, line_start, line_end
                                )
                                < 0.1
                            ):
                                return member.id

            elif is_shell and member.entity_type == "surface":
                # Check if element is part of this surface
                if hasattr(member, "geometry"):
                    geometry = member.geometry

                    # Extract surface boundary
                    boundary_points = []
                    if isinstance(geometry, dict) and "boundaries" in geometry:
                        if geometry["boundaries"] and isinstance(
                            geometry["boundaries"][0], list
                        ):
                            boundary_points = geometry["boundaries"][0]

                    # If we have valid boundary, check if element center is inside
                    if boundary_points and len(boundary_points) >= 3:
                        # Project to 2D for point-in-polygon test
                        # This is simplified - in a real implementation you'd project onto the proper plane
                        if self._point_in_polygon_2d(element_center, boundary_points):
                            return member.id

        return None

    def _point_to_line_distance(self, point, line_start, line_end):
        """Calculate the distance from a point to a line segment."""
        line_vec = line_end - line_start
        point_vec = point - line_start
        line_len = np.linalg.norm(line_vec)

        if line_len == 0:
            return np.linalg.norm(point_vec)

        # Calculate projection
        line_unit_vec = line_vec / line_len
        projection = np.dot(point_vec, line_unit_vec)

        if projection <= 0:
            return np.linalg.norm(point_vec)
        elif projection >= line_len:
            return np.linalg.norm(point - line_end)
        else:
            # Distance to line
            return np.linalg.norm(point_vec - projection * line_unit_vec)

    def _point_in_polygon_2d(self, point, polygon):
        """
        Determine if a point is inside a polygon using ray casting algorithm.
        This is a 2D implementation that works on the XY plane.
        """
        # Extract only x and y coordinates
        x, y = point[0], point[1]
        n = len(polygon)
        inside = False

        p1x, p1y = polygon[0][0], polygon[0][1]
        for i in range(n + 1):
            p2x, p2y = polygon[i % n][0], polygon[i % n][1]
            if y > min(p1y, p2y) and y <= max(p1y, p2y) and x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
            p1x, p1y = p2x, p2y

        return inside

    def _map_element_to_member(
        self, element_id: int, element_type: str, nodes: List[int]
    ) -> Optional[str]:
        """
        Map a mesh element to a domain model member.

        This method tries to identify the corresponding domain member
        based on simple heuristics and properly populates element sets.

        Args:
            element_id (int): The element's ID
            element_type (str): The Gmsh element type
            nodes (List[int]): The nodes of the element

        Returns:
            Optional[str]: The domain entity ID if found
        """
        # Only attempt mapping if a domain model exists
        if not self.domain_model or not self.domain_model.members:
            return None

        # Determine element type category
        if element_type.startswith(("line", "edge")):
            category = "curve"
        elif element_type.startswith(("triangle", "quad", "polygon")):
            category = "surface"
        elif element_type.startswith(("tetra", "hexa")):
            category = "solid"
        else:
            # Unknown element type, skip mapping
            logger.warning(
                f"Unknown element type {element_type} for element {element_id}, skipping mapping"
            )
            return None

        # Look for members of the appropriate type
        for member in self.domain_model.members:
            if member.entity_type == category:
                # Store in element_to_member_map for backward compatibility and future reference
                self.element_to_member_map[element_id] = member.id

                # Create or update element set for this member
                member_set_key = f"MEMBER_{member.id}"
                if member_set_key not in self.element_sets:
                    self.element_sets[member_set_key] = []

                # Add element to the set if not already there
                if element_id not in self.element_sets[member_set_key]:
                    self.element_sets[member_set_key].append(element_id)
                    logger.debug(f"Added element {element_id} to set {member_set_key}")

                return member.id

        # No suitable member found
        logger.warning(
            f"No matching member found for element {element_id} of type {element_type}"
        )
        return None

    def _write_node_sets(self, file) -> None:
        """
        Write node sets to the CalculiX input file.

        Args:
            file: The file object to write to.
        """
        # Write each node set
        for set_name, node_ids in self.node_sets.items():
            if node_ids:
                file.write(f"*NSET, NSET={set_name}\n")

                # Write node IDs with at most 8 per line
                for i in range(0, len(node_ids), 8):
                    line_nodes = node_ids[i : i + 8]
                    line = ", ".join(map(str, line_nodes))
                    file.write(f"{line}\n")

                file.write("\n")

    def _write_element_sets(self, file) -> None:
        """
        Write element sets to the CalculiX input file.

        Args:
            file: The file object to write to.
        """
        # Write each element set
        for set_name, element_ids in self.element_sets.items():
            if element_ids:
                file.write(f"*ELSET, ELSET={set_name}\n")

                # Write element IDs with at most 8 per line
                for i in range(0, len(element_ids), 8):
                    line_elements = element_ids[i : i + 8]
                    line = ", ".join(map(str, line_elements))
                    file.write(f"{line}\n")

                file.write("\n")

    def _write_materials(self, file) -> None:
        """
        Write material definitions to the CalculiX input file.

        Args:
            file: The file object to write to.
        """
        if not self.domain_model:
            return

        # Collect unique materials from members
        materials = {}
        for member in self.domain_model.members:
            if member.material and member.material.id not in materials:
                materials[member.material.id] = member.material

        # Write each material
        for material_id, material in materials.items():
            material_name = f"MAT_{material_id}"
            file.write(f"*MATERIAL, NAME={material_name}\n")

            # Register this material in the mapper
            self.mapper.register_material(material_id, material_name)

            # Write elastic properties
            file.write("*ELASTIC\n")
            young_modulus = getattr(
                material, "elastic_modulus", 2.1e11
            )  # Default to steel
            poisson_ratio = getattr(material, "poisson_ratio", 0.3)  # Default value

            # Handle different types to avoid formatting issues
            if isinstance(young_modulus, (int, float)):
                young_str = f"{young_modulus:.6e}"
            else:
                young_str = str(young_modulus)

            if isinstance(poisson_ratio, (int, float)):
                poisson_str = f"{poisson_ratio:.6e}"
            else:
                poisson_str = str(poisson_ratio)

            file.write(f"{young_str}, {poisson_str}\n")

            # Write density if available
            density = getattr(material, "density", None)
            if density is not None:
                file.write("*DENSITY\n")
                if isinstance(density, (int, float)):
                    density_str = f"{density:.6e}"
                else:
                    density_str = str(density)
                file.write(f"{density_str}\n")

            file.write("\n")

    def _write_element_properties(self, file) -> None:
        """
        Write element properties to the CalculiX input file with improved assignment.

        Args:
            file: The file object to write to.

        Raises:
            MeshingError: If required element sets are missing for property assignment.
        """
        if not self.domain_model:
            return

        from ..utils.error_handling import MeshingError

        file.write("** Element Properties\n")

        # Process curve members (beam sections)
        beam_members = [
            m
            for m in self.domain_model.members
            if m.entity_type == "curve" and hasattr(m, "section")
        ]

        for member in beam_members:
            # Look for element sets for this member
            member_set = f"MEMBER_{member.id}"

            # If no specific set exists, check which elements might belong to this member
            if member_set not in self.element_sets or not self.element_sets[member_set]:
                logger.warning(
                    f"No elements mapped to beam member {member.id}, checking element-to-member map"
                )
                # Try to find elements that we've mapped to this member
                mapped_elements = []
                for element_id, member_id in self.element_to_member_map.items():
                    if member_id == member.id:
                        mapped_elements.append(element_id)

                if mapped_elements:
                    self.element_sets[member_set] = mapped_elements
                    logger.info(
                        f"Created element set {member_set} with {len(mapped_elements)} elements"
                    )
                else:
                    # No elements found for this member
                    raise MeshingError(
                        f"No elements found for beam member {member.id}. Cannot create section without elements."
                    )

            # Only proceed if we have an element set with elements
            if member_set in self.element_sets and self.element_sets[member_set]:
                material_name = f"MAT_{member.material.id}"

                # Determine section type
                section_type = "RECT"  # Default rectangular
                if hasattr(member.section, "section_type"):
                    if member.section.section_type == "circular":
                        section_type = "CIRC"
                    elif member.section.section_type == "i":
                        section_type = "I"

                file.write(
                    f"*BEAM SECTION, ELSET={member_set}, MATERIAL={material_name}, SECTION={section_type}\n"
                )

                # Register section in mapper
                self.mapper.register_section(
                    member.section.id, f"SECT_{member.section.id}"
                )

                # Write dimensions based on section type
                if section_type == "RECT":
                    width = member.section.dimensions.get("width", 0.1)
                    height = member.section.dimensions.get("height", 0.2)
                    file.write(f"{width:.6e}, {height:.6e}\n")
                elif section_type == "CIRC":
                    radius = member.section.dimensions.get("radius", 0.1)
                    file.write(f"{radius:.6e}\n")
                elif section_type == "I":
                    # For I-section, use a general section approach
                    file.write(
                        f"*BEAM GENERAL SECTION, ELSET={member_set}, MATERIAL={material_name}\n"
                    )
                    # Approximate I-section properties
                    area = getattr(member.section, "area", 0.01)
                    i_yy = getattr(member.section, "moment_of_inertia_y", area * 0.01)
                    i_zz = getattr(member.section, "moment_of_inertia_z", area * 0.01)
                    i_yz = 0.0  # Usually 0 for symmetric sections
                    it = getattr(member.section, "torsional_constant", area * 0.01)
                    warping = getattr(member.section, "warping_constant", 0.0) or 0.0
                    file.write(
                        f"{area:.6e}, {i_yy:.6e}, {i_zz:.6e}, {i_yz:.6e}, {it:.6e}, {warping:.6e}\n"
                    )

                # Direction cosines (local orientation)
                file.write("0.0, 0.0, -1.0\n\n")

        # Process surface members (shell thicknesses)
        shell_members = [
            m
            for m in self.domain_model.members
            if m.entity_type == "surface" and hasattr(m, "thickness")
        ]

        for member in shell_members:
            # Look for element sets for this member
            member_set = f"MEMBER_{member.id}"

            # If no specific set exists, check which elements might belong to this member
            if member_set not in self.element_sets or not self.element_sets[member_set]:
                logger.warning(
                    f"No elements mapped to shell member {member.id}, checking element-to-member map"
                )
                # Try to find elements that we've mapped to this member
                mapped_elements = []
                for element_id, member_id in self.element_to_member_map.items():
                    if member_id == member.id:
                        mapped_elements.append(element_id)

                if mapped_elements:
                    self.element_sets[member_set] = mapped_elements
                    logger.info(
                        f"Created element set {member_set} with {len(mapped_elements)} elements"
                    )
                else:
                    # No elements found for this member
                    raise MeshingError(
                        f"No elements found for shell member {member.id}. Cannot create section without elements."
                    )

            # Only proceed if we have an element set with elements
            if member_set in self.element_sets and self.element_sets[member_set]:
                material_name = f"MAT_{member.material.id}"

                file.write(
                    f"*SHELL SECTION, ELSET={member_set}, MATERIAL={material_name}\n"
                )

                # Get thickness value
                thickness_value = getattr(member.thickness, "value", 0.1)
                file.write(f"{thickness_value:.6e}\n\n")

    def _write_boundary_conditions(self, file) -> None:
        """
        Write boundary conditions to the CalculiX input file.

        Args:
            file: The file object to write to.
        """
        if not self.domain_model:
            return

        # Find all nodes with boundary conditions
        for member in self.domain_model.members:
            for bc in getattr(member, "boundary_conditions", []):
                # In a real implementation, you would identify the specific nodes
                # where the boundary condition applies based on its location
                # For now, we'll use a placeholder approach

                # Create a node set for this boundary condition
                bc_id = getattr(bc, "id", f"BC_{len(self.node_sets) + 1}")
                set_name = f"BC_{bc_id}"

                # Register this boundary condition in the mapper
                self.mapper.register_boundary_condition(bc_id, set_name)

                # Find nodes that correspond to this member and boundary condition
                # For a real implementation, you would use the BC location
                # For this placeholder, we'll just use the first few nodes of the member's elements
                if member.id in self.mapper.get_domain_entities_by_type("element"):
                    # Get elements belonging to this member
                    member_elements = []
                    for element_id in self.mapper.get_ccx_entities_by_type("element"):
                        try:
                            if (
                                self.mapper.get_domain_entity_id(element_id, "element")
                                == member.id
                            ):
                                member_elements.append(element_id)
                        except KeyError:
                            continue

                    # Get nodes from the first element (placeholder approach)
                    if member_elements:
                        # We would need to determine which nodes correctly represent the BC
                        # For now, add a placeholder node set with a comment
                        self.node_sets[set_name] = [1]  # Placeholder
                        file.write(
                            f"** Boundary condition {bc_id} requires proper node identification\n"
                        )
                        file.write("** Current implementation uses a placeholder\n")

        # Write the actual boundary conditions
        file.write("** Boundary Conditions\n")

        # Write fixed boundary conditions
        has_fixed_bcs = False
        for member in self.domain_model.members:
            for bc in getattr(member, "boundary_conditions", []):
                bc_type = getattr(bc, "type", "")
                bc_id = getattr(bc, "id", "")
                set_name = f"BC_{bc_id}"

                if bc_type.lower() in ["fixed", "pinned", "roller"]:
                    has_fixed_bcs = True

                    file.write("*BOUNDARY\n")

                    # Different BC types constrain different degrees of freedom
                    if bc_type.lower() == "fixed":
                        # Fixed: constrain all 6 DOF (1-6)
                        file.write(f"{set_name}, 1, 6\n\n")
                    elif bc_type.lower() == "pinned":
                        # Pinned: constrain translations (1-3), but not rotations
                        file.write(f"{set_name}, 1, 3\n\n")
                    elif bc_type.lower() == "roller":
                        # Roller: constrain only in certain directions
                        # For simplicity, we'll constrain vertical movement (2) as an example
                        file.write(f"{set_name}, 2, 2\n\n")

        if not has_fixed_bcs:
            # If no boundary conditions were found, add a warning
            file.write("** WARNING: No fixed boundary conditions defined\n")
            file.write("** Add appropriate *BOUNDARY definitions here\n\n")

    def get_mapper(self) -> DomainToCalculixMapper:
        """
        Get the domain to CalculiX mapper.

        Returns:
            DomainToCalculixMapper: The mapper used by this converter.
        """
        return self.mapper

    @staticmethod
    def run_complete_workflow(
        domain_model: StructuralModel,
        output_inp_file: str,
        mapping_file: Optional[str] = None,
        meshing_config=None,
        system_config=None,
        intermediate_msh_file=None,
    ) -> Tuple[str, DomainToCalculixMapper]:
        """
        Run the complete meshing workflow from domain model to CalculiX input.

        This static method provides a convenient way to run the entire meshing pipeline
        in one step, from domain model to CalculiX input file.

        Args:
            domain_model (StructuralModel): The structural model to mesh.
            output_inp_file (str): Path where the final CalculiX input file should be written.
            mapping_file (Optional[str]): Path where the mapping information should be saved.
                If not provided, mapping information will not be saved.
            meshing_config (Optional): Meshing configuration to use.
            system_config (Optional): System configuration to use.
            intermediate_msh_file (Optional[str]): Path where the intermediate Gmsh mesh file
                should be written. If None, a temporary file will be used.

        Returns:
            Tuple[str, DomainToCalculixMapper]: Path to the generated CalculiX input file and the mapper
                used for the conversion.

        Raises:
            MeshingError: If an error occurs during any stage of the workflow.
        """
        from .gmsh_geometry import GmshGeometryConverter
        from .gmsh_runner import GmshRunner

        try:
            # First, ensure we're using the shared temp directory system
            temp_dir = get_temp_dir()

            # Create a mapper to track mappings throughout the workflow
            mapper = DomainToCalculixMapper()

            # Step 1: Convert domain model to Gmsh geometry
            logger.info("Converting domain model to Gmsh geometry...")
            geometry_converter = GmshGeometryConverter(meshing_config=meshing_config)
            entity_map = geometry_converter.convert_model(domain_model)
            logger.info(f"Created Gmsh geometry with {len(entity_map)} entities")

            # Step 2: Run the meshing process
            logger.info("Running Gmsh meshing process...")
            gmsh_runner = GmshRunner(
                meshing_config=meshing_config, system_config=system_config
            )
            success = gmsh_runner.run_meshing()

            if not success:
                raise MeshingError("Gmsh meshing process failed")

            # Generate mesh file
            if intermediate_msh_file is None:
                # Create a temporary mesh file in our shared temp directory
                intermediate_msh_file = os.path.join(
                    temp_dir, f"intermediate_{domain_model.id}.msh"
                )

            mesh_file = gmsh_runner.generate_mesh_file(intermediate_msh_file)
            logger.info(f"Generated mesh file at {mesh_file}")

            # Step 3: Convert mesh to CalculiX format
            logger.info("Converting mesh to CalculiX format...")
            mesh_converter = MeshConverter(domain_model=domain_model, mapper=mapper)
            inp_file = mesh_converter.convert_mesh(
                mesh_file, output_file=output_inp_file, mapping_file=mapping_file
            )
            logger.info(f"Generated CalculiX input file at {inp_file}")

            return inp_file, mapper

        except Exception as e:
            logger.error(f"Error in meshing workflow: {str(e)}")
            raise MeshingError(f"Complete meshing workflow failed: {str(e)}")
