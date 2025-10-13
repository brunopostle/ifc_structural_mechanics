"""
Result visualization using PyVista for interactive 3D rendering.

This module provides tools for visualizing structural analysis results including
deformed meshes, displacement fields, stress/strain contours, and more.
"""

import logging
import numpy as np
from typing import Optional, Dict, List, Tuple
from pathlib import Path

try:
    import pyvista as pv
    import meshio
    PYVISTA_AVAILABLE = True
except ImportError:
    PYVISTA_AVAILABLE = False

from ..domain.structural_model import StructuralModel
from ..domain.result import DisplacementResult, StressResult, StrainResult

logger = logging.getLogger(__name__)


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
            'line': pv.CellType.LINE,
            'line3': pv.CellType.QUADRATIC_EDGE,
            'triangle': pv.CellType.TRIANGLE,
            'triangle6': pv.CellType.QUADRATIC_TRIANGLE,
            'quad': pv.CellType.QUAD,
            'quad8': pv.CellType.QUADRATIC_QUAD,
            'tetra': pv.CellType.TETRA,
            'tetra10': pv.CellType.QUADRATIC_TETRA,
            'hexahedron': pv.CellType.HEXAHEDRON,
            'hexahedron20': pv.CellType.QUADRATIC_HEXAHEDRON,
            'wedge': pv.CellType.WEDGE,
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

        logger.info(f"Loaded mesh: {self.mesh.n_points} nodes, {self.mesh.n_cells} elements")
        return self.mesh

    def apply_displacement_field(
        self,
        scale_factor: float = 1.0,
        displacement_results: Optional[List[DisplacementResult]] = None
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
            displacement_results = [r for r in self.model.results if isinstance(r, DisplacementResult)]

        if not displacement_results:
            logger.warning("No displacement results found")
            return self.mesh

        # Create displacement array (initialized to zero)
        n_points = self.mesh.n_points
        displacements = np.zeros((n_points, 3))
        displacement_magnitude = np.zeros(n_points)

        # Map node IDs to array indices
        # Note: assuming node IDs are 1-based and sequential
        for result in displacement_results:
            try:
                node_id = int(result.reference_element) - 1  # Convert to 0-based
                if 0 <= node_id < n_points:
                    trans = result.get_translations()
                    displacements[node_id] = trans
                    displacement_magnitude[node_id] = result.get_magnitude()
            except (ValueError, IndexError) as e:
                logger.warning(f"Error processing displacement for node {result.reference_element}: {e}")

        # Create displaced mesh
        displaced_points = self.mesh.points + scale_factor * displacements
        self.displaced_mesh = self.mesh.copy()
        self.displaced_mesh.points = displaced_points

        # Add displacement magnitude as scalar field
        self.displaced_mesh['Displacement'] = displacement_magnitude

        logger.info(f"Applied displacements with scale factor {scale_factor}")
        logger.info(f"Max displacement: {displacement_magnitude.max():.6e}")

        return self.displaced_mesh

    def add_stress_field(self, stress_results: Optional[List[StressResult]] = None) -> None:
        """
        Add stress field to mesh for visualization.

        Handles both node-based and element-based stress results. If stress IDs
        are beyond node count, treats them as element centers and averages to nodes.

        Args:
            stress_results: List of stress results (or use model.results)
        """
        if self.displaced_mesh is None:
            raise ValueError("Create displaced mesh first using apply_displacement_field()")

        # Get stress results
        if stress_results is None:
            if self.model is None:
                raise ValueError("No model or stress results provided")
            stress_results = [r for r in self.model.results if isinstance(r, StressResult)]

        if not stress_results:
            logger.warning("No stress results found")
            return

        n_points = self.displaced_mesh.n_points
        n_cells = self.displaced_mesh.n_cells

        # Check if results are node-based or element-based
        stress_ids = [int(r.reference_element) for r in stress_results]
        min_id = min(stress_ids)
        max_id = max(stress_ids)

        # If IDs are within node range (1-based), treat as node data
        if max_id <= n_points:
            logger.info("Treating stress as node-based data")
            von_mises = np.zeros(n_points)

            for result in stress_results:
                try:
                    node_id = int(result.reference_element) - 1  # Convert to 0-based
                    if 0 <= node_id < n_points:
                        try:
                            vm_stress = result.get_von_mises_stress()
                            von_mises[node_id] = vm_stress
                        except ValueError:
                            pass
                except (ValueError, IndexError) as e:
                    logger.warning(f"Error processing stress for element {result.reference_element}: {e}")

            self.displaced_mesh['Von Mises Stress'] = von_mises
        else:
            # Element-based data - map integration points to elements, then to nodes
            logger.info("Treating stress as element/integration point data")
            logger.info(f"Stress IDs range: {min_id} to {max_id}, mesh has {n_points} nodes, {n_cells} elements")

            # Collect all stress values (integration points)
            stress_values = []
            for result in stress_results:
                try:
                    vm_stress = result.get_von_mises_stress()
                    stress_values.append(vm_stress)
                except (ValueError, IndexError):
                    pass

            if stress_values:
                stress_array = np.array(stress_values)
                logger.info(f"Collected {len(stress_array)} stress values")
                logger.info(f"Stress range: {stress_array.min():.6e} to {stress_array.max():.6e}")

                # Map stress results to mesh elements
                # CalculiX typically outputs multiple integration points per element
                # Try to determine integration points per element
                n_integration_points = len(stress_array) // n_cells if n_cells > 0 else 1
                logger.info(f"Estimated integration points per element: {n_integration_points:.1f}")

                # Assign stress to elements by averaging integration points
                cell_stress = np.zeros(n_cells)
                if n_integration_points >= 1:
                    # Reshape and average integration points for each element
                    # Handle case where we don't have exact multiple
                    points_per_elem = max(1, int(len(stress_array) / n_cells))
                    for i in range(n_cells):
                        start_idx = i * points_per_elem
                        end_idx = min(start_idx + points_per_elem, len(stress_array))
                        if end_idx > start_idx:
                            cell_stress[i] = np.mean(stress_array[start_idx:end_idx])
                        else:
                            # Fallback: use overall mean
                            cell_stress[i] = np.mean(stress_array)
                else:
                    # Fallback: distribute all values
                    cell_stress[:] = np.mean(stress_array)

                logger.info(f"Element stress range: {cell_stress.min():.6e} to {cell_stress.max():.6e}")

                # Extrapolate element stresses to nodes
                node_stress = np.zeros(n_points)
                node_count = np.zeros(n_points)

                for i in range(n_cells):
                    cell = self.displaced_mesh.get_cell(i)
                    for node_id in cell.point_ids:
                        node_stress[node_id] += cell_stress[i]
                        node_count[node_id] += 1

                # Average the accumulated stresses
                mask = node_count > 0
                node_stress[mask] /= node_count[mask]

                logger.info(f"Node stress range: {node_stress.min():.6e} to {node_stress.max():.6e}")
                self.displaced_mesh['Von Mises Stress'] = node_stress
            else:
                logger.warning("No valid stress values found")
                self.displaced_mesh['Von Mises Stress'] = np.zeros(n_points)

        max_stress = self.displaced_mesh['Von Mises Stress'].max()
        logger.info(f"Added stress field, max von Mises: {max_stress:.6e}")

    def plot_deformed(
        self,
        scale_factor: float = 1.0,
        show_undeformed: bool = True,
        field: str = 'Displacement',
        cmap: str = 'jet',
        screenshot: Optional[str] = None,
        window_size: Tuple[int, int] = (1024, 768)
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
            raise ValueError("Create displaced mesh first using apply_displacement_field()")

        # Create plotter
        plotter = pv.Plotter(window_size=window_size)
        plotter.add_title("Structural Analysis Results", font_size=14)

        # Add deformed mesh with color coding
        if field in self.displaced_mesh.array_names:
            plotter.add_mesh(
                self.displaced_mesh,
                scalars=field,
                cmap=cmap,
                show_edges=True,
                edge_color='gray',
                line_width=0.5,
                scalar_bar_args={
                    'title': field,
                    'vertical': True,
                    'position_x': 0.85,
                    'position_y': 0.1
                }
            )
        else:
            logger.warning(f"Field '{field}' not found, showing without coloring")
            plotter.add_mesh(self.displaced_mesh, show_edges=True, color='lightblue')

        # Add undeformed mesh as wireframe
        if show_undeformed and self.mesh is not None:
            plotter.add_mesh(
                self.mesh,
                style='wireframe',
                color='gray',
                opacity=0.3,
                line_width=1.0,
                label='Undeformed'
            )

        # Add axes
        plotter.add_axes(xlabel='X', ylabel='Y', zlabel='Z')

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
        field: str = 'Displacement',
        cmap: str = 'jet'
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
            raise ValueError("Create displaced mesh first using apply_displacement_field()")

        # Create plotter for export
        plotter = pv.Plotter(off_screen=True)

        # Add mesh
        if field in self.displaced_mesh.array_names:
            plotter.add_mesh(
                self.displaced_mesh,
                scalars=field,
                cmap=cmap,
                show_edges=True
            )
        else:
            plotter.add_mesh(self.displaced_mesh, show_edges=True, color='lightblue')

        # Export to HTML
        plotter.export_html(output_file)
        logger.info(f"Exported visualization to {output_file}")


def visualize_analysis_results(
    mesh_file: str,
    model: StructuralModel,
    scale_factor: float = 1.0,
    show_stress: bool = False,
    screenshot: Optional[str] = None
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
        viz.plot_deformed(scale_factor=scale_factor, field='Von Mises Stress', screenshot=screenshot)
    else:
        viz.plot_deformed(scale_factor=scale_factor, field='Displacement', screenshot=screenshot)
