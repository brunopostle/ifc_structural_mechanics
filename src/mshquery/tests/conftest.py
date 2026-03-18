"""Shared fixtures for mshquery tests."""

import pytest

MSH_BEAM = """\
$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
5
1 0.0 0.0 0.0
2 1.0 0.0 0.0
3 2.0 0.0 0.0
4 3.0 0.0 0.0
5 4.0 0.0 0.0
$EndNodes
$Elements
6
1 15 2 0 1 1
2 15 2 0 2 5
3 1 2 0 1 1 2
4 1 2 0 1 2 3
5 1 2 0 1 3 4
6 1 2 0 1 4 5
$EndElements
"""

MSH_TRI = """\
$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
4
1 0.0 0.0 0.0
2 1.0 0.0 0.0
3 0.5 1.0 0.0
4 1.5 1.0 0.0
$EndNodes
$Elements
2
1 2 2 0 1 1 2 3
2 2 2 0 1 2 4 3
$EndElements
"""


@pytest.fixture
def msh_file(tmp_path):
    """Create a simple .msh file (Gmsh 2.2 format)."""
    path = tmp_path / "test.msh"
    path.write_text(MSH_BEAM)
    return str(path)


@pytest.fixture
def msh_file_3d(tmp_path):
    """Create a .msh file with triangles."""
    path = tmp_path / "tri.msh"
    path.write_text(MSH_TRI)
    return str(path)
