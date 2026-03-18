"""Tests for mshquery command modules."""

import meshio

from mshquery import groups, info, nodes, select, summary


class TestSummary:
    def test_node_count(self, msh_file):
        mesh = meshio.read(msh_file)
        result = summary.summary(mesh)
        assert result["nodes"] == 5

    def test_element_count(self, msh_file):
        mesh = meshio.read(msh_file)
        result = summary.summary(mesh)
        assert result["elements"] == 6  # 2 vertex + 4 line

    def test_element_types(self, msh_file):
        mesh = meshio.read(msh_file)
        result = summary.summary(mesh)
        assert result["element_types"]["line"] == 4
        assert result["element_types"]["vertex"] == 2

    def test_bounding_box(self, msh_file):
        mesh = meshio.read(msh_file)
        result = summary.summary(mesh)
        bbox = result["bounding_box"]
        assert bbox["min"]["x"] == 0.0
        assert bbox["max"]["x"] == 4.0

    def test_3d_mesh(self, msh_file_3d):
        mesh = meshio.read(msh_file_3d)
        result = summary.summary(mesh)
        assert result["nodes"] == 4
        assert result["element_types"]["triangle"] == 2


class TestInfo:
    def test_node_info(self, msh_file):
        mesh = meshio.read(msh_file)
        result = info.node_info(mesh, 1)
        assert result["id"] == 1
        assert result["x"] == 0.0
        assert result["y"] == 0.0
        assert result["z"] == 0.0

    def test_node_info_last(self, msh_file):
        mesh = meshio.read(msh_file)
        result = info.node_info(mesh, 5)
        assert result["id"] == 5
        assert result["x"] == 4.0

    def test_node_not_found(self, msh_file):
        mesh = meshio.read(msh_file)
        result = info.node_info(mesh, 999)
        assert "error" in result

    def test_node_zero_invalid(self, msh_file):
        mesh = meshio.read(msh_file)
        result = info.node_info(mesh, 0)
        assert "error" in result

    def test_element_info(self, msh_file):
        mesh = meshio.read(msh_file)
        # Element 1 is first vertex
        result = info.element_info(mesh, 1)
        assert result["id"] == 1
        assert result["type"] == "vertex"
        assert result["connectivity"] == [1]  # 1-based

    def test_element_info_line(self, msh_file):
        mesh = meshio.read(msh_file)
        # Elements 3-6 are lines (after 2 vertices)
        result = info.element_info(mesh, 3)
        assert result["type"] == "line"
        assert len(result["connectivity"]) == 2

    def test_element_not_found(self, msh_file):
        mesh = meshio.read(msh_file)
        result = info.element_info(mesh, 999)
        assert "error" in result

    def test_triangle_element(self, msh_file_3d):
        mesh = meshio.read(msh_file_3d)
        result = info.element_info(mesh, 1)
        assert result["type"] == "triangle"
        assert len(result["connectivity"]) == 3


class TestNodes:
    def test_list_all(self, msh_file):
        mesh = meshio.read(msh_file)
        result = nodes.list_nodes(mesh)
        assert len(result) == 5
        assert result[0]["id"] == 1
        assert result[4]["id"] == 5

    def test_range(self, msh_file):
        mesh = meshio.read(msh_file)
        result = nodes.list_nodes(mesh, range_str="2-4")
        assert len(result) == 3
        assert result[0]["id"] == 2
        assert result[2]["id"] == 4

    def test_single_node_range(self, msh_file):
        mesh = meshio.read(msh_file)
        result = nodes.list_nodes(mesh, range_str="3")
        assert len(result) == 1
        assert result[0]["id"] == 3

    def test_coordinates_present(self, msh_file):
        mesh = meshio.read(msh_file)
        result = nodes.list_nodes(mesh, range_str="1-1")
        n = result[0]
        assert "x" in n
        assert "y" in n
        assert "z" in n


class TestSelect:
    def test_nodes_at_origin(self, msh_file):
        mesh = meshio.read(msh_file)
        result = select.nodes_at(mesh, x=0.0, y=0.0, z=0.0)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_nodes_at_partial(self, msh_file):
        mesh = meshio.read(msh_file)
        # All nodes have y=0
        result = select.nodes_at(mesh, y=0.0)
        assert len(result) == 5

    def test_nodes_at_no_match(self, msh_file):
        mesh = meshio.read(msh_file)
        result = select.nodes_at(mesh, x=99.0)
        assert len(result) == 0

    def test_nodes_at_tolerance(self, msh_file):
        mesh = meshio.read(msh_file)
        result = select.nodes_at(mesh, x=0.005, tol=0.01)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_elements_with_node(self, msh_file):
        mesh = meshio.read(msh_file)
        # Node 1 (0-based: 0) is in vertex[0] and line[0]
        result = select.elements_with_node(mesh, 1)
        assert len(result) >= 1
        types = [e["type"] for e in result]
        assert "vertex" in types or "line" in types

    def test_elements_by_type_line(self, msh_file):
        mesh = meshio.read(msh_file)
        result = select.elements_by_type(mesh, "line")
        assert len(result) == 4
        for e in result:
            assert e["type"] == "line"

    def test_elements_by_type_vertex(self, msh_file):
        mesh = meshio.read(msh_file)
        result = select.elements_by_type(mesh, "vertex")
        assert len(result) == 2

    def test_elements_by_type_none(self, msh_file):
        mesh = meshio.read(msh_file)
        result = select.elements_by_type(mesh, "quad")
        assert len(result) == 0

    def test_elements_by_type_triangle(self, msh_file_3d):
        mesh = meshio.read(msh_file_3d)
        result = select.elements_by_type(mesh, "triangle")
        assert len(result) == 2


class TestGroups:
    def test_no_groups(self, msh_file):
        mesh = meshio.read(msh_file)
        result = groups.groups(mesh)
        # Our simple fixture has no physical groups
        assert isinstance(result, list)
