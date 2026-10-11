"""
Gmsh runner module for the IFC structural analysis extension.

This module runs the Gmsh meshing process through the Gmsh Python API, on the
model that ``GmshGeometryConverter`` has built in it, and writes the mesh file.
"""

import logging
import os
from typing import Optional

import gmsh

from ..config.meshing_config import MeshingConfig
from ..config.system_config import SystemConfig
from ..utils.error_handling import MeshingError

logger = logging.getLogger(__name__)


class GmshRunner:
    """
    Runs the Gmsh meshing process.

    The geometry lives in the Gmsh Python API, where ``GmshGeometryConverter``
    put it, so the mesh is generated there too. There is no way of running the
    Gmsh executable on it instead.
    """

    def __init__(
        self,
        meshing_config: Optional[MeshingConfig] = None,
        system_config: Optional[SystemConfig] = None,
    ):
        """
        Initialize the Gmsh runner.

        Args:
            meshing_config (Optional[MeshingConfig]): Meshing configuration to use.
                If not provided, a default configuration will be created.
            system_config (Optional[SystemConfig]): System configuration to use.
                If not provided, a default configuration will be created.
        """
        self.meshing_config = meshing_config or MeshingConfig()
        self.system_config = system_config or SystemConfig()

        # Note: gmsh.option.getNumber() does NOT raise a Python exception
        # when Gmsh is uninitialized — it just prints to stderr and returns 0.
        # Use gmsh.isInitialized() for a reliable check.
        self._we_initialized_gmsh = False
        if not gmsh.isInitialized():
            gmsh.initialize()
            self._we_initialized_gmsh = True

    def run_meshing(self, algorithm: str = "Delaunay") -> bool:
        """
        Mesh the current Gmsh model.

        Args:
            algorithm (str, optional): Meshing algorithm to use. Defaults to "Delaunay".

        Returns:
            bool: True; a failure raises.

        Raises:
            MeshingError: If there's an error during the meshing process.
        """
        try:
            gmsh.option.setNumber("Mesh.Algorithm", self._get_algorithm_code(algorithm))
            gmsh.option.setNumber(
                "Mesh.CharacteristicLengthMin",
                self.meshing_config.get_min_element_size(),
            )
            gmsh.option.setNumber(
                "Mesh.CharacteristicLengthMax",
                self.meshing_config.get_max_element_size(),
            )
            gmsh.option.setNumber(
                "Mesh.ElementOrder", self.meshing_config.get_element_order()
            )

            # Set additional meshing options from config
            for option, value in self.meshing_config.get_additional_options().items():
                if isinstance(value, bool):
                    gmsh.option.setNumber(option, 1 if value else 0)
                elif isinstance(value, (int, float)):
                    gmsh.option.setNumber(option, value)
                elif isinstance(value, str):
                    gmsh.option.setString(option, value)

            gmsh.model.mesh.generate(self.meshing_config.get_mesh_dimension())
            return True
        except MeshingError:
            raise
        except Exception as e:
            raise MeshingError(f"Meshing failed: {str(e)}") from e

    def generate_mesh_file(self, output_file: str) -> str:
        """
        Write the mesh of the current Gmsh model to a file.

        Args:
            output_file (str): Path where the mesh file should be written; its
                extension gives the format.

        Returns:
            str: Path to the generated mesh file.

        Raises:
            MeshingError: If the file is not written.
        """
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            gmsh.write(output_file)
        except Exception as e:
            raise MeshingError(f"Error generating mesh file: {str(e)}") from e

        if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            raise MeshingError(f"Gmsh wrote no mesh to {output_file}")
        return output_file

    def _get_algorithm_code(self, algorithm: str) -> int:
        """
        Convert algorithm name to Gmsh algorithm code.

        Args:
            algorithm (str): Name of the algorithm.

        Returns:
            int: Gmsh algorithm code.

        Raises:
            MeshingError: If the algorithm is not one Gmsh has.
        """
        algo_map = {
            "MeshAdapt": 1,
            "Automatic": 2,
            "Delaunay": 5,
            "Frontal": 6,
            "BAMG": 7,
            "DelaunayForQuads": 8,
        }
        if algorithm not in algo_map:
            raise MeshingError(
                f"Unknown meshing algorithm {algorithm!r}; choose one of "
                f"{', '.join(algo_map)}."
            )
        return algo_map[algorithm]

    def __del__(self):
        """
        Cleanup Gmsh resources when the runner is deleted.
        """
        # Only finalize Gmsh if we were the ones who initialized it
        if hasattr(self, "_we_initialized_gmsh") and self._we_initialized_gmsh:
            try:
                gmsh.finalize()
            except Exception:
                # Ignore any errors during finalization
                pass
