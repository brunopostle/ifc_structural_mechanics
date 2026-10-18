"""
Result visualization using PyVista for interactive 3D rendering.

This module provides tools for visualizing structural analysis results including
deformed meshes, displacement fields, stress/strain contours, and more.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import meshio
    import pyvista as pv

    PYVISTA_AVAILABLE = True
except ImportError:
    PYVISTA_AVAILABLE = False

from ..domain.result import DisplacementResult, StressResult
from ..domain.structural_model import StructuralModel

logger = logging.getLogger(__name__)

# CalculiX element types and the VTK cells drawn for them, with the order of
# their nodes in the VTK cell. CalculiX lists a three-node beam as (start,
# middle, end) and VTK wants (start, end, middle); a six-node triangle is the
# same in both. A spring has one node and nothing to draw.
_CALCULIX_CELLS = {
    "B31": ("LINE", (0, 1)),
    "U1": ("LINE", (0, 1)),
    "B32R": ("QUADRATIC_EDGE", (0, 2, 1)),
    "S3": ("TRIANGLE", (0, 1, 2)),
    "S6": ("QUADRATIC_TRIANGLE", (0, 1, 2, 3, 4, 5)),
}
_NOT_DRAWN = {"SPRING1"}


def read_calculix_mesh(
    inp_file: str,
) -> Tuple[np.ndarray, np.ndarray, dict, Dict[int, List[int]]]:
    """Read the nodes and elements of a CalculiX input file as written.

    Args:
        inp_file: Path to the .inp file.

    Returns:
        The node numbers, their coordinates (one row each, in the same order),
        ``{VTK cell type: [connectivity as indices into the rows]}``, and the
        node numbers of every element drawn, by element number.

    Raises:
        ValueError: For an element type there is no cell for.
    """
    nodes: dict = {}
    elements: List[Tuple[str, int, List[int]]] = []
    section = None
    element_type = None
    pending: List[str] = []
    with open(inp_file) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                keyword = line.split(",")[0].strip().upper()
                section = keyword
                if keyword == "*ELEMENT":
                    options = {
                        key.strip().upper(): value.strip().upper()
                        for key, _, value in (
                            part.partition("=") for part in line.split(",")[1:]
                        )
                    }
                    element_type = options.get("TYPE")
                continue
            if section == "*NODE":
                values = [v for v in line.split(",") if v.strip()]
                nodes[int(values[0])] = [float(v) for v in values[1:4]]
            elif section == "*ELEMENT":
                pending.extend(v for v in line.split(",") if v.strip())
                if line.endswith(","):
                    continue
                numbers = [int(v) for v in pending]
                elements.append((element_type, numbers[0], numbers[1:]))
                pending = []

    node_ids = np.array(sorted(nodes), dtype=int)
    points = np.array([nodes[n] for n in node_ids], dtype=float).reshape(-1, 3)
    index = {int(n): i for i, n in enumerate(node_ids)}
    cells_by_type: dict = {}
    element_nodes: Dict[int, List[int]] = {}
    for element_type, number, connectivity in elements:
        if element_type in _NOT_DRAWN:
            continue
        element_nodes[number] = connectivity
        if element_type not in _CALCULIX_CELLS:
            raise ValueError(f"Element type {element_type} cannot be drawn")
        cell_name, order = _CALCULIX_CELLS[element_type]
        cell_type = getattr(pv.CellType, cell_name)
        cells_by_type.setdefault(cell_type, []).append(
            [index[connectivity[k]] for k in order]
        )
    return node_ids, points, cells_by_type, element_nodes


class ResultVisualizer:
    """
    Visualize structural analysis results using PyVista.

    This class handles loading mesh data, mapping analysis results to nodes/elements,
    and creating interactive 3D visualizations of deformed meshes with color-coded
    results (displacement, stress, strain).
    """

    def __init__(self, model: Optional[StructuralModel] = None):
        """
        Initialize the result visualizer.

        Args:
            model: Structural model with analysis results (optional)

        Raises:
            ImportError: If PyVista is not installed
        """
        if not PYVISTA_AVAILABLE:
            raise ImportError(
                "PyVista is required for visualization. Install with: pip install pyvista"
            )

        self.model = model
        self.mesh = None
        self.displaced_mesh = None

    def load_mesh_from_file(self, mesh_file: str) -> pv.UnstructuredGrid:
        """
        Load mesh from Gmsh .msh file.

        Args:
            mesh_file: Path to .msh file

        Returns:
            PyVista unstructured grid
        """
        logger.info(f"Loading mesh from {mesh_file}")

        # Use meshio to read Gmsh file
        mesh_data = meshio.read(mesh_file)

        # Convert to PyVista format
        cells = []
        cell_types = []

        # Map meshio cell types to VTK cell types
        vtk_type_map = {
            "line": pv.CellType.LINE,
            "line3": pv.CellType.QUADRATIC_EDGE,
            "triangle": pv.CellType.TRIANGLE,
            "triangle6": pv.CellType.QUADRATIC_TRIANGLE,
            "quad": pv.CellType.QUAD,
            "quad8": pv.CellType.QUADRATIC_QUAD,
            "tetra": pv.CellType.TETRA,
            "tetra10": pv.CellType.QUADRATIC_TETRA,
            "hexahedron": pv.CellType.HEXAHEDRON,
            "hexahedron20": pv.CellType.QUADRATIC_HEXAHEDRON,
            "wedge": pv.CellType.WEDGE,
        }

        for cell_block in mesh_data.cells:
            cell_type_str = cell_block.type
            if cell_type_str in vtk_type_map:
                vtk_type = vtk_type_map[cell_type_str]
                for cell in cell_block.data:
                    cells.append(np.insert(cell, 0, len(cell)))
                    cell_types.append(vtk_type)

        # Create PyVista unstructured grid
        cells_array = np.hstack(cells)
        self.mesh = pv.UnstructuredGrid(cells_array, cell_types, mesh_data.points)

        logger.info(
            f"Loaded mesh: {self.mesh.n_points} nodes, {self.mesh.n_cells} elements"
        )
        return self.mesh

    def load_mesh_from_frd(
        self, frd_file: str, inp_file: Optional[str] = None
    ) -> pv.UnstructuredGrid:
        """
        Load mesh from CalculiX FRD and INP files.

        The INP file has the beams and shells as written; the FRD file has the
        solids CalculiX expands them into, which keep the number of the element
        they came from. Each node of a solid is attributed to the node of its
        element it is nearest to, so a beam or shell node has the result nodes
        of its cross-section or thickness.

        Args:
            frd_file: Path to .frd file
            inp_file: Path to .inp file (defaults to same directory as frd_file)

        Returns:
            PyVista unstructured grid
        """
        logger.info(f"Loading mesh from FRD: {frd_file}")

        # Default inp_file location
        if inp_file is None:
            frd_path = Path(frd_file)
            inp_file = str(frd_path.parent / frd_path.stem) + ".inp"

        logger.info(f"Reading mesh structure from INP: {inp_file}")

        # Read FRD file for node coordinates (CalculiX renumbered nodes)
        frd_nodes = {}  # node_id -> [x, y, z]
        with open(frd_file, "r") as f:
            for line in f:
                if "PSTEP" in line:
                    break
                if line.startswith(" -1") and len(line) >= 37:
                    try:
                        node_id = int(line[3:13].strip())
                        x = float(line[13:25].strip())
                        y = float(line[25:37].strip())
                        z = float(line[37:49].strip()) if len(line) >= 49 else 0.0
                        frd_nodes[node_id] = np.array([x, y, z])
                    except (ValueError, IndexError):
                        pass

        logger.info(f"Parsed {len(frd_nodes)} nodes from FRD")

        # Read the mesh as written (meshio's Abaqus reader knows no B32R)
        node_ids, points, cells_by_type, input_elements = read_calculix_mesh(inp_file)
        self._mesh_node_ids = node_ids

        logger.info(
            f"Read INP mesh: {len(points)} nodes, "
            f"{sum(len(c) for c in cells_by_type.values())} elements"
        )

        # CalculiX draws beams and shells as the solids it expands them into,
        # which keep the number of their element: each of their nodes belongs
        # to the node of that element it is nearest to. A node of an element
        # that is not expanded (U1) keeps its own number.
        from ..analysis.results_parser import ResultsParser

        expanded = ResultsParser().parse_element_nodes(frd_file)
        coordinates = dict(zip((int(n) for n in node_ids), points))
        inp_to_frd_mapping: Dict[int, List[int]] = {}
        for element, own in input_elements.items():
            if element not in expanded:
                continue
            own_points = np.array([coordinates[n] for n in own])
            for result_node in expanded[element]:
                point = frd_nodes.get(result_node)
                if point is None:
                    continue
                nearest = int(np.argmin(np.linalg.norm(own_points - point, axis=1)))
                nodes = inp_to_frd_mapping.setdefault(own[nearest], [])
                if result_node not in nodes:
                    nodes.append(result_node)
        for node in coordinates:
            if node not in inp_to_frd_mapping and node in frd_nodes:
                inp_to_frd_mapping[node] = [node]

        logger.info(f"Mapped {len(inp_to_frd_mapping)} INP nodes to FRD nodes")

        # Store mapping for later use in apply_displacement_field
        self._inp_node_to_frd_node = inp_to_frd_mapping

        # Create PyVista mesh from INP data
        cells = []
        cell_types = []
        for vtk_type, connectivity in cells_by_type.items():
            for cell in connectivity:
                cells.append(np.insert(cell, 0, len(cell)))
                cell_types.append(vtk_type)

        cells_array = np.hstack(cells)
        self.mesh = pv.UnstructuredGrid(cells_array, cell_types, points)

        logger.info(
            f"Created mesh: {self.mesh.n_points} nodes, {self.mesh.n_cells} elements"
        )
        return self.mesh

    def apply_displacement_field(
        self,
        scale_factor: float = 1.0,
        displacement_results: Optional[List[DisplacementResult]] = None,
    ) -> pv.UnstructuredGrid:
        """
        Create displaced mesh by applying displacement field.

        Args:
            scale_factor: Scaling factor for displacements (for visualization)
            displacement_results: List of displacement results (or use model.results)

        Returns:
            Displaced PyVista mesh
        """
        if self.mesh is None:
            raise ValueError("Load mesh first using load_mesh_from_file()")

        # Get displacement results
        if displacement_results is None:
            if self.model is None:
                raise ValueError("No model or displacement results provided")
            displacement_results = [
                r for r in self.model.results if isinstance(r, DisplacementResult)
            ]

        if not displacement_results:
            logger.warning("No displacement results found")
            return self.mesh

        # Create displacement array (initialized to zero)
        n_points = self.mesh.n_points
        displacements = np.zeros((n_points, 3))
        displacement_magnitude = np.zeros(n_points)

        # Build FRD node ID to result mapping
        frd_result_map = {}
        for result in displacement_results:
            frd_node_id = int(result.reference_element)
            frd_result_map[frd_node_id] = result

        # Apply results through the expanded elements when they are known
        if hasattr(self, "_inp_node_to_frd_node"):
            logger.info("Using INP-to-FRD mapping for displacement field")
            mapped_count = 0
            for mesh_idx in range(n_points):
                inp_node_id = int(self._mesh_node_ids[mesh_idx])
                # The mean over a cross-section is the movement of its axis
                found = [
                    frd_result_map[n]
                    for n in self._inp_node_to_frd_node.get(inp_node_id, ())
                    if n in frd_result_map
                ]
                if found:
                    trans = np.mean([r.get_translations() for r in found], axis=0)
                    displacements[mesh_idx] = trans
                    displacement_magnitude[mesh_idx] = np.linalg.norm(trans)
                    mapped_count += 1
            logger.info(
                f"Mapped {mapped_count}/{n_points} nodes to displacement results"
            )
        else:
            # Fallback: assume sequential node IDs (1-based)
            logger.info("Using direct node ID mapping (1-based)")
            for result in displacement_results:
                try:
                    node_id = int(result.reference_element) - 1  # Convert to 0-based
                    if 0 <= node_id < n_points:
                        trans = result.get_translations()
                        displacements[node_id] = trans
                        displacement_magnitude[node_id] = result.get_magnitude()
                except (ValueError, IndexError) as e:
                    logger.warning(
                        f"Error processing displacement for node {result.reference_element}: {e}"
                    )

        # Create displaced mesh
        displaced_points = self.mesh.points + scale_factor * displacements
        self.displaced_mesh = self.mesh.copy()
        self.displaced_mesh.points = displaced_points

        # Add displacement magnitude as scalar field (in mm for readability)
        displacement_magnitude_mm = displacement_magnitude * 1000.0
        self.displaced_mesh["Displacement (mm)"] = displacement_magnitude_mm

        logger.info(f"Applied displacements with scale factor {scale_factor}")
        logger.info(
            f"Max displacement: {displacement_magnitude.max():.6e} m ({displacement_magnitude_mm.max():.4f} mm)"
        )

        return self.displaced_mesh

    def add_stress_field(
        self, stress_results: Optional[List[StressResult]] = None
    ) -> None:
        """
        Add stress field to mesh for visualization.

        Handles both node-based and element-based stress results. Uses INP-to-FRD
        node mapping if available to correctly map CalculiX results to mesh nodes.

        Args:
            stress_results: List of stress results (or use model.results)
        """
        if self.displaced_mesh is None:
            raise ValueError(
                "Create displaced mesh first using apply_displacement_field()"
            )

        # Get stress results
        if stress_results is None:
            if self.model is None:
                raise ValueError("No model or stress results provided")
            stress_results = [
                r for r in self.model.results if isinstance(r, StressResult)
            ]

        if not stress_results:
            logger.warning("No stress results found")
            return

        n_points = self.displaced_mesh.n_points
        von_mises = np.zeros(n_points)

        # Build FRD node ID to stress result mapping
        frd_stress_map = {}
        for result in stress_results:
            frd_node_id = int(result.reference_element)
            try:
                vm_stress = result.get_von_mises_stress()
                frd_stress_map[frd_node_id] = vm_stress
            except ValueError:
                pass

        logger.info(f"Parsed {len(frd_stress_map)} stress results from FRD")

        # Apply stress through the expanded elements when they are known
        if hasattr(self, "_inp_node_to_frd_node"):
            logger.info("Using INP-to-FRD mapping for stress field")
            mapped_count = 0
            for mesh_idx in range(n_points):
                inp_node_id = int(self._mesh_node_ids[mesh_idx])
                # The largest over a cross-section, which is on its faces
                found = [
                    frd_stress_map[n]
                    for n in self._inp_node_to_frd_node.get(inp_node_id, ())
                    if n in frd_stress_map
                ]
                if found:
                    von_mises[mesh_idx] = max(found)
                    mapped_count += 1
            logger.info(f"Mapped {mapped_count}/{n_points} nodes to stress results")
        else:
            # Fallback: try direct node ID mapping
            logger.info("Using direct node ID mapping for stress")
            stress_ids = list(frd_stress_map.keys())
            min_id = min(stress_ids)
            max_id = max(stress_ids)
            logger.info(
                f"Stress IDs range: {min_id} to {max_id}, mesh has {n_points} nodes"
            )

            if max_id <= n_points:
                # Direct mapping possible
                for frd_id, vm_stress in frd_stress_map.items():
                    node_idx = frd_id - 1  # Convert to 0-based
                    if 0 <= node_idx < n_points:
                        von_mises[node_idx] = vm_stress
            else:
                logger.warning(
                    f"Cannot map stress: FRD IDs ({min_id}-{max_id}) don't match mesh nodes (1-{n_points})"
                )

        # Add stress field to mesh
        self.displaced_mesh["Von Mises Stress"] = von_mises
        max_stress = von_mises.max()
        logger.info(f"Added stress field, max von Mises: {max_stress:.6e}")

    def plot_deformed(
        self,
        scale_factor: float = 1.0,
        show_undeformed: bool = True,
        field: str = "Displacement",
        cmap: str = "jet",
        screenshot: Optional[str] = None,
        window_size: Tuple[int, int] = (1024, 768),
    ) -> None:
        """
        Create interactive 3D plot of deformed mesh.

        Args:
            scale_factor: Displacement scale factor for visualization
            show_undeformed: Show original undeformed mesh as wireframe
            field: Scalar field to display ('Displacement', 'Von Mises Stress', etc.)
            cmap: Colormap name
            screenshot: If provided, save screenshot to this file path
            window_size: Window size (width, height)
        """
        if self.displaced_mesh is None:
            raise ValueError(
                "Create displaced mesh first using apply_displacement_field()"
            )

        # Create plotter (off-screen when saving screenshot)
        plotter = pv.Plotter(window_size=window_size, off_screen=bool(screenshot))
        plotter.add_title("Structural Analysis Results", font_size=14)

        # Add deformed mesh with color coding
        if field in self.displaced_mesh.array_names:
            plotter.add_mesh(
                self.displaced_mesh,
                scalars=field,
                cmap=cmap,
                show_edges=True,
                edge_color="gray",
                line_width=0.5,
                scalar_bar_args={
                    "title": field,
                    "vertical": True,
                    "position_x": 0.85,
                    "position_y": 0.1,
                    "fmt": "%.3g",
                },
            )
        else:
            logger.warning(f"Field '{field}' not found, showing without coloring")
            plotter.add_mesh(self.displaced_mesh, show_edges=True, color="lightblue")

        # Add undeformed mesh as wireframe
        if show_undeformed and self.mesh is not None:
            plotter.add_mesh(
                self.mesh,
                style="wireframe",
                color="gray",
                opacity=0.3,
                line_width=1.0,
                label="Undeformed",
            )

        # Add axes
        plotter.add_axes(xlabel="X", ylabel="Y", zlabel="Z")

        # Add legend if showing undeformed
        if show_undeformed:
            plotter.add_legend()

        # Save screenshot if requested
        if screenshot:
            plotter.show(screenshot=screenshot, window_size=window_size)
            logger.info(f"Screenshot saved to {screenshot}")
        else:
            # Interactive display
            plotter.show()

    def export_to_html(
        self,
        output_file: str,
        scale_factor: float = 1.0,
        field: str = "Displacement (mm)",
        cmap: str = "jet",
    ) -> None:
        """
        Export interactive 3D visualization to HTML file.

        Args:
            output_file: Output HTML file path
            scale_factor: Displacement scale factor
            field: Scalar field to display
            cmap: Colormap name
        """
        if self.displaced_mesh is None:
            raise ValueError(
                "Create displaced mesh first using apply_displacement_field()"
            )

        # Create plotter for export
        plotter = pv.Plotter(off_screen=True)

        # Add mesh
        if field in self.displaced_mesh.array_names:
            plotter.add_mesh(
                self.displaced_mesh, scalars=field, cmap=cmap, show_edges=True
            )
        else:
            plotter.add_mesh(self.displaced_mesh, show_edges=True, color="lightblue")

        # Export to HTML
        plotter.export_html(output_file)
        logger.info(f"Exported visualization to {output_file}")


def visualize_analysis_results(
    mesh_file: str,
    model: StructuralModel,
    scale_factor: float = 1.0,
    show_stress: bool = False,
    screenshot: Optional[str] = None,
) -> None:
    """
    Convenience function to visualize analysis results.

    Args:
        mesh_file: Path to mesh file (.msh)
        model: Structural model with results
        scale_factor: Displacement scale factor
        show_stress: Show von Mises stress instead of displacement
        screenshot: Save screenshot to this file
    """
    viz = ResultVisualizer(model)
    viz.load_mesh_from_file(mesh_file)
    viz.apply_displacement_field(scale_factor=scale_factor)

    if show_stress:
        viz.add_stress_field()
        viz.plot_deformed(
            scale_factor=scale_factor, field="Von Mises Stress", screenshot=screenshot
        )
    else:
        viz.plot_deformed(
            scale_factor=scale_factor, field="Displacement (mm)", screenshot=screenshot
        )
