"""
Meshing module for the IFC structural analysis extension.

This module provides functionality to convert domain models to finite element meshes
suitable for analysis with CalculiX.
"""

from .gmsh_geometry import GmshGeometryConverter
from .gmsh_runner import GmshRunner

__all__ = ["GmshGeometryConverter", "GmshRunner", "MeshConverter"]
